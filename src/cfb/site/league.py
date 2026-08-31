"""
The league dashboard (docs/cfb/league/) - the CFB fantasy league itself.

Four sections, each rendering whatever the season has produced so far and
saying plainly what it is still waiting on:

  * Standings      - records, points, FAAB and moves (teams exist predraft).
  * Power Rankings - every roster's best starting lineup in projected season
                     points, off the draft board's own projections; follows
                     the live rosters, so waivers move it all season.
  * Matchups       - the current week's scoreboard; pairings before kickoff,
                     projections and points once Yahoo serves them.
  * Draft Results  - empty until the draft; afterwards the snake grid coloured
                     by position, every pick graded against the *pre-draft*
                     board snapshot (yahoo.predraft_board), the same Δ = pick −
                     board rank treatment the NFL draft board uses.
  * Transactions   - player adds / drops / trades. Yahoo logs commissioner
                     actions too; those are noise and are filtered out here.

    python -m cfb.site.league       # rebuild the page
"""
from datetime import datetime

import pandas as pd

from cfb import yahoo
from cfb.config import LEAGUE_TEAMS, LEAGUE_TZ, SEASON, WEB_DIR
from cfb.site import write_page
from cfb.site.draft import _draft_when

# Half a round of this 10-team draft is noise; anything more is a decision.
NUDGE = 5

_CSS = """<style>
.cfb-league{font-size:14px;color:#334155;border:1px solid #e5e7eb;border-radius:12px;
  padding:10px 14px;background:#f8fafc;margin:10px 0}
table.lg-table{width:100%;border-collapse:collapse;font-size:14px}
table.lg-table th{background:#eef2f7;color:#334155;padding:7px 10px;text-align:center;
  font-size:12px;text-transform:uppercase;letter-spacing:.03em;white-space:nowrap;
  border:1px solid #e2e8f0}
table.lg-table td{padding:6px 10px;border:1px solid #eef2f7;color:#0f172a;
  background:#fff;text-align:center;white-space:nowrap}
table.lg-table td.lg-team{text-align:left}
table.lg-table tbody tr:nth-child(even) td{background:#f8fafc}
/* The remote theme decorates every img with a border, padding, margins and a
   drop shadow — figure styling that turns a 22px logo into a postage stamp.
   Reset all of it here. */
table.lg-table img.lg-logo{width:22px;height:22px;border-radius:50%;
  vertical-align:middle;margin:0 7px 0 0;border:none;padding:0;box-shadow:none}
.mu-note{font-size:13px;color:#4a5a68;margin:4px 0 10px}
table.draft-board td{border:1px solid #eef2f7;padding:5px 8px;font-size:13px;
  background:#fff;color:#0f172a;text-align:center}
table.draft-board th{background:#eef2f7;color:#334155;padding:6px 8px;font-size:12px;
  border:1px solid #e2e8f0;white-space:nowrap}
table.draft-board td .p{font-weight:600;white-space:nowrap}
table.draft-board td .t{font-size:11px;color:#4a5a68;white-space:nowrap}
table.draft-board td.cur-QB{background:#d3ddf5}
table.draft-board td.cur-RB{background:#d5efdd}
table.draft-board td.cur-WR{background:#fbeec2}
table.draft-board td.cur-TE{background:#fadfc8}
table.draft-board td.cur-DEF{background:#d4f0f7}
table.draft-board td .v{font-size:11px;font-weight:700}
table.draft-board td .v.up{color:#1a7f4b}
table.draft-board td .v.down{color:#b3382c}
@media (prefers-color-scheme: dark){
  .cfb-league{background:#1b2540;border-color:#2b3852;color:#dde5ef}
  table.lg-table th{background:#223052;color:#dde5ef;border-color:#2b3852}
  table.lg-table td{background:#16203a;border-color:#2b3852;color:#dde5ef}
  table.lg-table tbody tr:nth-child(even) td{background:#1b2540}
  .mu-note{color:#aab7c9}
  table.draft-board th{background:#223052;color:#dde5ef;border-color:#2b3852}
  table.draft-board td{background:#16203a;border-color:#2b3852;color:#dde5ef}
  table.draft-board td .t{color:#aab7c9}
  table.draft-board td.cur-QB{background:#1e2c52}
  table.draft-board td.cur-RB{background:#123c2e}
  table.draft-board td.cur-WR{background:#3d3413}
  table.draft-board td.cur-TE{background:#40280f}
  table.draft-board td.cur-DEF{background:#143a45}
  table.draft-board td .v.up{color:#8ff0bd}
  table.draft-board td .v.down{color:#ffb4ab}
}
</style>"""


