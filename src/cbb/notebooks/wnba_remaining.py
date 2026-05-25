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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from cbb.lib import paths

ET = ZoneInfo("America/New_York")
 
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
    10: ("2026-07-20", "2026-07-26"),
    11: ("2026-07-27", "2026-08-02"),
    12: ("2026-08-03", "2026-09-14"),
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
        })
    return players
 
# ── Core optimizer ────────────────────────────────────────────────────────────
 
def calc_max_games(players: list[dict], dates: list[str], schedule: dict) -> tuple[int, list]:
    """
    Greedy day-by-day slot filler. For each date:
      1. Fill up to 2 G slots from guards with a game that day
      2. Fill up to 3 F/C slots from forwards/centers with a game that day
      3. Fill 1 UTIL slot from any remaining player with a game that day
 
    Returns (total_max_games, daily_log).
    daily_log is a list of (date_str, slots_filled) where slots_filled is
    a list of (slot_label, player_name, abbrev).
    """
    total  = 0
    daily_log = []
 
    for d in dates:
        playing   = teams_playing_on(schedule, d)
        available = [p for p in players if p["abbrev"] in playing]
 
        guards = [p for p in available if p["is_g"]]
        fcs    = [p for p in available if p["is_fc"]]
 
        used   = set()
        slots  = []
 
        # Guards
        for p in guards:
            if len([s for s in slots if s[0] == "G"]) >= G_LIMIT:
                break
            used.add(p["name"])
            slots.append(("G", p["name"], p["abbrev"]))
 
        # F/C
        for p in fcs:
            if len([s for s in slots if s[0] == "F/C"]) >= FC_LIMIT:
                break
            used.add(p["name"])
            slots.append(("F/C", p["name"], p["abbrev"]))
 
        # UTIL — any unused player with a game
        for p in available:
            if len([s for s in slots if s[0] == "UTIL"]) >= UTIL_LIMIT:
                break
            if p["name"] not in used:
                used.add(p["name"])
                slots.append(("UTIL", p["name"], p["abbrev"]))
 
        total += len(slots)
        daily_log.append((d, slots))
 
    return total, daily_log
 
# ── Matchup comparison ────────────────────────────────────────────────────────
 
def get_week_matchups(fantasy_data: dict, week: int) -> list[dict]:
    """Return matchup objects for the given week."""
    return [m for m in fantasy_data["schedule"] if m.get("matchupPeriodId") == week]
 
def print_matchup_scoreboard(fantasy_data: dict, week: int, max_games: dict[int, int]) -> None:
    """
    Print a head-to-head scoreboard for every matchup in the week.
 
    max_games: { fantasy_team_id: max_games_remaining }
 
    Scoring note:
        totalPoints     = finalized points (excludes any live/current scoring period)
        totalPointsLive = includes the current live scoring period
    We display totalPointsLive as the live score and note the finalized separately.
    """
    matchups   = get_week_matchups(fantasy_data, week)
    all_teams  = {t["id"]: t["name"] for t in fantasy_data["teams"]}
 
    print(f"\n{'═'*62}")
    print(f"  WEEK {week} MATCHUPS — LIVE SCOREBOARD")
    print(f"{'═'*62}")
 
    for m in matchups:
        home_id    = m["home"]["teamId"]
        away_id    = m["away"]["teamId"]
        home_name  = all_teams.get(home_id, f"Team {home_id}")
        away_name  = all_teams.get(away_id, f"Team {away_id}")
 
        home_live  = m["home"].get("totalPointsLive", 0) or 0
        away_live  = m["away"].get("totalPointsLive", 0) or 0
        home_final = m["home"].get("totalPoints", 0) or 0
        away_final = m["away"].get("totalPoints", 0) or 0
        live_today = home_live != home_final or away_live != away_final
 
        home_rem   = max_games.get(home_id, 0)
        away_rem   = max_games.get(away_id, 0)
        winner     = m.get("winner", "UNDECIDED")
 
        # Who's leading on live score
        if home_live > away_live:
            home_lead, away_lead = "▲", " "
        elif away_live > home_live:
            home_lead, away_lead = " ", "▲"
        else:
            home_lead = away_lead = "–"
 
        print(f"\n  {'─'*58}")
        print(f"  {'FINAL' if winner != 'UNDECIDED' else 'IN PROGRESS'}")
        print(f"  {'─'*58}")
 
        # Home row
        print(
            f"  {home_lead} {home_name:<33}"
            f"  {home_live:>7.1f} pts"
            f"  {home_rem:>2} games left"
        )
        # Away row
        print(
            f"  {away_lead} {away_name:<33}"
            f"  {away_live:>7.1f} pts"
            f"  {away_rem:>2} games left"
        )
 
        # Gap line
        gap = abs(home_live - away_live)
        if winner != "UNDECIDED":
            win_name = home_name if winner == "HOME" else away_name
            print(f"\n  Winner: {win_name}  (by {gap:.1f} pts)")
        else:
            leading  = home_name if home_live >= away_live else away_name
            trailing = away_name if home_live >= away_live else home_name
            print(f"\n  {leading} leads by {gap:.1f} pts", end="")
            if live_today:
                live_diff = home_live - home_final if home_live != home_final else away_live - away_final
                print(f"  (includes live scoring)", end="")
            print()
            # Finalized-only note if there's live activity
            if live_today:
                print(f"  Finalized only → {home_name}: {home_final:.1f}  |  {away_name}: {away_final:.1f}")
 
    print(f"\n  {'═'*58}\n")
 
