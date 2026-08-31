"""
The draft review (docs/cfb/live/) - what the draft was, now that it happened.

This URL spent draft night as the live board; the draft is over, so the same
address now grades it. Same pricing as the board used live - every player's
projection, value over replacement and board rank under this league's own
scoring - applied to the 170 picks that actually happened:

  * Team grades   - every drafted roster priced as its best starting lineup,
                    ranked, lettered, with each team's best and toughest pick.
  * Headlines     - the steal, the reach, the late-round find.
  * The verdict   - Yahoo's own draft-day grades and power scores beside this
                    board's, with the two drawn on one chart (the same
                    draft-consensus chart the NFL power page uses).

    python -m cfb.site.draft_review     # rebuild the page
"""
import json
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import numpy as np               # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd              # noqa: E402

from cfb import projections, yahoo
from cfb.config import DATA_DIR, LEAGUE_TZ, SEASON, WEB_DIR
from cfb.site import write_page
from cfb.site.league_power import best_lineup

OUTPUT = WEB_DIR / "live" / "index.html"

# Half a round of this 10-team draft is noise; anything more is a decision.
NUDGE = 5

# Letter for each lineup rank, best roster first.
GRADES = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D"]

_CSS = """<style>
table.lg-table{width:100%;border-collapse:collapse;font-size:14px}
table.lg-table th{background:#eef2f7;color:#334155;padding:7px 10px;text-align:center;
  font-size:12px;text-transform:uppercase;letter-spacing:.03em;white-space:nowrap;
  border:1px solid #e2e8f0}
table.lg-table td{padding:6px 10px;border:1px solid #eef2f7;color:#0f172a;
  background:#fff;text-align:center;white-space:nowrap}
table.lg-table td.lg-team{text-align:left}
table.lg-table tbody tr:nth-child(even) td{background:#f8fafc}
.rv-scroll{max-height:520px;overflow:auto;overscroll-behavior:contain;
  border:1px solid #e5e7eb;border-radius:10px}
.rv-scroll table.lg-table th{position:sticky;top:0;z-index:2}
.rv-grade{font-weight:800}
.rv-up{color:#1a7f4b;font-weight:700}
.rv-down{color:#b3382c;font-weight:700}
.rv-dim{color:#93a1ad}
.rv-cards{display:grid;gap:10px;margin:10px 0;
  grid-template-columns:repeat(auto-fit,minmax(240px,1fr))}
.rv-card{border:1px solid #e5e7eb;border-radius:12px;background:#fff;
  padding:10px 12px;box-shadow:0 2px 8px rgba(15,23,42,.05)}
.rv-card .k{font-size:11px;text-transform:uppercase;letter-spacing:.04em;
  color:#4a5a68;margin-bottom:4px}
.rv-card .nm{font-weight:700;font-size:15px;color:#0f172a}
.rv-card .why{font-size:12.5px;color:#334155;margin:4px 0 0;line-height:1.5}
.mu-note{font-size:13px;color:#4a5a68;margin:4px 0 10px}
@media (prefers-color-scheme: dark){
  table.lg-table th{background:#223052;color:#dde5ef;border-color:#2b3852}
  table.lg-table td{background:#16203a;border-color:#2b3852;color:#dde5ef}
  table.lg-table tbody tr:nth-child(even) td{background:#1b2540}
  .rv-scroll{border-color:#2b3852}
  .rv-up{color:#8ff0bd}
  .rv-down{color:#ffb4ab}
  .rv-card{background:#1b2540;border-color:#2b3852}
  .rv-card .nm{color:#fff}
  .rv-card .k,.mu-note{color:#aab7c9}
  .rv-card .why{color:#dde5ef}
}
</style>"""


# --------------------------------------------------------------------------- #
# The graded picks
# --------------------------------------------------------------------------- #

