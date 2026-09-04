"""
Weekly matchups (docs/fantasy/matchups/) - every roster in the league, side
by side, for every week of the season.

Per matchup: both lineups in slot order with, for each player, his NFL game
this week (kickoff, then the live score, then the final), this site's own
projection for the week, three outside projections (Sleeper, ESPN, the
FantasyPros consensus), the points he has scored and the stat line behind
them. The outside three average into a consensus the scoreboard and the
matchup headers use; a Disagreements section lists where our number is
furthest from it, and once weeks are final an Accuracy section scores every
source against what happened. Starters total up; bench and IR sit below. Where a
roster's best lineup by our projection is not the one set, the swap is
spelled out under the table.

The data and the weekly projection are fantasy.league.matchups; the look is
gordstats.matchup_page, shared with the college league's page.

    python -m fantasy.site.matchups     # rebuild the page
"""
from datetime import datetime
from html import escape

import pandas as pd

from fantasy import paths, projections
from fantasy.config import LEAGUE_TZ, UPCOMING_LEAGUE_ID, UPCOMING_SEASON, UPCOMING_YEAR
from fantasy.league import ext_projections as ext
from fantasy.league import matchups as data_mod
from fantasy.site import layout
from gordstats import matchup_page as ui
from gordstats.frontmatter import add_front_matter

LOGO = "https://a.espncdn.com/i/teamlogos/nfl/500/{abbr}.png"
AVATAR = "https://sleepercdn.com/avatars/thumbs/{id}"
LEAGUE_URL = f"https://sleeper.com/leagues/{UPCOMING_LEAGUE_ID}"

SWAP_MIN = 1.0
INJURY_TAGS = {"Questionable": "Q", "Doubtful": "D", "Out": "O", "IR": "IR", "PUP": "PUP",
               "Sus": "SUS", "NA": "NA", "DNR": "DNR", "COV": "COV"}

# How a stat line reads, by position group, from Sleeper's stat keys.
_LINE = {
    "pass": [("pass_yd", "{v} pass yds"), ("pass_td", "{v} TD"), ("pass_int", "{v} INT")],
    "rush": [("rush_att", "{v} car"), ("rush_yd", "{v} rush yds"), ("rush_td", "{v} TD")],
    "rec": [("rec", "{v} rec"), ("rec_yd", "{v} rec yds"), ("rec_td", "{v} TD")],
    "misc": [("fum_lost", "{v} fum lost")],
    "k": [("fgm", "{v} FG"), ("xpm", "{v} XP")],
    "def": [("pts_allow", "{v} PA"), ("sack", "{v} sk"), ("int", "{v} INT"),
            ("fum_rec", "{v} FR"), ("def_td", "{v} TD"), ("safe", "{v} saf"),
            ("blk_kick", "{v} blk")],
}
_GROUPS = {"K": ["k"], "DEF": ["def"]}
_SKILL = ["pass", "rush", "rec", "misc"]


# --------------------------------------------------------------------------- #
# Players
# --------------------------------------------------------------------------- #

def _registry() -> dict:
    """{sleeper_id: {name, pos, team}} from the cached Sleeper player table."""
    path = paths.PLAYERS_DIR / "sleeper.parquet"
    if not path.exists():
        return {}
    df = pd.read_parquet(path, columns=["sleeper_id", "full_name", "position", "team"])
    return {str(r.sleeper_id): {"name": r.full_name or "", "pos": r.position or "",
                                "team": r.team or ""}
            for r in df.itertuples(index=False)}


def player_card(pid: str, data: dict, board: dict, registry: dict) -> dict:
    """Name, position and team for a rostered id, best source first: this
    week's Sleeper projection (current team), the projection board, then the
    player registry. A defense is its team code."""
    proj = (data.get("projections") or {}).get(pid) or {}
    b = board.get(pid) or {}
    reg = registry.get(pid) or {}
    if pid in data_mod.__dict__.get("TEAMS", ()) or (len(pid) <= 3 and pid.isalpha()):
        return {"name": f"{pid} D/ST", "pos": "DEF", "team": pid, "injury": ""}
    return {"name": proj.get("name") or b.get("player") or reg.get("name") or f"Player {pid}",
            "pos": proj.get("pos") or b.get("pos") or reg.get("pos") or "",
            "team": proj.get("team") or b.get("team") or reg.get("team") or "",
            "injury": proj.get("injury") or ""}


