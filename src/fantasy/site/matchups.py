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
from fantasy.config import (LEAGUE_TZ, ROSTER_NAMES, UPCOMING_LEAGUE_ID, UPCOMING_SEASON,
                            UPCOMING_YEAR)
from fantasy.league import ext_projections as ext
from fantasy.league import head_to_head as h2h
from fantasy.league import matchups as data_mod
from fantasy.site import layout
from gordstats import logos, matchup_page as ui
from gordstats import my_league, my_league_data, my_matchups, my_week
from gordstats.frontmatter import add_front_matter

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


def injury_status(data: dict) -> dict:
    """{sleeper_id: Sleeper's injury designation} as the week's archive saw it."""
    return {pid: v["injury"] for pid, v in (data.get("projections") or {}).items()
            if v.get("injury")}


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
    return logos.img("nfl", team, 18, cls="mu-logo")


N_COLS = 9


def _sd_for(sd, proj) -> float:
    """The spread of a player's week: the board's, or a share of the
    projection when it has none for him, and never trivially small."""
    if sd is not None and not pd.isna(sd) and sd > 0:
        return float(sd)
    return max(2.0, 0.6 * float(proj or 0.0))


def expected(pts, proj, sd, g: dict | None) -> tuple:
    """(expected final, variance) for one player this week: the projection
    before kickoff, the points once the game is over, and in between the
    points so far plus the unplayed share of the projection, with the
    variance shrinking the same way. The live script does the same sum in
    the browser as the clocks run."""
    proj = float(proj or 0.0)
    pts = float(pts or 0.0)
    done = float((g or {}).get("elapsed", 0.0)) if g else 0.0
    left = 1.0 - done
    return pts + proj * left, _sd_for(sd, proj) ** 2 * left


def game_state(g: dict | None) -> str:
    """pre/in/post for a player's game, "bye" when his team has none."""
    return (g.get("state") or "pre") if g else "bye"


def hybrid_score(pts, hproj, g: dict | None) -> str:
    """The Pts cell (ui.score_cell) on the blended projection: what the
    sources expect before kickoff, points plus the unplayed share of
    it during the game, points after."""
    state = game_state(g)
    exp = expected(pts, hproj, None, g)[0] if state == "in" else None
    return ui.score_cell(pts, hproj, state, exp)


def _proj_cell(v, col: str, cls: str = "") -> str:
    pre = "" if v is None else f' data-pre="{round(float(v), 2)}"'
    klass = f' class="{cls}"' if cls else ""
    return f'<td{klass} data-col="{col}"{pre}>{ui.fmt(v)}</td>'


