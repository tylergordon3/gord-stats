"""
Schedule-stats page (src/).

Three sections, all computed from data/season/<season>.json:
  * All-Play (roto) standings - everyone vs everyone, every week.
  * Strength of Schedule / Victory / Expected Wins.
  * Records vs every other team's schedule (matrix).

    python -m src.site.schedule 2526   # writes docs/2526/schedule/index.html
"""
import sys

import pandas as pd

from src.config import EXPW_RATIO, FANTASY_REG_WEEKS, FORMAL_SEASON, ROOT, ROSTER_NAMES, SEASON_DIR
from src.site import styles
from src.site.frontmatter import add_front_matter

_GRID = [styles.GRID_TD, styles.GRID_TH]


def _load(season_str: str) -> pd.DataFrame:
    df = pd.read_json(SEASON_DIR / f"{season_str}.json")
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
    pivot[["win", "loss"]] = pivot["Total"].str.extract(r"(\d+)-(\d+)")
    pivot = pivot.sort_values("win", ascending=False)
    win, loss = pd.to_numeric(pivot["win"]), pd.to_numeric(pivot["loss"])
    pivot["Win %"] = (win / (win + loss)).map("{:.1%}".format)
    pivot = pivot.drop(columns=["win", "loss"])
    pivot.index.name, pivot.columns.name = "Team", "Week"

    return (pivot.style
            .apply(styles.highlight_roto, subset=list(pivot.columns[:-2]))
            .apply(styles.highlight_on_record, subset=["Total"])
            .set_table_styles(_GRID, overwrite=False)
            .set_table_attributes('class="sticky-table"'))


# --------------------------------------------------------------------------- #
# Strength of schedule / victory / expected wins (single season)
# --------------------------------------------------------------------------- #

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
        team = reg[reg["roster_id"] == roster_id]
        beaten = team[team["win"] == 1]["opp"]
        return sum(winp[o] for o in beaten) / len(beaten)

    last["SOV"] = last["roster_id"].map(sov)
    last["Exp W (Actual)"] = last.apply(
        lambda x: f"{(x.PF**EXPW_RATIO) / (x.PF**EXPW_RATIO + x.PA**EXPW_RATIO) * FANTASY_REG_WEEKS:.1f}"
                  f" ({int(x.h2h_wins)})", axis=1)

    df = last[["team_name", "SOS", "SOV", "Exp W (Actual)"]].sort_values("SOS", ascending=False)
    df = df.rename(columns={"team_name": "Team"})
    return (df.style.hide(axis="index")
            .format(lambda x: f"{x:.3f}" if isinstance(x, float) else x)
            .background_gradient(cmap="RdYlGn_r", subset=["SOS"])
            .background_gradient(cmap="RdYlGn", subset=["SOV"])
            .apply(styles.bg_from_pythag_str, subset=["Exp W (Actual)"])
            .set_table_styles(_GRID + [styles.TABLE_STYLE], overwrite=False)
            .set_table_attributes('class="sticky-table"'))


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
    df.index.name, df.columns.name = "Schedules", "Teams"

    return (df.style
            .set_table_styles(_GRID, overwrite=False)
            .apply(styles.highlight_actual_records, axis=None)
            .apply(styles.style_total_bottom, axis=1, subset=pd.IndexSlice[df.index[-1]:, :])
            .apply(styles.style_total_right, axis=0, subset=pd.IndexSlice[:, df.columns[-1]:])
            .set_table_attributes('class="sticky-table"'))


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #

def generate(season_str: str):
    """Build and write docs/<season_str>/schedule/index.html."""
    html = (
        '<h2>All-Play Standings</h2><p>Whole league goes H2H, every week.</p>'
        f'<div class="table-scroll">{all_play(season_str).to_html()}</div>'
        '<h2>Strength of Schedule & Victory</h2>'
        '<p><strong>SOS:</strong> Strength of Schedule - difficulty of schedule '
        '(<a href="https://hackastat.eu/en/learn-a-stat-strength-of-schedule-sos/">Learn More</a>)</p>'
        '<p><strong>SOV:</strong> Strength of Victory - combined win-loss % of defeated opponents</p>'
        '<p><strong>Exp Wins:</strong> Expected wins (vs actual) via Pythagorean expectation on PF/PA</p>'
        '<p>*Sorted by SOS</p>'
        f'<div class="table-scroll">{schedule_metrics(season_str).to_html()}</div>'
        '<h2>Records vs Every Schedule</h2>'
        '<p>Left to right - all teams (columns) compared to 1 schedule (row)</p>'
        '<p>Top to bottom - 1 team (column) compared to every schedule (row)</p>'
        f'<div class="table-scroll">{schedule_compare(season_str).to_html(index=False)}</div>'
    )

    # Freeze the first column on horizontal scroll (first <td> of each row).
    lines = [ln.replace("<td>", '<td class="first-col">', 1) if "<td>" in ln else ln
             for ln in html.split("\n")]
    page = add_front_matter("\n".join(lines), f"Schedule Stats {FORMAL_SEASON[season_str]}")

    out = ROOT / "docs" / season_str / "schedule" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"Wrote schedule page -> {out}")


if __name__ == "__main__":
    generate(sys.argv[1] if len(sys.argv) > 1 else "2526")