# --------------------------------------------------------------------------- #
# Lineups
# --------------------------------------------------------------------------- #

def starter_slots(roster_positions: list) -> list:
    return [s for s in roster_positions if s not in data_mod.BENCH_SLOTS]


def roster_rows(side: dict, reserve: list, roster_positions: list) -> list[dict]:
    """[{pid, slot}] in lineup order: starters by slot, then bench, then IR.
    Sleeper's starters list is in roster_positions order, "0" for an empty slot."""
    slots = starter_slots(roster_positions)
    rows = []
    for i, pid in enumerate(side["starters"]):
        rows.append({"pid": pid, "slot": slots[i] if i < len(slots) else "?"})
    started = set(side["starters"])
    ir = [p for p in side["players"] if p in set(reserve) and p not in started]
    bench = [p for p in side["players"] if p not in started and p not in set(ir)]
    rows.extend({"pid": p, "slot": "BN"} for p in bench)
    rows.extend({"pid": p, "slot": "IR"} for p in ir)
    return rows


def best_lineup(rows: list[dict], cards: dict, proj: dict, roster_positions: list) -> set:
    """The ids of the best lineup by `proj`: dedicated slots first, then each
    FLEX to the best RB/WR/TE left. IR players are unavailable; a player with
    no projection counts as zero."""
    avail = [r["pid"] for r in rows if r["slot"] != "IR" and r["pid"] != "0"]
    value = {p: (proj.get(p) or 0.0) for p in avail}
    pools = {}
    for p in avail:
        pools.setdefault(cards[p]["pos"], []).append(p)
    for pos in pools:
        pools[pos].sort(key=lambda i: value[i], reverse=True)
    used = {pos: 0 for pos in pools}
    chosen = set()
    flex = 0
    for slot in starter_slots(roster_positions):
        if slot == "FLEX":
            flex += 1
            continue
        pool = pools.get(slot, [])
        if used.get(slot, 0) < len(pool):
            chosen.add(pool[used[slot]])
            used[slot] += 1
    for _ in range(flex):
        best, best_v = None, -1.0
        for pos in data_mod.FLEX_POSITIONS:
            pool = pools.get(pos, [])
            if used.get(pos, 0) < len(pool) and value[pool[used[pos]]] > best_v:
                best, best_v = pos, value[pool[used[pos]]]
        if best is None:
            break
        chosen.add(pools[best][used[best]])
        used[best] += 1
    return chosen


# --------------------------------------------------------------------------- #
# Cells
# --------------------------------------------------------------------------- #

def _g(v):
    return f"{float(v):g}"


def stat_line(stats: dict, pos: str) -> str:
    bits = []
    for group in _GROUPS.get(pos, _SKILL):
        for key, fmt in _LINE[group]:
            v = stats.get(key)
            if v:
                if key == "fgm" and stats.get("fga"):
                    bits.append(f"{_g(v)}/{_g(stats['fga'])} FG")
                elif key == "xpm" and stats.get("xpa"):
                    bits.append(f"{_g(v)}/{_g(stats['xpa'])} XP")
                elif key == "rec" and stats.get("rec_tgt"):
                    bits.append(f"{_g(v)} rec ({_g(stats['rec_tgt'])} tgt)")
                else:
                    bits.append(fmt.format(v=_g(v)))
    return ", ".join(bits)


def game_cell(g: dict | None) -> str:
    if not g:
        return '<span class="bye">Bye</span>'
    where = "vs" if g.get("home") else "at"
    opp = escape(str(g.get("opp") or ""))
    sf, sa = g.get("score_for"), g.get("score_against")
    have = sf is not None and sa is not None
    state = g.get("state") or "pre"
    if state == "post" and have:
        res = "W" if sf > sa else ("L" if sf < sa else "T")
        return f'<span class="fin">{res} {int(sf)}–{int(sa)}</span> {where} {opp}'
    if state == "in":
        score = f" {int(sf)}–{int(sa)}" if have else ""
        return f'<span class="live">Live{score}</span> {where} {opp}'
    when = g.get("date")
    if when:
        try:
            when = datetime.fromisoformat(when.replace("Z", "+00:00")).astimezone(LEAGUE_TZ)
            return (f"{where} {opp} · {when:%a %-I:%M}{when:%p}"
                    .replace("AM", "a").replace("PM", "p"))
        except ValueError:
            pass
    return f"{where} {opp}"


