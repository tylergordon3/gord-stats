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
from cbb.wnba import wnba_schedule
from cbb.wnba import wnba_fantasy

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
            "is_out":  player.get("injuryStatus", "ACTIVE") == "OUT",
        })
    return players
 
# ── Core optimizer ────────────────────────────────────────────────────────────
def calc_max_games(players: list[dict], dates: list[str], schedule: dict) -> tuple[int, list]:
    """
    Greedy day-by-day slot filler. For each date:
      1. Fill up to 2 G slots from active guards with a game that day
      2. Fill up to 3 F/C slots from active forwards/centers with a game that day
      3. Fill 1 UTIL slot from any remaining active player with a game that day
 
    OUT players are excluded from slot counts but appear in the daily log
    with is_out=True so the display layer can highlight them.
 
    Returns (total_max_games, daily_log).
    daily_log is a list of (date_str, slots_filled, out_players) where:
      slots_filled = list of (slot_label, player_name, abbrev)
      out_players  = list of (player_name, abbrev) who have a game but are OUT
    """
    total  = 0
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
 
        guards = [p for p in active if p["is_g"]]
        fcs    = [p for p in active if p["is_fc"]]
 
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
        for p in active:
            if len([s for s in slots if s[0] == "UTIL"]) >= UTIL_LIMIT:
                break
            if p["name"] not in used:
                used.add(p["name"])
                slots.append(("UTIL", p["name"], p["abbrev"]))
 
        total += len(slots)
        daily_log.append((d, slots, [(p["name"], p["abbrev"]) for p in out_today]))
    return total, daily_log
 
# ── Matchup comparison ────────────────────────────────────────────────────────
def get_week_matchups(fantasy_data: dict, week: int) -> list[dict]:
    """Return matchup objects for the given week."""
    return [m for m in fantasy_data["schedule"] if m.get("matchupPeriodId") == week]
 
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
            summary = f"{home_name} leads by {gap:.0f}"
        elif away_live > home_live:
            home_class, away_class = "team-side", "team-side leader"
            summary = f"{away_name} leads by {gap:.0f}"
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
              <div class="score">{home_live:.0f}</div>
              <div class="games-left">{home_rem:.0f} games left</div>
              <div class="finalized">Finalized: {home_final:.0f}</div>
            </div>

            <div class="vs-pill">vs</div>

            <div class="{away_class}">
              <div class="team-label">Away</div>
              <div class="team-name">{away_name}</div>
              <div class="score">{away_live:.0f}</div>
              <div class="games-left">{away_rem:.0f} games left</div>
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

    for ft, total, daily_log in results:
        html.append(f"""
        <article class="team-report">
          <header class="team-report-header">
            <h3>{ft["name"]}</h3>
            <div class="max-games">
              <strong>{int(total)}</strong> MAX games left
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
                for slot_label, name, abbrev in slots:
                    html.append(f"""
                    <li>
                      <span class="slot">{slot_label}</span>
                      <span class="player-name">{name}</span>
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
 
    results = []
    for ft in teams_to_show:
        players        = get_players(ft)
        total, log     = calc_max_games(players, remaining, schedule)
        results.append((ft, total, log))
        if DEBUG:
            print(f"  {ft['name']:<35} {total:>9}")
 
    if DEBUG:
        print(f"{'─'*50}")
 
    html_parts = []
    # Matchup scoreboard (all matchups for the week, not filtered by --team)
    if not args.no_scoreboard:
        max_games_by_id = {ft["id"]: total for ft, total, _ in results}
        html_parts.append(
            matchup_scoreboard_html(fantasy_data, week, max_games_by_id)
        )

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
    main()