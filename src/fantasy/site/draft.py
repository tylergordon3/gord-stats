"""
Draft pick data (src/) - internal data module.

Builds each season's drafted players with where they were taken (overall +
positional) and where they finished, from Sleeper draft picks + rosters and
fantasy.stats.player_points. Consumed by fantasy.site.adp (the Draft vs ADP page).

Also archives per-team games-missed for the homepage injury section
(save_games_missed), which is why this module survived the draft-page removal.
"""
from functools import lru_cache

import pandas as pd
from sleeper_wrapper import Drafts, League

from fantasy import archive, stats
from fantasy.config import DATA_DIR, DRAFT_IDS, LEAGUE_IDS, SEASON_YEAR

REG_WEEKS = 14
# In-season pickups enter the injury stats only when held this many weeks -
# streamers and one-week rentals aren't an injury story.
PICKUP_MIN_WEEKS = 4


def _rosters(league) -> pd.DataFrame:
    """roster_id -> owner_id, team_name."""
    users = league.map_users_to_team_name(league.get_users())
    users = pd.Series(users).rename_axis("owner_id").reset_index(name="team_name")
    rosters = pd.DataFrame(league.get_rosters())[["owner_id", "roster_id"]]
    return rosters.merge(users, on="owner_id", how="inner")


def _sum_pts(players, pid):
    return players[players["sleeper_id"] == str(pid)]["fantasy_points_ppr"].sum()


def _num_games(players, pid):
    return players[players["sleeper_id"] == str(pid)]["fantasy_points_ppr"][:13].count()


def _med_pts(players, pid):
    return players[players["sleeper_id"] == str(pid)]["fantasy_points_ppr"][:13].median()


def _final_rank(row, df):
    return len(df[df["total_pts"] > row.total_pts]) + 1


def _pos_rank(row, position_df):
    return len(position_df[position_df["pick_no"] < row.pick_no]) + 1


def _final_rank_missed_szn(final_ranks, position, pts):
    same = final_ranks[(final_ranks["pos"] == position) & (final_ranks["tot_pts"] == pts)]
    return int(same.head(1)["pos_rank"].iloc[0]) if not same.empty else 999


