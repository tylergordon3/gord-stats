"""
wnba_pickups.py
---------------
Suggested free-agent pickups for the current fantasy matchup period.

Candidates are players on no fantasy roster (free agents + waivers) who are
not OUT. Each is ranked by projected total fantasy points over their team's
remaining games this matchup period, so games-left and per-game scoring both
drive the ranking.

The per-game estimate leans on recent evidence over season-long averages:
    form     = 0.65 * last-14-day avg  +  0.35 * season avg
    baseline = form * opponent defense factor (vs the player's position group)
    estimate = 0.5 * avg vs THAT opponent this season + 0.5 * baseline
               (falls back to just the baseline when they haven't met yet;
                the vs-opponent half is used raw — it already embeds the
                opponent, so no defense factor on top)

Game history comes from the box scores cached by wnba_defense; availability,
injury status and season averages come from the ESPN fantasy API.
"""

import json
from datetime import date, timedelta

import requests

from cbb.wnba import wnba_defense, wnba_fantasy
from cbb.wnba import wnba_remaining as wr

RECENT_DAYS = 14
W_RECENT    = 0.65  # last-14 weight vs season average in "form"
W_VS_OPP    = 0.5   # weight of the head-to-head average when it exists
MAX_ROWS    = 20
FA_LIMIT    = 150

# Only suggest players who are demonstrably playing: enough box-score
# appearances this season, with the latest not too long ago. This screens out
# the retired/overseas/season-long-injured names ESPN still lists as ACTIVE
# free agents (with tempting preseason projections but zero 2026 games).
MIN_SEASON_GAMES = 3
MAX_IDLE_DAYS    = 21


# ── Free agents ───────────────────────────────────────────────────────────────

def fetch_free_agents(league_id: int = wnba_fantasy.LEAGUE_ID,
                      season: int = wnba_fantasy.SEASON,
                      limit: int = FA_LIMIT) -> list[dict]:
    """Rostered-nowhere players from ESPN, most-owned first."""
    url = (f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/wfba/"
           f"seasons/{season}/segments/0/leagues/{league_id}")
    flt = {"players": {
        "filterStatus": {"value": ["FREEAGENT", "WAIVERS"]},
        "limit": limit,
        "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
    }}

    cookies = wnba_fantasy.get_espn_cookies()
    s = requests.Session()
    s.cookies.set("espn_s2", cookies["espn_s2"], domain=".espn.com")
    s.cookies.set("SWID", cookies["SWID"], domain=".espn.com")
    r = s.get(url, params={"view": "kona_player_info"},
              headers={**wnba_fantasy.HEADERS, "X-Fantasy-Filter": json.dumps(flt)},
              timeout=20)
    r.raise_for_status()

    out = []
    for entry in r.json().get("players", []):
        p = entry["player"]
        es = p.get("eligibleSlots", [])
        out.append({
            "name":       p["fullName"],
            "abbrev":     wr.TEAM_DICT.get(str(p.get("proTeamId")), None),
            "injury":     p.get("injuryStatus", "ACTIVE"),
            "is_g":       wr.G_SLOT in es,
            "is_fc":      wr.FC_SLOT in es,
            "own_pct":    p.get("ownership", {}).get("percentOwned", 0.0),
            "season_avg": _actual_season_avg(p, season),
        })
    return out


def _actual_season_avg(p: dict, season: int) -> float:
    """
    This-season average from real games only. Deliberately NOT
    wr.get_avg_points, whose fallback to ESPN's preseason projection is
    right for rostered players but would rank never-played free agents
    (e.g. an 18.6 'average' for a player with zero 2026 games).
    """
    for s in p.get("stats", []):
        if s["id"] == f"00{season}" and s.get("appliedAverage"):
            return s["appliedAverage"]
    return 0.0


def pos_label(p: dict) -> str:
    slots = [s for s, ok in (("G", p["is_g"]), ("F/C", p["is_fc"])) if ok]
    return "/".join(slots) or "—"


# ── Ranking ───────────────────────────────────────────────────────────────────

def _mean(vals):
    return sum(vals) / len(vals) if vals else None


def remaining_games(schedule: dict, abbrev: str, dates: list[str]) -> list[tuple[str, str]]:
    """[(date, opponent), ...] not yet played, in matchup-period order."""
    games = []
    for d in dates:
        opp = wr.opponent_on(schedule, d, abbrev)
        if opp:
            games.append((d, opp))
    return games


