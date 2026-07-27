"""
Best Ball page (src/): what each team's score would have been with its optimal
lineup each week, plus a season standings summary.

Uses Sleeper's authoritative per-player points (league scoring); src.stats is
only used to resolve each player's name/position. Current-season section
(writes docs/bestball/), matching the legacy site structure.

    python -m src.site.bestball 2526
"""
import json
import sys
from io import StringIO

import pandas as pd
from sleeper_wrapper import League

from src import stats, util
from src.config import DATA_DIR, LEAGUE_IDS, ROOT, SEASON_YEAR
from src.league import rosters as rosters_mod
from src.site import styles
from src.site.frontmatter import add_front_matter
from src.site.landing import generate_landing

BESTBALL_JSON = DATA_DIR / "bestball.json"
OUT_DIR = ROOT / "docs" / "bestball"
LINEUP = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2, "DEF": 1, "K": 1}


def _create_df(raw: pd.DataFrame, db: pd.DataFrame) -> pd.DataFrame:
    raw = raw.copy()
    raw["obj"] = raw["id"].apply(lambda x: stats.from_id(x, db))
    raw["name"] = raw["obj"].apply(lambda y: y.cleaned_name.item() if not y.cleaned_name.empty else "err")
    raw["position"] = raw["obj"].apply(lambda y: y.position.item() if not y.position.empty else "err")
    valid = raw[(raw["name"] != "err")]
    return valid.drop(columns=["obj"])


def _best_lineup(df: pd.DataFrame) -> pd.DataFrame:
    best = pd.DataFrame()
    for pos, amt in LINEUP.items():
        if pos == "FLEX":
            pool = df[df["position"].isin(["RB", "TE", "WR"])].copy()
            pool["position"] = "FLEX"
        else:
            pool = df[df["position"] == pos]
        pool = pool.sort_values("points", ascending=False)
        best = pd.concat([best, pool.iloc[0:amt]])
        df = df.drop(pool.iloc[0:amt].index)
    return best


def _weekly(week: int, league: League, db: pd.DataFrame) -> pd.DataFrame:
    matchups = pd.DataFrame.from_dict(league.get_matchups(week))
    combined = pd.DataFrame()
    for _, team in matchups.iterrows():
        raw = pd.DataFrame(team["players_points"].items(), columns=["id", "points"])
        best = _best_lineup(_create_df(raw, db))
        best["roster_id"] = team["roster_id"]
        best["week"] = week
        combined = pd.concat([combined, best])
    return combined


def _matchup_pairs(matchups: pd.DataFrame):
    n = int(matchups["matchup_id"].max())
    return [list(matchups[matchups["matchup_id"] == i + 1]["roster_id"]) for i in range(n)]


# --------------------------------------------------------------------------- #
# Weekly HTML (side-by-side matchup lineups)
# --------------------------------------------------------------------------- #

_CSS = """<style>
.flex-container{display:flex;justify-content:space-around;flex-wrap:wrap}
.flex-item{margin:10px;border:1px solid #ddd;padding:10px}
.flex-item table{border-collapse:collapse;width:100%}
.flex-item th,.flex-item td{border:1px solid #ddd;padding:8px;text-align:center}
</style>"""


def _weekly_html(results, pairs, week, league):
    matchups = pd.DataFrame.from_dict(league.get_matchups(week))
    names = rosters_mod.get(league).set_index("roster_id")["team_name"].to_dict()
    html = _CSS
    for a, b in pairs:
        cards = ""
        for rid in (a, b):
            team = results[results["roster_id"] == rid].reset_index(drop=True)
            team = team.drop(columns=["id", "roster_id"], errors="ignore")[["name", "position", "points"]]
            total = team["points"].sum()
            original = matchups[matchups["roster_id"] == rid]["points"].iloc[0]
            cards += (f'<div class="flex-item"><div style="text-align:center;">'
                      f"<p><strong>{names.get(rid, rid)}</strong></p>"
                      f"<p>Best Lineup: <strong>{total:.2f} pts</strong></p>"
                      f"<p>Original: {original:.2f}</p>{team.to_html(index=False)}</div></div>")
        html += f'<div class="flex-container">{cards}</div>'
    page = add_front_matter(html, f"Week {week} Best Ball")
    (OUT_DIR / f"week{week}_bestball.html").write_text(page, encoding="utf-8")


# --------------------------------------------------------------------------- #
# Season summary + standings
# --------------------------------------------------------------------------- #

def _team_totals(week_df, roster_id, matchups):
    team = week_df[week_df["roster_id"] == roster_id]
    new_total = round(float(team["points"].sum()), 2)
    original = matchups[matchups["roster_id"] == roster_id]["points"].iloc[0]
    return new_total, original