def _details(summary: str, body: str, open: bool = False) -> str:
    return (f'<details class="section"{" open" if open else ""}>'
            f"<summary>{summary}</summary>{body}</details>")


def _rec(t: dict) -> str:
    w, l, ti = (int(t.get(k) or 0) for k in ("wins", "losses", "ties"))
    return f"{w}-{l}" + (f"-{ti}" if ti else "")


# --------------------------------------------------------------------------- #
# Standings
# --------------------------------------------------------------------------- #

def standings_section(lg: dict) -> str:
    teams = sorted(lg["teams"],
                   key=lambda t: (t.get("rank") or 99, t.get("name") or ""))
    played = any((t.get("wins") or t.get("losses")) for t in teams)
    # Yahoo masks manager nicknames on signed-out reads; only show the column
    # if it would say something.
    named = any(t.get("manager") for t in teams)
    rows = []
    for i, t in enumerate(teams, 1):
        rank = int(t["rank"]) if t.get("rank") else i
        logo = (f'<img class="lg-logo" src="{t["logo"]}" alt="" loading="lazy">'
                if t.get("logo") else "")
        mgr = f"<td>{t['manager'] or '—'}</td>" if named else ""
        rows.append(
            f"<tr><td>{rank if played else '—'}</td>"
            f'<td class="lg-team">{logo}{t["name"]}</td>'
            f"{mgr}<td>{_rec(t)}</td>"
            f"<td>{t.get('points_for') or 0:g}</td>"
            f"<td>{t.get('points_against') or 0:g}</td>"
            f"<td>${t.get('faab') or 0:g}</td>"
            f"<td>{int(t.get('moves') or 0)}</td></tr>")
    note = ("" if played else
            '<p class="mu-note">Everyone is 0-0 until the games start; '
            "FAAB is the season's $100 waiver budget.</p>")
    mgr_head = "<th>Manager</th>" if named else ""
    return (note + '<div class="table-scroll"><table class="lg-table">'
            f"<thead><tr><th>Rk</th><th>Team</th>{mgr_head}<th>Record</th>"
            "<th>PF</th><th>PA</th><th>FAAB</th><th>Moves</th></tr></thead>"
            f'<tbody>{"".join(rows)}</tbody></table></div>')


# --------------------------------------------------------------------------- #
# Matchups
# --------------------------------------------------------------------------- #

def matchups_section(sb: dict) -> str:
    if not sb.get("matchups"):
        return "<p>No matchups scheduled yet.</p>"
    mu0 = sb["matchups"][0]
    start = datetime.strptime(mu0["week_start"], "%Y-%m-%d").strftime("%b %-d")
    end = datetime.strptime(mu0["week_end"], "%Y-%m-%d").strftime("%b %-d")
    live = any(t.get("points") for m in sb["matchups"] for t in m["teams"])
    rows = []
    for m in sb["matchups"]:
        a, b = m["teams"]

        def side(t):
            pts = t.get("points")
            proj = t.get("projected")
            num = (f"{pts:g}" if pts else "") or (f"proj {proj:g}" if proj else "—")
            return t["name"], num
        an, ax = side(a)
        bn, bx = side(b)
        rows.append(f'<tr><td class="lg-team">{an}</td><td>{ax}</td>'
                    f'<td>{bx}</td><td class="lg-team">{bn}</td></tr>')
    note = ("" if live else
            '<p class="mu-note">Pairings are set; points appear once the '
            "week's games kick off.</p>")
    return (f"<p><strong>Week {int(sb['week'])}</strong> · {start} – {end}"
            + (" (playoffs)" if mu0.get("is_playoffs") else "") + "</p>" + note
            + '<div class="table-scroll"><table class="lg-table">'
              "<thead><tr><th></th><th colspan='2'>Score</th><th></th></tr></thead>"
            f'<tbody>{"".join(rows)}</tbody></table></div>')


# --------------------------------------------------------------------------- #
# Power rankings
# --------------------------------------------------------------------------- #
# Each roster priced the way the live draft board priced the players: the best
# starting lineup it can field, in projected season points under this league's
# own scoring and slots. Built from Yahoo's roster feed so waivers and trades
# move the rankings all season; the feed stays empty until the draft completes
# (checked during the live one), so fresh off the draft the picks stand in.