def _logo(team: str) -> str:
    if not team:
        return ""
    abbr = {"WAS": "wsh"}.get(team, team.lower())
    return f'<img class="mu-logo" src="{LOGO.format(abbr=escape(abbr))}" alt="" loading="lazy">'


N_COLS = 9


def player_row(row: dict, card: dict, g: dict | None, proj, outside: list, pts, stats: dict,
               hint: str = "", grade: str = "") -> str:
    pid, slot = row["pid"], row["slot"]
    bench = slot in ("BN", "IR")
    if pid == "0":
        return (f'<tr class="starter"><td class="mu-slot">{escape(slot)}</td>'
                f'<td class="mu-p"><span class="mu-meta">empty</span></td><td class="mu-g"></td>'
                + "<td>—</td>" * (N_COLS - 4) + "<td class='mu-s'></td></tr>")
    inj = card.get("injury")
    inj_html = (f'<span class="inj" title="{escape(inj)}">'
                f'{escape(INJURY_TAGS.get(inj, inj[:3].upper()))}</span>' if inj else "")
    tag = {"in": '<span class="mu-hint in" title="Projects into the best lineup">start</span>',
           "out": '<span class="mu-hint out" title="A bench player projects higher">sit</span>'
           }.get(hint, "")
    grade_html = (f'<span class="mu-meta" title="FantasyPros start/sit grade">{escape(grade)}</span>'
                  if grade else "")
    return (f'<tr class="{"bench" if bench else "starter"}">'
            f'<td class="mu-slot">{escape(slot)}</td>'
            f'<td class="mu-p"><span class="nm">{_logo(card["team"])}{escape(card["name"])}</span> '
            f'<span class="mu-lbl"><span class="mu-meta">{escape(card["pos"])}'
            f'{" · " + escape(card["team"]) if card["team"] and card["pos"] != "DEF" else ""}'
            f"</span>{inj_html}{tag}{grade_html}</span></td>"
            f'<td class="mu-g">{game_cell(g)}</td>'
            f"<td>{ui.fmt(proj)}</td>"
            + "".join(f"<td>{ui.fmt(v)}</td>" for v in outside)
            + f"<td><b>{ui.fmt(pts)}</b></td>"
            f'<td class="mu-s">{escape(stat_line(stats, card["pos"]))}</td></tr>')