def _results(season_df, matchups_by_week, league):
    def win(a, b):
        return 1 if a > b else 0

    outcomes = pd.DataFrame()
    for week in range(1, int(season_df["week"].max()) + 1):
        matchups = pd.DataFrame.from_dict(league.get_matchups(week))
        wk = season_df[season_df["week"] == week]
        for a, b in matchups_by_week[week]:
            a_bb, a_og = _team_totals(wk, a, matchups)
            b_bb, b_og = _team_totals(wk, b, matchups)
            outcomes = pd.concat([outcomes, pd.DataFrame({
                "week": week, "roster_id": [a, b],
                "score": [a_og, b_og], "bb_score": [a_bb, b_bb],
                "opp_score": [b_og, a_og], "bb_opp_score": [b_bb, a_bb],
                "winner": [win(a_og, b_og), win(b_og, a_og)],
                "bb_winner": [win(a_bb, b_bb), win(b_bb, a_bb)],
            })])
    outcomes = outcomes.reset_index(drop=True)

    def med(group):
        return (group > group.median()).astype(int)

    outcomes["median"] = outcomes.groupby("week")["score"].transform(med)
    outcomes["bb_median"] = outcomes.groupby("week")["bb_score"].transform(med)
    return outcomes


def bestball_season(season_str: str, league: League):
    end_week = min(14, util.get_week()) if season_str == util.year_str() else 14
    full_db = stats.get(0, SEASON_YEAR[season_str])   # full-season points, computed once
    season_combined, matchups_by_week = pd.DataFrame(), {}
    for week in range(1, end_week + 1):
        db = full_db[full_db["week"] == week]
        weekly = _weekly(week, league, db)
        season_combined = pd.concat([season_combined, weekly])
        pairs = _matchup_pairs(pd.DataFrame.from_dict(league.get_matchups(week)))
        _weekly_html(weekly, pairs, week, league)
        matchups_by_week[week] = pairs

    outcomes = _results(season_combined, matchups_by_week, league)
    with open(BESTBALL_JSON, "w", encoding="utf-8") as f:
        json.dump(outcomes.to_json(), f, indent=4)


def _standings(league: League) -> pd.DataFrame:
    with open(BESTBALL_JSON, "r", encoding="utf-8") as f:
        df = pd.read_json(StringIO(json.load(f)))
    last_wk = df["week"].max()

    r = rosters_mod.get(league)[["roster_id", "wins", "team_name", "PF", "PA"]].set_index("roster_id")
    r = r.rename(columns={"wins": "Wins", "team_name": "Team"})
    r["BestBall Wins"] = df.groupby("roster_id")["bb_median"].sum() + df.groupby("roster_id")["bb_winner"].sum()
    r["Losses"] = last_wk * 2 - r["Wins"]
    r["BestBall Losses"] = last_wk * 2 - r["BestBall Wins"]
    r["Record"] = r["Wins"].astype(int).astype(str) + "-" + r["Losses"].astype(int).astype(str)
    r["BB Record"] = r["BestBall Wins"].astype(int).astype(str) + "-" + r["BestBall Losses"].astype(int).astype(str)
    r["BB PF"] = df.groupby("roster_id")["bb_score"].sum()
    r["BB PA"] = df.groupby("roster_id")["bb_opp_score"].sum()
    r["Change"] = r["BestBall Wins"] - r["Wins"]
    r = r.sort_values("BestBall Wins", ascending=False)
    return r[["Team", "Change", "BB Record", "BB PF", "BB PA", "Record", "PF", "PA"]]


def update(league: League):
    summary = _standings(league)
    styler = (summary.style.hide(axis="index")
              .format("{:.2f}", subset=summary.select_dtypes(include="number").columns)
              .background_gradient(cmap="RdYlGn", subset=["Change"])
              .background_gradient(cmap="RdYlGn", subset=["BB PF"])
              .background_gradient(cmap="RdYlGn_r", subset=["BB PA"])
              .set_table_styles([styles.GRID_TD, styles.GRID_TH, styles.TABLE_STYLE], overwrite=False)
              .set_table_attributes('class="sticky-table"'))
    html = f'<div class="table-scroll">{styler.to_html()}</div>'
    page = add_front_matter(html, "BestBall Summary")
    (OUT_DIR / "bestball.html").write_text(page, encoding="utf-8")


def generate(season_str: str):
    """Regenerate the full Best Ball section for a season."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    league = League(LEAGUE_IDS[season_str])
    bestball_season(season_str, league)
    update(league)
    generate_landing(str(OUT_DIR), "bestball", "Best Ball")
    print(f"Wrote Best Ball section -> {OUT_DIR}")


if __name__ == "__main__":
    generate(sys.argv[1] if len(sys.argv) > 1 else "2526")
