"""
The league dashboard (docs/cfb/league/) - the CFB fantasy league itself.

Four sections, each rendering whatever the season has produced so far and
saying plainly what it is still waiting on:

  * Standings      - records, points, FAAB and moves (teams exist predraft).
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
/* An identity cell (team, or the transactions date) leads every lg-table, so
   pinning first-child holds it while the rest scrolls on a phone. The cells
   already carry opaque themed backgrounds (zebra and dark) from these rules. */
table.lg-table td:first-child,table.lg-table th:first-child{
  position:sticky;left:0;z-index:1}
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
            '<tr><td class="lg-team">'
            + (f'<span class="row-rank">{rank}</span>' if played else "")
            + f'{logo}{t["name"]}</td>'
            f"{mgr}<td>{_rec(t)}</td>"
            f"<td>{t.get('points_for') or 0:g}</td>"
            f"<td>{t.get('points_against') or 0:g}</td>"
            f"<td>${t.get('faab') or 0:g}</td>"
            f"<td>{int(t.get('moves') or 0)}</td></tr>")
    note = ('<p class="mu-note">'
            + ("" if played else "Everyone is 0-0 until the games start. ")
            + "<strong>PF</strong>/<strong>PA</strong> are points for and "
            "against; <strong>FAAB</strong> is the season's $100 waiver "
            "budget.</p>")
    mgr_head = "<th>Manager</th>" if named else ""
    return (note + '<div class="table-scroll"><table class="lg-table">'
            f"<thead><tr><th>Team</th>{mgr_head}<th>Record</th>"
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
    note = ('<p class="mu-note">'
            + ("" if live else "Pairings are set; points appear once the "
               "week's games kick off. ")
            + 'Full rosters, player by player, are on the '
            '<a href="/cfb/matchups/">matchups page</a>.</p>')
    return (f"<p><strong>Week {int(sb['week'])}</strong> · {start} – {end}"
            + (" (playoffs)" if mu0.get("is_playoffs") else "") + "</p>" + note
            + '<div class="table-scroll"><table class="lg-table">'
              "<thead><tr><th>Team</th><th colspan='2'>Score</th><th>Team</th></tr></thead>"
            f'<tbody>{"".join(rows)}</tbody></table></div>')


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
    return (f"<table class='draft-board'><thead><tr><th>Rd</th>{header}</tr></thead>"
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
        + '{% include cfb_countdown.html %}'
        + f'<p><a href="{lg["url"]}"><strong>{lg["name"]}</strong></a> on Yahoo — '
        f'{lg["num_teams"]} teams, {lg["scoring_label"]}, weeks '
        f'{lg["start_week"]}–{lg["end_week"]}, playoffs from week '
        f'{lg["playoff_start_week"]}. Rebuilt daily (last: {built}); every '
        "section below fills in as the season generates it. Roster-strength "
        'power rankings have <a href="/cfb/league-power/">their own page</a>, '
        'and the draft is graded on the <a href="/cfb/live/">draft '
        "review</a>.</p>"
        + _details("Standings", standings_section(lg), open=True)
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
