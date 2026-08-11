"""
wnba_remaining.py
-----------------
For a given fantasy matchup week, shows how many games each player on each
fantasy team has remaining, and the total games left across the roster.

Slot definitions (from ESPN settings lineupSlotCounts):
    0 = PG, 1 = SG, 2 = SF, 3 = PF, 4 = C/F (flex), 5 = UTIL, 6 = BENCH, 7 = IR

Usage:
    python wnba_remaining.py
    python wnba_remaining.py --week 2
    python wnba_remaining.py --week 2 --team 6
    python wnba_remaining.py --week 2 --all-teams
    python wnba_remaining.py --week 2 --starters-only

Requires:
    wnba_fantasy_data.json   (from wnba_fantasy_fetch.py)
    wnba_schedule_2026.json  (from wnba_schedule.py)
"""

import argparse
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from cbb.lib import paths
from cbb.wnba import wnba_schedule
from cbb.wnba import wnba_fantasy
from cbb.wnba import wnba_defense

ET = ZoneInfo("America/New_York")
DEBUG = False

def today_et() -> str:
    """Current date in Eastern Time as YYYY-MM-DD."""
    return datetime.now(ET).date().isoformat()

# ── File paths (adjust if yours are elsewhere) ────────────────────────────────
FANTASY_FILE  = paths.WNBA_DATA / "wnba_fantasy_data.json"
SCHEDULE_FILE =  paths.WNBA_DATA / "wnba_schedule_2026.json"

# ── Slot IDs ──────────────────────────────────────────────────────────────────
# From ESPN settings lineupSlotCounts: {1: 2, 4: 3, 5: 1, 6: 3(bench), 7: 1(IR)}
G_SLOT    = 1   # Guard   — eligibleSlots contains 1
FC_SLOT   = 4   # F/C     — eligibleSlots contains 4
# UTIL (slot 5) accepts anyone; IR (slot 7) excluded entirely
 
G_LIMIT   = 2
FC_LIMIT  = 3
UTIL_LIMIT = 1
 
IR_SLOTS  = {7}

TEAM_COUNT = {}
# ── Team dict: ESPN proTeamId → WNBA abbreviation ─────────────────────────────
TEAM_DICT = {
    "3":      "DAL", "5":      "IND", "6":      "LA",  "8":      "MIN",
    "9":      "NY",  "11":     "PHX", "14":     "SEA", "16":     "WSH",
    "17":     "LV",  "18":     "CON", "19":     "CHI", "20":     "ATL",
    "129689": "GS",  "131935": "TOR", "132052": "POR",
}
 
# ── Week date ranges ──────────────────────────────────────────────────────────
WEEK_DATES = {
    1:  ("2026-05-08", "2026-05-17"),
    2:  ("2026-05-18", "2026-05-24"),
    3:  ("2026-05-25", "2026-05-31"),
    4:  ("2026-06-01", "2026-06-07"),
    5:  ("2026-06-08", "2026-06-14"),
    6:  ("2026-06-15", "2026-06-21"),
    7:  ("2026-06-22", "2026-06-28"),
    8:  ("2026-06-29", "2026-07-05"),
    9:  ("2026-07-06", "2026-07-12"),
    10: ("2026-07-13", "2026-07-19"),
    11: ("2026-07-20", "2026-08-02"),
    12: ("2026-08-03", "2026-08-09"),
    13: ("2026-08-10", "2026-08-23"),
    14: ("2026-08-24", "2026-09-24")
}
 
# ── Helpers ───────────────────────────────────────────────────────────────────
def dates_in_range(start: str, end: str) -> list[str]:
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    out = []
    while s <= e:
        out.append(s.isoformat())
        s += timedelta(days=1)
    return out
 
def teams_playing_on(schedule: dict, date_str: str) -> set[str]:
    """
    Returns teams with a game on date_str that has not yet been played.
    Excludes any game with status='post', which handles the case where BDL
    dates a late ET game (e.g. 10pm ET) as the next calendar day in UTC.
    """
    playing = set()
    for abbrev, games in schedule.get(date_str, {}).items():
        for g in games:
            if g.get("status") != "post":
                playing.add(abbrev)
                break
    return playing
 