def graded() -> pd.DataFrame:
    """One row per pick: who, where, and both gradings.

    delta_adp  = pick - Yahoo ADP: how far past his market price he lasted.
    delta_board = pick - this board's value rank: how far past what he is
    actually worth in this league's scoring. The second is the one that knows
    two starting quarterbacks are worth something.
    """
    lg = yahoo.league()
    board = (projections.value_board().drop_duplicates("yahoo_id")
             .set_index("yahoo_id"))
    pre = yahoo.predraft_board().drop_duplicates("yahoo_id").set_index("yahoo_id")
    team_names = {t["team_key"]: t["name"] for t in lg["teams"]}

    rows = []
    for p in yahoo.draft_results():
        pid = str(p["player_key"] or "").rsplit(".", 1)[-1]
        b = board.loc[pid] if pid in board.index else None
        a = pre.loc[pid] if pid in pre.index else None
        rows.append({
            "pick": int(p["pick"]), "round": int(p["round"]),
            "team_key": p["team_key"],
            "team": team_names.get(p["team_key"], p["team_key"]),
            "player": (b["player"] if b is not None
                       else a["player"] if a is not None else f"Player {pid}"),
            "pos": b["pos"] if b is not None else (a["pos"] if a is not None else ""),
            "school": b["team"] if b is not None else (a["team"] if a is not None else ""),
            "adp": float(a["adp"]) if a is not None and pd.notna(a["adp"]) else None,
            "proj": float(b["proj"]) if b is not None else None,
            "vorp": float(b["vorp"]) if b is not None else None,
            "value_rank": int(b["value_rank"]) if b is not None else None,
            "yahoo_id": pid,
        })
    df = pd.DataFrame(rows).sort_values("pick", ignore_index=True)
    df["delta_adp"] = df["pick"] - df["adp"]
    df["delta_board"] = df["pick"] - df["value_rank"]
    return df


def _tag(delta, dim_within=NUDGE) -> str:
    if delta is None or pd.isna(delta):
        return "<span class='rv-dim'>—</span>"
    d = int(round(delta))
    if abs(d) < dim_within:
        return "<span class='rv-dim'>·</span>"
    cls = "rv-up" if d > 0 else "rv-down"
    return f"<span class='{cls}'>{'+' if d > 0 else '−'}{abs(d)}</span>"


# --------------------------------------------------------------------------- #
# Team grades
# --------------------------------------------------------------------------- #

def grade_rows(df: pd.DataFrame, lg: dict) -> list[dict]:
    """One dict per team, best drafted roster first, letter attached."""
    board = (projections.value_board().drop_duplicates("yahoo_id")
             .set_index("yahoo_id"))
    rows = []
    for key, g in df.groupby("team_key"):
        have = [i for i in g["yahoo_id"] if i in board.index]
        lu = best_lineup(board.loc[have], lg)
        rated = g.dropna(subset=["delta_board"])
        best = rated.loc[rated["delta_board"].idxmax()] if len(rated) else None
        worst = rated.loc[rated["delta_board"].idxmin()] if len(rated) else None
        rows.append({
            "team": g["team"].iloc[0], "total": lu["total"],
            "bench": lu["bench"], "vorp": float(g["vorp"].fillna(0).sum()),
            "avg_adp": float(g["delta_adp"].mean()) if g["delta_adp"].notna().any() else None,
            "values": int((g["delta_board"] >= NUDGE).sum()),
            "reaches": int((g["delta_board"] <= -NUDGE).sum()),
            "best": (f"{best['player']} ({best['delta_board']:+.0f})"
                     if best is not None else "—"),
            "worst": (f"{worst['player']} ({worst['delta_board']:+.0f})"
                      if worst is not None else "—"),
        })
    rows.sort(key=lambda r: r["total"], reverse=True)
    for i, r in enumerate(rows):
        r["grade"] = GRADES[min(i, len(GRADES) - 1)]
    return rows


def team_grades(df: pd.DataFrame, lg: dict) -> str:
    rows = grade_rows(df, lg)
    avg = sum(r["total"] for r in rows) / len(rows)
    cells = "".join(
        f"<tr><td class='rv-grade'>{r['grade']}</td>"
        f"<td class='lg-team'>{r['team']}</td>"
        f"<td><b>{r['total']:.0f}</b></td><td>{r['total'] - avg:+.0f}</td>"
        f"<td>{r['vorp']:.0f}</td><td>{r['bench']:.0f}</td>"
        f"<td>{_tag(r['avg_adp'], 2)}</td>"
        f"<td>{r['values']}</td><td>{r['reaches']}</td>"
        f"<td class='lg-team'>{r['best']}</td>"
        f"<td class='lg-team'>{r['worst']}</td></tr>"
        for i, r in enumerate(rows))
    return (
        "<p>Ranked by what was actually assembled: each drafted roster priced "
        "as the best starting lineup it can field, in projected season points "
        "under this league's scoring. <b>VORP</b> is the total value over "
        "replacement drafted, bench included; <b>vs ADP</b> is the average "
        "picks of market value captured per selection; a value or a reach is "
        f"a pick {NUDGE}+ spots past either side of this board's rank.</p>"
        '<div class="table-scroll"><table class="lg-table">'
        "<thead><tr><th>Grade</th><th>Team</th><th>Lineup</th><th>±Avg</th>"
        "<th>VORP</th><th>Bench</th><th>vs ADP</th><th>Values</th>"
        "<th>Reaches</th><th>Best pick</th><th>Toughest pick</th></tr></thead>"
        f"<tbody>{cells}</tbody></table></div>")


