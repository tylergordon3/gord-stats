"""
Schedule-stats page (src/).

Four sections, all computed from data/season/<season>.json:
  * Schedule Difficulty - what the schedule has done to each record, in wins,
    split into opponents' strength and their timing (gordstats.schedule_luck).
  * All-Play (roto) standings - everyone vs everyone, every week.
  * Strength of Schedule / Victory / Expected Wins.
  * Records vs every other team's schedule (matrix).

Every season lives on the one page (docs/schedule/index.html), picked with the
season buttons - same shape as the draft report.

    python -m fantasy.site.schedule
"""
from html import escape, unescape

import pandas as pd

from fantasy import paths
from fantasy.config import (
    EXPW_RATIO, FANTASY_REG_WEEKS, FORMAL_SEASON, LEAGUE_IDS, ROOT, ROSTER_NAMES, SEASON_DIR,
)
from fantasy.site import layout, styles
from gordstats import how, schedule_luck
from gordstats.frontmatter import add_front_matter

_GRID = [styles.GRID_TD, styles.GRID_TH]
# The team column reads left to right like every name column; pandas states
# its grid centred in an ID rule, so the override has to be one too.
_NAME_LEFT = [{"selector": "td.col0", "props": [("text-align", "left")]},
              {"selector": "th.col0", "props": [("text-align", "left")]}]
_CLASS = 'class="sticky-table sc-table"'

# On a phone the site-wide sticky-table floor (every column 70px or more, the
# first 150px) left the all-play table three columns on a 390px screen - the
# name and two weeks, never the season's total. Here each column takes what
# its values need (a two-word header wraps rather than set the width) and the
# name gives way to an ellipsis first.
_CSS = """<style>
@media (max-width:600px){
  /* important: pandas states the padding in an ID rule (styles.GRID_TD). */
  .sticky-table.sc-table th,.sticky-table.sc-table td{min-width:0;padding:6px 7px !important}
  .sticky-table.sc-table thead th{white-space:normal;vertical-align:bottom}
  .sticky-table.sc-table td:first-child,.sticky-table.sc-table th:first-child{
    min-width:0;max-width:114px}
}
</style>"""


def _load(season_str: str) -> pd.DataFrame:
    df = pd.read_json(SEASON_DIR / f"{season_str}.json")
    # Team names are whatever a manager typed into Sleeper, and pandas' Styler
    # writes cell values out raw: escaped here, once, before any table sees them.
    if "team_name" in df:
        df["team_name"] = df["team_name"].map(lambda n: escape(str(n)))
    return df[df["week"] <= FANTASY_REG_WEEKS]


# --------------------------------------------------------------------------- #
# All-play (roto) standings
# --------------------------------------------------------------------------- #

def _process_roto(week_df: pd.DataFrame) -> pd.DataFrame:
    def record(team):
        wins = int((team["points"] > week_df["points"]).sum())
        loss = int((team["points"] < week_df["points"]).sum())
        return [f"{wins}-{loss}", wins, loss]

    week_df[["roto", "roto_win", "roto_loss"]] = week_df.apply(
        lambda t: record(t), axis=1, result_type="expand")
    return week_df


def all_play(season_str: str):
    reg = _load(season_str)
    weekly = pd.concat([_process_roto(g) for _, g in reg.groupby("week")])

    roto = weekly[["team_name", "roto", "week"]]
    summary = weekly.groupby("team_name")[["roto_win", "roto_loss"]].sum()
    summary["roto"] = summary["roto_win"].astype(str) + "-" + summary["roto_loss"].astype(str)
    summary["week"] = "Total"
    summary = summary.drop(columns=["roto_win", "roto_loss"]).reset_index()

    roto = pd.concat([roto, summary])
    pivot = roto.pivot(index="team_name", columns="week", values="roto")
    # Numbers, not the extracted strings: sorted as text "8" beat "17", and an
    # 8-10 team led the table over a 17-1 one.
    pivot[["win", "loss"]] = pivot["Total"].str.extract(r"(\d+)-(\d+)").astype(int)
    pivot = pivot.sort_values("win", ascending=False)
    win, loss = pivot["win"], pivot["loss"]
    pivot["Win %"] = (win / (win + loss)).map("{:.1%}".format)
    pivot = pivot.drop(columns=["win", "loss"])
    # reset_index() makes Team a real, labelled column — a styled index renders
    # its name as a phantom second header row, with the columns' name ("week")
    # sitting over the frozen team column.
    pivot.columns.name = None
    pivot = pivot.rename_axis("Team").reset_index()
    # The season's answer beside the name, the weeks behind it: on a phone
    # the total and the win rate were past the edge of the screen, after
    # every week of the season.
    weeks = [c for c in pivot.columns if c not in ("Team", "Total", "Win %")]
    pivot = pivot[["Team", "Total", "Win %", *weeks]]

    return (pivot.style.hide(axis="index")
            .apply(styles.highlight_roto, subset=weeks)
            .apply(styles.highlight_on_record, subset=["Total"])
            .set_table_styles(_GRID + _NAME_LEFT, overwrite=False)
            .set_table_attributes(_CLASS))