def player_row(row: dict, card: dict, g: dict | None, proj, outside: list, pts, stats: dict,
               hint: str = "", grade: str = "", sd: float = 0.0, hproj=None) -> str:
    pid, slot = row["pid"], row["slot"]
    bench = slot in ("BN", "IR")
    if pid == "0":
        return (f'<tr class="starter"><td class="mu-pts">—</td>'
                f'<td class="mu-slot">{escape(slot)}</td>'
                f'<td class="mu-p"><span class="mu-meta">empty</span></td><td class="mu-g"></td>'
                + "<td>—</td>" * (N_COLS - 5) + "<td class='mu-s'></td></tr>")
    inj = card.get("injury")
    inj_html = (f'<span class="inj" title="{escape(inj)}">'
                f'{escape(INJURY_TAGS.get(inj, inj[:3].upper()))}</span>' if inj else "")
    tag = {"in": '<span class="mu-hint in" title="Projects into the best lineup">start</span>',
           "out": '<span class="mu-hint out" title="A bench player projects higher">sit</span>'
           }.get(hint, "")
    grade_html = (f'<span class="mu-meta" title="FantasyPros start/sit grade">{escape(grade)}</span>'
                  if grade else "")
    live = " live" if g and g.get("state") == "in" else ""
    done = " done" if g and g.get("state") == "post" else ""
    gid = (g or {}).get("game_id")
    attrs = (f' data-gid="{escape(str(gid))}" data-side="{"home" if g.get("home") else "away"}"'
             if gid else "")
    return (f'<tr class="{"bench" if bench else "starter"}{live}{done}" data-pid="{escape(pid)}" '
            f'data-team="{escape(card["team"] or "")}"{attrs} '
            f'data-nm="{escape(_short_name(card["name"]))}" data-pos="{escape(card["pos"])}" '
            f'data-proj="{"" if proj is None else round(proj, 2)}" data-sd="{sd:.2f}" '
            f'data-hproj="{"" if hproj is None else round(hproj, 2)}">'
            f'<td class="mu-pts">{hybrid_score(pts, hproj, g)}</td>'
            f'<td class="mu-slot">{escape(slot)}</td>'
            f'<td class="mu-p"><span class="mu-pc"><span class="nm">{_logo(card["team"])}'
            f'{escape(card["name"])}</span> '
            f'<span class="mu-lbl"><span class="mu-meta">{escape(card["pos"])}'
            f'{" · " + escape(card["team"]) if card["team"] and card["pos"] != "DEF" else ""}'
            f"</span>{inj_html}{tag}{grade_html}</span></span></td>"
            f'<td class="mu-g">{game_cell(g)}</td>'
            # data-pre / data-col: LIVE_JS turns each projection into a live
            # expected final once his game starts, and the totals follow.
            + _proj_cell(proj, "gs", "mu-gs")
            + "".join(_proj_cell(v, f"s{i}") for i, v in enumerate(outside))
            + f'<td class="mu-s">{escape(stat_line(stats, card["pos"]))}</td></tr>')


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
    # The projection the page tracks with (Pts cells, the median game): every
    # source that has him averaged, ours included, so no one site's lean -
    # ours ran 5-10% light in week 1 - sets the number. The scoreboard's
    # Consensus column stays the outside three, the yardstick GS is read against.
    hproj = ext.consensus({pid: v for pid, v in proj.items() if v is not None}, *sources.values())
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
                          (grades.get(r["pid"]) or {}).get("grade") or "",
                          sd=_sd_for(ctx.get("sd", {}).get(r["pid"]), proj.get(r["pid"])),
                          hproj=hproj.get(r["pid"]))

    gs_total = sum(proj.get(r["pid"]) or 0 for r in starters)
    # Expected final and its variance over the starters, for the win bar.
    exp_total, var_total = 0.0, 0.0
    for r in starters:
        if r["pid"] == "0":
            continue
        c = cards.get(r["pid"]) or {}
        e, v = expected(pts.get(r["pid"]), proj.get(r["pid"]),
                        ctx.get("sd", {}).get(r["pid"]), ctx["by_team"].get(c.get("team")))
        exp_total += e
        var_total += v
    src_totals = [sum((src.get(r["pid"]) or 0) for r in starters) for src in sources.values()]
    cons_total = sum(cons.get(r["pid"]) or 0 for r in starters)
    pts_total = float(side.get("points") or 0)
    games = [ctx["by_team"].get((cards.get(r["pid"]) or {}).get("team"))
             for r in starters if r["pid"] != "0"]
    states = {game_state(g) for g in games}
    team_state = ("post" if final else
                  "in" if pts_total > 0 or states & {"in", "post"} else "pre")
    hexp_total = sum(expected(pts.get(r["pid"]), hproj.get(r["pid"]), None,
                              ctx["by_team"].get((cards.get(r["pid"]) or {}).get("team")))[0]
                     for r in starters if r["pid"] != "0")
    total_cell = ui.score_cell(pts_total, hexp_total, team_state, hexp_total, mark_proj=True)
    key = side["roster_id"]
    total_cell = total_cell.replace('<b class="mu-now', f'<b data-tpts="{key}" class="mu-now', 1) \
                           .replace('<span class="mu-exp', f'<span data-thexp="{key}" class="mu-exp', 1)
    html_rows = [cell(r) for r in starters]
    html_rows.append(f'<tr class="total"><td class="mu-pts">{total_cell}</td><td></td>'
                     '<td class="mu-p">Starters</td><td></td>'
                     f'<td class="mu-gs" data-tcol="gs">{gs_total:.1f}</td>'
                     + "".join(f'<td data-tcol="s{i}">{t:.1f}</td>'
                               for i, t in enumerate(src_totals))
                     + "<td></td></tr>")
    if bench:
        html_rows.append(f'<tr class="sep"><td colspan="{4 + len(sources) + 2}">Bench</td></tr>')
        html_rows.extend(cell(r) for r in bench)
    heads = "".join(f"<th title='{ext.SOURCES[k]} projection for this week'>{SHORT[k]}</th>"
                    for k in sources)
    html = (f'<div class="table-scroll" data-roster="{side["roster_id"]}"><table class="mu-roster"><thead><tr>'
            "<th class='mu-pts' title='Points scored, with the live expected final under them; "
            "the blended projection of all four sources before kickoff'>Pts</th>"
            "<th>Slot</th><th>Player</th><th>Game</th>"
            f"<th title='GordStats projection for this week'>GS</th>{heads}"
            "<th>Stats</th>"
            f'</tr></thead><tbody>{"".join(html_rows)}</tbody></table></div>{swaps}')
    parts = {"starters": starters, "bench": bench, "cards": cards, "pts": pts,
             "hints": hints, "pts_total": pts_total, "proj": proj, "hproj": hproj,
             "hexp": hexp_total}
    return html, gs_total, cons_total, pts_total, exp_total, var_total, parts


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
    """The team's picture - its own where the manager set one, else the
    manager's profile picture (fantasy.league.matchups.teams resolves which)."""
    src = t.get("avatar") or ""
    if src and "/" not in src:          # an archive from before URLs: a bare profile id
        src = data_mod.AVATAR_THUMB.format(id=src)
    return (f'<img class="mu-tlogo" src="{escape(src)}" alt="" loading="lazy">'
            if src else "")


def _record(t: dict) -> str:
    return f"{t.get('wins', 0)}-{t.get('losses', 0)}" + (f"-{t['ties']}" if t.get("ties") else "")


def _short_name(name: str) -> str:
    """"Ja'Marr Chase" -> "J. Chase": a full name does not fit half a phone."""
    parts = str(name).split()
    if len(parts) < 2 or parts[-1] == "D/ST":       # "DAL D/ST" is already short
        return str(name)
    return f"{parts[0][0]}. " + " ".join(parts[1:])