@lru_cache(maxsize=None)
def _build(season_str: str, keep_streamers: bool = False):
    """Return (picks df, final_ranks) for the season. Cached; callers must not mutate.

    K / team-defense picks are dropped by default (the value pages judge skill
    positions only); keep_streamers=True keeps them for full-draft views.
    """
    league = League(LEAGUE_IDS[season_str])
    draft = Drafts(DRAFT_IDS[season_str])
    rosters = _rosters(league)

    players = stats.player_points(season=SEASON_YEAR[season_str])
    players = players[players["week"] < REG_WEEKS + 1]

    final_ranks = players.groupby("cleaned_name").agg(
        tot_pts=("fantasy_points_ppr", "sum"),
        tot_games=("fantasy_points_ppr", "count"),
        pos=("position", "first"),
    )
    final_ranks["overall"] = final_ranks["tot_pts"].rank(ascending=False).astype(int)
    final_ranks = final_ranks.sort_values("overall")
    final_ranks["pos_rank"] = final_ranks.groupby("pos")["tot_pts"].rank(ascending=False).astype(int)

    picks = pd.DataFrame(draft.get_all_picks())
    # Drop metadata fields that collide with pick columns (esp. player_id) or add noise.
    meta = picks["metadata"].apply(pd.Series).drop(
        columns=["team_abbr", "team_changed_at", "sport", "news_updated", "years_exp",
                 "status", "injury_status", "number", "player_id"], errors="ignore")
    draft_df = pd.concat([picks, meta], axis=1)

    roster_by_owner = dict(zip(rosters["owner_id"], rosters["roster_id"]))
    team_by_roster = dict(zip(rosters["roster_id"], rosters["team_name"]))
    draft_df["roster_id"] = draft_df["picked_by"].map(roster_by_owner)
    draft_df["team_name"] = draft_df["roster_id"].map(team_by_roster)

    df = draft_df[["pick_no", "roster_id", "team_name", "player_id", "first_name",
                   "last_name", "round", "position", "team"]].copy()

    # Where the pick sits inside its round, for the "2.3" label below. Derived
    # from the overall pick rather than Sleeper's draft_slot: draft_slot is the
    # manager's seat, so in a snake round it counts backwards (the first pick of
    # round 2 belongs to seat 10 and is 2.1, not 2.10).
    per_round = int(draft_df.groupby("round")["pick_no"].count().max())
    df["pick_in_round"] = df["pick_no"] - (df["round"] - 1) * per_round

    # Player key (same CamelCase scheme as stats), team abbrev for defenses.
    df["name"] = stats.cleaned_name(df["first_name"].fillna("") + " " + df["last_name"].fillna(""))
    df["name"] = df.apply(lambda x: x["team"] if x["position"] == "DEF" else x["name"], axis=1)

    # Human spelling ("Ja'Marr Chase") - "name" below is the CamelCase join key.
    df["Display Name"] = (df["first_name"].fillna("") + " " + df["last_name"].fillna("")).str.strip()

    df["pos_rank"] = df.apply(lambda x: _pos_rank(x, df[df["position"] == x.position]), axis=1)
    df["total_pts"] = df["player_id"].apply(lambda pid: _sum_pts(players, pid))
    df["num_games"] = df["player_id"].apply(lambda pid: _num_games(players, pid))
    # Median weekly score: robust "typical week" for injury weighting — a couple
    # of spike weeks shouldn't read as starter-level production.
    df["med_ppg"] = df["player_id"].apply(lambda pid: _med_pts(players, pid))
    df["final_rank"] = df.apply(lambda x: _final_rank(x, df), axis=1)

    df["final_pos_rank"] = df["name"].apply(
        lambda n: list(final_ranks[final_ranks.index == n]["pos_rank"]))
    df["final_pos_rank"] = df.apply(
        lambda x: x["final_pos_rank"][0] if len(x["final_pos_rank"]) > 0
        else _final_rank_missed_szn(final_ranks, x["position"], x["total_pts"]), axis=1)

    df["overall_diff"] = df["pick_no"] - df["final_rank"]
    df["pos_diff"] = df["pos_rank"] - df["final_pos_rank"]
    df["Position Rk"] = df.apply(lambda x: f"{x['pos_rank']} -> {x['final_pos_rank']}", axis=1)
    df["Overall Rk"] = df.apply(lambda x: f"{x['pick_no']} -> {x['final_rank']}", axis=1)

    df = df.drop(columns=["player_id", "first_name", "last_name", "pos_rank",
                          "final_pos_rank", "final_rank"])
    if not keep_streamers:
        df = df[~df["position"].isin(["K", "DEF"])]
    df = df.rename(columns={
        "pos_diff": "Pos. Rank Δ", "overall_diff": "Overall Rank Δ", "pick_no": "Pick",
        "position": "Pos.", "team_name": "Owner", "total_pts": "Pts.",
        "name": "Name", "team": "Team", "num_games": "Games Played",
        "med_ppg": "Med PPG",
    })
    df["Pick"] = df["round"].astype(str) + "." + df["pick_in_round"].astype(str)
    return df.drop(columns="pick_in_round"), final_ranks