def roster_table(side: dict, team: dict, data: dict, ctx: dict, final: bool) -> tuple:
    """One roster. Returns (html, gs total, sleeper total, points total)."""
    rows = roster_rows(side, team.get("reserve") or [], ctx["slots"])
    cards = {r["pid"]: player_card(r["pid"], data, ctx["board"], ctx["registry"])
             for r in rows if r["pid"] != "0"}
    wk = ctx["wk"]
    proj = {}
    for pid in cards:
        if pid in wk.index and not pd.isna(wk.loc[pid, "proj_week"]):
            proj[pid] = float(wk.loc[pid, "proj_week"])
        elif cards[pid]["team"] and cards[pid]["team"] not in ctx["by_team"]:
            proj[pid] = 0.0                         # bye week, board or not
        else:
            proj[pid] = None
    sources = outside_sources(data)
    outside = {pid: [src.get(pid) for src in sources.values()] for pid in cards}
    cons = ext.consensus(*sources.values())
    grades = (data.get("external") or {}).get("fp_rank") or {}
    pts = side.get("players_points") or {}
    starters = [r for r in rows if r["slot"] not in ("BN", "IR")]
    bench = [r for r in rows if r["slot"] in ("BN", "IR")]

    hints, swaps = {}, ""
    if not final:
        best = best_lineup(rows, cards, proj, ctx["slots"])
        current = {r["pid"] for r in starters if r["pid"] != "0"}
        ins = [r["pid"] for r in bench if r["pid"] in best]
        outs = [r["pid"] for r in starters if r["pid"] != "0" and r["pid"] not in best]
        gain = sum(proj.get(i) or 0 for i in best) - sum(proj.get(i) or 0 for i in current)
        if ins and gain >= SWAP_MIN:
            hints = {**{i: "in" for i in ins}, **{o: "out" for o in outs}}
            if len(ins) == 1 and len(outs) == 1:
                what = f"{escape(cards[ins[0]]['name'])} for {escape(cards[outs[0]]['name'])}"
            else:
                what = ("start " + ", ".join(escape(cards[i]["name"]) for i in ins)
                        + ("; sit " + ", ".join(escape(cards[o]["name"]) for o in outs)
                           if outs else ""))
            swaps = (f'<p class="mu-swap">Best lineup by projection: <b>+{gain:.1f}</b> '
                     f"&mdash; {what}</p>")

    def cell(r):
        c = cards.get(r["pid"], {"name": "", "pos": "", "team": "", "injury": ""})
        return player_row(r, c, ctx["by_team"].get(c["team"]), proj.get(r["pid"]),
                          outside.get(r["pid"], [None] * len(sources)), pts.get(r["pid"]),
                          (data.get("stats") or {}).get(r["pid"]) or {}, hints.get(r["pid"]),
                          (grades.get(r["pid"]) or {}).get("grade") or "")

    gs_total = sum(proj.get(r["pid"]) or 0 for r in starters)
    src_totals = [sum((src.get(r["pid"]) or 0) for r in starters) for src in sources.values()]
    cons_total = sum(cons.get(r["pid"]) or 0 for r in starters)
    pts_total = float(side.get("points") or 0)
    html_rows = [cell(r) for r in starters]
    html_rows.append(f'<tr class="total"><td></td><td class="mu-p">Starters</td><td></td>'
                     f"<td>{gs_total:.1f}</td>"
                     + "".join(f"<td>{t:.1f}</td>" for t in src_totals)
                     + f"<td>{pts_total:.1f}</td><td></td></tr>")
    if bench:
        html_rows.append(f'<tr class="sep"><td colspan="{4 + len(sources) + 2}">Bench</td></tr>')
        html_rows.extend(cell(r) for r in bench)
    heads = "".join(f"<th title='{ext.SOURCES[k]} projection for this week'>{SHORT[k]}</th>"
                    for k in sources)
    html = ('<div class="table-scroll"><table class="mu-roster"><thead><tr>'
            "<th>Slot</th><th>Player</th><th>Game</th>"
            f"<th title='GordStats projection for this week'>GS</th>{heads}"
            "<th title='Points scored this week'>Pts</th><th>Stats</th>"
            f'</tr></thead><tbody>{"".join(html_rows)}</tbody></table></div>{swaps}')
    return html, gs_total, cons_total, pts_total


SHORT = {"sleeper": "Slpr", "espn": "ESPN", "fp": "FP"}


def outside_sources(data: dict) -> dict:
    """{key: {player_id: pts}} for every outside projection the week carries,
    in a fixed order, Sleeper's own first."""
    out = {"sleeper": {pid: v["pts"] for pid, v in (data.get("projections") or {}).items()
                       if v.get("pts") is not None}}
    external = data.get("external") or {}
    for key in ("espn", "fp"):
        if external.get(key):
            out[key] = external[key]
    return out


# --------------------------------------------------------------------------- #
# A matchup, a week, the page
# --------------------------------------------------------------------------- #

def _avatar(t: dict) -> str:
    return (f'<img class="mu-tlogo" src="{AVATAR.format(id=escape(t["avatar"]))}" alt="" '
            'loading="lazy">' if t.get("avatar") else "")


def _record(t: dict) -> str:
    return f"{t.get('wins', 0)}-{t.get('losses', 0)}" + (f"-{t['ties']}" if t.get("ties") else "")


