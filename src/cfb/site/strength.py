"""
Matchup strength (docs/cfb/strength/): whose schedule helps, and which
defences are worth attacking.

Two tables, both off cfb.defense - fantasy points allowed per position,
against what the model said the opposing offence should have produced, so a
defence is not flattered by three weeks of cupcakes:

  * Schedule ahead   every roster's remaining games, each player's opponent
                     priced at his own position and weighted by what he is
                     projected to be worth. A schedule is only easy in the
                     places you actually start somebody.
  * Defence vs pos   the league-wide table the first one is built from.

    python -m cfb.site.strength
"""
from html import escape

import pandas as pd

from cfb import defense, espn, in_season, predict, schools as schools_mod, yahoo
from cfb.config import SEASON, WEB_DIR
from cfb.site import write_page

# How many weeks ahead the schedule table looks. Past this the rosters that
# own these players will have changed anyway.
WEEKS_AHEAD = 6
POSITIONS = defense.POSITIONS

_CSS = """<style>
table.st{width:100%;border-collapse:collapse;font-size:14px}
table.st th{background:#eef2f7;color:#334155;padding:6px 9px;text-align:center;font-size:12px;
  text-transform:uppercase;letter-spacing:.03em;white-space:nowrap;border:1px solid #e2e8f0}
table.st td{padding:5px 9px;border:1px solid #eef2f7;color:#0f172a;background:#fff;
  text-align:center;white-space:nowrap}
table.st td.st-name{text-align:left;font-weight:600}
table.st tbody tr:nth-child(even) td{background:#f8fafc}
table.st td:first-child,table.st th:first-child{position:sticky;left:0;z-index:1}
.st-note{font-size:13px;color:#4a5a68;margin:6px 0 12px;line-height:1.55}
.st-rk{display:inline-block;min-width:18px;text-align:right;color:#64748b;font-size:11px;
  margin-right:6px}
.st-scroll{overflow-x:auto}
@media (prefers-color-scheme: dark){
  table.st th{background:#223052;color:#dde5ef;border-color:#2b3852}
  table.st td{background:#16203a;border-color:#2b3852;color:#dde5ef}
  table.st tbody tr:nth-child(even) td{background:#1b2540}
  .st-note{color:#aab7c9}
  .st-rk{color:#aab7c9}
}
</style>"""


def _heat(value, low=0.85, high=1.15) -> str:
    """Green where a schedule or a defence gives points up, red where it does
    not - the same direction in both tables."""
    if value is None or pd.isna(value):
        return ""
    span = max(high - low, 1e-9)
    t = min(max((float(value) - low) / span, 0.0), 1.0)
    # red (stingy) -> amber -> green (generous)
    r, g, b = (211, 47, 47) if t < 0.5 else (46, 125, 50)
    alpha = abs(t - 0.5) * 2 * 0.45
    return f"background:rgba({r},{g},{b},{alpha:.2f})"


def _names() -> dict:
    sched = espn.schedule()
    out = {}
    for _, g in sched.iterrows():
        out[str(g["home_id"])] = str(g["home"])
        out[str(g["away_id"])] = str(g["away"])
    return out


def defense_section(grid: pd.DataFrame, names: dict) -> str:
    rows = []
    # Ranked the way the dashboards rank a matchup: 1 is the stingiest defence,
    # the last place gives up the most.
    for rank, (team_id, row) in enumerate(grid.iloc[::-1].iterrows(), 1):
        cells = "".join(
            f"<td style='{_heat(row.get(pos))}'>"
            + ("&mdash;" if pd.isna(row.get(pos)) else f"{row[pos]:.2f}") + "</td>"
            for pos in POSITIONS)
        rows.append(f"<tr><td class='st-name'><span class='st-rk'>{rank}</span>"
                    f"{escape(names.get(str(team_id), str(team_id)))}</td>{cells}"
                    f"<td style='{_heat(row['all'])}'>{row['all']:.2f}</td></tr>")
    head = ("<tr><th>Defence</th>" + "".join(f"<th>{p}</th>" for p in POSITIONS)
            + "<th>All</th></tr>")
    return ("<div class='st-scroll'><table class='st'>"
            f"<thead>{head}</thead><tbody>{''.join(rows)}</tbody></table></div>")


def _roster_players(board: pd.DataFrame) -> pd.DataFrame:
    """Every rostered player with his school, position and season projection."""
    rosters = yahoo.rosters()
    teams = {t["team_key"]: t["name"]
             for m in (yahoo.scoreboard().get("matchups") or [])
             for t in m.get("teams") or []}
    priced = board.drop_duplicates("yahoo_id").set_index("yahoo_id")
    # The board names a player's school; the schedule keys on ESPN's team id.
    espn_id = schools_mod.espn_ids()
    rows = []
    for key, ids in rosters.items():
        for pid in ids:
            if pid not in priced.index:
                continue
            p = priced.loc[pid]
            rows.append({"team_key": key, "manager": teams.get(key, key),
                         "yahoo_id": pid, "player": p["player"],
                         "pos": str(p["pos"]).split(",")[0],
                         "school_id": str(espn_id.get(p.get("school"), "") or ""),
                         "team_full": p.get("team_full"),
                         "proj": float(p["proj"]) if pd.notna(p.get("proj")) else 0.0})
    return pd.DataFrame(rows)