def matchup_scoreboard_html(fantasy_data, week, max_games):
    matchups = get_week_matchups(fantasy_data, week)
    all_teams = {t["id"]: t["name"] for t in fantasy_data["teams"]}

    time_obj = datetime.now(ET)
    time = time_obj.strftime("Last Update: %A %m/%d/%y %I:%M %p")

    html = []
    html.append('<section class="wnba-fantasy-week">')
    html.append(f'<h2>Week {week} Matchups</h2>')
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

        winner = m.get("winner", "UNDECIDED")
        status = "Final" if winner != "UNDECIDED" else "In Progress"

        gap = abs(home_live - away_live)

        if home_live > away_live:
            home_class, away_class = "team-side leader", "team-side"
            summary = f"{home_name} leads by {gap:.1f}"
        elif away_live > home_live:
            home_class, away_class = "team-side", "team-side leader"
            summary = f"{away_name} leads by {gap:.1f}"
        else:
            home_class = away_class = "team-side tied"
            summary = "Tied"

        html.append(f"""
        <article class="matchup-card">
          <div class="matchup-topline">
            <span>{status}</span>
            <strong>{summary}</strong>
          </div>

          <div class="matchup-sides">
            <div class="{home_class}">
              <div class="team-label">Home</div>
              <div class="team-name">{home_name}</div>
              <div class="score">{home_live:.1f}</div>
              <div class="games-left">{home_rem} games left</div>
              <div class="finalized">Finalized: {home_final:.1f}</div>
            </div>

            <div class="vs-pill">vs</div>

            <div class="{away_class}">
              <div class="team-label">Away</div>
              <div class="team-name">{away_name}</div>
              <div class="score">{away_live:.1f}</div>
              <div class="games-left">{away_rem} games left</div>
              <div class="finalized">Finalized: {away_final:.1f}</div>
            </div>
          </div>
        </article>
        """)

    html.append("</div>")
    html.append("</section>")
    return "\n".join(html)

# ── Display ───────────────────────────────────────────────────────────────────
 