def _label(t: dict) -> str:
    name = escape(t.get("name") or "")
    mgr = t.get("manager")
    return name + (f' <span class="mu-meta">({escape(mgr)})</span>' if mgr and mgr not in name else "")


def matchup_section(m: dict, data: dict, ctx: dict, anchor: str) -> tuple:
    final = data_mod.week_final(data)
    started = data_mod.week_started(data)
    sides = []
    for s in m["sides"]:
        t = data["teams"].get(str(s["roster_id"])) or data["teams"].get(s["roster_id"]) or {}
        html, gs, sp, pts = roster_table(s, t, data, ctx, final)
        sides.append({"team": t, "name": t.get("name") or f"Team {s['roster_id']}",
                      "html": html, "gs": gs, "sp": sp, "pts": pts if started else None})
    if len(sides) != 2:
        return "", sides
    a, b = sides
    lead = (None if not started or a["pts"] == b["pts"]
            else ("a" if (a["pts"] or 0) > (b["pts"] or 0) else "b"))

    def side_html(s, which):
        big = ui.fmt(s["pts"]) if started else ui.fmt(s["gs"])
        cls = " lead" if lead == which else ""
        sub = (f"Consensus <b>{ui.fmt(s['sp'])}</b> · GordStats <b>{ui.fmt(s['gs'])}</b>"
               if started else f"Consensus proj <b>{ui.fmt(s['sp'])}</b>")
        return (f'<div class="mu-side {"r" if which == "b" else ""}">{_avatar(s["team"])}'
                f'<div><div class="nm">{_label(s["team"])}'
                f'<span class="rec">{_record(s["team"])}</span></div>'
                f'<div class="num{cls}">{big}</div><div class="sub">{sub}</div></div></div>')

    mid = "Final" if final else ("Live" if started else "Preview")
    edge = a["gs"] - b["gs"]
    note = (f"GordStats has <b>{escape(a['name'] if edge >= 0 else b['name'])}</b> by "
            f"{abs(edge):.1f} on projection ({ui.fmt(a['gs'])}–{ui.fmt(b['gs'])}); the "
            f"consensus has {ui.fmt(a['sp'])}–{ui.fmt(b['sp'])}." if not final else
            f"GordStats projected {ui.fmt(a['gs'])}–{ui.fmt(b['gs'])} going in, the consensus "
            f"{ui.fmt(a['sp'])}–{ui.fmt(b['sp'])}.")
    body = (f'<div class="mu-head">{side_html(a, "a")}<div class="mu-mid">{mid}</div>'
            f'{side_html(b, "b")}</div><p class="mu-note">{note}</p>'
            f'<div class="mu-grid"><div><div class="mu-who">{escape(a["name"])}</div>{a["html"]}</div>'
            f'<div><div class="mu-who">{escape(b["name"])}</div>{b["html"]}</div></div>')
    head = (f'{escape(a["name"])} {ui.fmt(a["pts"]) if started else ""} '
            f'<span style="color:#94a3b8">vs</span> '
            f'{ui.fmt(b["pts"]) if started else ""} {escape(b["name"])}')
    return layout.details(head, body, open=True, anchor=anchor), sides


def week_board(rows: list, started: bool) -> str:
    def num(s, o, key):
        v, ov = s.get(key), o.get(key)
        lead = v is not None and ov is not None and v > ov
        return f"<td>{'<b class=lead>' if lead else ''}{ui.fmt(v)}{'</b>' if lead else ''}</td>"
    cells = []
    for anchor, a, b in rows:
        cells.append(
            f'<tr><td class="mu-t"><a href="#{anchor}">{_avatar(a["team"])}'
            f'{escape(a["name"])}</a></td>'
            + (num(a, b, "pts") if started else "") + num(a, b, "sp") + num(a, b, "gs")
            + '<td class="mu-vs">vs</td>'
            + num(b, a, "gs") + num(b, a, "sp") + (num(b, a, "pts") if started else "")
            + f'<td class="mu-t r"><a href="#{anchor}">{escape(b["name"])}'
              f'{_avatar(b["team"])}</a></td></tr>')
    pts_h = "<th>Pts</th>" if started else ""
    return ('<div class="table-scroll"><table class="mu-board"><thead><tr>'
            f"<th>Team</th>{pts_h}<th title='Average of the outside projections for the lineup as set'>Consensus</th>"
            "<th title='GordStats projected total for the lineup as set'>GS Proj</th><th></th>"
            f"<th>GS Proj</th><th>Consensus</th>{pts_h}<th>Team</th>"
            f'</tr></thead><tbody>{"".join(cells)}</tbody></table></div>')