def _pickup_detail(season_str: str) -> pd.DataFrame:
    """Injury-stat rows for in-season waiver / free-agent pickups.

    A pickup counts only when it looks like a real roster piece:
      * held at least PICKUP_MIN_WEEKS weeks (add week through the week before
        the player left the roster again - drop or trade - capped at week 14);
      * not drafted that season (a drafted player's missed games are already
        charged to his drafter - counting his pickup stint too would double-bill
        the same absences);
      * not a K / team defense (mirrors the drafted table).

    Unlike drafted players (accountable all 14 weeks), a pickup is only on the
    hook for games missed inside his ownership window ("Window Weeks").
    """
    path = DATA_DIR / "transactions" / f"{season_str}.json"
    if not path.exists():
        print(f"[games-missed] no transactions for {season_str}, pickups skipped")
        return pd.DataFrame()
    tx = pd.read_json(path)

    drafted_ids = {str(p["player_id"]) for p in Drafts(DRAFT_IDS[season_str]).get_all_picks()}
    rosters = _rosters(League(LEAGUE_IDS[season_str]))
    team_by_roster = dict(zip(rosters["roster_id"], rosters["team_name"]))

    players = stats.player_points(season=SEASON_YEAR[season_str])
    players = players[players["week"] <= REG_WEEKS]

    # Every time (player, roster) parted ways, by any transaction type.
    removals = [(str(pid), r, t["leg"]) for _, t in tx.iterrows()
                for pid, r in (t["drops"] or {}).items()]

    rows = []
    for _, t in tx[tx["type"].isin(["waiver", "free_agent"])].iterrows():
        for pid, roster_id in (t["adds"] or {}).items():
            pid, start = str(pid), t["leg"]
            if pid in drafted_ids or pid.isalpha() or start > REG_WEEKS:
                continue                          # drafted / team defense / playoffs add
            ends = [w for p, r, w in removals if p == pid and r == roster_id and w > start]
            end = min(ends) - 1 if ends else REG_WEEKS
            window = min(end, REG_WEEKS) - start + 1
            if window < PICKUP_MIN_WEEKS:
                continue
            mine = players[players["sleeper_id"] == pid]
            if mine.empty or mine["position"].iloc[0] in ("K", "DEF"):
                continue                          # never played this season, or streamer slot
            in_window = mine[(mine["week"] >= start) & (mine["week"] <= end)]
            rows.append({
                "Owner": team_by_roster.get(roster_id), "roster_id": roster_id,
                "Name": mine["cleaned_name"].iloc[0], "Pos.": mine["position"].iloc[0],
                "round": None, "Pick": f"Wk {start} add",
                "Pts.": in_window["fantasy_points_ppr"].sum(),
                "Games Played": int(in_window["fantasy_points_ppr"].count()),
                # Season-wide typical week: the injury weighting needs to know how
                # much the player mattered, and the window alone can be all-injury.
                "Med PPG": mine["fantasy_points_ppr"].median(),
                "Sample Games": int(mine["fantasy_points_ppr"].count()),
                "Window Weeks": window, "Source": "Pickup",
            })
    return pd.DataFrame(rows)


def save_games_missed(season_str: str):
    """Archive per-team games missed by drafted players and substantial pickups
    (feeds the homepage injury section)."""
    df, _ = _build(season_str)
    detail = df[["Owner", "roster_id", "Name", "Pos.", "round", "Pick",
                 "Pts.", "Games Played", "Med PPG"]].copy()
    detail["Sample Games"] = detail["Games Played"]
    detail["Window Weeks"] = REG_WEEKS
    detail["Source"] = "Drafted"
    detail = pd.concat([detail, _pickup_detail(season_str)], ignore_index=True)

    missing = detail.groupby(by=["Owner", "roster_id"]).agg(
        num_games=("Games Played", "sum"), tot_players=("Games Played", "count"),
        tot_games=("Window Weeks", "sum"))
    missing["Total Games Missed"] = missing["tot_games"] - missing["num_games"]
    missing["% of Games Missed"] = (missing["Total Games Missed"] / missing["tot_games"]).apply(
        lambda x: f"{x:.2%}")
    archive.save_statistic(season_str, "missing_df", missing.reset_index().to_dict(orient="records"))

    # Per-player detail so the injury section can weight injuries by how much the
    # player mattered (draft capital, scoring pace) instead of counting all missed
    # games equally. Tiering/weighting happens at render time in fantasy.site.injuries.
    archive.save_statistic(season_str, "injury_detail_df", detail.to_dict(orient="records"))
    print(f"[games-missed] archived {season_str} "
          f"({(detail['Source'] == 'Pickup').sum()} qualifying pickups)")