def _pair_cell(row: dict | None, card: dict | None, key: str, pts, g: dict | None,
               hint: str = "", hproj=None) -> str:
    """One team's player in the paired phone view - the same data-pid, .mu-pts
    and live attributes as the table row, inside a data-roster wrapper, so
    the live poll moves it exactly the same way."""
    if row is None or row["pid"] == "0":
        return '<div class="mu-pp empty" aria-hidden="true"></div>'
    card = card or {"name": f"Player {row['pid']}", "pos": "", "team": "", "injury": ""}
    inj = card.get("injury")
    inj_html = (f'<span class="inj">{escape(INJURY_TAGS.get(inj, inj[:3].upper()))}</span>'
                if inj else "")
    tag = {"in": '<span class="mu-hint in">start</span>',
           "out": '<span class="mu-hint out">sit</span>'}.get(hint, "")
    live = " live" if g and g.get("state") == "in" else ""
    done = " done" if g and g.get("state") == "post" else ""
    gid = (g or {}).get("game_id")
    attrs = (f' data-gid="{escape(str(gid))}" data-side="{"home" if g.get("home") else "away"}"'
             if gid else "")
    return (f'<div class="mu-pp{live}{done}" data-roster="{escape(key)}" '
            f'data-pid="{escape(row["pid"])}"'
            f'{attrs} data-hproj="{"" if hproj is None else round(hproj, 2)}"><div class="mu-pn">'
            f'<span class="nm" title="{escape(card["name"])}">{_logo(card["team"])}'
            f'{escape(_short_name(card["name"]))}</span>'
            f'<span class="mu-pm">{escape(card["pos"])}'
            f'{" · " + escape(card["team"]) if card["team"] and card["pos"] != "DEF" else ""}'
            f'{inj_html}{tag}</span>'
            f'<span class="mu-g">{game_cell(g)}</span></div>'
            f'<div class="mu-pcol"><span class="mu-pts">{hybrid_score(pts, hproj, g)}</span>'
            f'</div></div>')


def pair_view(a: dict, b: dict, ctx: dict) -> str:
    """The two rosters as one column of slot-paired rows, for a phone - the
    college page's layout: one row per lineup slot, your player on the left,
    theirs on the right, the slot between them. Both sides fill the same
    slots in the same order, so the rows pair by position."""
    ap, bp = a["parts"], b["parts"]

    def cell(parts, key, row):
        if row is None:
            return _pair_cell(None, None, key, None, None)
        card = parts["cards"].get(row["pid"])
        g = ctx["by_team"].get((card or {}).get("team")) if card else None
        return _pair_cell(row, card, key, parts["pts"].get(row["pid"]), g,
                          parts["hints"].get(row["pid"], ""), parts["hproj"].get(row["pid"]))

    def rows(a_list, b_list, bench=False) -> str:
        out = []
        for i in range(max(len(a_list), len(b_list))):
            ra = a_list[i] if i < len(a_list) else None
            rb = b_list[i] if i < len(b_list) else None
            slot = (ra or rb or {}).get("slot", "")
            out.append(f'<div class="mu-pr{" bench" if bench else ""}">'
                       + cell(ap, a["key"], ra)
                       + f'<div class="mu-pslot">{escape(slot)}</div>'
                       + cell(bp, b["key"], rb) + "</div>")
        return "".join(out)

    starters = rows(ap["starters"], bp["starters"])
    bench = ""
    if ap["bench"] or bp["bench"]:
        bench = '<div class="mu-pbench-h">Bench</div>' + rows(ap["bench"], bp["bench"], bench=True)
    total = (f'<div class="mu-pr total">'
             f'<div class="mu-pp"><div class="mu-pn"><span class="nm">Starters</span></div>'
             f'<span class="mu-pts" data-tpts="{escape(a["key"])}">{ap["pts_total"]:.1f}</span></div>'
             f'<div class="mu-pslot"></div>'
             f'<div class="mu-pp"><span class="mu-pts" data-tpts="{escape(b["key"])}">'
             f'{bp["pts_total"]:.1f}</span>'
             f'<div class="mu-pn"><span class="nm">Starters</span></div></div></div>')
    return f'<div class="mu-pair">{starters}{total}{bench}</div>'


def _label(t: dict) -> str:
    name = escape(t.get("name") or "")
    mgr = t.get("manager")
    return name + (f' <span class="mu-meta">({escape(mgr)})</span>' if mgr and mgr not in name else "")


def lifetime_note(key_a: str, key_b: str) -> str:
    """The two managers' lifetime head-to-head, regular season and winners-bracket
    playoffs kept apart (fantasy.league.head_to_head)."""
    try:
        a, b = int(key_a), int(key_b)
        reg, po = h2h.record(a, b, "regular"), h2h.record(a, b, "playoff")
    except Exception as exc:                            # noqa: BLE001
        print(f"[matchups] head-to-head unavailable ({exc})")
        return ""
    na, nb = ROSTER_NAMES.get(a, key_a), ROSTER_NAMES.get(b, key_b)

    def rec(r):
        return f"{r['w']}&ndash;{r['l']}" + (f"&ndash;{r['t']}" if r["t"] else "")
    regular = (f"regular season <b>{rec(reg)}</b> (avg {reg['pf'] / reg['games']:.1f}&ndash;"
               f"{reg['pa'] / reg['games']:.1f})" if reg["games"] else "no regular-season meetings")
    playoffs = f"playoffs <b>{rec(po)}</b>" if po["games"] else "never met in the playoffs"
    return (f'<p class="mu-note mu-h2h">Lifetime, {escape(na)}&ndash;{escape(nb)}: '
            f"{regular} &middot; {playoffs}</p>")