def get_avg_points(player: dict, season: int = 2026) -> float:
    """Season-average fantasy points; falls back to ESPN's season projection."""
    stats = {s["id"]: s for s in player.get("stats", [])}
    for stat_id in (f"00{season}", f"10{season}"):
        s = stats.get(stat_id)
        if s and s.get("appliedAverage"):
            return s["appliedAverage"]
    return 0.0

MINUTES_STAT = "40"  # averageStats["40"] = minutes per game

def get_avg_minutes(player: dict, season: int = 2026) -> float:
    """Season-average minutes per game; falls back to ESPN's season projection."""
    stats = {s["id"]: s for s in player.get("stats", [])}
    for stat_id in (f"00{season}", f"10{season}"):
        s = stats.get(stat_id)
        if s and s.get("averageStats", {}).get(MINUTES_STAT):
            return s["averageStats"][MINUTES_STAT]
    return 0.0

def get_players(fantasy_team: dict) -> list[dict]:
    """Extract non-IR players with position category from a fantasy team."""
    players = []
    for entry in fantasy_team["roster"]["entries"]:
        if entry["lineupSlotId"] in IR_SLOTS:
            continue
        player = entry["playerPoolEntry"]["player"]
        es     = player["eligibleSlots"]
        abbrev = TEAM_DICT.get(str(player["proTeamId"]), f'?{player["proTeamId"]}')
        players.append({
            "name":   player["fullName"],
            "abbrev": abbrev,
            "is_g":   G_SLOT  in es,
            "is_fc":  FC_SLOT in es,
            "is_out":  player.get("injuryStatus", "ACTIVE") == "OUT",
            "avg":    get_avg_points(player),
            "mpg":    get_avg_minutes(player),
        })
    return players

def opponent_on(schedule: dict, date_str: str, abbrev: str) -> str | None:
    """Opponent abbreviation for a team's first unplayed game on a date."""
    for g in schedule.get(date_str, {}).get(abbrev, []):
        if g.get("status") != "post":
            return g["away"] if g["home"] == abbrev else g["home"]
    return None

def project_points(player: dict, opp: str | None, factors: dict) -> float:
    """Player's average scaled by the opponent's defense vs their position group."""
    group  = "G" if player["is_g"] else "FC"
    factor = factors.get(opp, {}).get(group, 1.0) if opp else 1.0
    return player["avg"] * factor

# Margin std dev scales with sqrt(total max minutes left). 2.0 treats a full
# player-game (~40 min) as ~±12.6 fantasy pts of swing — deliberately generous
# so favorites aren't shown as overwhelming while games remain.
SIGMA_PER_SQRT_MIN = 2.0

def win_probability(home_proj: float, away_proj: float,
                    home_min: float, away_min: float) -> float:
    """
    P(home wins) given projected finals and MAX minutes left to play.
    The projected margin covers points needed (current gap + expected
    remaining production); the minutes left set how much can still change —
    as clocks run out the leader's probability hardens toward certainty.
    """
    margin    = home_proj - away_proj
    total_min = home_min + away_min
    if total_min <= 0:
        return 1.0 if margin > 0 else 0.0 if margin < 0 else 0.5
    sigma = SIGMA_PER_SQRT_MIN * math.sqrt(total_min)
    return 0.5 * (1 + math.erf(margin / (sigma * math.sqrt(2))))
 