def _team_rosters() -> dict:
    """{team_key: [player_id, ...]} - live rosters, or the draft while
    Yahoo's roster feed still lags it."""
    rosters = yahoo.rosters()
    if any(rosters.values()):
        return rosters
    out = {}
    for p in yahoo.draft_results():
        pid = str(p["player_key"] or "").rsplit(".", 1)[-1]
        out.setdefault(p["team_key"], []).append(pid)
    return out


def _best_lineup(players: pd.DataFrame, lg: dict) -> dict:
    """The best starting lineup this roster supports.

    Dedicated slots take the top projections at their position; the flex slots
    then take the best skill player left - the same fill the live board uses,
    because it is what a manager setting a lineup does. A slot nobody fills
    counts zero, which is what makes a half-drafted roster rank honestly low.
    """
    from cfb import projections

    pools = {p: players[players["pos"] == p].sort_values("proj", ascending=False)
             for p in projections.POSITIONS}
    used = {p: 0 for p in pools}
    by_pos = {p: 0.0 for p in pools}
    starters, flex_n = [], 0
    for slot in lg["roster"]:
        pos, n = slot["position"], int(slot["count"])
        if pos == projections.FLEX_SLOT:
            flex_n += n
            continue
        if pos not in pools:
            continue
        for _ in range(n):
            pool = pools[pos]
            if used[pos] < len(pool):
                by_pos[pos] += float(pool.iloc[used[pos]]["proj"])
                starters.append(pool.index[used[pos]])
            used[pos] += 1
    for _ in range(flex_n):
        best_pos = None
        best = 0.0
        for pos in projections.FLEX_POSITIONS:
            pool = pools[pos]
            if used[pos] < len(pool) and float(pool.iloc[used[pos]]["proj"]) > best:
                best, best_pos = float(pool.iloc[used[pos]]["proj"]), pos
        if best_pos is None:
            continue
        by_pos[best_pos] += best
        starters.append(pools[best_pos].index[used[best_pos]])
        used[best_pos] += 1

    lineup = players.loc[starters]
    bench = players.drop(starters)
    weight = lineup["proj"].sum()
    ratio = (lineup["proj"] * lineup["playoff_ratio"].fillna(1.0)).sum() / weight \
        if weight else 1.0
    return {
        "total": float(sum(by_pos.values())),
        "by_pos": by_pos,
        "bench": float(bench["vorp"].clip(lower=0).sum()),
        "playoff": float(ratio),
        "anchor": (lineup.loc[lineup["vorp"].idxmax()] if len(lineup) else None),
    }


def power_section(lg: dict) -> str:
    from cfb import projections

    rosters = _team_rosters()
    if not any(rosters.values()):
        return ("<p>Nothing to rank yet — the rankings appear on the first "
                "rebuild after the draft, priced off the same projections as "
                "the live draft board.</p>")

    board = (projections.value_board().drop_duplicates("yahoo_id")
             .set_index("yahoo_id"))
    names = {t["team_key"]: t for t in lg["teams"]}
    rows = []
    for key, ids in rosters.items():
        have = [i for i in dict.fromkeys(ids) if i in board.index]
        r = _best_lineup(board.loc[have], lg)
        r["team"] = names.get(key, {"name": key})
        r["unrated"] = len(set(ids)) - len(have)
        rows.append(r)
    rows.sort(key=lambda r: r["total"], reverse=True)
    avg = sum(r["total"] for r in rows) / len(rows)
    best_pos = {p: max(r["by_pos"][p] for r in rows) for p in projections.POSITIONS}

    cells = []
    for i, r in enumerate(rows, 1):
        t = r["team"]
        logo = (f'<img class="lg-logo" src="{t["logo"]}" alt="" loading="lazy">'
                if t.get("logo") else "")
        edge = r["total"] - avg
        pos_tds = "".join(
            f"<td>{'<b>' if r['by_pos'][p] == best_pos[p] and r['by_pos'][p] else ''}"
            f"{r['by_pos'][p]:.0f}"
            f"{'</b>' if r['by_pos'][p] == best_pos[p] and r['by_pos'][p] else ''}</td>"
            for p in projections.POSITIONS)
        tilt = (r["playoff"] - 1) * 100
        anchor = (f"{r['anchor']['player']} ({r['anchor']['pos']})"
                  if r["anchor"] is not None else "—")
        cells.append(
            f'<tr><td>{i}</td><td class="lg-team">{logo}{t["name"]}'
            + (f' <span class="mu-note">({r["unrated"]} unrated)</span>'
               if r["unrated"] else "") + "</td>"
            f"<td><b>{r['total']:.0f}</b></td>"
            f"<td>{edge:+.0f}</td>{pos_tds}"
            f"<td>{r['bench']:.0f}</td>"
            f"<td>{tilt:+.0f}%</td>"
            f'<td class="lg-team">{anchor}</td></tr>')

    return (
        "<p>Every roster priced the way the draft board priced the players: "
        "the best starting lineup it can field, in projected season points "
        "under this league's scoring. <b>Bench</b> is the value over "
        "replacement sitting behind the starters; <b>Wks "
        f"{lg['playoff_start_week']}–{lg['end_week']}</b> is how the lineup's "
        "schedule tilts across the fantasy playoffs. Rebuilt daily, so "
        "waivers and trades move it all season.</p>"
        '<div class="table-scroll"><table class="lg-table">'
        "<thead><tr><th>Rk</th><th>Team</th><th>Lineup</th><th>±Avg</th>"
        "<th>QB</th><th>RB</th><th>WR</th><th>TE</th><th>DEF</th>"
        f"<th>Bench</th><th>Wks {lg['playoff_start_week']}–{lg['end_week']}</th>"
        "<th>Anchor</th></tr></thead>"
        f'<tbody>{"".join(cells)}</tbody></table></div>')