def matchup_section(m: dict, data: dict, ctx: dict, anchor: str) -> tuple:
    final = data_mod.week_final(data)
    started = data_mod.week_started(data)
    sides = []
    for s in m["sides"]:
        t = data["teams"].get(str(s["roster_id"])) or data["teams"].get(s["roster_id"]) or {}
        html, gs, sp, pts, exp, var, parts = roster_table(s, t, data, ctx, final)
        sides.append({"team": t, "name": t.get("name") or f"Team {s['roster_id']}",
                      "key": str(s["roster_id"]),
                      "html": html, "gs": gs, "sp": sp, "pts": pts if started else None,
                      "exp": exp, "var": var, "parts": parts})
    if len(sides) != 2:
        return "", sides
    a, b = sides
    lead = (None if not started or a["pts"] == b["pts"]
            else ("a" if (a["pts"] or 0) > (b["pts"] or 0) else "b"))

    def side_html(s, which):
        big = ui.fmt(s["pts"]) if started else ui.fmt(s["gs"])
        cls = " lead" if lead == which else ""
        sub = (f"GordStats <b data-tgs='{s['key']}'>{ui.fmt(s['gs'])}</b> · "
               f"Consensus <b>{ui.fmt(s['sp'])}</b>"
               if started else f"projected · Consensus <b>{ui.fmt(s['sp'])}</b>")
        return (f'<div class="mu-side {"r" if which == "b" else ""}">{_avatar(s["team"])}'
                f'<div><div class="nm">{_label(s["team"])}'
                f'<span class="rec">{_record(s["team"])}</span></div>'
                f'<div class="num{cls}" data-num="{s["key"]}" data-mu="{anchor}" '
                f'data-val="{s["pts"] if s["pts"] is not None else ""}">{big}</div>'
                f'<div class="sub">{sub}</div></div></div>')

    mid = "Final" if final else ("Live" if started else "Preview")
    # Our chance for each side: the expected finals against the spread that
    # is still to be played, from the players' own week-to-week variances.
    wp_a = win_probability(a["exp"], a["var"], b["exp"], b["var"])
    a["wp"], b["wp"] = wp_a, 1 - wp_a
    bar = "" if final else ui.win_bar(wp_a, 1 - wp_a, "GordStats", a["key"], b["key"])
    edge = a["gs"] - b["gs"]
    note = (f"GordStats has <b>{escape(a['name'] if edge >= 0 else b['name'])}</b> by "
            f"{abs(edge):.1f} on projection ({ui.fmt(a['gs'])}–{ui.fmt(b['gs'])}); the "
            f"consensus has {ui.fmt(a['sp'])}–{ui.fmt(b['sp'])}." if not final else
            f"GordStats projected {ui.fmt(a['gs'])}–{ui.fmt(b['gs'])} going in, the consensus "
            f"{ui.fmt(a['sp'])}–{ui.fmt(b['sp'])}.")
    body = (f'<div class="mu-head">{side_html(a, "a")}<div class="mu-mid">{mid}</div>'
            f'{side_html(b, "b")}</div>{bar}<p class="mu-note">{note}</p>'
            + lifetime_note(a["key"], b["key"])
            + pair_view(a, b, ctx)
            + f'<div class="mu-grid"><div><div class="mu-who">{escape(a["name"])}</div>{a["html"]}</div>'
            f'<div><div class="mu-who">{escape(b["name"])}</div>{b["html"]}</div></div>')
    head = f'{escape(a["name"])}<span class="mu-vs-sum">vs</span>{escape(b["name"])}'
    return layout.details(head, body, open=True, anchor=anchor), sides


def win_probability(exp_a: float, var_a: float, exp_b: float, var_b: float) -> float:
    """P(A outscores B): a normal on the difference of expected finals, with a
    floor on the spread so a matchup that is all but over still reads as odds
    rather than a certainty."""
    from math import erf, sqrt
    sd = sqrt(max(var_a + var_b, 4.0))
    return 0.5 * (1 + erf(((exp_a - exp_b) / sd) / sqrt(2)))