# ── Core optimizer ────────────────────────────────────────────────────────────
def calc_max_games(
    players: list[dict],
    dates: list[str],
    schedule: dict,
    factors: dict | None = None,
    live_mins: dict | None = None,
) -> tuple[int, float, float, list]:
    """
    Greedy day-by-day slot filler. For each date:
      1. Fill up to 2 G slots from active guards with a game that day
      2. Fill up to 3 F/C slots from active forwards/centers with a game that day
      3. Fill 1 UTIL slot from any remaining active player with a game that day

    Within each pool, higher-averaging players get slots first, and each
    slotted player is projected for avg points x opponent defense factor
    vs their position group.

    OUT players are excluded from slot counts but appear in the daily log
    with is_out=True so the display layer can highlight them.

    Tracks two minute totals per team:
      max minutes  — the game clock: live minutes (via live_mins
                     {abbrev: minutes}) for today, 40 per future game.
                     Feeds the matchup cards and win probability.
      proj minutes — each slotted player's average minutes, capped by the
                     game clock. Feeds the roster lists.

    Returns (total_max_games, total_projected_points, total_max_minutes,
             total_proj_minutes, daily_log).
    daily_log is a list of (date_str, slots_filled, out_players) where:
      slots_filled = list of (slot_label, player_name, abbrev, proj_pts, opp, proj_mins)
      out_players  = list of (player_name, abbrev) who have a game but are OUT
    """
    factors = factors or {}
    live_mins = live_mins if live_mins is not None else {}
    today = today_et()
    total  = 0
    proj_total = 0.0
    min_total  = 0.0
    proj_min_total = 0.0
    daily_log = []
    for d in dates:
        playing   = teams_playing_on(schedule, d)

        for team in playing:
            if team not in TEAM_COUNT:
                TEAM_COUNT[team] = [d]
            else:
                list = TEAM_COUNT[team]
                if d not in list:
                    TEAM_COUNT[team] += [d]

        # Split into active and out players who have a game today
        active    = [p for p in players if p["abbrev"] in playing and not p["is_out"]]
        out_today = [p for p in players if p["abbrev"] in playing and p["is_out"]]

        active.sort(key=lambda p: p["avg"], reverse=True)
        guards = [p for p in active if p["is_g"]]
        fcs    = [p for p in active if p["is_fc"]]

        used   = set()
        slots  = []

        def fill(label, pool, limit):
            for p in pool:
                if len([s for s in slots if s[0] == label]) >= limit:
                    break
                if p["name"] in used:
                    continue
                used.add(p["name"])
                opp  = opponent_on(schedule, d, p["abbrev"])
                proj = project_points(p, opp, factors)
                if d == today:
                    game_mins = live_mins.get(p["abbrev"], 40.0)
                else:
                    game_mins = 40.0
                p_mins = min(p["mpg"], game_mins)
                slots.append((label, p["name"], p["abbrev"], proj, opp, game_mins, p_mins))

        fill("G", guards, G_LIMIT)
        fill("F/C", fcs, FC_LIMIT)
        fill("UTIL", active, UTIL_LIMIT)

        total += len(slots)
        proj_total += sum(s[3] for s in slots)
        min_total  += sum(s[5] for s in slots)
        proj_min_total += sum(s[6] for s in slots)
        daily_log.append((d, slots, [(p["name"], p["abbrev"]) for p in out_today]))
    return total, proj_total, min_total, proj_min_total, daily_log
 
# ── Playoff bracket ───────────────────────────────────────────────────────────
PLAYOFF_ROUND_NAMES = {1: "Semifinals", 2: "Championship"}

def _bracket_team_html(team, score, is_winner, tbd_label="TBD"):
    if team is None:
        return f"""
            <div class="bracket-team tbd">
              <span class="bseed">–</span>
              <span class="bteam-name">{tbd_label}</span>
              <span class="bscore"></span>
            </div>"""
    rec = team.get("record", {}).get("overall", {})
    rec_s = f"{rec.get('wins', 0)}-{rec.get('losses', 0)}"
    cls = "bracket-team winner" if is_winner else "bracket-team"
    score_s = f"{score:.0f}" if score is not None else ""
    return f"""
            <div class="{cls}">
              <span class="bseed">{team.get("playoffSeed", "–")}</span>
              <span class="bteam-name">{team["name"]} <em>({rec_s})</em></span>
              <span class="bscore">{score_s}</span>
            </div>"""

def _bracket_game_html(home, away, home_score, away_score, winner, tbd=("TBD", "TBD")):
    return f"""
          <div class="bracket-game">
            {_bracket_team_html(home, home_score, winner == "HOME", tbd[0])}
            {_bracket_team_html(away, away_score, winner == "AWAY", tbd[1])}
          </div>"""