# --------------------------------------------------------------------------- #
# Draft results
# --------------------------------------------------------------------------- #

def _graded_picks(picks: list[dict], lg: dict) -> pd.DataFrame:
    """Draft picks joined to the pre-draft board: name, pos, school, Δ."""
    board = yahoo.predraft_board().set_index("yahoo_id")
    team_names = {t["team_key"]: t["name"] for t in lg["teams"]}
    per_round = max((p["pick"] for p in picks if p["round"] == 1), default=LEAGUE_TEAMS)
    rows = []
    for p in picks:
        pid = str(p["player_key"] or "").rsplit(".", 1)[-1]
        b = board.loc[pid] if pid in board.index else None
        pick, rnd = int(p["pick"]), int(p["round"])
        pick_in_round = pick - (rnd - 1) * int(per_round)
        rows.append({
            "Pick": pick, "round": rnd,
            "slot": (pick_in_round if rnd % 2 == 1
                     else int(per_round) + 1 - pick_in_round),
            "Team": team_names.get(p["team_key"], p["team_key"]),
            "Player": b["player"] if b is not None else f"Player {pid}",
            "Pos": b["pos"] if b is not None else "",
            "School": b["team"] if b is not None else "",
            "Board": float(b["rank"]) if b is not None else None,
        })
    df = pd.DataFrame(rows)
    df["Δ"] = df["Pick"] - df["Board"]
    return df


def _delta_tag(delta) -> str:
    if pd.isna(delta) or abs(delta) < NUDGE:
        return ""
    cls = "up" if delta > 0 else "down"
    return f"<div class='v {cls}'>{'+' if delta > 0 else '−'}{abs(int(delta))}</div>"


def _draft_grid(df: pd.DataFrame) -> str:
    slot_owner = (df[df["round"] == 1].sort_values("slot")
                  .set_index("slot")["Team"].to_dict())
    header = "".join(f"<th>{slot_owner.get(s, '?')}</th>" for s in sorted(slot_owner))
    rows = []
    for rnd, grp in df.groupby("round"):
        by_slot = grp.set_index("slot")
        cells = []
        for s in sorted(slot_owner):
            if s not in by_slot.index:
                cells.append("<td></td>")
                continue
            p = by_slot.loc[s]
            cells.append(
                f"<td class='cur-{p['Pos']}'><div class='p'>{p['Player']}</div>"
                f"<div class='t'>{p['Pos']}{' · ' + p['School'] if p['School'] else ''}</div>"
                f"{_delta_tag(p['Δ'])}</td>")
        rows.append(f"<tr><th>Rd {int(rnd)}</th>{''.join(cells)}</tr>")
    return (f"<table class='draft-board'><thead><tr><th></th>{header}</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>")


def _manager_table(df: pd.DataFrame) -> str:
    graded = df.dropna(subset=["Δ"])
    rows = []
    for team, g in graded.groupby("Team"):
        best, worst = g.loc[g["Δ"].idxmax()], g.loc[g["Δ"].idxmin()]
        rows.append((team, g["Δ"].mean(),
                     int((g["Δ"] >= NUDGE).sum()), int((g["Δ"] <= -NUDGE).sum()),
                     f"{best['Player']} ({best['Δ']:+.0f})",
                     f"{worst['Player']} ({worst['Δ']:+.0f})"))
    rows.sort(key=lambda r: r[1], reverse=True)
    cells = "".join(
        f'<tr><td class="lg-team">{team}</td><td>{avg:+.1f}</td><td>{val}</td>'
        f'<td>{rch}</td><td class="lg-team">{best}</td><td class="lg-team">{worst}</td></tr>'
        for team, avg, val, rch, best, worst in rows)
    return ('<table class="lg-table"><thead><tr><th>Team</th><th>Avg Δ</th>'
            "<th>Values</th><th>Reaches</th><th>Best value</th><th>Biggest reach</th>"
            f'</tr></thead><tbody>{cells}</tbody></table>')