def week_board(rows: list, started: bool, med_now=None, med_proj=None) -> str:
    def num(s, o, key):
        v, ov = s.get(key), o.get(key)
        lead = v is not None and ov is not None and v > ov
        attr = (f' data-sb="{s["key"]}" data-val="{v if v is not None else ""}"'
                if key == "pts" else "")
        return f"<td{attr}>{'<b class=lead>' if lead else ''}{ui.fmt(v)}{'</b>' if lead else ''}</td>"

    def med(s):
        v = s.get("med")
        cls = "" if v is None else ("mu-med-up" if v > 0 else "mu-med-down" if v < 0 else "")
        return (f'<td class="{cls}" data-vsmed="{s["key"]}">'
                f'{"—" if v is None else f"{v:+.1f}"}</td>')
    cells = []
    for anchor, a, b in rows:
        cells.append(
            f'<tr><td class="mu-t"><a href="#{anchor}">{_avatar(a["team"])}'
            f'{escape(a["name"])}</a></td>'
            + (num(a, b, "pts") if started else "") + num(a, b, "sp") + num(a, b, "gs") + med(a)
            + '<td class="mu-vs">vs</td>'
            + med(b) + num(b, a, "gs") + num(b, a, "sp") + (num(b, a, "pts") if started else "")
            + f'<td class="mu-t r"><a href="#{anchor}">{escape(b["name"])}'
              f'{_avatar(b["team"])}</a></td></tr>')
    pts_h = "<th>Pts</th>" if started else ""
    med_h = ("<th title='Margin against the week\'s median score - the league\'s second game "
             "each week'>Med</th>")
    # The week's median itself heads the median tracker (median_tracker) now.
    strip = ""
    final = all((a.get("pts") or 0) > 0 and (b.get("pts") or 0) > 0 for _, a, b in rows) and started
    cards = ui.board_cards(
        [(anchor, {"name": escape(a["name"]), "logo": _avatar(a["team"]), "key": a["key"],
                   "pts": a["pts"], "gs": a["gs"], "wp": a.get("wp"), "med": a.get("med")},
          {"name": escape(b["name"]), "logo": _avatar(b["team"]), "key": b["key"],
           "pts": b["pts"], "gs": b["gs"], "wp": b.get("wp"), "med": b.get("med")})
         for anchor, a, b in rows],
        started, False)
    return (strip + cards + '<div class="mu-board-wrap"><div class="table-scroll"><table class="mu-board"><thead><tr>'
            f"<th>Team</th>{pts_h}<th title='Average of the outside projections for the lineup as set'>Consensus</th>"
            f"<th title='GordStats projected total for the lineup as set'>GS Proj</th>{med_h}<th></th>"
            f"{med_h}<th>GS Proj</th><th>Consensus</th>{pts_h}<th>Team</th>"
            f'</tr></thead><tbody>{"".join(cells)}</tbody></table></div></div>')


# --------------------------------------------------------------------------- #
# The median game
# --------------------------------------------------------------------------- #

def tracker_side(s: dict, ctx: dict) -> dict:
    """One team for the median tracker: points so far, expected final, and the
    starters still to finish with what they are projected to add (the unplayed
    share of the GordStats projection - the same sum as `expected`)."""
    parts = s["parts"]
    left = []
    for r in parts["starters"]:
        card = parts["cards"].get(r["pid"])
        g = ctx["by_team"].get((card or {}).get("team")) if card else None
        if not card or game_state(g) not in ("pre", "in"):
            continue
        rem = float(parts["hproj"].get(r["pid"]) or 0.0) * (1.0 - float(g.get("elapsed", 0.0)))
        left.append({"n": _short_name(card["name"]), "r": round(rem, 1),
                     "live": game_state(g) == "in", "pos": card["pos"],
                     "p": round(float(parts["pts"].get(r["pid"]) or 0.0), 2)})
    return {"k": s["key"], "name": s["name"], "logo": _avatar(s["team"]),
            "pts": round(float(s["pts"] or 0.0), 2), "exp": round(float(parts["hexp"]), 2),
            "left": left}


def position_extremes(registry: dict, datas: dict) -> dict:
    """{"max": {pos: pts}, "min": {pos: pts}}: the best and worst single weeks
    any rostered player has put up at each position in league history - the
    season files (every rostered player, starters and bench) plus this
    season's finished weeks. The tracker's ceilings and floors: a starter
    still to play can add at most his position's record, lose at most its
    worst week."""
    import glob
    import json
    hi, lo = {}, {}

    def add(pid, pts, pos):
        pos = "DEF" if str(pid).isalpha() else (pos or (registry.get(str(pid)) or {}).get("pos"))
        if pos is None or pts is None:
            return
        hi[pos] = max(hi.get(pos, float("-inf")), float(pts))
        lo[pos] = min(lo.get(pos, float("inf")), float(pts))
    for f in sorted(glob.glob(str(paths.DATA_DIR / "season" / "*.json"))):
        try:
            season = json.loads(open(f, encoding="utf-8").read())
        except (OSError, ValueError):
            continue
        for players in (season.get("players_dict") or {}).values():
            for pid, pts in (players or {}).items():
                add(pid, pts, None)
    for d in datas.values():
        if not data_mod.week_final(d):
            continue
        proj = d.get("projections") or {}
        for m in d["matchups"]:
            for side in m["sides"]:
                for pid, pts in (side.get("players_points") or {}).items():
                    add(pid, pts, (proj.get(pid) or {}).get("pos"))
    return {"max": {k: round(v, 2) for k, v in hi.items()},
            "min": {k: round(v, 2) for k, v in lo.items()}}