def print_team_report(
    fantasy_team: dict,
    total: int,
    daily_log: list,
    week: int,
    start: str,
    end: str,
    all_dates: list[str],
    remaining_dates: list[str],
) -> None:
    played_dates = [d for d in all_dates if d not in remaining_dates]
    today = today_et()
    print(f"  Team {fantasy_team['id']}: {fantasy_team['name']}")
    print(f"  Week {week}  ({start} → {end})")
    print(f"  Today: {today}  |  Days left: {len(remaining_dates)}")
    print(f"{'═'*60}")
 
    if played_dates:
        print(f"\n  (Days already played: {', '.join(played_dates)})")
 
    max_possible = len(remaining_dates) * (G_LIMIT + FC_LIMIT + UTIL_LIMIT)
    print(f"\n  MAX STARTABLE GAMES REMAINING: {total}  (cap: {max_possible})")
    print()
 
    for d, slots in daily_log:
        label = " ◀ today" if d == today else ""
        if not slots:
            print(f"  {d}  — no games{label}")
        else:
            print(f"  {d}{label}")
            for slot_label, name, abbrev in slots:
                print(f"    [{slot_label:<4}]  {name} ({abbrev})")
 
    print()

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

    for ft, total, daily_log in results:
        max_possible = len(remaining_dates) * (G_LIMIT + FC_LIMIT + UTIL_LIMIT)

        html.append(f"""
        <article class="team-report">
          <header class="team-report-header">
            <h3>{ft["name"]}</h3>
            <div class="max-games">
              <strong>{total}</strong> startable games
            </div>
          </header>
        """)

        html.append('<div class="daily-games">')

        for d, slots in daily_log:
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
                for slot_label, name, abbrev in slots:
                    html.append(f"""
                    <li>
                      <span class="slot">{slot_label}</span>
                      <span class="player-name">{name}</span>
                      <span class="team-abbrev">{abbrev}</span>
                    </li>
                    """)
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
    print(f"Fantasy data: {d['metadata']['pulled_at_readable']}")
    return d["data"]
 
def load_schedule(path: Path) -> dict:
    with open(path) as f:
        d = json.load(f)
    print(f"Schedule:     fetched {d['fetched_on']}  ({d['total_games']} games)")
    return d["schedule"]
 
# ── CLI ───────────────────────────────────────────────────────────────────────
 
def main():
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
    args = parser.parse_args()
 
    fantasy_data = load_fantasy(args.fantasy_file)
    schedule     = load_schedule(args.schedule_file)
 
    # Determine week
    week         = args.week or fantasy_data["status"]["currentMatchupPeriod"]
    start, end   = WEEK_DATES[week]
    all_dates    = dates_in_range(start, end)
    today        = today_et()
    remaining    = all_dates if args.full_week else [d for d in all_dates if d >= today]
 
    print(f"\nWeek {week}: {start} → {end}")
    print(f"Counting: {'full week' if args.full_week else f'remaining ({len(remaining)} days)'}")
 
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
    print(f"\n{'─'*50}")
    print(f"  {'Team':<35} {'Max Games':>9}")
    print(f"{'─'*50}")
 
    results = []
    for ft in teams_to_show:
        players        = get_players(ft)
        total, log     = calc_max_games(players, remaining, schedule)
        results.append((ft, total, log))
        print(f"  {ft['name']:<35} {total:>9}")
 
    print(f"{'─'*50}")
 
    html_parts = []
    # Matchup scoreboard (all matchups for the week, not filtered by --team)
    if not args.no_scoreboard:
        max_games_by_id = {ft["id"]: total for ft, total, _ in results}
        html_parts.append(
            matchup_scoreboard_html(fantasy_data, week, max_games_by_id)
        )
        # If showing a single team, still compute the opponent's max games
        '''
        if args.team:
            all_t = {t["id"]: t for t in fantasy_data["teams"]}
            matchups = [m for m in fantasy_data["schedule"] if m.get("matchupPeriodId") == week]
            for m in matchups:
                for side in ("home", "away"):
                    tid = m[side]["teamId"]
                    if tid not in max_games_by_id:
                        ft_extra = all_t.get(tid)
                        if ft_extra:
                            p = get_players(ft_extra)
                            t, _ = calc_max_games(p, remaining, schedule)
                            max_games_by_id[tid] = t
        '''
        # print_matchup_scoreboard(fantasy_data, week, max_games_by_id)

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

        output_file = paths.DOCS / "_includes" / "wnba_fantasy_matchups.html"

        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n\n".join(html_parts))

        print(f"Wrote HTML to {output_file}")
            
    # Detailed breakdown per team
    # for ft, total, log in results:
    #    print_team_report(ft, total, log, week, start, end, all_dates, remaining)
 
 
if __name__ == "__main__":
    main()