def project_pickup(player: dict, games: list[tuple[str, str]],
                   factors: dict, log_entries: list[dict], today: str) -> dict:
    """Fill in recent form, per-opponent estimates and projected totals."""
    cutoff = (date.fromisoformat(today) - timedelta(days=RECENT_DAYS)).isoformat()
    grp = "G" if player["is_g"] else "FC"

    recent_avg = _mean([e["pts"] for e in log_entries if e["date"] >= cutoff])
    season_avg = player["season_avg"] or _mean([e["pts"] for e in log_entries]) or 0.0

    if recent_avg is not None:
        form = W_RECENT * recent_avg + (1 - W_RECENT) * season_avg
    else:
        form = season_avg

    total = 0.0
    for _, opp in games:
        baseline = form * factors.get(opp, {}).get(grp, 1.0)
        vs_avg = _mean([e["pts"] for e in log_entries if e["opp"] == opp])
        if vs_avg is not None:
            est = W_VS_OPP * vs_avg + (1 - W_VS_OPP) * baseline
        else:
            est = baseline
        total += est

    n = len(games)
    return {
        **player,
        "pos":        pos_label(player),
        "n_games":    n,
        "opps":       [o for _, o in games],
        "recent_avg": recent_avg,
        "season_avg": season_avg,
        "proj_pg":    total / n if n else 0.0,
        "proj_total": total,
    }


def build_pickups(schedule: dict, week: int, factors: dict,
                  today: str, max_rows: int = MAX_ROWS) -> list[dict]:
    start, end = wr.WEEK_DATES[week]
    dates = [d for d in wr.dates_in_range(start, end) if d >= today]
    log = wnba_defense.player_game_log()

    idle_cutoff = (date.fromisoformat(today) - timedelta(days=MAX_IDLE_DAYS)).isoformat()

    rows = []
    for p in fetch_free_agents():
        if p["injury"] == "OUT" or not p["abbrev"]:
            continue
        entries = log.get(p["name"], [])
        # Must actually be playing: enough games, recently (entries are sorted)
        if len(entries) < MIN_SEASON_GAMES or entries[-1]["date"] < idle_cutoff:
            continue
        games = remaining_games(schedule, p["abbrev"], dates)
        if not games:
            continue
        rows.append(project_pickup(p, games, factors, entries, today))

    rows.sort(key=lambda r: -r["proj_total"])
    return rows[:max_rows]


# ── HTML ──────────────────────────────────────────────────────────────────────

def suggested_pickups_html(rows: list[dict], week: int) -> str:
    html = ['<section class="wnba-pickups">', "<h2>Suggested Pickups</h2>"]
    html.append(
        '<p class="week-meta">Available players ranked by projected fantasy points '
        f"over their remaining Week {week} games — recent form and history vs "
        "upcoming opponents weigh above season averages</p>"
    )

    if not rows:
        html.append('<p class="no-games">No startable free agents with games left.</p>')
        html.append("</section>")
        return "\n".join(html)

    html.append('<div class="table-scroll"><table class="pickups-table">')
    html.append(
        "<thead><tr>"
        "<th>#</th><th>Player</th><th>Pos</th><th>Team</th>"
        "<th>Games left</th><th>Opponents</th>"
        "<th>Szn avg</th><th>L14 avg</th><th>Proj/gm</th><th>Proj total</th>"
        "</tr></thead><tbody>"
    )
    for i, r in enumerate(rows, 1):
        tag = (f' <span class="inj-tag">{r["injury"].replace("_", "-")}</span>'
               if r["injury"] not in ("ACTIVE",) else "")
        l14 = f'{r["recent_avg"]:.1f}' if r["recent_avg"] is not None else "—"
        html.append(
            "<tr>"
            f"<td>{i}</td>"
            f'<td class="pickup-name">{r["name"]}{tag}</td>'
            f"<td>{r['pos']}</td>"
            f'<td class="team-abbrev">{r["abbrev"]}</td>'
            f"<td>{r['n_games']}</td>"
            f'<td class="pickup-opps">{", ".join(r["opps"])}</td>'
            f"<td>{r['season_avg']:.1f}</td>"
            f"<td>{l14}</td>"
            f"<td>{r['proj_pg']:.1f}</td>"
            f'<td class="proj-strong">{r["proj_total"]:.1f}</td>'
            "</tr>"
        )
    html.append("</tbody></table></div>")
    html.append("</section>")
    return "\n".join(html)