def median_tracker(rows: list, ctx: dict, week: int, started: bool, final: bool) -> str:
    """The median game at a glance: every team ranked by expected final with
    the median line drawn through the middle, and for each the team it has to
    stay ahead of (or pass), the points that takes from the starters it has
    left, and who those starters are. Rendered in the browser by
    MEDIAN_TRACKER_JS from the JSON here, which the live poll rebuilds."""
    teams = [tracker_side(s, ctx) for _, a, b in rows for s in (a, b)]
    return ui.median_tracker(teams, week, started, final, ctx.get("extremes"))


# The tracker's markup and arithmetic are shared with the college page:
# gordstats.matchup_page.MEDIAN_TRACKER_JS.
MEDIAN_TRACKER_JS = ui.MEDIAN_TRACKER_JS



# What the browser does between rebuilds: Sleeper's points per player and
# ESPN's clocks per game, folded into each player's expected final (points
# so far plus the unplayed share of his projection) and each side's chance -
# the same arithmetic as `expected` and `win_probability` above. Projections
# and spreads are read off the rows, so nothing the page already knows is
# refetched. `compute` is exposed so it can be exercised with a fake payload.
_LIVE_FETCH_JS = """window.MU_LIVE={interval:__INTERVAL__,root:'#mm-built #wk-view-__WEEK__',
compute:function(rows,games){
  var teams={};
  function erf(x){var t=1/(1+0.3275911*Math.abs(x));var y=1-(((((1.061405429*t-1.453152027)*t)+1.421413741)*t-0.284496736)*t+0.254829592)*t*Math.exp(-x*x);return x>=0?y:-y;}
  function elapsed(g){if(!g||g.state==='pre')return 0;if(g.state==='post')return 1;if(!g.period)return .5;if(g.period>4)return .95;
    var m=String(g.clock||'0:00').split(':'),left=(parseInt(m[0],10)||0)+((parseInt(m[1],10)||0)/60);
    return Math.min(Math.max(((g.period-1)*15+(15-left))/60,0),1);}
  (rows||[]).forEach(function(r){
    var key=String(r.roster_id),pp=r.players_points||{},players={},exp=0,v=0;
    var hexp=0;
    var left=[];
    document.querySelectorAll('#mm-built #wk-view-__WEEK__ [data-roster="'+key+'"] tr[data-pid]').forEach(function(tr){
      var pid=tr.getAttribute('data-pid'),proj=parseFloat(tr.getAttribute('data-proj')),sd=parseFloat(tr.getAttribute('data-sd'))||2;
      var hp=parseFloat(tr.getAttribute('data-hproj'));
      var g=games[tr.getAttribute('data-team')],done=elapsed(g),pts=pp[pid]||0;
      if(isNaN(proj))proj=0;if(isNaN(hp))hp=proj;
      var e=pts+proj*(1-done),he=pts+hp*(1-done);
      if(tr.classList.contains('starter')){exp+=e;v+=sd*sd*(1-done);hexp+=he;
        if(g&&(g.state==='pre'||g.state==='in'))left.push({n:tr.getAttribute('data-nm')||'',r:hp*(1-done),live:g.state==='in',pos:tr.getAttribute('data-pos')||'',p:pts});}
      players[pid]={points:pp[pid],hexp:(g&&g.state!=='pre')?he:undefined,done:g?done:undefined,
        state:g?g.state:undefined,game:g?muGameText(g.state,g.score,g.opp_score,g.detail):undefined};
    });
    Object.keys(pp).forEach(function(k){if(!players[k])players[k]={points:pp[k]};});
    teams[key]={points:r.points,players:players,exp:exp,v:v,matchup:r.matchup_id,gs_live:exp,hexp:hexp};
    // Who is still to play, for the median tracker - unknowable without the clocks.
    if(Object.keys(games).length)teams[key].left=left;
  });
  Object.keys(teams).forEach(function(k){
    var t=teams[k],o=Object.keys(teams).filter(function(j){return j!==k&&teams[j].matchup===t.matchup;})[0];
    if(!o)return;var u=teams[o],sd=Math.sqrt(Math.max(t.v+u.v,4));
    t.win_probability=0.5*(1+erf(((t.exp-u.exp)/sd)/Math.SQRT2));
  });
  // The week's median: of the scores once anyone has one, of the expected finals as the projection.
  function median(a){if(!a.length)return null;a=a.slice().sort(function(x,y){return x-y;});var m=a.length>>1;return a.length%2?a[m]:(a[m-1]+a[m])/2;}
  var ks=Object.keys(teams),pts=ks.map(function(k){return teams[k].points||0;}),exps=ks.map(function(k){return teams[k].hexp;});
  var started=pts.some(function(p){return p>0;});
  var medNow=started?median(pts):null,medProj=median(exps);
  ks.forEach(function(k){var t=teams[k];t.vs_median=started?((t.points||0)-medNow):(t.hexp-medProj);});
  return {teams:teams,median:{now:medNow,proj:medProj}};
},
fetch:function(){
  var self=this;
  var sleeper=fetch('__SLEEPER__').then(function(r){return r.json();});
  var espn=fetch('__ESPN__').then(function(r){return r.json();}).then(function(d){
    var games={};(d.events||[]).forEach(function(e){var c=(e.competitions||[])[0];if(!c)return;var st=c.status||{};
      var cs=c.competitors||[];cs.forEach(function(x,i){var ab=x.team&&x.team.abbreviation;if(ab==='WSH')ab='WAS';
        var o=cs[1-i]||{};
        games[ab]={state:(st.type||{}).state||'pre',period:st.period,clock:st.displayClock,
          detail:(st.type||{}).shortDetail,score:x.score,opp_score:o.score};});});
    return games;}).catch(function(){return {};});
  return Promise.all([sleeper,espn]).then(function(both){var out=self.compute(both[0],both[1]);
    if(window.muMedTrack)window.muMedTrack.update(__WEEK__,out,document.getElementById('mm-built'));return out;});
}};"""