CONSOLATION_ROUND_NAMES = {1: "Consolation Semifinals", 2: "Consolation Finals"}

def _bracket_rounds_html(teams, seeds, by_period, n_regular,
                         seed_lo, seed_hi, round_names) -> list[str]:
    """
    One bracket (championship or consolation) as round columns. Renders real
    matchups for a round when ESPN has them, otherwise synthesizes round 1
    from seeds (lo v hi, lo+1 v hi-1, ...) and later rounds as TBD.
    """
    n_teams  = seed_hi - seed_lo + 1
    n_rounds = max(1, (n_teams - 1).bit_length())

    html = ['<div class="bracket">']
    for i in range(1, n_rounds + 1):
        period = n_regular + i
        name   = round_names.get(i, f"Round {i}")
        start, end = WEEK_DATES.get(period, (None, None))
        dates = f' <span class="round-dates">{start} → {end}</span>' if start else ""
        html.append(f'<div class="bracket-round"><h3>{name}{dates}</h3>')

        ms = by_period.get(period, [])
        if ms:
            for m in ms:
                home = teams.get(m.get("home", {}).get("teamId"))
                away = teams.get(m.get("away", {}).get("teamId"))
                hs  = m.get("home", {}).get("totalPointsLive") or m.get("home", {}).get("totalPoints")
                as_ = m.get("away", {}).get("totalPointsLive") or m.get("away", {}).get("totalPoints")
                html.append(_bracket_game_html(home, away, hs, as_, m.get("winner", "UNDECIDED")))
        elif i == 1:
            for s in range(n_teams // 2):
                html.append(_bracket_game_html(
                    seeds.get(seed_lo + s), seeds.get(seed_hi - s), None, None, "UNDECIDED"
                ))
        else:
            prev = round_names.get(i - 1, f"Round {i - 1}")
            for _ in range(max(1, n_teams // (2 ** i))):
                html.append(_bracket_game_html(
                    None, None, None, None, "UNDECIDED",
                    tbd=(f"Winner {prev} 1", f"Winner {prev} 2"),
                ))
        html.append("</div>")
    html.append("</div>")
    return html

def _matchup_seeds(m, teams):
    return [teams[i].get("playoffSeed", 99)
            for i in (m.get("home", {}).get("teamId"), m.get("away", {}).get("teamId"))
            if i in teams]

def is_championship_matchup(m, teams, n_playoff) -> bool:
    """
    True for winners-bracket matchups. ESPN omits playoffTierType on some
    leagues — a matchup of only top seeds is championship, else consolation.
    """
    tier = m.get("playoffTierType")
    if tier == "WINNERS_BRACKET":
        return True
    if tier:
        return False
    s = _matchup_seeds(m, teams)
    return bool(s) and max(s) <= n_playoff

def playoff_bracket_sections(fantasy_data) -> tuple[str, str]:
    """
    (championship, consolation) bracket sections: top playoffTeamCount seeds
    in the championship bracket, every remaining team in the consolation.
    Real ESPN playoff matchups drive each bracket once published; until then
    pairings are synthesized from current playoff seeds.
    """
    ss        = fantasy_data["settings"]["scheduleSettings"]
    n_regular = ss["matchupPeriodCount"]
    n_playoff = ss.get("playoffTeamCount", 4)
    n_total   = len(fantasy_data["teams"])
    teams     = {t["id"]: t for t in fantasy_data["teams"]}
    seeds     = {t.get("playoffSeed"): t for t in fantasy_data["teams"]}

    playoff = [m for m in fantasy_data["schedule"]
               if m.get("matchupPeriodId", 0) > n_regular]
    win_by_period, cons_by_period = {}, {}
    for m in playoff:
        dest = (win_by_period if is_championship_matchup(m, teams, n_playoff)
                else cons_by_period)
        dest.setdefault(m["matchupPeriodId"], []).append(m)

    # Best seed first within each round (1v4 above 2v3)
    for by_period in (win_by_period, cons_by_period):
        for ms in by_period.values():
            ms.sort(key=lambda m: min(_matchup_seeds(m, teams) or [99]))

    champ = ['<section class="wnba-playoff-bracket">', "<h2>Playoff Bracket</h2>"]
    if not playoff:
        champ.append('<p class="week-meta">Seeds from current standings — '
                     "bracket locks when the regular season finalizes</p>")
    champ.append('<h3 class="bracket-title">Championship Bracket</h3>')
    champ += _bracket_rounds_html(
        teams, seeds, win_by_period, n_regular, 1, n_playoff, PLAYOFF_ROUND_NAMES
    )
    champ.append("</section>")

    cons = []
    if n_total - n_playoff >= 2:
        cons = ['<section class="wnba-playoff-bracket">',
                '<h3 class="bracket-title consolation-title">Consolation Bracket</h3>']
        cons += _bracket_rounds_html(
            teams, seeds, cons_by_period, n_regular,
            n_playoff + 1, n_total, CONSOLATION_ROUND_NAMES
        )
        cons.append("</section>")

    return "\n".join(champ), "\n".join(cons)

# ── Matchup comparison ────────────────────────────────────────────────────────
def get_week_matchups(fantasy_data: dict, week: int) -> list[dict]:
    """Return matchup objects for the given week."""
    return [m for m in fantasy_data["schedule"] if m.get("matchupPeriodId") == week]
 
def matchup_scoreboard_html(fantasy_data, week, max_games, proj_left=None, min_left=None,
                            matchups=None, title=None, show_updated=True):
    proj_left = proj_left or {}
    min_left = min_left or {}
    if matchups is None:
        matchups = get_week_matchups(fantasy_data, week)
    all_teams = {t["id"]: t["name"] for t in fantasy_data["teams"]}

    html = []
    html.append('<section class="wnba-fantasy-week">')
    html.append(f'<h2>{title or f"Week {week} Matchups"}</h2>')
    if show_updated:
        time = datetime.now(ET).strftime("Last Update: %A %m/%d/%y %I:%M %p")
        html.append(f'<p>{time}</p>')
    html.append('<div class="matchup-grid">')

    for m in matchups:
        home_id = m["home"]["teamId"]
        away_id = m["away"]["teamId"]

        home_name = all_teams.get(home_id, f"Team {home_id}")
        away_name = all_teams.get(away_id, f"Team {away_id}")

        home_live = m["home"].get("totalPointsLive", 0) or 0
        away_live = m["away"].get("totalPointsLive", 0) or 0
        home_final = m["home"].get("totalPoints", 0) or 0
        away_final = m["away"].get("totalPoints", 0) or 0

        home_rem = max_games.get(home_id, 0)
        away_rem = max_games.get(away_id, 0)

        home_min = min_left.get(home_id, 0)
        away_min = min_left.get(away_id, 0)

        home_proj = home_live + proj_left.get(home_id, 0)
        away_proj = away_live + proj_left.get(away_id, 0)

        winner = m.get("winner", "UNDECIDED")
        status = "Final" if winner != "UNDECIDED" else "In Progress"

        gap = abs(home_live - away_live)

        if home_live > away_live:
            home_class, away_class = "team-side leader", "team-side"
            summary = f"{home_name} leads by {gap:.0f}"
        elif away_live > home_live:
            home_class, away_class = "team-side", "team-side leader"
            summary = f"{away_name} leads by {gap:.0f}"
        else:
            home_class = away_class = "team-side tied"
            summary = "Tied"

        home_proj_class = " proj-leader" if home_proj > away_proj else ""
        away_proj_class = " proj-leader" if away_proj > home_proj else ""

        if winner == "HOME":
            p_home = 1.0
        elif winner == "AWAY":
            p_home = 0.0
        else:
            p_home = win_probability(home_proj, away_proj, home_min, away_min)

        home_pct = round(100 * p_home)
        # An undecided matchup with time left never shows 0/100
        if winner == "UNDECIDED" and (home_min + away_min) > 0:
            home_pct = min(99, max(1, home_pct))
        away_pct = 100 - home_pct

        home_fill = "proj-fill proj-win" if home_pct > away_pct else "proj-fill"
        away_fill = "proj-fill proj-win" if away_pct > home_pct else "proj-fill"

        tooltip = f"Projected final: {home_name} {home_proj:.0f} – {away_proj:.0f} {away_name}"
        if winner == "UNDECIDED" and gap > 0:
            trailer, t_min = (
                (away_name, away_min) if home_live > away_live else (home_name, home_min)
            )
            tooltip += f" · {trailer} needs {gap:.0f} pts with {t_min:.0f} min left"

        html.append(f"""
        <article class="matchup-card">
          <div class="matchup-topline">
            <span>{status}</span>
            <strong>{summary}</strong>
          </div>
          <div class="matchup-projline" title="{tooltip}">
            <span>Win %</span>
            <div class="proj-bar">
              <div class="{home_fill}" style="width:{home_pct}%">{home_pct}%</div>
              <div class="{away_fill}" style="width:{away_pct}%">{away_pct}%</div>
            </div>
          </div>

          <div class="matchup-sides">
            <div class="{home_class}">
              <div class="team-label">Home</div>
              <div class="team-name">{home_name}</div>
              <div class="score">{home_live:.0f}</div>
              <div class="projected{home_proj_class}">Proj final: {home_proj:.0f}</div>
              <div class="games-left">{home_rem:.0f} games · {home_min:.0f} min left</div>
              <div class="finalized">Finalized: {home_final:.0f}</div>
            </div>

            <div class="vs-pill">vs</div>

            <div class="{away_class}">
              <div class="team-label">Away</div>
              <div class="team-name">{away_name}</div>
              <div class="score">{away_live:.0f}</div>
              <div class="projected{away_proj_class}">Proj final: {away_proj:.0f}</div>
              <div class="games-left">{away_rem:.0f} games · {away_min:.0f} min left</div>
              <div class="finalized">Finalized: {away_final:.0f}</div>
            </div>
          </div>
        </article>
        """)

    html.append("</div>")
    html.append("</section>")
    return "\n".join(html)

def team_reports_html(results, week, start, end, all_dates, remaining_dates):
    today = today_et()
    played_dates = [d for d in all_dates if d not in remaining_dates]

    html = []
    html.append('<section class="wnba-team-reports">')
    html.append(f'<h2>Week {week} Player Games Remaining</h2>')
    html.append(f'<p class="week-meta">{start} → {end} | Today: {today}</p>')

    if played_dates:
        html.append(
            f'<p class="played-days">Days already played: {", ".join(played_dates)}</p>'
        )

    for ft, total, proj_total, min_total, proj_min_total, daily_log in results:
        html.append(f"""
        <article class="team-report">
          <header class="team-report-header">
            <h3>{ft["name"]}</h3>
            <div class="header-stats">
              <div class="max-games">
                <strong>{int(total)}</strong> MAX games left
              </div>
              <div class="max-games proj-total">
                <strong>{proj_total:.0f}</strong> proj pts left
              </div>
              <div class="max-games min-total">
                <strong>~{proj_min_total:.0f}</strong> proj min left
              </div>
            </div>
          </header>
        """)

        html.append('<div class="daily-games">')

        for d, slots, out_players in daily_log:
            today_class = " today" if d == today else ""
            today_label = " <span class='today-badge'>Today</span>" if d == today else ""

            html.append(f"""
            <div class="day-card{today_class}">
              <h4>{d}{today_label}</h4>
            """)

            if not slots:
                html.append('<p class="no-games">No startable games</p>')
            else:
                html.append('<ul class="player-list">')
                for slot_label, name, abbrev, proj, opp, game_mins, p_mins in slots:
                    vs = f" title=\"vs {opp} · ~{p_mins:.0f} proj min\"" if opp else ""
                    html.append(f"""
                    <li class="with-proj">
                      <span class="slot">{slot_label}</span>
                      <span class="player-name">{name}</span>
                      <span class="proj"{vs}>{proj:.1f}</span>
                      <span class="team-abbrev">{abbrev}</span>
                    </li>
                    """)
                for name, abbrev in out_players:
                    html.append(f"""
                                <li>
                                    <span class="slot injured">OUT </span>
                                    <span class="player-name injured"> {name}</span>
                                    <span class="team-abbrev injured">{abbrev}</span>
                                </li>""")
                html.append('</ul>')
            html.append('</div>')
        html.append('</div>')
        html.append('</article>')
    html.append('</section>')
    return "\n".join(html)
 
# ── Load ──────────────────────────────────────────────────────────────────────
def load_fantasy(path: Path) -> dict:
    with open(path) as f:
        d = json.load(f)
    if DEBUG:
        print(f"Fantasy data: {d['metadata']['pulled_at_readable']}")
    return d["data"]
 
def load_schedule(path: Path) -> dict:
    with open(path) as f:
        d = json.load(f)
    if DEBUG:
        print(f"Schedule:     fetched {d['fetched_on']}  ({d['total_games']} games)")
    return d["schedule"]
 
# ── CLI ───────────────────────────────────────────────────────────────────────
def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Calculate max startable games remaining for each fantasy team."
    )
    parser.add_argument("--week",      type=int,  default=None,
        help="Matchup week 1–12 (default: current week from data)")
    parser.add_argument("--team",      type=int,  default=None,
        help="Show a single fantasy team by ID")
    parser.add_argument("--all-teams", action="store_true",
        help="Show all fantasy teams")
    parser.add_argument("--full-week", action="store_true",
        help="Calculate over the entire week, not just remaining days")
    parser.add_argument("--no-scoreboard", action="store_true",
        help="Skip the matchup scoreboard, show only the games-remaining breakdown")
    parser.add_argument("--fantasy-file",  type=Path, default=FANTASY_FILE)
    parser.add_argument("--schedule-file", type=Path, default=SCHEDULE_FILE)
    args = parser.parse_args(argv)
 
    fantasy_data = load_fantasy(args.fantasy_file)
    schedule     = load_schedule(args.schedule_file)
 
    # Determine week
    week         = args.week or fantasy_data["status"]["currentMatchupPeriod"]
    start, end   = WEEK_DATES[week]
    all_dates    = dates_in_range(start, end)
    today        = today_et()
    remaining    = all_dates if args.full_week else [d for d in all_dates if d >= today]

    print(f"\nWeek {week}: {start} → {end}")
    if DEBUG:
        print(f"Counting: {'full week' if args.full_week else f'remaining ({len(remaining)} days)'}\n")
 
    # Which fantasy teams to show
    all_teams = {t["id"]: t for t in fantasy_data["teams"]}
 
    if args.all_teams:
        teams_to_show = sorted(all_teams.values(), key=lambda t: t["id"])
    elif args.team:
        if args.team not in all_teams:
            print(f"Team {args.team} not found. Valid IDs: {sorted(all_teams.keys())}")
            return
        teams_to_show = [all_teams[args.team]]
    else:
        # Default: show teams in the week's matchups
        matchups = [m for m in fantasy_data["schedule"] if m.get("matchupPeriodId") == week]
        ids = set()
        for m in matchups:
            ids.add(m["home"]["teamId"])
            ids.add(m["away"]["teamId"])
        teams_to_show = sorted(
            [all_teams[i] for i in ids if i in all_teams],
            key=lambda t: t["id"]
        )
 
    # Summary table header
    if DEBUG:
        print(f"\n{'─'*50}")
        print(f"  {'Team':<35} {'Max Games':>9}")
        print(f"{'─'*50}")
 
    # Defense-vs-position factors for projections (empty dict → neutral 1.0)
    try:
        factors = wnba_defense.get_defense_factors()
    except Exception as e:
        print(f"⚠ Could not load defense factors, using neutral projections: {e}")
        factors = {}

    # Live game clocks for today's games (missing team → assume full 40)
    try:
        live_mins = wnba_defense.live_minutes_by_team(today)
    except Exception as e:
        print(f"⚠ Could not fetch live game clocks: {e}")
        live_mins = {}

    results = []
    for ft in teams_to_show:
        players = get_players(ft)
        total, proj, mins, pmins, log = calc_max_games(
            players, remaining, schedule, factors, live_mins
        )
        results.append((ft, total, proj, mins, pmins, log))
        if DEBUG:
            print(f"  {ft['name']:<35} {total:>9} {proj:>9.1f} {mins:>7.0f} {pmins:>7.0f}")
 
    if DEBUG:
        print(f"{'─'*50}")
 
    html_parts = []
    # Matchup scoreboard (all matchups for the week, not filtered by --team)
    if not args.no_scoreboard:
        max_games_by_id = {ft["id"]: total for ft, total, _, _, _, _ in results}
        proj_left_by_id = {ft["id"]: proj for ft, _, proj, _, _, _ in results}
        min_left_by_id  = {ft["id"]: mins for ft, _, _, mins, _, _ in results}

        def scoreboard(matchups=None, title=None, show_updated=True):
            return matchup_scoreboard_html(
                fantasy_data, week, max_games_by_id, proj_left_by_id, min_left_by_id,
                matchups=matchups, title=title, show_updated=show_updated,
            )

        ss        = fantasy_data["settings"]["scheduleSettings"]
        n_regular = ss["matchupPeriodCount"]
        n_playoff = ss.get("playoffTeamCount", 4)
        teams_by_id = {t["id"]: t for t in fantasy_data["teams"]}

        if week > n_regular:
            # Playoffs: championship bracket + its games, then consolation
            champ_bracket, cons_bracket = playoff_bracket_sections(fantasy_data)
            week_ms = get_week_matchups(fantasy_data, week)
            week_ms.sort(key=lambda m: min(_matchup_seeds(m, teams_by_id) or [99]))
            champ_ms = [m for m in week_ms
                        if is_championship_matchup(m, teams_by_id, n_playoff)]
            cons_ms  = [m for m in week_ms if m not in champ_ms]

            html_parts.append(champ_bracket)
            html_parts.append(scoreboard(champ_ms, f"Championship Matchups — Week {week}"))
            if cons_bracket:
                html_parts.append(cons_bracket)
            if cons_ms:
                html_parts.append(scoreboard(
                    cons_ms, f"Consolation Matchups — Week {week}", show_updated=False
                ))
        else:
            # Bracket preview in the last regular-season week
            if week >= n_regular:
                champ_bracket, cons_bracket = playoff_bracket_sections(fantasy_data)
                html_parts.append(champ_bracket)
                if cons_bracket:
                    html_parts.append(cons_bracket)
            html_parts.append(scoreboard())

        html_parts.append(
            team_reports_html(
                results,
                week,
                start,
                end,
                all_dates,
                remaining,
            )
        )

        for team in TEAM_COUNT:
            TEAM_COUNT[team] = len(TEAM_COUNT[team])
        invert = {}
        for key, value in TEAM_COUNT.items():
            if value not in invert:
                invert[value] = []
            invert[value].append(key)
        html_parts.append('<ul class="player-list">')

        html_parts.append("<h3>Games left for each team</h3>")
        for value, teams in invert.items():
            html_parts.append(f"<p>Teams with {value} games left:</p>")
            for team in teams:
                html_parts.append(f"""
                        <li>
                        {team}
                        </li>
                        """)

        output_file = paths.DOCS / "_includes" / "wnba_fantasy_matchups.html"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n\n".join(html_parts))
        if DEBUG:
            print(f"Wrote HTML to {output_file}")
        
if __name__ ==" __main__":
    main()
    
# WNBA
def wnba_update():
    # update schedule (5 requests an hour max)
    wnba_schedule.main(["--refresh"])
    wnba_fantasy.fetch_and_save()
    # refresh defense-vs-position cache (only fetches new final games)
    try:
        wnba_defense.update_cache()
    except Exception as e:
        print(f"⚠ Defense cache update failed: {e}")
    main()