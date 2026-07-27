"""
Median-race page (src/): for the in-progress week, who is locked above/below the
league median (5th place), with max-points scenarios. Current-season section
(writes docs/median/), matching the legacy site structure.

    python -m src.site.median 2526
"""
import datetime
import re
import sys

import pandas as pd
from pytz import timezone
from sleeper_wrapper import League

from src import stats, util
from src.config import LEAGUE_IDS, MAX_POINTS, ROOT, SEASON_YEAR
from src.league import rosters as rosters_mod
from src.site import styles
from src.site.frontmatter import add_front_matter
from src.site.landing import generate_landing

OUT_DIR = ROOT / "docs" / "median"


def _to_play(starters, weeks_players, db, week):
    """Starters who have not yet played this week (empty for completed weeks)."""
    series = pd.Series(starters)
    to_play = series[~series.isin(weeks_players["sleeper_id"])]
    if week <= util.get_last_completed_week():
        return []
    names = db[db["sleeper_id"].isin(to_play)]["cleaned_name"]
    return list(pd.unique(names))


def _hypothetical_max(names, db):
    players = db[db["cleaned_name"].isin(names)]
    total = 0
    for name in pd.unique(players["cleaned_name"]):
        pos = players[players["cleaned_name"] == name]["position"].mode()
        total += MAX_POINTS.get(list(pos)[0], 0)
    return total


def _pretty_players(names) -> str:
    out = []
    for name in names:
        if name.isupper():
            out.append(name)
            continue
        parts = re.findall(r"[A-Z][a-z]*", name)
        out.append(f"{parts[0][0]}. {parts[-1]}" if parts else name)
    return ", ".join(out)


def _set_winners(team, df):
    rank = team["rank"]
    if rank > 5:
        return team["status"]
    beaten = df[(df["rank"] > rank) & ((df["num_to_play"] == 0) | (df["status"] == "L"))]
    magic = 6 - rank
    if (10 - rank - beaten.shape[0]) < magic:
        return "W"
    if team["num_to_play"] == 0:
        return None
    return team["status"]


def _rule_out_set(matchup_df):
    df = matchup_df[["roster_id", "matchup_id", "team", "points", "to_play", "max_pts"]].copy()
    df = df.sort_values("points", ascending=False)
    df["rank"] = df["points"].rank(ascending=False)
    df["num_to_play"] = df["to_play"].apply(len)

    fifth = list(df[df["rank"] == 5]["points"])
    if fifth:
        median = fifth[0]
    elif df["points"].sum() > 0:
        median = df["points"].median()
    else:
        return pd.DataFrame()
    df["status"] = df.apply(lambda t: "L" if t["max_pts"] < median else "tbd", axis=1)
    df["status"] = df.apply(lambda t: _set_winners(t, df), axis=1)
    return df


def _median_scenarios(df) -> str:
    html = ""
    for _, row in df.iterrows():
        if row["status"] in ("L", "W"):
            html += f"<p><strong>{row['team']}</strong>, has: <strong>{row['status']}</strong> vs the median.</p>"
        elif row["rank"] <= 5:
            check = df[(df["status"] == "tbd") & (df["rank"] > row["rank"])]
            to_lose = int(6 - row["rank"])
            remain = f" Remaining players: {_pretty_players(row['to_play'])}" if row["num_to_play"] > 0 else ""
            html += f"<p><strong>{row['team']} loses median if {to_lose} / {len(check)} pass.{remain}</strong></p>"
            for opp in check.itertuples():
                diff = round(row["points"] - opp.points, 2)
                html += (f"<p><u>{opp.team}:</u> {_pretty_players(opp.to_play)} "
                         f"outscore(s) remaining players by <strong>{diff}</strong></p>")
    return html


def _highlight_rows(row, status_by_team):
    status = status_by_team.get(row["Team"])
    if status == "W":
        return ["background-color: #3CB371"] * len(row)
    if status == "L":
        return ["background-color: #FF8080"] * len(row)
    if row["Rank"] <= 5:
        return ["background-color: lightgreen"] * len(row)
    return [""] * len(row)


def _week_page(prepped, week):
    if prepped.empty:
        return  # no data for this week yet (matches legacy: write nothing)

    scenarios = _median_scenarios(prepped)
    status_by_team = dict(zip(prepped["team"], prepped["status"]))
    view = prepped.copy()
    view["Players"] = view["to_play"].apply(_pretty_players)
    view = view.sort_values(["rank", "max_pts"], ascending=[True, False])
    view["rank"] = view["rank"].astype(int)
    view = view.rename(columns={"team": "Team", "points": "Points", "max_pts": "Max Points", "rank": "Rank"})
    view = view[["Rank", "Team", "Players", "Points", "Max Points"]]

    styler = (view.style.apply(_highlight_rows, axis=1, status_by_team=status_by_team)
              .format(precision=2).hide(axis="index"))
    table = f'<div class="table-scroll">{styler.to_html(index=False)}</div>'

    stamp = datetime.datetime.now(timezone("EST")).strftime("Last Update: %A %m/%d/%y %I:%M %p")
    page = add_front_matter(stamp + "<br>" + table + scenarios, f"Median - Week {week}")
    (OUT_DIR / f"week{week}_median.html").write_text(page, encoding="utf-8")


def _median_week(league, week, rosters, db):
    matchups = pd.DataFrame.from_dict(league.get_matchups(week))
    if matchups.empty or "starters" not in matchups.columns:
        return  # week not played / no matchups
    starters = matchups[["roster_id", "matchup_id", "starters"]].copy()

    weeks_players = db[db["week"] == week]
    starters["to_play"] = starters["starters"].apply(lambda s: _to_play(s, weeks_players, db, week))

    combined = starters.merge(rosters, on="roster_id")
    matchups["to_play"] = combined["to_play"]
    matchups["team"] = combined["team_name"]
    matchups["max_pts"] = matchups["to_play"].apply(lambda n: _hypothetical_max(n, db)) + matchups["points"]
    _week_page(_rule_out_set(matchups), week)


def generate(season_str: str):
    """Regenerate the Median section for a season's weeks."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    league = League(LEAGUE_IDS[season_str])
    rosters = rosters_mod.get(league)[["roster_id", "team_name"]]
    db = stats.get(0, SEASON_YEAR[season_str])   # full-season points, computed once
    last = min(14, util.get_week()) if season_str == util.year_str() else 14
    for week in range(1, last + 1):
        _median_week(league, week, rosters, db)
    generate_landing(str(OUT_DIR), "median", "Median")
    print(f"Wrote Median section -> {OUT_DIR}")


if __name__ == "__main__":
    generate(sys.argv[1] if len(sys.argv) > 1 else "2526")