def week_view(data: dict, ctx: dict) -> str:
    week = int(data["week"])
    ctx = {**ctx, "by_team": data_mod.team_games(data["games"]),
           "wk": data_mod.week_projections(ctx["board_frame"], data["games"])}
    final = data_mod.week_final(data)
    started = data_mod.week_started(data)
    sections, rows = [], []
    for i, m in enumerate(data["matchups"], 1):
        anchor = f"wk{week}-m{i}"
        html, sides = matchup_section(m, data, ctx, anchor)
        if html:
            sections.append(html)
            rows.append((anchor, sides[0], sides[1]))
    dates = sorted(g["date"] for g in data["games"] if g.get("date"))
    span = ""
    if dates:
        lo = datetime.fromisoformat(dates[0].replace("Z", "+00:00")).astimezone(LEAGUE_TZ)
        hi = datetime.fromisoformat(dates[-1].replace("Z", "+00:00")).astimezone(LEAGUE_TZ)
        span = f" · {lo:%b %-d} – {hi:%b %-d}"
    extra = disagreements_section(data, ctx)
    state = "Final" if final else "In progress" if started else "Not started"
    asof = ""
    if started and not final and data.get("fetched"):
        asof = (" · points as of " + datetime.fromisoformat(data["fetched"])
                .astimezone(LEAGUE_TZ).strftime("%a %-I:%M %p"))
    playoffs = " (playoffs)" if ctx["playoff_start"] and week >= ctx["playoff_start"] else ""
    return (f"<p><strong>Week {week}</strong>{span}{playoffs} · {state}{asof}</p>"
            + week_board(rows, started) + extra + "".join(sections))


# --------------------------------------------------------------------------- #
# Where the sources part ways, and who was right
# --------------------------------------------------------------------------- #

DISAGREE_N = 12


def rostered(data: dict) -> dict:
    """{player_id: (team name, slot)} for every player on a roster this week."""
    out = {}
    slots = starter_slots(ctx_slots(data))
    for m in data["matchups"]:
        for s in m["sides"]:
            t = data["teams"].get(str(s["roster_id"])) or {}
            for i, pid in enumerate(s["starters"]):
                if pid != "0":
                    out[pid] = (t.get("name", ""), slots[i] if i < len(slots) else "?")
            for pid in s["players"]:
                out.setdefault(pid, (t.get("name", ""), "BN"))
    return out


def ctx_slots(data: dict) -> list:
    return data.get("roster_positions") or ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX",
                                            "K", "DEF"]


def disagreements(data: dict, ctx: dict) -> list[dict]:
    """Rostered players where our projection sits furthest from the consensus,
    biggest gap first: [{pid, name, pos, owner, slot, gs, cons, gap, sources}]."""
    sources = outside_sources(data)
    cons = ext.consensus(*sources.values())
    wk = ctx["wk"]
    out = []
    for pid, (owner, slot) in rostered(data).items():
        if pid not in cons or pid not in wk.index or pd.isna(wk.loc[pid, "proj_week"]):
            continue
        gs = float(wk.loc[pid, "proj_week"])
        card = player_card(pid, data, ctx["board"], ctx["registry"])
        out.append({"pid": pid, "name": card["name"], "pos": card["pos"], "team": card["team"],
                    "owner": owner, "slot": slot, "gs": gs, "cons": cons[pid],
                    "gap": gs - cons[pid],
                    "sources": [src.get(pid) for src in sources.values()]})
    out.sort(key=lambda r: -abs(r["gap"]))
    return out


