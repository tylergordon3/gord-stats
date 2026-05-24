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
from datetime import date, datetime, timedelta
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
    """Returns teams with a game that has not yet been played on date_str."""
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
    parser.add_argument("--html", type=Path, default=None, metavar="FILE",
        help="Also write an HTML report to FILE (e.g. --html report.html)")
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
 
    # Matchup scoreboard (all matchups for the week, not filtered by --team)
    if not args.no_scoreboard:
        max_games_by_id = {ft["id"]: total for ft, total, _ in results}
        # If showing a single team, still compute the opponent's max games
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
        print_matchup_scoreboard(fantasy_data, week, max_games_by_id)
 
    # Detailed breakdown per team
    for ft, total, log in results:
        print_team_report(ft, total, log, week, start, end, all_dates, remaining)

    # HTML output
    if args.html:
        # Attach metadata so build_html can show pulled_at
        fantasy_data["metadata"] = json.load(open(args.fantasy_file))["metadata"]
        html = build_html(
            fantasy_data, week, start, end, all_dates, remaining,
            results, max_games_by_id,
        )
        args.html.write_text(html)
        print(f"\nHTML report written → {args.html}")
 
 
# ── HTML output ───────────────────────────────────────────────────────────────

def _slot_color(slot_label: str) -> str:
    return {"G": "#e8f4fd", "F/C": "#fef3e8", "UTIL": "#f0fde8"}.get(slot_label, "#f8f8f8")