# --------------------------------------------------------------------------- #
# Yahoo's verdict
# --------------------------------------------------------------------------- #
# Yahoo publishes its own draft-day grades, projected standings and power
# numbers the moment a draft ends. They are read off the league page once and
# committed (data/cfb/yahoo_draft_verdict.json) - a static record on purpose,
# because Yahoo grades against its pooled game and this board against a 2-QB
# league, and that argument is worth keeping the receipts for.

VERDICT = DATA_DIR / "yahoo_draft_verdict.json"


def _vs_chart(ours: list[dict], v: dict) -> str:
    """The two boards on one scale - the draft-consensus chart the NFL power
    page draws, with two sources instead of three.

    Both rate a roster in projected season points, but not the same points:
    this board prices a 2-QB league and Yahoo prices its pooled game, so each
    is normalised to its own league average (=100) and the span between the
    dots is the argument, drawn.
    """
    from gordstats import charts, palette

    yahoo = dict(v["power"])
    rows = [(r["team"], r["total"], yahoo[r["team"]])
            for r in ours if r["team"] in yahoo]
    if len(rows) < 2:
        return ""
    g_avg = sum(r[1] for r in rows) / len(rows)
    y_avg = sum(r[2] for r in rows) / len(rows)
    rows = [(t, g / g_avg * 100, yp / y_avg * 100) for t, g, yp in rows]
    rows.sort(key=lambda r: r[1])           # best at the top once drawn
    y = np.arange(len(rows))
    gord = [r[1] for r in rows]
    yah = [r[2] for r in rows]

    fig, ax = plt.subplots(figsize=(9, 4.6))
    ax.axvline(100, color=palette.MUTED, linewidth=1.0, linestyle="--", zorder=1)
    ax.hlines(y, np.minimum(gord, yah), np.maximum(gord, yah),
              color=palette.CONTEXT, linewidth=2.0, zorder=2)
    ax.plot(gord, y, "o", markersize=9, label="GordStats", color=palette.SERIES[0],
            markeredgecolor="white", markeredgewidth=1.5, linestyle="none", zorder=3)
    ax.plot(yah, y, "o", markersize=9, label="Yahoo", color=palette.SERIES[1],
            markeredgecolor="white", markeredgewidth=1.5, linestyle="none", zorder=3)
    ax.set_yticks(y)
    ax.set_yticklabels([r[0] for r in rows])
    ax.set_ylim(-0.7, len(rows) - 0.3)
    ax.set_xlabel("draft-day rating (100 = that source's league average)")
    ax.set_title("Draft power: GordStats vs Yahoo")
    ax.grid(axis="x", color=palette.GRIDLINE)
    ax.set_axisbelow(True)
    ax.tick_params(axis="y", length=0)
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.legend(fontsize=9, ncol=2, loc="upper center", bbox_to_anchor=(0.5, -0.13),
              frameon=False)
    fig.tight_layout()
    return charts.save("cfb-draft-review", "gordstats-vs-yahoo",
                       alt="Each roster's draft-day rating from GordStats and "
                           "from Yahoo on one scale, the gap between them drawn")


def yahoo_section(df: pd.DataFrame, lg: dict) -> str:
    if not VERDICT.exists():
        return ""
    v = json.loads(VERDICT.read_text())
    alias = v.get("alias", {})
    ours = {r["team"]: (i + 1, r["grade"])
            for i, r in enumerate(grade_rows(df, lg))}
    recs = {alias.get(t, t): rec for t, rec in v["projected"]}

    rows, gaps = [], []
    for i, (name, pts) in enumerate(v["power"], 1):
        team = alias.get(name, name)
        our_rank, our_grade = ours.get(team, (None, "—"))
        gap = (i - our_rank) if our_rank else None
        if gap is not None:
            gaps.append((gap, name, our_rank, i))
        rows.append(
            f"<tr><td>{i}</td><td class='lg-team'>{name}</td>"
            f"<td class='rv-grade'>{v['grades'].get(name, '—')}</td>"
            f"<td>{pts:g}</td><td>{recs.get(team, '—')}</td>"
            f"<td class='rv-grade'>{our_grade}"
            + (f" <span class='rv-dim'>#{our_rank}</span>" if our_rank else "")
            + f"</td><td>{_tag(gap, 2)}</td></tr>")

    up = max(gaps) if gaps else None
    down = min(gaps) if gaps else None
    contrast = ""
    if up and up[0] >= 3:
        contrast += (f" The biggest argument is <b>{up[1]}</b>: Yahoo's "
                     f"#{up[3]}, this board's #{up[2]} — the gap is what two "
                     "starting quarterbacks and 6-point passing touchdowns "
                     "are worth.")
    if down and down[0] <= -3:
        contrast += (f" It goes the other way on <b>{down[1]}</b>: Yahoo's "
                     f"#{down[3]}, only #{down[2]} here.")
    return (
        "<h2>Yahoo's Draft-Day Verdict</h2>"
        f"<p>What Yahoo said the moment the draft ended ({v['captured']}), "
        "kept as-is for the record: its letter grades, its power score for "
        "every roster, and the season it projected. <b>Δ</b> is how many "
        "spots higher this board ranks the same roster — the two disagree "
        "because Yahoo prices every league the same and this one is not "
        "priced like the average league." + contrast + "</p>"
        + _vs_chart(grade_rows(df, lg), v)
        + '<div class="table-scroll"><table class="lg-table">'
        "<thead><tr><th>Yahoo Rk</th><th>Team</th><th>Yahoo grade</th>"
        "<th>Yahoo power</th><th>Proj record</th><th>This board</th>"
        "<th>Δ</th></tr></thead>"
        f'<tbody>{"".join(rows)}</tbody></table></div>')