def schedule_section(ratings: dict, names: dict, frame: pd.DataFrame,
                     board: pd.DataFrame) -> str:
    """Each roster's next few weeks, priced by who its players face."""
    players = _roster_players(board)
    if players.empty:
        return "<p>No rosters to price yet.</p>"
    players = players[players["pos"].isin(POSITIONS) & (players["proj"] > 0)]

    # Every school's opponent, week by week, from the model's own frame.
    weeks = sorted({int(w) for w in frame.loc[~frame["played"], "week"].dropna().unique()})
    weeks = weeks[:WEEKS_AHEAD]
    opponents = {}
    for _, g in frame[frame["week"].isin(weeks)].iterrows():
        opponents[(str(g["home_id"]), int(g["week"]))] = str(g["away_id"])
        opponents[(str(g["away_id"]), int(g["week"]))] = str(g["home_id"])

    rows = []
    for manager, group in players.groupby("manager"):
        per_week, weights = {}, {}
        for week in weeks:
            total = weight = 0.0
            for _, p in group.iterrows():
                opp = opponents.get((p["school_id"], week))
                if not opp:
                    continue                       # bye: no matchup to price
                rating = (ratings.get(opp) or {}).get(p["pos"])
                if rating is None:
                    continue
                total += rating * p["proj"]
                weight += p["proj"]
            per_week[week] = (total / weight) if weight else None
            weights[week] = weight
        got = [v for v in per_week.values() if v is not None]
        rows.append({"manager": manager, "weeks": per_week,
                     "mean": sum(got) / len(got) if got else None})

    rows = [r for r in rows if r["mean"] is not None]
    rows.sort(key=lambda r: -r["mean"])
    body = []
    for rank, r in enumerate(rows, 1):
        cells = "".join(
            f"<td style='{_heat(r['weeks'][w])}'>"
            + ("&mdash;" if r["weeks"][w] is None else f"{r['weeks'][w]:.2f}") + "</td>"
            for w in weeks)
        body.append(f"<tr><td class='st-name'><span class='st-rk'>{rank}</span>"
                    f"{escape(str(r['manager']))}</td>{cells}"
                    f"<td style='{_heat(r['mean'])}'><b>{r['mean']:.2f}</b></td></tr>")
    head = ("<tr><th>Team</th>" + "".join(f"<th>Wk {w}</th>" for w in weeks)
            + "<th>Average</th></tr>")
    return ("<div class='st-scroll'><table class='st'>"
            f"<thead>{head}</thead><tbody>{''.join(body)}</tbody></table></div>")


def body() -> str:
    grid = defense.table()
    if grid.empty:
        return (_CSS + "<p>No box scores archived yet — this page fills in once "
                "<code>python -m cfb.boxscores</code> has run.</p>")
    names = _names()
    ratings = {str(k): {p: (None if pd.isna(v) else float(v)) for p, v in row.items()}
               for k, row in grid.iterrows()}
    frame, _model, _names_map = predict.season()
    board = in_season.board(frame=frame)
    played = int(frame["played"].sum())

    return (
        _CSS
        # One line up top; the rest of what used to be two paragraphs before the
        # first table is one tap away.
        + "<p><strong>1.00 is par</strong>: above 1, a defence to attack; below 1, one "
        f"to avoid. From {played} games so far.</p>"
        "<details class='section'><summary>How this is worked out</summary>"
        "<p class='st-note'>Fantasy points allowed per position, in this league's own "
        "scoring, against what this site's model said the opposing offence should have "
        "scored - 1.00 is a defence giving up exactly what its schedule implies.</p>"
        "<p class='st-note'>Every finished game's ESPN box score is scored with the "
        "league's modifiers, then each position's haul is set against the share of the "
        "opposing offence's <em>predicted</em> points that position normally takes. That "
        "adjustment is the whole point: three weeks of FCS visitors make any defence look "
        "elite, and this asks instead whether it held offences to less than they should "
        "have managed. Ratings on fewer than five games are pulled toward par, so one "
        "shootout in September does not brand a defence for the season.</p></details>"
        "<h2>Schedule ahead</h2>"
        "<p class='st-note'>Each roster's next weeks, priced by who its players face "
        "(weighted by what each is projected to be worth). Higher is easier; a bye is "
        "left out.</p>"
        + schedule_section(ratings, names, frame, board)
        + "<h2>Defence vs position</h2>"
        "<p class='st-note'>Every FBS defence, toughest first: 1 gives up the least against expectation, the last place the most.</p>"
        + defense_section(grid, names))


def generate():
    write_page(WEB_DIR / "strength" / "index.html", "CFB Matchup Strength", body(),
               subtitle=f"{SEASON} — fantasy points allowed by position, schedule-adjusted")


if __name__ == "__main__":
    generate()