# --------------------------------------------------------------------------- #
# Strength of schedule / victory / expected wins (single season)
# --------------------------------------------------------------------------- #

def difficulty(season_str: str) -> tuple:
    """(schedule_luck table, {roster_id: team name}) for one season's
    head-to-head games."""
    reg = _load(season_str)
    games = reg[reg["opp"].notna()]
    rows = games[["week", "roster_id", "opp", "points", "opp_points"]].values.tolist()
    # _load escapes the names for the Styler tables; schedule_luck escapes its own.
    names = {rid: unescape(str(n)) for rid, n in zip(reg["roster_id"], reg["team_name"])}
    return schedule_luck.table(rows), names


def _avg_over(roster_id, season, value_by_roster):
    opps = season[season["roster_id"] == roster_id]["opp"]
    return sum(value_by_roster[o] for o in opps) / len(opps)


def schedule_metrics(season_str: str):
    reg = _load(season_str)
    reg["W%"] = reg["total_wins"] / (reg["total_wins"] + reg["total_loss"])

    last = reg[reg["week"] == reg["week"].max()].copy()
    winp = dict(zip(last["roster_id"], last["W%"]))
    last["OW%"] = last["roster_id"].map(lambda r: _avg_over(r, reg, winp))
    oow = dict(zip(last["roster_id"], last["OW%"]))
    last["OOW%"] = last["roster_id"].map(lambda r: _avg_over(r, reg, oow))
    last["SOS"] = (last["OW%"] * 2 + last["OOW%"]) / 3

    def sov(roster_id):
        """Average win rate of the teams this roster has beaten.

        Undefined with no wins, which is not a hypothetical: two weeks into a
        season somebody is 0-2, and dividing by nobody took the whole page
        down. NaN rather than zero - a winless team has not got a strength of
        victory of zero, it has not got one at all - and the formatter prints
        it as a dash.
        """
        team = reg[reg["roster_id"] == roster_id]
        beaten = team[team["win"] == 1]["opp"]
        if not len(beaten):
            return float("nan")
        return sum(winp[o] for o in beaten) / len(beaten)

    last["SOV"] = last["roster_id"].map(sov)
    last["Exp W (Actual)"] = last.apply(
        lambda x: f"{(x.PF**EXPW_RATIO) / (x.PF**EXPW_RATIO + x.PA**EXPW_RATIO) * (x.h2h_wins + x.h2h_loss):.1f}"
                  f" ({int(x.h2h_wins)})", axis=1)

    df = last[["team_name", "SOS", "SOV", "Exp W (Actual)"]].sort_values("SOS", ascending=False)
    df = df.rename(columns={"team_name": "Team"})
    return (df.style.hide(axis="index")
            .format(lambda x: ("&mdash;" if pd.isna(x) else f"{x:.3f}")
                    if isinstance(x, float) else x)
            .background_gradient(text_color_threshold=styles.GRADIENT_INK, cmap="RdYlGn_r", subset=["SOS"])
            # Only the teams with a win: the ramp has no colour for a missing
            # value and pandas writes its transparent "bad" colour out as
            # #000000, so a winless team's SOV dash sat in a solid black block.
            .background_gradient(text_color_threshold=styles.GRADIENT_INK, cmap="RdYlGn", subset=pd.IndexSlice[df.index[df["SOV"].notna()], ["SOV"]])
            .apply(styles.bg_from_pythag_str, subset=["Exp W (Actual)"])
            .set_table_styles(_GRID + [styles.TABLE_STYLE] + _NAME_LEFT, overwrite=False)
            .set_table_attributes(_CLASS))


# --------------------------------------------------------------------------- #
# Records vs every schedule (matrix)
# --------------------------------------------------------------------------- #