# --------------------------------------------------------------------------- #
# Headlines
# --------------------------------------------------------------------------- #

def _card(k, nm, why) -> str:
    return (f'<div class="rv-card"><div class="k">{k}</div>'
            f'<div class="nm">{nm}</div><p class="why">{why}</p></div>')


def headlines(df: pd.DataFrame) -> str:
    rated = df.dropna(subset=["delta_board"])
    cards = []
    meaningful = rated[rated["value_rank"] <= 100]
    if len(meaningful):
        s = meaningful.loc[meaningful["delta_board"].idxmax()]
        cards.append(_card(
            "Steal of the draft", f"{s['player']} — {s['team']}",
            f"This board's #{s['value_rank']} lasted to pick {s['pick']:.0f} "
            f"(round {s['round']:.0f}), {s['delta_board']:+.0f} spots past his "
            f"value and worth {s['vorp']:.0f} points over replacement."))
    early = rated[rated["round"] <= 8]
    if len(early):
        r = early.loc[early["delta_board"].idxmin()]
        cards.append(_card(
            "Biggest reach", f"{r['player']} — {r['team']}",
            f"Taken at pick {r['pick']:.0f}, {-r['delta_board']:.0f} spots "
            f"ahead of this board's #{r['value_rank']}"
            + (f" and {-r['delta_adp']:.0f} ahead of his ADP"
               if pd.notna(r["delta_adp"]) and r["delta_adp"] < 0 else "")
            + "."))
    late = rated[rated["round"] >= 10]
    if len(late) and late["vorp"].max() > 0:
        f = late.loc[late["vorp"].idxmax()]
        cards.append(_card(
            "Late-round find", f"{f['player']} — {f['team']}",
            f"Round {f['round']:.0f}, pick {f['pick']:.0f}, and still worth "
            f"{f['vorp']:.0f} points over replacement — the most value taken "
            "in the double-digit rounds."))
    return f'<div class="rv-cards">{"".join(cards)}</div>'


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #

def body() -> str:
    lg = yahoo.league()
    df = graded()
    if not len(df):
        return (_CSS + "<p>No draft to review yet — this page grades the "
                "draft once Yahoo publishes its results.</p>")

    when = ""
    if lg.get("draft_time"):
        when = (pd.Timestamp(lg["draft_time"], unit="s", tz="UTC")
                .tz_convert(LEAGUE_TZ).strftime("%B %-d"))
    unrated = int(df["value_rank"].isna().sum())
    return (
        _CSS
        + f'<p>The <a href="{lg["url"]}">{lg["name"]}</a> draft'
        + (f" of {when}" if when else "") + f": {len(df)} picks, "
        f"{lg['num_teams']} teams, graded with the same numbers the live "
        "board ran on draft night — every player's projection and value over "
        "replacement under this league's own scoring (two starting QBs, "
        "6-point passing TDs), plus Yahoo's pooled ADP for what the market "
        "thought."
        + (f" {unrated} pick{'s' if unrated != 1 else ''} came from beyond "
           "the board's 500 rated players." if unrated else "") + " The full "
        'snake grid is on the <a href="/cfb/league/">league dashboard</a>; '
        "how these rosters rank now, and all season, is on the "
        '<a href="/cfb/league-power/">league power rankings</a>.</p>'
        + headlines(df)
        + "<h2>Team Grades</h2>" + team_grades(df, lg)
        + yahoo_section(df, lg))


def generate():
    write_page(OUTPUT, f"CFB Draft Review {SEASON}", body())


if __name__ == "__main__":
    generate()