def disagreements_section(data: dict, ctx: dict) -> str:
    rows = disagreements(data, ctx)
    if not rows:
        return ""
    sources = outside_sources(data)
    heads = "".join(f"<th>{SHORT[k]}</th>" for k in sources)
    cells = []
    for r in rows[:DISAGREE_N]:
        up = r["gap"] > 0
        cells.append(
            f'<tr><td class="mu-t">{_logo(r["team"])}{escape(r["name"])} '
            f'<span class="mu-meta">{escape(r["pos"])}</span></td>'
            f'<td class="mu-t">{escape(r["owner"])} <span class="mu-meta">{escape(r["slot"])}</span></td>'
            f"<td><b>{ui.fmt(r['gs'])}</b></td>"
            + "".join(f"<td>{ui.fmt(v)}</td>" for v in r["sources"])
            + f"<td>{ui.fmt(r['cons'])}</td>"
            f'<td><b class="{"lead" if up else ""}">{r["gap"]:+.1f}</b></td></tr>')
    n_src = len(sources)
    body = ('<p class="mu-note">Rostered players where this site\'s projection sits furthest '
            f"from the average of the {n_src} outside sources. A positive gap means we like "
            "him more than the market does; the Accuracy section below says, once weeks are "
            "final, which side of these calls has been right.</p>"
            '<div class="table-scroll"><table class="mu-board"><thead><tr><th>Player</th>'
            f"<th>Roster</th><th>GS</th>{heads}<th>Consensus</th><th>Gap</th></tr></thead>"
            f'<tbody>{"".join(cells)}</tbody></table></div>')
    return layout.details("Disagreements &mdash; where GordStats parts from the consensus",
                          body, open=False)


def accuracy(datas: dict, ctx: dict) -> pd.DataFrame | None:
    """Every source scored on the finished weeks: mean absolute error and bias
    over starters who were projected and played, plus the consensus and us."""
    records = []
    for w, data in datas.items():
        if not data_mod.week_final(data):
            continue
        sources = outside_sources(data)
        cons = ext.consensus(*sources.values())
        wk = data_mod.week_projections(ctx["board_frame"], data["games"])
        for m in data["matchups"]:
            for s in m["sides"]:
                pts = s.get("players_points") or {}
                for pid in s["starters"]:
                    if pid == "0" or pid not in pts:
                        continue
                    actual = float(pts[pid] or 0)
                    row = {"week": w, "pid": pid, "actual": actual}
                    row["gordstats"] = (float(wk.loc[pid, "proj_week"])
                                        if pid in wk.index and not pd.isna(wk.loc[pid, "proj_week"])
                                        else None)
                    for k, src in sources.items():
                        row[k] = src.get(pid)
                    row["consensus"] = cons.get(pid)
                    records.append(row)
    if not records:
        return None
    frame = pd.DataFrame(records)
    cols = ["gordstats"] + [k for k in ("sleeper", "espn", "fp") if k in frame.columns] + ["consensus"]
    rows = []
    for c in cols:
        have = frame.dropna(subset=[c])
        if have.empty:
            continue
        err = have[c] - have["actual"]
        rows.append({"source": c, "n": len(have), "mae": err.abs().mean(),
                     "bias": err.mean(), "corr": have[c].corr(have["actual"])})
    return pd.DataFrame(rows).sort_values("mae")


def accuracy_section(datas: dict, ctx: dict) -> str:
    table = accuracy(datas, ctx)
    if table is None or table.empty:
        return ""
    names = {"gordstats": "GordStats", "consensus": "Consensus", **ext.SOURCES}
    weeks = sorted(w for w, d in datas.items() if data_mod.week_final(d))
    cells = "".join(
        f'<tr><td class="mu-t"><b>{names.get(r.source, r.source)}</b></td><td>{r.n}</td>'
        f"<td>{r.mae:.2f}</td><td>{r.bias:+.2f}</td><td>{r.corr:.2f}</td></tr>"
        for r in table.itertuples())
    body = ('<p class="mu-note">Every source against what starters actually scored, over '
            f"week{'s' if len(weeks) > 1 else ''} {', '.join(map(str, weeks))}. "
            "<b>MAE</b> is the average miss in points, <b>Bias</b> the average signed "
            "miss (positive = projected too high), <b>r</b> the correlation with the "
            "real score. Lowest MAE first.</p>"
            '<div class="table-scroll"><table class="mu-board"><thead><tr><th>Source</th>'
            "<th>Players</th><th>MAE</th><th>Bias</th><th>r</th></tr></thead>"
            f"<tbody>{cells}</tbody></table></div>")
    return layout.details("Projection accuracy &mdash; who has been right", body, open=False)