def build_html(
    fantasy_data: dict,
    week: int,
    start: str,
    end: str,
    all_dates: list,
    remaining: list,
    results: list,
    max_games_by_id: dict,
) -> str:
    today      = today_et()
    pulled_at  = fantasy_data.get("metadata", {}).get("pulled_at_readable", "")
    all_teams  = {t["id"]: t["name"] for t in fantasy_data["teams"]}
    matchups   = get_week_matchups(fantasy_data, week)

    # ── matchup cards html ────────────────────────────────────────────────────
    matchup_cards = ""
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
        home_rem   = max_games_by_id.get(home_id, 0)
        away_rem   = max_games_by_id.get(away_id, 0)
        winner     = m.get("winner", "UNDECIDED")
        gap        = abs(home_live - away_live)

        home_winning = home_live > away_live
        away_winning = away_live > home_live

        status_label = "FINAL" if winner != "UNDECIDED" else ("🔴 LIVE" if live_today else "IN PROGRESS")
        status_class = "final" if winner != "UNDECIDED" else ("live" if live_today else "progress")

        win_name = ""
        if winner != "UNDECIDED":
            win_name = home_name if winner == "HOME" else away_name
            summary = f'{win_name} wins by {gap:.1f} pts'
        else:
            leader = home_name if home_live >= away_live else away_name
            summary = f'{leader} leads by {gap:.1f} pts'
            if live_today:
                summary += f' <span class="live-note">(live · finalized: {home_name} {home_final:.1f} / {away_name} {away_final:.1f})</span>'

        def team_row(name, live, rem, winning, tid):
            w_class = "winning" if winning else ""
            arrow   = "▲" if winning else ""
            return f"""
            <div class="team-row {w_class}">
                <span class="arrow">{arrow}</span>
                <span class="team-name">{name}</span>
                <span class="pts">{live:.1f}</span>
                <span class="rem-badge">{rem}G left</span>
            </div>"""

        matchup_cards += f"""
        <div class="matchup-card">
            <div class="matchup-status {status_class}">{status_label}</div>
            {team_row(home_name, home_live, home_rem, home_winning, home_id)}
            {team_row(away_name, away_live, away_rem, away_winning, away_id)}
            <div class="matchup-summary">{summary}</div>
        </div>"""

    # ── team detail cards ─────────────────────────────────────────────────────
    team_cards = ""
    for ft, total, daily_log in results:
        max_possible = len(remaining) * (G_LIMIT + FC_LIMIT + UTIL_LIMIT)

        day_rows = ""
        for d, slots in daily_log:
            is_today = d == today
            today_cls = " today-row" if is_today else ""
            if not slots:
                day_rows += f'<div class="day-row{today_cls}"><span class="day-label">{d}</span><span class="no-games">— no games</span></div>'
            else:
                slot_pills = "".join(
                    f'<span class="pill pill-{sl.lower().replace("/","")}" style="background:{_slot_color(sl)}">'
                    f'<b>{sl}</b> {name} <span class="abbrev">({abbrev})</span></span>'
                    for sl, name, abbrev in slots
                )
                today_badge = '<span class="today-badge">TODAY</span>' if is_today else ""
                day_rows += f'<div class="day-row{today_cls}"><span class="day-label">{d}{today_badge}</span><div class="slots">{slot_pills}</div></div>'

        pct = int((total / max_possible * 100)) if max_possible else 0
        team_cards += f"""
        <div class="team-card">
            <div class="team-header">
                <span class="team-title">{ft["name"]}</span>
                <span class="games-badge">{total} / {max_possible} games</span>
            </div>
            <div class="progress-bar-wrap">
                <div class="progress-bar-fill" style="width:{pct}%"></div>
            </div>
            <div class="day-log">{day_rows}</div>
        </div>"""

    # ── full page ─────────────────────────────────────────────────────────────
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WNBA Fantasy — Week {week}</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Barlow+Condensed:wght@400;600;800&family=Barlow:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg:        #0d0f14;
    --surface:   #161a22;
    --surface2:  #1e2330;
    --border:    #2a3040;
    --accent:    #ff6b35;
    --accent2:   #ffc947;
    --green:     #3ddc84;
    --red:       #ff4757;
    --text:      #e8eaf0;
    --muted:     #8892a4;
    --g-color:   #3b82f6;
    --fc-color:  #f59e0b;
    --util-color:#10b981;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: 'Barlow', sans-serif;
    min-height: 100vh;
    padding: 0 0 60px;
  }}

  /* ── header ── */
  header {{
    background: linear-gradient(135deg, #0d0f14 0%, #1a1f2e 50%, #0d1520 100%);
    border-bottom: 2px solid var(--accent);
    padding: 32px 40px 24px;
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 16px;
  }}
  .header-left h1 {{
    font-family: 'Barlow Condensed', sans-serif;
    font-size: clamp(2rem, 5vw, 3.5rem);
    font-weight: 800;
    letter-spacing: -0.5px;
    line-height: 1;
    color: #fff;
  }}
  .header-left h1 span {{ color: var(--accent); }}
  .week-badge {{
    font-family: 'Barlow Condensed', sans-serif;
    font-size: 1rem;
    font-weight: 600;
    letter-spacing: 2px;
    color: var(--muted);
    text-transform: uppercase;
    margin-top: 6px;
  }}
  .header-meta {{
    text-align: right;
    font-family: 'DM Mono', monospace;
    font-size: 0.75rem;
    color: var(--muted);
    line-height: 1.8;
  }}

  /* ── layout ── */
  .container {{ max-width: 1200px; margin: 0 auto; padding: 0 24px; }}
  .section-title {{
    font-family: 'Barlow Condensed', sans-serif;
    font-size: 1.1rem;
    font-weight: 600;
    letter-spacing: 3px;
    text-transform: uppercase;
    color: var(--muted);
    margin: 40px 0 16px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border);
  }}

  /* ── matchup grid ── */
  .matchup-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 16px;
  }}
  .matchup-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    transition: border-color .2s;
  }}
  .matchup-card:hover {{ border-color: var(--accent); }}
  .matchup-status {{
    font-family: 'Barlow Condensed', sans-serif;
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 2px;
    text-transform: uppercase;
    padding: 3px 8px;
    border-radius: 4px;
    align-self: flex-start;
  }}
  .matchup-status.final    {{ background: #1e2a1e; color: var(--green); }}
  .matchup-status.live     {{ background: #2a1a1a; color: var(--red); animation: pulse 1.5s infinite; }}
  .matchup-status.progress {{ background: #2a2510; color: var(--accent2); }}
  @keyframes pulse {{ 0%,100% {{ opacity:1 }} 50% {{ opacity:.5 }} }}

  .team-row {{
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 12px;
    border-radius: 8px;
    background: var(--surface2);
    border: 1px solid transparent;
    transition: all .15s;
  }}
  .team-row.winning {{
    border-color: var(--accent);
    background: #1e1812;
  }}
  .arrow {{ width: 14px; color: var(--accent); font-size: 0.8rem; }}
  .team-name {{ flex: 1; font-size: 0.9rem; font-weight: 500; }}
  .pts {{
    font-family: 'DM Mono', monospace;
    font-size: 1rem;
    font-weight: 500;
    color: var(--accent2);
  }}
  .rem-badge {{
    font-family: 'DM Mono', monospace;
    font-size: 0.7rem;
    padding: 2px 7px;
    border-radius: 20px;
    background: var(--surface);
    border: 1px solid var(--border);
    color: var(--muted);
    white-space: nowrap;
  }}
  .matchup-summary {{
    font-size: 0.8rem;
    color: var(--muted);
    padding-top: 4px;
  }}
  .live-note {{ color: var(--muted); font-style: italic; }}

  /* ── team detail cards ── */
  .teams-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(500px, 1fr));
    gap: 20px;
  }}
  .team-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    overflow: hidden;
    transition: border-color .2s;
  }}
  .team-card:hover {{ border-color: var(--border); }}
  .team-header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 20px;
    border-bottom: 1px solid var(--border);
    background: var(--surface2);
  }}
  .team-title {{
    font-family: 'Barlow Condensed', sans-serif;
    font-size: 1.2rem;
    font-weight: 700;
    letter-spacing: 0.3px;
  }}
  .games-badge {{
    font-family: 'DM Mono', monospace;
    font-size: 0.8rem;
    padding: 4px 10px;
    border-radius: 20px;
    background: var(--bg);
    border: 1px solid var(--accent);
    color: var(--accent);
  }}
  .progress-bar-wrap {{
    height: 3px;
    background: var(--border);
  }}
  .progress-bar-fill {{
    height: 100%;
    background: linear-gradient(90deg, var(--accent), var(--accent2));
    transition: width .6s ease;
  }}
  .day-log {{ padding: 12px 16px; display: flex; flex-direction: column; gap: 8px; }}
  .day-row {{
    display: flex;
    align-items: flex-start;
    gap: 12px;
    padding: 8px 10px;
    border-radius: 6px;
    border: 1px solid transparent;
  }}
  .day-row.today-row {{
    background: #161d28;
    border-color: #2a3d58;
  }}
  .day-label {{
    font-family: 'DM Mono', monospace;
    font-size: 0.72rem;
    color: var(--muted);
    white-space: nowrap;
    padding-top: 3px;
    min-width: 90px;
    display: flex;
    align-items: center;
    gap: 6px;
  }}
  .today-badge {{
    font-family: 'Barlow Condensed', sans-serif;
    font-size: 0.6rem;
    font-weight: 700;
    letter-spacing: 1px;
    padding: 1px 5px;
    border-radius: 3px;
    background: var(--accent);
    color: #fff;
  }}
  .no-games {{ font-size: 0.8rem; color: var(--border); font-style: italic; }}
  .slots {{ display: flex; flex-wrap: wrap; gap: 6px; }}
  .pill {{
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 0.75rem;
    padding: 3px 8px;
    border-radius: 20px;
    border: 1px solid rgba(0,0,0,0.1);
    color: #1a1a1a;
    font-family: 'Barlow', sans-serif;
  }}
  .pill b {{ font-weight: 700; font-family: 'DM Mono', monospace; font-size: 0.65rem; }}
  .abbrev {{ color: #555; font-size: 0.68rem; }}

  /* legend */
  .legend {{
    display: flex; gap: 16px; flex-wrap: wrap;
    margin: 20px 0 0;
    font-size: 0.78rem;
    color: var(--muted);
    align-items: center;
  }}
  .legend-item {{ display: flex; align-items: center; gap: 6px; }}
  .legend-dot {{
    width: 10px; height: 10px; border-radius: 50%;
  }}
  footer {{
    text-align: center;
    color: var(--muted);
    font-family: 'DM Mono', monospace;
    font-size: 0.72rem;
    margin-top: 60px;
    padding-top: 20px;
    border-top: 1px solid var(--border);
  }}
</style>
</head>
<body>

<header>
  <div class="header-left">
    <h1>WNBA <span>Fantasy</span></h1>
    <div class="week-badge">Week {week} &nbsp;·&nbsp; {start} – {end}</div>
  </div>
  <div class="header-meta">
    Generated {today}<br>
    Data pulled {pulled_at}<br>
    {len(remaining)} day(s) remaining
  </div>
</header>

<div class="container">

  <div class="section-title">Matchups</div>
  <div class="matchup-grid">
    {matchup_cards}
  </div>

  <div class="section-title">Max Startable Games Remaining</div>
  <div class="legend">
    <span>Slot colors:</span>
    <span class="legend-item"><span class="legend-dot" style="background:#3b82f6"></span> G</span>
    <span class="legend-item"><span class="legend-dot" style="background:#f59e0b"></span> F/C</span>
    <span class="legend-item"><span class="legend-dot" style="background:#10b981"></span> UTIL</span>
  </div>
  <div class="teams-grid" style="margin-top:16px">
    {team_cards}
  </div>

</div>

<footer>
  wnba_remaining.py &nbsp;·&nbsp; data via ESPN Fantasy &amp; BallDontLie
</footer>

</body>
</html>"""



if __name__ == "__main__":
    main()