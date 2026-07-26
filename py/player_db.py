import pandas as pd
import nflreadpy as nfl
import constants as c
import nfl_stats as stats
import src_bridge as bridge

# Legacy special-case names, kept so the CamelCase key matches draft.py's.
_NAME_RENAMES = {
    'Mike Badgley': 'Michael Badgley',
    'Amon-Ra St. Brown': 'AmonRa StBrown',
    'Chigoziem Okonkwo': 'ChigOkonkwo',
    'Hollywood Brown': 'Marquise Brown',
}


def _cleaned_name(display_series):
    """CamelCase key from the first two name tokens (e.g. 'PatrickMahomes').

    Mirrors the legacy key exactly so draft.py's name-based joins still line up.
    Team defenses keep their abbreviation.
    """
    s = display_series.replace(_NAME_RENAMES)
    s = s.str.replace(r"[.'-]", "", regex=True)

    def key(name):
        if not isinstance(name, str):
            return name
        parts = name.split()
        return ''.join(parts[:2]) if len(parts) >= 2 else ''.join(parts)

    return s.map(key)


def get(week):
    """Player + team-defense fantasy points for the current season.

    Returns the columns the legacy consumers rely on - sleeper_id, cleaned_name,
    position, team, week, fantasy_points, fantasy_points_ppr - plus the raw
    nflverse stat columns. week <= 0 returns the whole season.

    Sleeper identity is attached by an exact gsis_id join to the src/ registry,
    replacing the old fuzzy search_full_name merge (and the fragile positional
    column rename that broke on nflverse schema changes).
    """
    season = nfl.get_current_season()

    # --- Skill-position players: columns referenced BY NAME (schema-robust) ---
    players = nfl.load_player_stats(season, 'week').to_pandas()
    pos_groups_remove = ["LB", "DL", "OL", "DB", "None"]
    spec_teams_remove = ["P", "LS"]
    players = players[~players['position_group'].isin(pos_groups_remove)]
    players = players[~players['position'].isin(spec_teams_remove)]
    players['team'] = players['team'].replace('LA', 'LAR')
    players['cleaned_name'] = _cleaned_name(players['player_display_name'])

    # Custom league kicker scoring overrides nflverse's standard points.
    is_k = players['position'] == 'K'
    players.loc[is_k, 'fantasy_points'] = stats.kicker_fpts(players[is_k])
    players.loc[is_k, 'fantasy_points_ppr'] = players.loc[is_k, 'fantasy_points']

    # Attach Sleeper id via exact gsis_id match (nflverse player_id IS gsis_id).
    reg = bridge.load_registry()[['gsis_id', 'sleeper_id']]
    players['gsis_id'] = players['player_id'].astype(str)
    players = players.merge(reg, on='gsis_id', how='left')
    players = players.rename(columns={'player_id': 'nflstats_id'})

    # --- Team defenses: custom DST scoring, keyed by team abbreviation ---
    team_stats = nfl.load_team_stats(season, 'week').to_pandas()
    team_stats['team'] = team_stats['team'].replace('LA', 'LAR')
    defense = stats.def_fpts(team_stats).rename(columns={'fpts': 'fantasy_points'})
    defense['team'] = defense['team1']
    defense['position'] = 'DEF'
    defense['fantasy_points_ppr'] = defense['fantasy_points']
    defense['sleeper_id'] = defense['cleaned_name']   # DST keyed by team abbrev
    defense = defense[['week', 'team', 'position', 'cleaned_name',
                       'sleeper_id', 'fantasy_points', 'fantasy_points_ppr']]

    db = pd.concat([players, defense], ignore_index=True)

    if week <= 0:
        return db
    return db[db['week'] == week]


def getFromID(id, db):
    if id in c.TEAMS:
        return db[db['cleaned_name'] == id]
    player = db[db['sleeper_id'] == id]
    return player


def checkForInjury(id, db):
    # NOTE: relies on an injury_status column (dropped in the registry migration).
    # Currently unused; wire injury data back in from src/ if this is revived.
    for i in id:
        df = db[db['sleeper_id'] == i]
        df = df.iloc[-1, :]
        if df['injury_status'] == "Out":
            id = id.drop(id.index)
    return id
