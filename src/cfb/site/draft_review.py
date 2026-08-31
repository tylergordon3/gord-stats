"""
The draft review (docs/cfb/live/) - what the draft was, now that it happened.

This URL spent draft night as the live board; the draft is over, so the same
address now grades it. Same pricing as the board used live - every player's
projection, value over replacement and board rank under this league's own
scoring - applied to the 170 picks that actually happened:

  * Team grades   - every drafted roster priced as its best starting lineup,
                    ranked, lettered, with each team's best and toughest pick.
  * Headlines     - the steal, the reach, the late-round find.
  * The room      - how the ten managers actually drafted each position
                    against Yahoo's pooled ADP; the 2-QB league showed.
  * Every pick    - the full log, each pick against ADP and this board.

    python -m cfb.site.draft_review     # rebuild the page
"""
from datetime import datetime

import pandas as pd

from cfb import projections, yahoo
from cfb.config import LEAGUE_TEAMS, LEAGUE_TZ, SEASON, WEB_DIR
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

def team_grades(df: pd.DataFrame, lg: dict) -> str:
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
    avg = sum(r["total"] for r in rows) / len(rows)
    cells = "".join(
        f"<tr><td class='rv-grade'>{GRADES[min(i, len(GRADES) - 1)]}</td>"
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
# How the room drafted
# --------------------------------------------------------------------------- #

def room_section(df: pd.DataFrame) -> str:
    rows = []
    for pos in projections.POSITIONS:
        g = df[df["pos"] == pos]
        if not len(g):
            continue
        first = g.loc[g["pick"].idxmin()]
        drift = g["delta_adp"].dropna()
        rows.append(
            f"<tr><td>{pos}</td><td>{len(g)}</td>"
            f"<td class='lg-team'>{first['player']} (pick {first['pick']:.0f})</td>"
            f"<td>{int((g['round'] <= 5).sum())}</td>"
            f"<td>{_tag(-drift.mean(), 2) if len(drift) else '—'}</td></tr>")
    return (
        "<p>Yahoo's ADP is pooled over every college league it runs, whatever "
        "the settings; this league starts two quarterbacks with 6-point "
        "passing touchdowns, and the room drafted like it knew. "
        "<b>Ahead of ADP</b> is how many picks earlier than the pooled market "
        "each position actually went here.</p>"
        '<div class="table-scroll"><table class="lg-table">'
        "<thead><tr><th>Pos</th><th>Drafted</th><th>First off the board</th>"
        "<th>In rounds 1–5</th><th>Ahead of ADP</th></tr></thead>"
        f'<tbody>{"".join(rows)}</tbody></table></div>')


# --------------------------------------------------------------------------- #
# Every pick
# --------------------------------------------------------------------------- #

def picks_table(df: pd.DataFrame) -> str:
    rows = []
    for _, p in df.iterrows():
        label = f"{p['round']:.0f}.{(p['pick'] - 1) % LEAGUE_TEAMS + 1:02.0f}"
        adp = "—" if pd.isna(p["adp"]) else f"{p['adp']:.1f}"
        vrank = "—" if pd.isna(p["value_rank"]) else f"{p['value_rank']:.0f}"
        vorp = "—" if pd.isna(p["vorp"]) else f"{p['vorp']:.0f}"
        rows.append(
            f"<tr><td>{p['pick']:.0f}</td><td>{label}</td>"
            f"<td class='lg-team'>{p['team']}</td>"
            f"<td class='lg-team'>{p['player']}</td><td>{p['pos'] or '—'}</td>"
            f"<td>{p['school'] or '—'}</td>"
            f"<td>{adp}</td><td>{_tag(p['delta_adp'])}</td>"
            f"<td>{vrank}</td><td>{_tag(p['delta_board'])}</td>"
            f"<td>{vorp}</td></tr>")
    return (
        "<p>Every pick against both prices: <b>Δ ADP</b> is picks lasted past "
        "Yahoo's pooled average pick, <b>Δ Board</b> is picks lasted past this "
        "board's value rank — green got value, red paid up, shown past "
        f"{NUDGE} spots either way.</p>"
        '<div class="rv-scroll"><table class="lg-table">'
        "<thead><tr><th>#</th><th>Rd</th><th>Team</th><th>Player</th>"
        "<th>Pos</th><th>School</th><th>ADP</th><th>Δ ADP</th>"
        "<th>Board</th><th>Δ Board</th><th>VORP</th></tr></thead>"
        f'<tbody>{"".join(rows)}</tbody></table></div>')


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
        + "<h2>How The Room Drafted</h2>" + room_section(df)
        + "<h2>Every Pick</h2>" + picks_table(df))


def generate():
    write_page(OUTPUT, f"CFB Draft Review {SEASON}", body())


if __name__ == "__main__":
    generate()
