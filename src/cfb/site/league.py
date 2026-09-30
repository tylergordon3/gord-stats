"""
The league dashboard (docs/cfb/league/) - the CFB fantasy league itself.

Four sections, each rendering whatever the season has produced so far and
saying plainly what it is still waiting on:

  * Standings      - records, points, FAAB and moves (teams exist predraft).
  * (Power Rankings - every roster priced as its best lineup - are the league's
     Power tab, docs/cfb/league/power/ (cfb.site.league_power); the
     Standings end with a link there, id="power" for the old anchor.)
  * Schedule Difficulty - what the schedule has done to each record, in
                     wins: opponents' strength and their timing
                     (gordstats.schedule_luck), from the finished weeks.
  * Matchups       - the current week's scoreboard; pairings before kickoff,
                     projections and points once Yahoo serves them.
  * (The draft - grid, grades, every pick - lives on the draft review page,
     cfb.site.draft_review, not here.)
  * Waiver Watch   - the best available player at each position for the week
                     ahead, and the weakest thing each roster is holding.
  * League Records - the archive as finding cards (gordstats.hub): the draft
                     review, leading with the best-graded draft.
  * Transactions   - player adds / drops / trades. Yahoo logs commissioner
                     actions too; those are noise and are filtered out here.

    python -m cfb.site.league       # rebuild the page
"""
from datetime import datetime

from html import escape

from cfb import waivers, yahoo
from cfb.config import LEAGUE_TZ, SEASON, WEB_DIR
from cfb.site import recap, write_page
from gordstats import hub, schedule_luck
from gordstats.frontmatter import liquid

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
.wv-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;
  margin:6px 0 16px}