def schedule_compare(season_str: str):
    reg = _load(season_str)
    roster_ids = list(pd.unique(reg["roster_id"]))
    names = [ROSTER_NAMES[r] for r in roster_ids]

    rows, totals = [], {ROSTER_NAMES[r]: [0, 0] for r in roster_ids}
    for rid in roster_ids:
        schedule = reg[reg["roster_id"] == rid]["opp_points"].to_numpy()
        row, sched_w, sched_l = {}, 0, 0
        for other in roster_ids:
            scores = reg[reg["roster_id"] == other]["points"].to_numpy()
            wins = int((scores > schedule).sum())
            losses = int((scores < schedule).sum())
            row[ROSTER_NAMES[other]] = f"{wins}-{losses}"
            sched_w += wins
            sched_l += losses
            totals[ROSTER_NAMES[other]][0] += wins
            totals[ROSTER_NAMES[other]][1] += losses
        row["Schedule Totals"] = f"{sched_w}-{sched_l}"
        rows.append(row)

    totals = {t: f"{w}-{l}" for t, (w, l) in totals.items()}
    totals["Schedule Totals"] = "0-0"
    df = pd.DataFrame(rows + [totals], index=names + ["Team Totals"])
    # The schedule owner renders as a real, labelled first column — a styled
    # index would name it in a phantom second header row. The index itself
    # stays (hidden): highlight_actual_records darkens the diagonal by
    # comparing row labels to column names.
    df.insert(0, "Schedule", df.index)
    # Each schedule's total - the whole league against it - is the row's
    # answer, so it sits beside the name rather than a dozen columns right.
    df.insert(1, "Schedule Totals", df.pop("Schedule Totals"))

    def rule_after(col):
        return ["font-weight: bold; border-right: 3px solid black !important;" for _ in col]

    return (df.style.hide(axis="index")
            .set_table_styles(_GRID + _NAME_LEFT, overwrite=False)
            .apply(styles.highlight_actual_records, axis=None, subset=list(df.columns[1:]))
            .apply(styles.style_total_bottom, axis=1, subset=pd.IndexSlice[df.index[-1]:, :])
            .apply(rule_after, axis=0, subset=["Schedule Totals"])
            .set_table_attributes(_CLASS))


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #

def _season_view(season_str: str) -> str:
    """One season's three tables, with the first column frozen on h-scroll."""
    frame, names = difficulty(season_str)
    html = (
        f"<h2>Schedule Difficulty {how.button('schedule-strength')}</h2>"
        + schedule_luck.html(frame, names)
        + '<h2>All-Play Standings</h2><p>Whole league goes H2H, every week.</p>'
        f'<div class="table-scroll">{styles.to_html(all_play(season_str))}</div>'
        '<h2>Strength of Schedule & Victory</h2>'
        '<p><strong>SOS:</strong> Strength of Schedule - difficulty of schedule '
        '(<a href="https://hackastat.eu/en/learn-a-stat-strength-of-schedule-sos/">Learn More</a>)</p>'
        '<p><strong>SOV:</strong> Strength of Victory - combined win-loss % of defeated opponents</p>'
        '<p><strong>Exp Wins:</strong> Expected wins (vs actual) via Pythagorean expectation on PF/PA</p>'
        '<p>*Sorted by SOS</p>'
        f'<div class="table-scroll">{styles.to_html(schedule_metrics(season_str))}</div>'
        '<h2>Records vs Every Schedule</h2>'
        '<p>Left to right - all teams (columns) compared to 1 schedule (row)</p>'
        '<p>Top to bottom - 1 team (column) compared to every schedule (row)</p>'
        f'<div class="table-scroll">{styles.to_html(schedule_compare(season_str))}</div>'
    )
    return html


def generate():
    """Build and write docs/schedule/index.html - every season, switchable."""
    views = [(s, FORMAL_SEASON[s], _season_view(s)) for s in LEAGUE_IDS]
    body = layout.HEAD + _CSS + layout.view_switcher(views, group="season", label="Season:",
                                                     pin=True)
    page = add_front_matter(
        body + how.JS_TAG, "Schedule Stats",
        description="How much the schedule has helped or hurt each fantasy team: schedule luck in "
                    "wins, all-play standings, strength of schedule and records vs every schedule.")

    out = paths.WEB_SCHEDULE
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"Wrote schedule page -> {out}")


if __name__ == "__main__":
    generate()