def draft_section(picks: list[dict], lg: dict) -> str:
    if not picks:
        when = _draft_when(lg)
        return (f"<p>Nothing here yet — the draft is <strong>{when}</strong>. "
                "Results land on the first rebuild after it, graded against the "
                "pre-draft board.</p>" if when else
                "<p>No draft results yet.</p>")
    df = _graded_picks(picks, lg)
    ungraded = int(df["Board"].isna().sum())
    return (
        "<p>Snake order, so even rounds run right to left. Each cell carries the "
        "pick against the player's rank on the pre-draft board: "
        "<span class='v up' style='font-weight:700;color:#1a7f4b'>+</span> lasted "
        "past the board, <span style='font-weight:700;color:#b3382c'>−</span> a "
        f"reach, shown past {NUDGE} spots either way."
        + (f" {ungraded} pick{'s' if ungraded != 1 else ''} had no board row."
           if ungraded else "") + "</p>"
        f'<div class="table-scroll">{_draft_grid(df)}</div>'
        "<h3>Teams vs the Board</h3>"
        f'<div class="table-scroll">{_manager_table(df)}</div>')


# --------------------------------------------------------------------------- #
# Transactions
# --------------------------------------------------------------------------- #

_PLAYER_MOVES = {"add", "drop", "add/drop", "trade"}


def transactions_section(txns: list[dict]) -> str:
    moves = [t for t in txns if t["type"] in _PLAYER_MOVES]
    if not moves:
        return ("<p>No player moves yet — waivers open once the draft is "
                "done.</p>")
    rows = []
    for t in moves:
        when = (datetime.fromtimestamp(t["timestamp"], tz=LEAGUE_TZ)
                .strftime("%b %-d") if t["timestamp"] else "—")
        bits = []
        for p in t["players"]:
            tag = f"{p['player']} ({p['pos']} · {p['team']})"
            if p["type"] == "add":
                dest = p.get("destination") or ""
                bid = f" for ${t['faab_bid']:g}" if t.get("faab_bid") else ""
                bits.append(f"{dest} added {tag}{bid}")
            elif p["type"] == "drop":
                bits.append(f"{p.get('source') or ''} dropped {tag}")
            else:
                bits.append(f"{p.get('source') or ''} → {p.get('destination') or ''}: {tag}")
        rows.append(f'<tr><td>{when}</td><td>{t["type"]}</td>'
                    f'<td class="lg-team">{"; ".join(bits) or "—"}</td></tr>')
    return ('<div class="table-scroll"><table class="lg-table">'
            "<thead><tr><th>Date</th><th>Type</th><th>Move</th></tr></thead>"
            f'<tbody>{"".join(rows)}</tbody></table></div>')


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #

def body() -> str:
    lg = yahoo.league()
    sb = yahoo.scoreboard()
    picks = yahoo.draft_results()
    txns = yahoo.transactions()

    built = datetime.now(LEAGUE_TZ).strftime("%b %-d, %-I:%M %p %Z")
    drafted = bool(picks)
    return (
        _CSS
        + '{% include countdown.html key="cfb" %}'
        + f'<p><a href="{lg["url"]}"><strong>{lg["name"]}</strong></a> on Yahoo — '
        f'{lg["num_teams"]} teams, {lg["scoring_label"]}, weeks '
        f'{lg["start_week"]}–{lg["end_week"]}, playoffs from week '
        f'{lg["playoff_start_week"]}. Rebuilt daily (last: {built}); every '
        "section below fills in as the season generates it.</p>"
        + _details("Standings", standings_section(lg), open=True)
        + _details("Power Rankings", power_section(lg), open=drafted)
        + _details(f"Matchups — Week {int(sb['week']) if sb.get('week') else '?'}",
                   matchups_section(sb), open=True)
        + _details("Draft Results", draft_section(picks, lg), open=drafted)
        + _details("Waivers &amp; Trades", transactions_section(txns))
    )


def generate():
    write_page(WEB_DIR / "league" / "index.html",
               f"CFB League Dashboard {SEASON}", body())


if __name__ == "__main__":
    generate()