def week_view(data: dict, ctx: dict) -> str:
    week = int(data["week"])
    bf = ctx["board_frame"].drop_duplicates("sleeper_id")
    ctx = {**ctx, "by_team": data_mod.team_games(data["games"]),
           "wk": data_mod.week_projections(ctx["board_frame"], data["games"],
                                           injuries=injury_status(data)),
           "sd": dict(zip(bf["sleeper_id"].astype(str), bf["sd"])) if "sd" in bf else {}}
    final = data_mod.week_final(data)
    started = data_mod.week_started(data)
    sections, rows = [], []
    for i, m in enumerate(data["matchups"], 1):
        anchor = f"wk{week}-m{i}"
        html, sides = matchup_section(m, data, ctx, anchor)
        if html:
            sections.append(html)
            rows.append((anchor, sides[0], sides[1]))
    # The league plays a second game each week against the median score, so
    # the board carries it: the live median of the ten scores once games are
    # on, the median of the expected finals as the projection, and every
    # side's margin against whichever applies.
    import statistics
    every = [s for _, a, b in rows for s in (a, b)]
    med_proj = statistics.median(s["parts"]["hexp"] for s in every) if every else None
    med_now = statistics.median((s["pts"] or 0.0) for s in every) if (every and started) else None
    for s in every:
        s["med"] = ((s["pts"] or 0.0) - med_now) if started else (s["parts"]["hexp"] - med_proj)
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
        asof = (' <span class="mu-asof">· points as of ' + datetime.fromisoformat(data["fetched"])
                .astimezone(LEAGUE_TZ).strftime("%a %-I:%M %p") + "</span>")
    playoffs = " (playoffs)" if ctx["playoff_start"] and week >= ctx["playoff_start"] else ""
    # Sleeper answers browsers directly (it sends CORS), so the week still
    # being played polls its matchups for live points: every minute while
    # games are on, every five before they start. Stat lines wait for the
    # ten-minute rebuild; Sleeper's stats feed is too big to poll.
    live = ("" if final else
            "<script>" + ui.LIVE_GAMES_JS + _LIVE_FETCH_JS
            .replace("__SLEEPER__", f"{data_mod.SLEEPER_API}/league/{UPCOMING_LEAGUE_ID}/matchups/{week}")
            .replace("__ESPN__", f"{data_mod.ESPN_SCOREBOARD}?week={week}&dates={UPCOMING_YEAR}&seasontype=2")
            .replace("__INTERVAL__", str(60000 if started else 300000))
            .replace("__WEEK__", str(week)) + "</script>")
    return (f"<p><strong>Week {week}</strong>{span}{playoffs} · {state}{asof}</p>"
            + median_tracker(rows, ctx, week, started, final)
            + week_board(rows, started, med_now, med_proj) + extra + "".join(sections) + live)


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
        theirs = [src.get(pid) for src in sources.values()]
        known = [v for v in theirs if v is not None]
        # A disagreement is with the field, not with its average: the row's
        # rank is the gap to the source nearest us, so a player one site
        # sees our way does not lead the list, and one site's outlier does
        # not put a player here on its own.
        if len(known) < 2:
            continue
        card = player_card(pid, data, ctx["board"], ctx["registry"])
        out.append({"pid": pid, "name": card["name"], "pos": card["pos"], "team": card["team"],
                    "owner": owner, "slot": slot, "gs": gs, "cons": cons[pid],
                    "gap": gs - cons[pid], "nearest": min(abs(gs - v) for v in known),
                    "sources": theirs})
    out.sort(key=lambda r: -r["nearest"])
    return out