def _board(weeks: list, datas: dict) -> pd.DataFrame:
    """The projection board, pulled toward the season so far once weeks have
    been played - the same blend the power page ranks on."""
    board = projections.load(UPCOMING_YEAR)
    scored = sum(1 for w in weeks if data_mod.week_final(datas[w]))
    through = min(scored, projections.completed_weeks(UPCOMING_YEAR))
    if through > 0:
        try:
            board = projections.current_form(board, UPCOMING_YEAR, refresh=False,
                                             through_week=through)
        except Exception as exc:                        # noqa: BLE001
            print(f"[matchups] preseason projections only ({exc})")
    return board


def body() -> str:
    # Fetch for itself, the way the power page does: the current week
    # refetches when its cache is older than a few hours, finished weeks
    # never do, and an unreachable Sleeper leaves whatever is on disk.
    try:
        weeks = data_mod.capture(year=UPCOMING_YEAR)
    except Exception as exc:                            # noqa: BLE001
        print(f"[matchups] using the archive only ({exc})")
        weeks = data_mod.archived_weeks(UPCOMING_YEAR)
    if not weeks:
        return (ui.CSS + f"<p>No matchups yet — Sleeper posts the {UPCOMING_SEASON} schedule "
                "once the draft is done, and this page fills in on the next rebuild.</p>")
    lg = data_mod.league()
    datas = {w: data_mod.week_matchups(w, UPCOMING_YEAR) for w in weeks}
    board_frame = _board(weeks, datas)
    board = {str(r.sleeper_id): {"player": r.player, "pos": r.pos, "team": r.team}
             for r in board_frame.drop_duplicates("sleeper_id").itertuples(index=False)}
    ctx = {"slots": lg["roster_positions"], "board_frame": board_frame, "board": board,
           "registry": _registry(), "playoff_start": lg.get("playoff_week_start") or 0}
    for d in datas.values():
        d["roster_positions"] = lg["roster_positions"]
    open_weeks = [w for w in weeks if not data_mod.week_final(datas[w])]
    current = open_weeks[0] if open_weeks else weeks[-1]
    views = {w: week_view(datas[w], ctx) for w in weeks}
    scored = accuracy_section(datas, ctx)

    built = datetime.now(LEAGUE_TZ).strftime("%b %-d, %-I:%M %p %Z")
    return (
        ui.CSS
        + f'<p><a href="{LEAGUE_URL}"><strong>{escape(lg["name"] or "The league")}</strong></a> '
        f"— every {UPCOMING_SEASON} matchup with both rosters in full. <b>GS Proj</b> is "
        "this site's projection for the week: the power model's points per game for "
        "each player, tilted by the market's implied total for his team this week "
        "(a defense the other way, on what its opponent is expected to score), and "
        "zero on a bye. Beside it, three outside projections for the same week: "
        "<b>Slpr</b> is Sleeper's, <b>ESPN</b> is ESPN's, <b>FP</b> is the FantasyPros "
        "expert consensus (whose start/sit grade sits by the name); their average is "
        "the <b>Consensus</b> the scoreboard compares us against. <b>Pts</b> is what "
        "the league has scored so far, with the stat line behind it. "
        "Ahead of the final whistle a roster whose bench out-projects a starter gets "
        f"the swap spelled out under the table. Rebuilt several times a day and every "
        f"ten minutes while games are on (last: {built}); finished weeks stay on "
        "record. Season-long standing lives on the "
        '<a href="/fantasy/power/">power rankings</a>.</p>'
        + scored + ui.week_switch(weeks, current, views))


def generate():
    page = add_front_matter(layout.HEAD + body(), "Weekly Matchups")
    out = paths.WEB_MATCHUPS
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"Wrote Weekly Matchups -> {out}")


if __name__ == "__main__":
    generate()