.wv-col h4{margin:0 0 4px;font-size:14px}
.wv-col .mu-meta{font-size:12px;color:#64748b}
.inj{font-size:10px;font-weight:700;color:#b3382c;margin-left:4px}
@media (prefers-color-scheme: dark){
  .cfb-league{background:#1b2540;border-color:#2b3852;color:#dde5ef}
  table.lg-table th{background:#223052;color:#dde5ef;border-color:#2b3852}
  table.lg-table td{background:#16203a;border-color:#2b3852;color:#dde5ef}
  table.lg-table tbody tr:nth-child(even) td{background:#1b2540}
  .mu-note{color:#aab7c9}
  .inj{color:#ffb4ab}
}
</style>"""


def _details(summary: str, body: str, open: bool = False, anchor: str = "") -> str:
    return (f'<details class="section"{" open" if open else ""}'
            f'{f" id={chr(34)}{anchor}{chr(34)}" if anchor else ""}>'
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
        logo = (f'<img class="lg-logo" src="{escape(t["logo"], quote=True)}" alt="" '
                'loading="lazy">' if t.get("logo") else "")
        mgr = f"<td>{escape(t['manager'] or '—')}</td>" if named else ""
        rows.append(
            '<tr><td class="lg-team">'
            + (f'<span class="row-rank">{rank}</span>' if played else "")
            + f'{logo}{escape(t["name"])}</td>'
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
            return escape(t["name"]), num
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
            tag = escape(f"{p['player']} ({p['pos']} · {p['team']})")
            src, dest = escape(p.get("source") or ""), escape(p.get("destination") or "")
            if p["type"] == "add":
                bid = f" for ${t['faab_bid']:g}" if t.get("faab_bid") else ""
                bits.append(f"{dest} added {tag}{bid}")
            elif p["type"] == "drop":
                bits.append(f"{src} dropped {tag}")
            else:
                bits.append(f"{src} → {dest}: {tag}")
        rows.append(f'<tr><td>{when}</td><td>{t["type"]}</td>'
                    f'<td class="lg-team">{"; ".join(bits) or "—"}</td></tr>')
    return ('<div class="table-scroll"><table class="lg-table">'
            "<thead><tr><th>Date</th><th>Type</th><th>Move</th></tr></thead>"
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def waiver_section(sb: dict) -> str:
    """The pool and the roster spots it could take.

    Ranked inside each position, never across them: a quarterback outscores a
    running back every week, and a single combined list would be five
    quarterbacks and nothing a reader could act on.
    """
    try:
        available, rostered, week = waivers.pools()
    except Exception as exc:                            # noqa: BLE001
        print(f"  ! waiver watch unavailable ({exc})")
        return ""
    by_pos = waivers.adds(available)
    if not by_pos:
        return "<p>Yahoo has no available players with a projection this week.</p>"

    cols = []
    for pos, rows in by_pos.items():
        cells = "".join(
            f'<tr><td class="lg-team">{escape(str(r["player"]))}'
            f'<span class="mu-meta"> {escape(str(r["team"]))}</span></td>'
            f'<td>{r["proj"]:.1f}</td></tr>'
            for _, r in rows.iterrows())
        cols.append('<div class="wv-col"><h4>' + pos + '</h4>'
                    '<table class="lg-table"><thead><tr><th>Player</th><th>Proj</th>'
                    f'</tr></thead><tbody>{cells}</tbody></table></div>')

    drop_rows = waivers.drops(rostered)
    # The scoreboard carries the names, one matchup at a time.
    names = {t["team_key"]: t.get("name") or t["team_key"]
             for m in (sb.get("matchups") or []) for t in m.get("teams") or []}
    drop_rows = drop_rows.assign(
        team_name=[names.get(k, k) for k in drop_rows["team_key"]]).sort_values(
        ["team_name", "proj"])
    drops = "".join(
        f'<tr><td class="lg-team">{escape(str(r["team_name"]))}</td>'
        f'<td class="lg-team">{escape(str(r["player"]))}'
        + (f' <span class="inj">{escape(str(r["status"]))}</span>' if r["status"] else "")
        + f'</td><td>{escape(str(r["pos"]))}</td><td>{escape(str(r["slot"]))}</td>'
        f'<td>{r["proj"]:.1f}</td></tr>'
        for _, r in drop_rows.iterrows())

    return (
        f'<p class="mu-note">The best available player at each position for '
        f'<strong>week {week}</strong>, on this site\'s own weekly projection, and the '
        'weakest player each roster is holding. Defences are left off the drop list '
        '(every roster has to field one) and anyone Yahoo has flagged sorts to the top '
        'of his team\'s row - an injured player is the roster spot doing nothing.</p>'
        f'<div class="wv-grid">{"".join(cols)}</div>'
        '<h4>Weakest rostered</h4><div class="table-scroll"><table class="lg-table">'
        '<thead><tr><th>Team</th><th>Player</th><th>Pos</th><th>Slot</th><th>Proj</th>'
        f'</tr></thead><tbody>{drops}</tbody></table></div>')


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #

def body() -> str:
    lg = yahoo.league()
    sb = yahoo.scoreboard()
    txns = yahoo.transactions()

    built = datetime.now(LEAGUE_TZ).strftime("%b %-d, %-I:%M %p %Z")
    return (
        _CSS
        + liquid('{% include cfb_countdown.html %}')
        + f'<p><a href="{escape(lg["url"], quote=True)}"><strong>{escape(lg["name"])}</strong></a> on Yahoo — '
        f'{lg["num_teams"]} teams, {lg["scoring_label"]}, weeks '
        f'{lg["start_week"]}–{lg["end_week"]}, playoffs from week '
        f'{lg["playoff_start_week"]}. Rebuilt daily (last: {built}); every '
        "section below fills in as the season generates it. The draft - every "
        'pick, graded - is on the <a href="/cfb/live/">draft review</a>.</p>'
        + recap.teaser()
        + _details("Standings", standings_section(lg) + _POWER_LINK, open=True)
        + _details("Schedule Difficulty", schedule_section(lg), open=True, anchor="schedule")
        + _details(f"Matchups — Week {int(sb['week']) if sb.get('week') else '?'}",
                   matchups_section(sb), open=True)
        + _details("League Records", records_section(), open=True, anchor="records")
        + _details("Waiver Watch", waiver_section(sb), open=True,
                   anchor="waivers")
        + _details("Waivers &amp; Trades", transactions_section(txns))
    )


# The power rankings are the Power tab now (docs/cfb/league/power/). id="power"
# keeps the section's old anchor landing somewhere that says where they went.
_POWER_LINK = ("<p class='mu-note' id='power'><a href='/cfb/league/power/'><b>Power "
               "rankings &rarr;</b></a> every roster's best lineup, the rest of the season "
               "played out.</p>")


def _draft_finding() -> str:
    try:
        from cfb.site import draft_review
        top = draft_review.grade_rows(draft_review.graded(), yahoo.league())[0]
        return f"Best draft by our grades: {top['team']} ({top['grade']})"
    except Exception as exc:                                # noqa: BLE001
        print(f"  ! records finding (draft): {type(exc).__name__}: {exc}")
        return ""


def schedule_section(lg: dict) -> str:
    """Schedule difficulty over the finished regular-season weeks."""
    first = int(lg.get("start_week") or 1)
    playoff_start = int(lg.get("playoff_start_week") or int(lg["end_week"]) + 1)
    rows = []
    for week in yahoo.archived_weeks():
        if not first <= week < playoff_start:
            continue
        data = yahoo.week_matchups(week)
        if not yahoo.week_final(data):
            continue
        for m in data["matchups"]:
            if len(m["teams"]) != 2:
                continue
            a, b = m["teams"]
            pa, pb = float(a.get("points") or 0.0), float(b.get("points") or 0.0)
            rows += [(week, a["team_key"], b["team_key"], pa, pb),
                     (week, b["team_key"], a["team_key"], pb, pa)]
    names = {t["team_key"]: t["name"] for t in lg["teams"]}
    return schedule_luck.html(schedule_luck.table(rows), names)


def records_section() -> str:
    """The archive, as on the NFL League Home (fantasy.site.records): a card
    per page, leading with what it found."""
    return hub.cards([
        ("/cfb/live/", "Draft review", _draft_finding(),
         "Every pick graded against where it went, our grades beside Yahoo's"),
    ])


def generate():
    write_page(WEB_DIR / "league" / "index.html", f"CFB League Dashboard {SEASON}", body())


if __name__ == "__main__":
    generate()