def disagreements_section(data: dict, ctx: dict) -> str:
    rows = disagreements(data, ctx)
    if not rows:
        return ""
    sources = outside_sources(data)
    heads = "".join(f'<th class="mu-src">{SHORT[k]}</th>' for k in sources)
    cells = []
    for r in rows[:DISAGREE_N]:
        up = r["gap"] > 0
        cells.append(
            f'<tr><td class="mu-t">{_logo(r["team"])}{escape(r["name"])} '
            f'<span class="mu-meta">{escape(r["pos"])}</span></td>'
            f'<td class="mu-t">{escape(r["owner"])} <span class="mu-meta">{escape(r["slot"])}</span></td>'
            f"<td><b>{ui.fmt(r['gs'])}</b></td>"
            + "".join(f'<td class="mu-src">{ui.fmt(v)}</td>' for v in r["sources"])
            + f"<td>{ui.fmt(r['cons'])}</td>"
            f'<td><b class="{"lead" if up else ""}">{r["gap"]:+.1f}</b></td></tr>')
    n_src = len(sources)
    body = ('<p class="mu-note">Rostered players where this site\'s projection sits furthest '
            f"from <em>every one</em> of the {n_src} outside sources - ranked by the gap to "
            "the source nearest us, so a player one site agrees with us on stays off the "
            "list. A positive gap means we like him more than the market does; the Accuracy "
            "section below says, once weeks are final, which side of these calls has been "
            "right.</p>"
            '<div class="table-scroll"><table class="mu-board mu-dis"><thead><tr><th>Player</th>'
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
        wk = data_mod.week_projections(ctx["board_frame"], data["games"],
                                       injuries=injury_status(data))
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
    # Pictures are presentation, not history: a finished week's archive keeps
    # the avatar it saw at capture, so every week draws the current one - a
    # manager who sets a team picture in November sees it on week 1 too.
    try:
        live = {str(rid): t for rid, t in data_mod.teams().items()}
    except Exception as exc:                            # noqa: BLE001
        print(f"[matchups] archived avatars only ({exc})")
        live = {}
    for d in datas.values():
        for rid, t in (d.get("teams") or {}).items():
            cur = live.get(str(rid))
            if cur and cur.get("avatar"):
                t["avatar"] = cur["avatar"]
    board_frame = _board(weeks, datas)
    board = {str(r.sleeper_id): {"player": r.player, "pos": r.pos, "team": r.team}
             for r in board_frame.drop_duplicates("sleeper_id").itertuples(index=False)}
    ctx = {"slots": lg["roster_positions"], "board_frame": board_frame, "board": board,
           "registry": _registry(), "playoff_start": lg.get("playoff_week_start") or 0}
    ctx["extremes"] = position_extremes(ctx["registry"], datas)
    for d in datas.values():
        d["roster_positions"] = lg["roster_positions"]
    open_weeks = [w for w in weeks if not data_mod.week_final(datas[w])]
    current = open_weeks[0] if open_weeks else weeks[-1]
    views = {w: week_view(datas[w], ctx) for w in weeks}
    scored = accuracy_section(datas, ctx)

    built = datetime.now(LEAGUE_TZ).strftime("%b %-d, %-I:%M %p %Z")
    return (
        ui.CSS
        + my_league.bar()
        + my_matchups.section(current, UPCOMING_YEAR)
        + '<div id="mm-built">'
        + f'<p><a href="{LEAGUE_URL}"><strong>{escape(lg["name"] or "The league")}</strong></a> '
        f"— every {UPCOMING_SEASON} matchup with both rosters in full, live while games "
        "are on.</p><details class='section'><summary>How to read this page</summary>"
        "<p>The <b>Median Tracker</b> ranks every team by points so far (by projection "
        "before kickoff), each with its expected final (points plus what its unfinished "
        "starters are projected to add), with the median line "
        "through the middle; each team is told who it has to stay ahead of or pass, "
        "and how many teams would have to pass it (or it has to pass) out of the "
        "teams that still can; "
        "how many points that takes, and which starters it has left to get them. A row "
        "turns solid green or red once a team is <b>locked</b> above or below the median: "
        "its ceiling (every starter still to play matching his position's best week in "
        "league history) or floor (his position's worst) can no longer change where it "
        "finishes against the others' ceilings and floors. "
        "<b>Med</b> is each team's margin against the week's median score - the league "
        "plays a second game against it every week - live once games are on, on the "
        "expected finals before. <b>GS Proj</b> is "
        "this site's projection for the week: the power model's points per game for "
        "each player, tilted by the market's implied total for his team this week "
        "(a defense the other way, on what its opponent is expected to score), and "
        "zero on a bye. Beside it, three outside projections for the same week: "
        "<b>Slpr</b> is Sleeper's, <b>ESPN</b> is ESPN's, <b>FP</b> is the FantasyPros "
        "expert consensus (whose start/sit grade sits by the name); their average is "
        "the <b>Consensus</b> the scoreboard compares us against. <b>Pts</b> is the "
        "blended projection (grey) - GordStats, Sleeper, ESPN and FantasyPros averaged, "
        "so no one source's lean sets it - until a player's game kicks off, then his points "
        "with the expected final under them (points plus the unplayed share of the "
        "blend), refreshed about once a minute, then <i>final</i>. The Median Tracker "
        "and <b>Med</b> run on the same blend; the win bars are GordStats alone. "
        "Ahead of the final whistle a roster whose bench out-projects a starter gets "
        f"the swap spelled out under the table. Rebuilt several times a day and every "
        f"ten minutes while games are on (last: {built}); finished weeks stay on "
        "record. Season-long standing lives on the "
        '<a href="/fantasy/power/">power rankings</a>.</p></details>'
        + scored + ui.week_switch(weeks, current, views)
        + "</div>"
        + MEDIAN_TRACKER_JS + ui.LIVE_JS + my_league.JS
        + my_league_data.JS + my_week.JS + my_matchups.JS)


def generate():
    page = add_front_matter(layout.HEAD + body(), "Weekly Matchups")
    out = paths.WEB_MATCHUPS
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"Wrote Weekly Matchups -> {out}")


if __name__ == "__main__":
    generate()
