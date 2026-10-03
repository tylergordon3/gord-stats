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
from gordstats import how, strength_page

WEEKS_AHEAD = strength_page.WEEKS_AHEAD
POSITIONS = defense.POSITIONS

# The look, the tables and the arithmetic are gordstats.strength_page, shared
# with the NFL league's /fantasy/strength/. `_heat` stays importable here: the
# team dashboard (cfb.site.roster) colours its opponent cells with it.
_CSS = strength_page.CSS
_heat = strength_page.heat


def _names() -> dict:
    sched = espn.schedule()
    out = {}
    for _, g in sched.iterrows():
        out[str(g["home_id"])] = str(g["home"])
        out[str(g["away_id"])] = str(g["away"])
    return out


def defense_section(grid: pd.DataFrame, names: dict) -> str:
    # Ranked the way the dashboards rank a matchup: 1 is the stingiest defence,
    # the last place gives up the most.
    rows = [(escape(names.get(str(team_id), str(team_id))), row, row["all"])
            for team_id, row in grid.iloc[::-1].iterrows()]
    return strength_page.defense_table(rows, POSITIONS)


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

    rows = strength_page.price(
        [{"key": p["manager"], "label": p["manager"], "team": p["school_id"],
          "pos": p["pos"], "weight": p["proj"]} for _, p in players.iterrows()],
        weeks, opponents, ratings)
    return strength_page.schedule_table(rows, weeks)


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
        # One line up top; how the ratings are made is the schedule-strength
        # explainer (gordstats.how), opened from the chip beside it.
        + "<p><strong>1.00 is par</strong>: above 1, a defense to attack; below 1, one "
        f"to avoid. From {played} games so far. " + how.button("schedule-strength") + "</p>"
        "<h2>Schedule ahead</h2>"
        "<p class='st-note'>Each roster's next weeks, priced by who its players face: every "
        "rostered player, bench included, weighted by what he is projected to be worth. "
        "Higher is easier; a bye is left out.</p>"
        + schedule_section(ratings, names, frame, board)
        + "<h2>Defense vs position</h2>"
        "<p class='st-note'>Every FBS defense, toughest first: 1 gives up the least against expectation, the last place the most.</p>"
        + defense_section(grid, names) + how.JS_TAG)


def generate():
    write_page(WEB_DIR / "strength" / "index.html", "CFB Matchup Strength", body(),
               subtitle=f"{SEASON} — fantasy points allowed by position, schedule-adjusted")


if __name__ == "__main__":
    generate()
