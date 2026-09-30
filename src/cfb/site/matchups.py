"""
Weekly matchups (docs/cfb/matchups/) - every roster in the league, side by side.

One view per week, the current week open. Each week: a scoreboard of the
five matchups, then each matchup in full - both rosters in lineup order with,
per player, the game he plays this week, the site's own weekly projection
(cfb.weekly), what Yahoo has scored him so far and the stat line behind it.
Starters total up; bench sits below.

Yahoo publishes a team projection for the college game but no per-player
one, so the only projection at the player level is ours. Where the roster's
best lineup by that projection is not the one set, the page says which swap
and what it is worth - ahead of kickoff only; after the week it is history.

Every week the league has played is archived (cfb.yahoo.week_matchups) and
stays on the page, so a finished week reads exactly as it ended.

    python -m cfb.site.matchups     # rebuild the page
"""
from datetime import datetime
from html import escape

import pandas as pd

from cfb import in_season, predict, pregame, projections, schools as schools_mod, weekly, yahoo
from cfb.config import LEAGUE_TZ, SEASON, WEB_DIR
from cfb.site import write_page
from gordstats import logos, matchup_page as ui, share_button, share_card, stakes

OUTPUT = WEB_DIR / "matchups" / "index.html"

# A lineup hint is worth printing past this many projected points.
SWAP_MIN = 1.0

# Slots a player cannot score from.
_BENCH = {"BN", "IL", "IR"}

# Stat ids -> how a stat line reads. Grouped so a quarterback's line says
# "245 pass yds, 2 TD, 1 INT" rather than listing every id in order.
_LINE = [
    ("pass", [("4", "{v} pass yds"), ("5", "{v} TD"), ("6", "{v} INT")]),
    ("rush", [("8", "{v} car"), ("9", "{v} rush yds"), ("10", "{v} TD")]),
    ("rec", [("11", "{v} rec"), ("12", "{v} rec yds"), ("13", "{v} TD")]),
    ("misc", [("15", "{v} ret TD"), ("16", "{v} 2-pt"), ("18", "{v} fum lost"),
              ("57", "{v} fum TD")]),
    ("def", [("31", "{v} PA"), ("32", "{v} sk"), ("33", "{v} INT"), ("34", "{v} FR"),
             ("35", "{v} TD"), ("36", "{v} saf"), ("37", "{v} blk"), ("49", "{v} ret TD")]),
]

# --------------------------------------------------------------------------- #
# Roster order and the best lineup
# --------------------------------------------------------------------------- #

def slot_order(lg: dict) -> list[str]:
    """Roster slots in lineup order, one entry per slot: QB, QB, RB, ..."""
    out = []
    for s in lg["roster"]:
        out.extend([s["position"]] * int(s["count"]))
    return out


def order_roster(players: list[dict], lg: dict) -> list[dict]:
    """Players in lineup order; ties within a slot keep Yahoo's order."""
    slots = slot_order(lg)
    rank = {}
    for i, s in enumerate(slots):
        rank.setdefault(s, i)
    return sorted(players, key=lambda p: rank.get(p["slot"], len(slots)))


def best_lineup(players: list[dict], lg: dict, proj: dict) -> set:
    """The yahoo_ids of the best lineup this roster can start by `proj`.

    Dedicated slots first, best projection at the position; then each flex
    goes to the best skill player left. Injured-list players are unavailable.
    A player with no projection counts as zero, so he is never preferred over
    one who has one.
    """
    avail = [p for p in players if p["slot"] not in ("IL", "IR")]
    value = {p["yahoo_id"]: (proj.get(p["yahoo_id"]) or 0.0) for p in avail}
    pools = {}
    for p in avail:
        pools.setdefault(p["pos"], []).append(p["yahoo_id"])
    for pos in pools:
        pools[pos].sort(key=lambda i: value[i], reverse=True)
    used = {pos: 0 for pos in pools}
    chosen = set()
    flex = 0
    for s in lg["roster"]:
        pos, n = s["position"], int(s["count"])
        if pos == projections.FLEX_SLOT:
            flex += n
            continue
        if pos not in pools:
            continue
        for _ in range(n):
            if used[pos] < len(pools[pos]):
                chosen.add(pools[pos][used[pos]])
                used[pos] += 1
    for _ in range(flex):
        best, best_v = None, -1.0
        for pos in projections.FLEX_POSITIONS:
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

def stat_line(stats: dict, pos: str) -> str:
    """'13 car, 37 rush yds, 2 rec, 8 rec yds' from Yahoo's stat ids."""
    bits = []
    for group, items in _LINE:
        if (group == "def") != (pos == "DEF"):
            continue
        for sid, fmt in items:
            v = stats.get(sid)
            if v:
                bits.append(fmt.format(v=f"{v:g}"))
    return ", ".join(bits)


def game_cell(g: pd.Series | None) -> str:
    """This week's game from the player's side: opponent, kickoff or score."""
    if g is None or not isinstance(g.get("opp"), str):
        return '<span class="bye">Bye</span>'
    where = "vs" if g.get("home") else "at"
    rank = g.get("opp_rank")
    opp = (f"#{int(rank)} " if rank and not pd.isna(rank) else "") + escape(str(g["opp"]))
    state = g.get("state") or "pre"
    sf, sa = g.get("score_for"), g.get("score_against")
    have_score = sf is not None and sa is not None and not (pd.isna(sf) or pd.isna(sa))
    if state == "post" and have_score:
        res = "W" if sf > sa else ("L" if sf < sa else "T")
        return f'<span class="fin">{res} {int(sf)}–{int(sa)}</span> {where} {opp}'
    if state == "in":
        score = f" {int(sf)}–{int(sa)}" if have_score else ""
        return f'<span class="live">Live{score}</span> {where} {opp}'
    when = g.get("kickoff")
    if when is not None and not pd.isna(when):
        when = pd.Timestamp(when).tz_convert(LEAGUE_TZ)
        return f"{where} {opp} · {when:%a %-I:%M}{when:%p}".replace("AM", "a").replace("PM", "p")
    return f"{where} {opp}"


def _school_logo(team_full: str, to_school: dict, espn: dict) -> str:
    tid = espn.get(to_school.get(team_full, ""))
    if not tid:
        return ""
    return logos.img("ncaa", tid, 18, cls="mu-logo")


def game_for(p: dict, wk: pd.DataFrame, by_team: dict, to_school: dict, espn: dict):
    """This week's game for a rostered player: from his projection row when
    he is on the board, otherwise by his school - a player past the board's
    depth still plays on Saturday."""
    pid = p["yahoo_id"]
    if pid in wk.index and isinstance(wk.loc[pid].get("opp"), str):
        return wk.loc[pid]
    team_id = espn.get(to_school.get(p.get("team_full") or "", ""))
    games = by_team.get(str(team_id)) if team_id else None
    if not games:
        return None
    g = games[0]
    return pd.Series({"opp": g["opp"], "opp_id": g.get("opp_id"),
                      "opp_rank": g.get("opp_rank"), "home": g["home"],
                      "kickoff": g["date"], "state": g["state"], "game_id": g.get("game_id"),
                      "score_for": g["score_for"], "score_against": g["score_against"]})


def _live_attrs(g) -> tuple:
    """(the row's state class, and the data attributes the live script keys
    on: ESPN's game id and which side the player is).

    " live" while the game is on, " done" once it is over - the NFL page's
    classes, styled once in gordstats.matchup_page. A finished player is muted
    whole so the eye goes to the ones still to play.
    """
    if g is None or not isinstance(g.get("opp"), str):
        return "", ""
    gid = g.get("game_id")
    attrs = (f' data-gid="{escape(str(gid))}"' if gid and not pd.isna(gid) else "") \
        + f' data-side="{"home" if g.get("home") else "away"}"'
    state = g.get("state")
    return (" live" if state == "in" else " done" if state == "post" else ""), attrs


def _state(g) -> str:
    """pre/in/post for the Pts cell, "bye" where game_cell says Bye."""
    if g is None or not isinstance(g.get("opp"), str):
        return "bye"
    return g.get("state") or "pre"


def player_row(p: dict, wk: pd.DataFrame, by_team: dict, to_school: dict, espn: dict,
               hint: str = "", yproj: dict = None) -> str:
    pid = p["yahoo_id"]
    g = game_for(p, wk, by_team, to_school, espn)
    proj = wk.loc[pid, "proj_week"] if pid in wk.index else None
    y = (yproj or {}).get(pid)
    bench = p["slot"] in _BENCH
    inj = (f'<span class="inj" title="{escape(p.get("injury_note") or p.get("status_full") or "")}">'
           f'{escape(p["status"])}</span>' if p.get("status") else "")
    tag = {"in": '<span class="mu-hint in" title="Projects into the best lineup">start</span>',
           "out": '<span class="mu-hint out" title="A bench player projects higher">sit</span>'
           }.get(hint, "")
    return (f'<tr class="{"bench" if bench else "starter"}{_live_attrs(g)[0]}" '
            f'data-pid="{escape(pid)}"{_live_attrs(g)[1]}'
            # The median tracker names the starters a team still has to come,
            # and the live updater builds that list off these rows.
            f' data-nm="{escape(_short_name(p["player"]), quote=True)}"'
            f' data-pos="{escape(p["pos"], quote=True)}"'
            f' data-proj="{"" if proj is None or pd.isna(proj) else round(float(proj), 2)}"'
            # Yahoo's number, for its live expected final in the header.
            f' data-yproj="{"" if y is None else round(float(y), 2)}">'
            f'<td class="mu-pts">{ui.score_cell(p.get("points"), proj, _state(g))}</td>'
            f'<td class="mu-slot">{escape(p["slot"])}</td>'
            f'<td class="mu-p"><span class="mu-pc"><span class="nm">'
            f'{_school_logo(p["team_full"], to_school, espn)}{escape(p["player"])}</span> '
            f'<span class="mu-lbl"><span class="mu-meta">{escape(p["pos"])} · {escape(p["team"])}'
            f'</span>{inj}{tag}</span></span></td>'
            f'<td class="mu-g">{game_cell(g)}</td>'
            f'<td class="mu-gs">{ui.fmt(proj)}</td>'
            f'<td class="mu-gs">{ui.fmt(y)}</td>'
            f'<td class="mu-s">{escape(stat_line(p.get("stats") or {}, p["pos"]))}</td></tr>')


def roster_table(players: list[dict], lg: dict, wk: pd.DataFrame, to_school: dict,
                 espn: dict, final: bool, key: str = "",
                 by_team: dict = None, yproj: dict = None) -> tuple[str, float, float]:
    """One roster in lineup order. Returns (html, projected starters, points).

    `yproj` is Yahoo's own per-player projection for the week, shown beside
    ours; the lineup advice stays on ours."""
    by_team = by_team or {}
    yproj = yproj or {}
    ordered = order_roster(players, lg)
    proj = {p["yahoo_id"]: (float(wk.loc[p["yahoo_id"], "proj_week"])
                            if p["yahoo_id"] in wk.index
                            and not pd.isna(wk.loc[p["yahoo_id"], "proj_week"]) else None)
            for p in ordered}
    starters = [p for p in ordered if p["slot"] not in _BENCH]
    bench = [p for p in ordered if p["slot"] in _BENCH]
    best = best_lineup(ordered, lg, proj)
    current = {p["yahoo_id"] for p in starters}
    hints = {}
    swaps = ""
    if not final:
        ins = [p for p in bench if p["yahoo_id"] in best]
        outs = [p for p in starters if p["yahoo_id"] not in best]
        gain = (sum(proj.get(i) or 0 for i in best)
                - sum(proj.get(i) or 0 for i in current))
        if ins and outs and gain >= SWAP_MIN:
            hints = {**{p["yahoo_id"]: "in" for p in ins}, **{p["yahoo_id"]: "out" for p in outs}}
            if len(ins) == 1 and len(outs) == 1:
                what = f"{escape(ins[0]['player'])} for {escape(outs[0]['player'])}"
            else:
                what = ("start " + ", ".join(escape(p["player"]) for p in ins)
                        + "; sit " + ", ".join(escape(p["player"]) for p in outs))
            swaps = (f'<p class="mu-swap">Best lineup by projection: <b>+{gain:.1f}</b> '
                     f"&mdash; {what}</p>")

    proj_total = sum(proj.get(p["yahoo_id"]) or 0 for p in starters)
    pts_total = sum(p.get("points") or 0 for p in starters)
    rows = [player_row(p, wk, by_team, to_school, espn, hints.get(p["yahoo_id"]), yproj)
            for p in starters]
    y_total = (sum(yproj.get(p["yahoo_id"]) or 0 for p in starters)
               if any(p["yahoo_id"] in yproj for p in starters) else None)
    states = {_state(game_for(p, wk, by_team, to_school, espn)) for p in starters}
    team_state = ("post" if final else
                  "in" if pts_total > 0 or states & {"in", "post"} else "pre")
    total_cell = (ui.score_cell(pts_total, proj_total, team_state, mark_proj=True)
                  .replace('<b class="mu-now', f'<b data-tpts="{escape(key)}" class="mu-now', 1)
                  .replace('<span class="mu-exp', f'<span data-thexp="{escape(key)}" class="mu-exp', 1))
    rows.append(f'<tr class="total"><td class="mu-pts">{total_cell}</td><td></td>'
                '<td class="mu-p">Starters</td><td></td>'
                f'<td class="mu-gs">{proj_total:.1f}</td><td class="mu-gs">{ui.fmt(y_total)}</td>'
                '<td></td></tr>')
    if bench:
        rows.append('<tr class="sep"><td colspan="7">Bench</td></tr>')
        rows.extend(player_row(p, wk, by_team, to_school, espn, hints.get(p["yahoo_id"]), yproj)
                    for p in bench)
    html = (f'<div class="table-scroll" data-roster="{escape(key)}"><table class="mu-roster"><thead><tr>'
            "<th class='mu-pts' title='Points scored, from Yahoo, with the live expected final under them; the projection before kickoff'>Pts</th>"
            "<th>Slot</th><th>Player</th><th>Game</th>"
            "<th title='GordStats projection for this week'>GS Proj</th>"
            "<th title='Yahoo projection for this week (Rotowire)'>Yahoo</th>"
            "<th>Stats</th>"
            f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>{swaps}')
    # The ordered players travel back with the html so `matchup_section` can
    # build the paired phone view without redoing the ordering and the best
    # lineup - both of which have to agree with the table or the two views
    # would disagree about who is starting.
    games = {p["yahoo_id"]: game_for(p, wk, by_team, to_school, espn) for p in ordered}
    # Each source's expected final - points so far plus the unplayed share of
    # its projections, by the clock - and the spread still to be played, for
    # the header and the GordStats win bar. The browser redoes this sum
    # (muLiveProjections) on every poll.
    gs_exp = y_exp = var = 0.0
    for p in starters:
        pid = p["yahoo_id"]
        left = 1.0 - _elapsed(games.get(pid))
        got = float(p.get("points") or 0.0)
        gs_exp += got + (proj.get(pid) or 0.0) * left
        y_exp += got + float(yproj.get(pid) or 0.0) * left
        var += ui.spread_for(None, proj.get(pid) or yproj.get(pid)) ** 2 * left
    parts = {"starters": starters, "bench": bench, "proj": proj, "games": games,
             "hints": hints, "pts": pts_total, "gs": proj_total,
             "gs_exp": gs_exp, "y_exp": y_exp if y_total is not None else None, "var": var}
    return html, proj_total, pts_total, parts


# --------------------------------------------------------------------------- #
# A matchup, a week, the page
# --------------------------------------------------------------------------- #

def _team_logo(t: dict) -> str:
    return (f'<img class="mu-tlogo" src="{escape(t["logo"])}" alt="" loading="lazy">'
            if t.get("logo") else "")


def _record(t: dict) -> str:
    w, l, ti = (int(t.get(k) or 0) for k in ("wins", "losses", "ties"))
    return f"{w}-{l}" + (f"-{ti}" if ti else "")


def _short_name(name: str) -> str:
    """"Trinidad Chambliss" -> "T. Chambliss".

    Each side of a paired row gets about 120px for a name at 390px wide, which
    a full college name does not fit - twenty-nine of thirty-six were clipped
    mid-word. The initial is what every fantasy app shows for the same reason.
    The full name stays in the title attribute.
    """
    parts = str(name).split()
    if len(parts) < 2:
        return str(name)
    return f"{parts[0][0]}. " + " ".join(parts[1:])


def _pair_cell(p: dict | None, key: str, to_school: dict, espn: dict,
               hint: str = "", game=None, proj=None) -> str:
    """One team's player in the paired phone view.

    Carries the same data-pid and .mu-pts the live updater looks for, inside a
    data-roster wrapper, so points tick over here exactly as they do in the
    wide table.
    """
    if p is None:
        return '<div class="mu-pp empty" aria-hidden="true"></div>'
    inj = (f'<span class="inj">{escape(p["status"])}</span>' if p.get("status") else "")
    tag = {"in": '<span class="mu-hint in">start</span>',
           "out": '<span class="mu-hint out">sit</span>'}.get(hint, "")
    live, attrs = _live_attrs(game)
    return (f'<div class="mu-pp{live}" data-roster="{escape(key)}" data-pid="{escape(p["yahoo_id"])}"{attrs}'
            f' data-proj="{"" if proj is None or pd.isna(proj) else round(float(proj), 2)}">'
            f'<div class="mu-pn">'
            f'<span class="nm" title="{escape(p["player"])}">'
            f'{_school_logo(p["team_full"], to_school, espn)}'
            f'{escape(_short_name(p["player"]))}</span>'
            f'<span class="mu-pm">{escape(p["pos"])} · {escape(p["team"])}{inj}{tag}</span>'
            f'<span class="mu-g">{game_cell(game)}</span></div>'
            f'<div class="mu-pcol"><span class="mu-pts">'
            f'{ui.score_cell(p.get("points"), proj, _state(game))}</span></div></div>')


def pair_view(a: dict, b: dict, to_school: dict, espn: dict) -> str:
    """The two rosters as one column of slot-paired rows, for a phone.

    Two tables of six columns each cannot be read side by side at 390px: they
    stack, so the opponent's quarterback is three thousand pixels below yours,
    and each table still scrolls sideways inside its own container. This is the
    layout every fantasy app uses instead - one row per lineup slot, your
    player on the left, theirs on the right, the slot between them - because it
    answers the only question the page exists for: who is winning this slot.

    Both sides run the same lineup, so the rows pair by position in the
    starters list; a side short of players pairs against an empty cell rather
    than shifting everything below it out of alignment.
    """
    ap, bp = a["parts"], b["parts"]

    def rows(a_list, b_list, bench=False) -> str:
        out = []
        for i in range(max(len(a_list), len(b_list))):
            pa = a_list[i] if i < len(a_list) else None
            pb = b_list[i] if i < len(b_list) else None
            slot = (pa or pb or {}).get("slot", "")
            out.append(
                f'<div class="mu-pr{" bench" if bench else ""}">'
                + _pair_cell(pa, a["key"], to_school, espn, ap["hints"].get((pa or {}).get("yahoo_id")),
                             ap["games"].get((pa or {}).get("yahoo_id")),
                             ap["proj"].get((pa or {}).get("yahoo_id")))
                + f'<div class="mu-pslot">{escape(slot)}</div>'
                + _pair_cell(pb, b["key"], to_school, espn, bp["hints"].get((pb or {}).get("yahoo_id")),
                             bp["games"].get((pb or {}).get("yahoo_id")),
                             bp["proj"].get((pb or {}).get("yahoo_id")))
                + "</div>")
        return "".join(out)

    starters = rows(ap["starters"], bp["starters"])
    bench = ""
    if ap["bench"] or bp["bench"]:
        bench = '<div class="mu-pbench-h">Bench</div>' + rows(ap["bench"], bp["bench"], bench=True)

    total = (f'<div class="mu-pr total">'
             f'<div class="mu-pp"><div class="mu-pn"><span class="nm">Starters</span></div>'
             f'<span class="mu-pts" data-tpts="{escape(a["key"])}">{ap["pts"]:.1f}</span></div>'
             f'<div class="mu-pslot"></div>'
             f'<div class="mu-pp"><span class="mu-pts" data-tpts="{escape(b["key"])}">'
             f'{bp["pts"]:.1f}</span>'
             f'<div class="mu-pn"><span class="nm">Starters</span></div></div>'
             f"</div>")

    return f'<div class="mu-pair">{starters}{total}{bench}</div>'


def matchup_section(m: dict, data: dict, lg: dict, wk: pd.DataFrame, to_school: dict,
                    espn: dict, teams: dict, anchor: str,
                    by_team: dict = None) -> tuple[str, list[dict]]:
    """One matchup in full. Returns (html, [summary per side])."""
    final = m.get("status") == yahoo.STATUS_FINAL
    started = m.get("status") != "preevent"
    sides = []
    for t in m["teams"]:
        html, proj_total, pts_total, parts = roster_table(
            data["rosters"].get(t["team_key"], []), lg, wk, to_school, espn, final,
            key=t["team_key"], by_team=by_team, yproj=data.get("yahoo_proj"))
        sides.append({"team": teams.get(t["team_key"], {"name": t["name"]}),
                      "name": t["name"], "key": t["team_key"], "html": html,
                      "gs": proj_total, "pts": pts_total if started else None,
                      "parts": parts,
                      "yproj": t.get("projected"), "wp": t.get("win_probability")})
    a, b = sides
    lead = (None if not started or a["pts"] == b["pts"]
            else ("a" if (a["pts"] or 0) > (b["pts"] or 0) else "b"))

    # The score is printed here and nowhere else in the section: the big
    # number is the live total (the GordStats projection before kickoff), and
    # the projections sit under it in italics, ours first.
    def side_html(s, which):
        big = ui.fmt(s["pts"]) if started else ui.fmt(s["gs"])
        cls = " lead" if lead == which else ""
        # Each source's numbers are on its own row under the header
        # (ui.source_bar); here only what the big number is, and once the
        # week is over, what the sources had going in.
        if not started:
            sub = "projected"
        elif final:
            sub = f"GordStats <b>{ui.fmt(s['gs'])}</b> · Yahoo <b>{ui.fmt(s['yproj'])}</b>"
        else:
            sub = ""
        return (f'<div class="mu-side {"r" if which == "b" else ""}">{_team_logo(s["team"])}'
                f'<div><div class="nm">{escape(s["name"])}'
                f'<span class="rec">{_record(s["team"])}</span></div>'
                f'<div class="num{cls}" data-num="{escape(s["key"])}" data-mu="{anchor}" '
                f'data-val="{s["pts"] if s["pts"] is not None else ""}">{big}</div>'
                + (f'<div class="sub">{sub}</div>' if sub else "") + '</div></div>')

    # Two bars: ours, from the GordStats expected finals and the spread still
    # to be played (gordstats.matchup_page.win_probability), and Yahoo's own.
    wp_a = a["wp"] if a["wp"] is not None else 0.5
    wp_b = b["wp"] if b["wp"] is not None else 1 - wp_a
    gs_a = ui.win_probability(a["parts"]["gs_exp"], a["parts"]["var"],
                              b["parts"]["gs_exp"], b["parts"]["var"])
    # Each source's expected final while the week is played, kept moving by
    # the live poll. Yahoo's own projected total stays where it was at kickoff
    # (week 1 finished 244 against a Yahoo 180), so its row sums Yahoo's
    # player projections the same way ours does.
    ka, kb = escape(a["key"]), escape(b["key"])
    # Yahoo leaves "preevent" days before the first kickoff.
    kicked = any(_state(g) in ("in", "post") for s in sides for g in s["parts"]["games"].values())

    def yahoo_final(s):
        return s["parts"]["y_exp"] if s["parts"]["y_exp"] is not None else s["yproj"]
    wp = ("" if final else ui.source_bars([
        ui.source_bar("GordStats", "gs", ka, kb, a["parts"]["gs_exp"], b["parts"]["gs_exp"],
                      gs_a, follows="gs"),
        ui.source_bar("Yahoo", "yahoo", ka, kb, yahoo_final(a), yahoo_final(b), wp_a, alt=True)],
        kicked))
    mid = "Final" if final else ("Live" if started else "Preview")
    gs_edge = a["gs"] - b["gs"]
    leader = escape(a['name'] if gs_edge >= 0 else b['name'])
    # "Going in" only when every number behind it was recorded before its
    # kickoff. The weeks before the archive existed are rebuilt from today's
    # fit, which has seen the games - so they say so.
    ids = [str(p["yahoo_id"]) for t in m["teams"] for p in data["rosters"].get(t["team_key"], [])]
    honest = pregame.complete(wk.loc[wk.index.intersection(ids)])
    if not final and kicked and honest:
        # The header moves with the games, so this is what it moved from.
        edge = f"Going in, GordStats had <b>{leader}</b> by {abs(gs_edge):.1f}."
    elif not final:
        edge = f"GordStats has <b>{leader}</b> by {abs(gs_edge):.1f} on projection."
    elif honest:
        edge = f"GordStats had <b>{leader}</b> by {abs(gs_edge):.1f} going in."
    else:
        edge = (f"On today's projections GordStats would have had <b>{leader}</b> "
                f"by {abs(gs_edge):.1f}.")
    body = (f'<div class="mu-head">{side_html(a, "a")}<div class="mu-mid">{mid}</div>'
            f'{side_html(b, "b")}</div>{wp}<p class="mu-note">{edge}</p>'
            + pair_view(a, b, to_school, espn)
            + f'<div class="mu-grid"><div><div class="mu-who">{escape(a["name"])}</div>{a["html"]}</div>'
            f'<div><div class="mu-who">{escape(b["name"])}</div>{b["html"]}</div></div>')
    head = f'{escape(a["name"])}<span class="mu-vs-sum">vs</span>{escape(b["name"])}'
    html = (f'<details class="section" open id="{anchor}"><summary>{head}</summary>'
            f"{body}</details>")
    return html, sides


def week_board(rows: list[tuple], started: bool, final: bool,
               med_now=None, med_proj=None, median: bool = True) -> str:
    """The scoreboard: one row per matchup linking down to the full view.

    Per side: the points (once games are on), the GordStats projection and
    Yahoo's win chance. Yahoo's projection is in each matchup's header, not
    here - with it the board ran eleven columns and pushed the right-hand
    team off any screen narrower than a laptop's.
    """
    cells = []
    for anchor, a, b in rows:
        def num(s, other, key):
            v = s.get(key)
            o = other.get(key)
            lead = v is not None and o is not None and v > o
            attr = (f' data-sb="{escape(s["key"])}" data-val="{v if v is not None else ""}"'
                    if key == "pts" else ' class="mu-proj"')
            return f"<td{attr}>{'<b class=lead>' if lead else ''}{ui.fmt(v)}{'</b>' if lead else ''}</td>"

        def med(s):
            v = s.get("med")
            cls = "" if v is None else ("mu-med-up" if v > 0 else "mu-med-down" if v < 0 else "")
            return (f'<td class="{cls}" data-vsmed="{escape(s["key"])}">'
                    f'{"—" if v is None else f"{v:+.1f}"}</td>')
        cells.append(
            f'<tr><td class="mu-t"><a href="#{anchor}" title="{escape(a["name"])}">'
            f'{_team_logo(a["team"])}{escape(a["name"])}</a></td>'
            + (num(a, b, "pts") if started else "")
            + num(a, b, "gs") + (med(a) if median else "")
            + (f"<td>{ui.fmt((a['wp'] or 0) * 100, 0)}%</td>" if not final else "")
            + '<td class="mu-vs">vs</td>'
            + (f"<td>{ui.fmt((b['wp'] or 0) * 100, 0)}%</td>" if not final else "")
            + (med(b) if median else "") + num(b, a, "gs")
            + (num(b, a, "pts") if started else "")
            + f'<td class="mu-t r"><a href="#{anchor}" title="{escape(b["name"])}">'
              f'{escape(b["name"])}{_team_logo(b["team"])}</a></td></tr>')
    pts_h = "<th>Pts</th>" if started else ""
    wp_h = "<th title='Yahoo win probability'>Win%</th>" if not final else ""
    proj_h = "<th class='mu-proj' title='GordStats projected total for the lineup as set'>Proj</th>"
    med_h = ("<th title='Margin against the week\'s median score - the league\'s second game "
             "each week'>Med</th>") if median else ""
    strip = ""
    if med_proj is not None:
        strip = ('<p class="mu-median"><b>Week median</b> '
                 + (f'<span data-median-now>{ui.fmt(med_now)}</span> now · ' if started else "")
                 + f'<span data-median-proj>{ui.fmt(med_proj)}</span> projected'
                 " - every team also plays the median each week; <b>Med</b> is the margin "
                 "against it" + (", live" if started else ", on projection") + ".</p>")
    # Once games are on, a narrow screen drops the projection columns (the
    # matchup headers carry them) so the names keep their room.
    cards = ui.board_cards(
        [(anchor, {"name": escape(a["name"]), "logo": _team_logo(a["team"]), "key": a["key"],
                   "pts": a["pts"], "gs": a["gs"], "wp": a["wp"], "med": a.get("med")},
          {"name": escape(b["name"]), "logo": _team_logo(b["team"]), "key": b["key"],
           "pts": b["pts"], "gs": b["gs"], "wp": b["wp"], "med": b.get("med")})
         for anchor, a, b in rows],
        started, final)
    return (strip + cards + f'<div class="mu-board-wrap"><div class="table-scroll"><table class="mu-board{" started" if started else ""}"><thead><tr>'
            f"<th>Team</th>{pts_h}{proj_h}{med_h}{wp_h}"
            f"<th></th>{wp_h}{med_h}{proj_h}{pts_h}<th>Team</th>"
            f'</tr></thead><tbody>{"".join(cells)}</tbody></table></div></div>')


def _elapsed(g) -> float:
    """How much of a game has been played, 0..1 - the same arithmetic as the
    browser's muElapsed, for the render that happens before any poll."""
    if g is None or not isinstance(g.get("state"), str):
        return 1.0
    if g["state"] == "pre":
        return 0.0
    if g["state"] == "post":
        return 1.0
    period = int(g.get("period") or 0)
    if not period:
        return 0.5
    if period > 4:
        return 0.95
    left = str(g.get("clock") or "0:00").split(":")
    try:
        mins = int(left[0]) + (int(left[1]) / 60 if len(left) > 1 else 0)
    except ValueError:
        mins = 0.0
    return min(max(((period - 1) * 15 + (15 - mins)) / 60, 0.0), 1.0)


def position_extremes(datas: dict) -> dict:
    """{"max": {pos: pts}, "min": {pos: pts}} from every archived week.

    The tracker's ceilings and floors: the best and worst single week anyone
    on these ten rosters has put up at each position. The NFL page reads
    seasons of history for this; the college league has only this season, so
    early on the ceiling is whatever the young season has seen. A position
    nobody has played yet falls back to FALLBACK_CEILING in the renderer.
    """
    hi, lo = {}, {}
    for data in datas.values():
        if not yahoo.week_final(data):
            continue
        for roster in data["rosters"].values():
            for p in roster:
                pos, pts = p.get("pos"), p.get("points")
                if not pos or pts is None:
                    continue
                hi[pos] = max(hi.get(pos, float("-inf")), float(pts))
                lo[pos] = min(lo.get(pos, float("inf")), float(pts))
    return {"max": {k: round(v, 2) for k, v in hi.items()},
            "min": {k: round(v, 2) for k, v in lo.items()}}


def tracker_side(side: dict, wk: pd.DataFrame) -> dict:
    """One roster for the median tracker: points so far, the expected final,
    and the starters still to play with what they are projected to add."""
    parts = side["parts"]
    left, expected = [], 0.0
    for p in parts["starters"]:
        pid = p["yahoo_id"]
        g = parts["games"].get(pid)
        done = _elapsed(g)
        proj = parts["proj"].get(pid) or 0.0
        pts = float(p.get("points") or 0.0)
        expected += pts + proj * (1 - done)
        if done >= 1.0:
            continue
        left.append({"n": _short_name(p["player"]), "r": round(proj * (1 - done), 1),
                     "live": bool(g is not None and g.get("state") == "in"),
                     "pos": p["pos"], "p": round(pts, 2)})
    # The name goes in raw: the renderer escapes it, and escaping here too
    # turned every apostrophe into a visible &#x27;.
    return {"k": side["key"], "name": side["name"], "logo": _team_logo(side["team"]),
            "pts": round(float(side["pts"] or 0.0), 2), "exp": round(expected, 2),
            "left": left}


def week_view(data: dict, lg: dict, board: pd.DataFrame, frame: pd.DataFrame,
              to_school: dict, espn: dict, teams: dict, extremes: dict = None) -> str:
    week = int(data["week"])
    statuses = {p["yahoo_id"]: p["status"] for roster in data["rosters"].values()
                for p in roster if p.get("status")}
    wk = weekly.week_projections(data["week_start"], data["week_end"],
                                 board=board, league=lg, frame=frame, injuries=statuses)
    # A started player's number is the one recorded before his kickoff, not
    # today's, which has already seen his game (see cfb.pregame).
    wk = pregame.freeze(week, wk)
    final = yahoo.week_final(data)
    started = any(m.get("status") != "preevent" for m in data["matchups"])
    start = datetime.strptime(data["week_start"], "%Y-%m-%d")
    end = datetime.strptime(data["week_end"], "%Y-%m-%d")
    by_team = weekly.team_games(weekly.games_between(frame, data["week_start"], data["week_end"]))
    sections, rows = [], []
    for i, m in enumerate(data["matchups"], 1):
        anchor = f"wk{week}-m{i}"
        html, sides = matchup_section(m, data, lg, wk, to_school, espn, teams, anchor,
                                      by_team=by_team)
        sections.append(html)
        rows.append((anchor, sides[0], sides[1]))
    # The league plays a second game each week against the median score: the
    # median of the live totals once games are on, of the projections before,
    # and every side's margin against whichever applies.
    # Yahoo plays it in the regular season only.
    import statistics
    median_on = bool(lg.get("uses_median_score", True)) and not data.get("is_playoffs")
    every = [s for _, a, b in rows for s in (a, b)]
    med_proj = statistics.median(s["gs"] for s in every) if (every and median_on) else None
    med_now = (statistics.median((s["pts"] or 0.0) for s in every)
               if (every and started and median_on) else None)
    for s in every if median_on else []:
        s["med"] = ((s["pts"] or 0.0) - med_now) if started else (s["gs"] - med_proj)
    state = ("Final" if final else "In progress" if started else "Not started")
    fetched = data.get("fetched")
    _CARDS[week] = {"pairs": [(a["name"], a["pts"], a["gs"], b["name"], b["pts"], b["gs"])
                              for _, a, b in rows],
                    "names": {s["key"]: s["name"] for _, a, b in rows for s in (a, b)},
                    "anchors": {s["key"]: anc for anc, a, b in rows for s in (a, b)},
                    "started": started, "final": final,
                    "asof": (datetime.fromisoformat(fetched).astimezone(LEAGUE_TZ)
                             .strftime("%a %-I:%M %p") if fetched else "")}
    asof = ""
    if fetched and started and not final:
        asof = (' <span class="mu-asof">· Yahoo points as of '
                + datetime.fromisoformat(fetched).astimezone(LEAGUE_TZ)
                .strftime("%a %-I:%M %p") + "</span>")
    # ESPN's own week number for these games. The poll used to ask for the
    # Yahoo week as a date range, and in September 2026 ESPN began answering
    # every range with a 400; a week query still works. ESPN folds Week 0 into
    # week 1, which only means a few extra games the page never looks up.
    in_window = weekly.games_between(frame, data["week_start"], data["week_end"])
    espn_week = (int(in_window["week"].mode().iloc[0])
                 if "week" in in_window and in_window["week"].notna().any() else week)
    # The week still being played polls Yahoo through the site's own proxy
    # (functions/api/cfb-matchups.js): a minute apart while games are on,
    # five minutes before they start.
    live = ("" if final else
            "<script>" + ui.LIVE_GAMES_JS + ui.LIVE_LEFT_JS + "window.MU_LIVE={fetch:function(){"
            "var api=fetch('/api/cfb-matchups?week="
            f"{week}&_='+Date.now()).then(function(r){{return r.json();}}).catch(function(){{return {{teams:{{}}}};}});"
            "var sb=muGames('https://site.api.espn.com/apis/site/v2/sports/football/college-football/"
            f"scoreboard?groups=80&limit=500&week={espn_week}&dates={SEASON}&seasontype=2');"
            "return Promise.all([api,sb]).then(function(x){"
            f"var R=document.querySelector('#wk-view-{week}');"
            "var out=muMedian(muTrackerLeft(muLiveProjections(muMergeGames(x[0],x[1],R),x[1],R,{yahoo:'data-yproj'}),x[1],R));"
            f"if(window.muMedTrack)window.muMedTrack.update({week},out,R);return out;}});}},"
            f"interval:{60000 if started else 300000},root:'#wk-view-{week}'}};</script>")
    # "Median 0.0 now" before anyone has scored is noise: Yahoo flips a week
    # off preevent at the start of its window, days before kickoff.
    scoring = started and any((s["pts"] or 0) > 0 for s in every)
    tracker = (ui.median_tracker([tracker_side(s, wk) for s in every], week, scoring, final,
                                 extremes or {}) if median_on else "")
    return (f"<p><strong>Week {week}</strong> · {start:%b %-d} – {end:%b %-d}"
            + (" (playoffs)" if data.get("is_playoffs") else "")
            + f" · {state}{asof}</p>" + tracker
            + week_board(rows, started, final, med_now, med_proj, median_on)
            + "".join(sections) + live)


_BENCH_SLOTS = {"BN", "IR", "IL"}


def accuracy(datas: dict) -> tuple:
    """(table, weeks, gordstats_closer) - GordStats and Yahoo scored on the
    same player-weeks: starters who played, in finished weeks, whom both
    projected before kickoff. Before GordStats has such a week, Yahoo alone.

    Ours is read from the pre-game archive (cfb.pregame), never rebuilt: a
    projection rebuilt after the games has seen them, and scored against
    Yahoo's kept pre-game numbers it would flatter us. Yahoo's are the ones
    the week's archive captured before kickoff.
    """
    from gordstats.pregame import load as load_pregame
    rows = []
    for w, data in sorted(datas.items()):
        if not yahoo.week_final(data):
            continue
        ours = load_pregame(pregame.path(w))
        theirs = data.get("yahoo_proj") or {}
        for roster in data["rosters"].values():
            for p in roster:
                pid = str(p["yahoo_id"])
                if p["slot"] in _BENCH_SLOTS or not p.get("stats") or theirs.get(pid) is None:
                    continue
                rows.append({"week": w, "actual": float(p.get("points") or 0.0),
                             "yahoo": float(theirs[pid]),
                             "gordstats": (float(ours[pid]) if ours.get(pid) is not None
                                           else None)})
    if not rows:
        return None, [], None
    frame = pd.DataFrame(rows)
    both = frame.dropna(subset=["gordstats"])
    if not both.empty:
        frame = both.assign(average=(both["gordstats"] + both["yahoo"]) / 2)
        cols = ["gordstats", "yahoo", "average"]
    else:
        cols = ["yahoo"]
    table = []
    for c in cols:
        err = frame[c] - frame["actual"]
        table.append({"source": c, "n": len(frame), "mae": err.abs().mean(),
                      "bias": err.mean(),
                      "corr": (frame[c].corr(frame["actual"]) if len(frame) >= 3
                               else float("nan"))})
    closer = None
    if not both.empty:
        g = (frame["gordstats"] - frame["actual"]).abs()
        y = (frame["yahoo"] - frame["actual"]).abs()
        closer = float((g < y).mean() + 0.5 * (g == y).mean())
    return pd.DataFrame(table).sort_values("mae"), sorted(frame["week"].unique()), closer


def accuracy_section(datas: dict) -> str:
    table, weeks, closer = accuracy(datas)
    if table is None or table.empty:
        return ""
    names = {"gordstats": "GordStats", "yahoo": "Yahoo", "average": "Both, averaged"}
    cells = "".join(
        f'<tr><td class="mu-t"><b>{names[r.source]}</b></td><td>{r.n}</td>'
        f"<td>{r.mae:.2f}</td><td>{r.bias:+.2f}</td>"
        f"<td>{'&mdash;' if pd.isna(r.corr) else f'{r.corr:.2f}'}</td></tr>"
        for r in table.itertuples())
    span = f"week{'s' if len(weeks) > 1 else ''} {', '.join(str(int(w)) for w in weeks)}"
    lead = (f"Head to head, GordStats was closer on <b>{closer:.0%}</b> of them. "
            if closer is not None else "")
    alone = "gordstats" not in set(table["source"])
    who = ("Yahoo's projection against what starters actually scored, "
           f"over {span}. " if alone else
           "Each projection against what starters actually scored, "
           f"over {span} - every source on the same players, the ones they all "
           "projected before kickoff. ")
    body = ('<p class="mu-note">' + who + lead
            + "<b>MAE</b> is the average miss in points, <b>Bias</b> the average signed miss "
            "(positive = projected too high), <b>r</b> the correlation with the real score. "
            "Lowest MAE first."
            + ("" if not alone else
               " GordStats joins once a week it projected before kickoff has finished - "
               "week 5 is the first.")
            + "</p>"
            '<div class="table-scroll"><table class="mu-board"><thead><tr><th>Source</th>'
            "<th>Players</th><th>MAE</th><th>Bias</th><th>r</th></tr></thead>"
            f"<tbody>{cells}</tbody></table></div>")
    return ("<details class='section'><summary>Projection accuracy &mdash; who has been "
            f"right</summary>{body}</details>")


def _recap_teaser() -> str:
    from cfb.site import recap              # it reads this module's best_lineup
    return recap.teaser()


def body() -> str:
    lg = yahoo.league()
    weeks = yahoo.archived_weeks()
    if not weeks:
        return (ui.CSS + "<p>No matchups yet — the page fills in on the first "
                "rebuild once Yahoo has scheduled week 1.</p>")
    frame, _model, _names = predict.season()
    board = in_season.board(frame=frame)
    to_school = schools_mod.yahoo_school()
    espn = schools_mod.espn_ids()
    teams = {t["team_key"]: t for t in lg["teams"]}

    datas = {w: yahoo.week_matchups(w) for w in weeks}
    current = max(w for w in weeks if not yahoo.week_final(datas[w])) \
        if any(not yahoo.week_final(d) for d in datas.values()) else weeks[-1]
    extremes = position_extremes(datas)
    _CARDS["current"], _CARDS["league"] = current, lg.get("name") or ""
    views = {w: week_view(datas[w], lg, board, frame, to_school, espn, teams, extremes)
             for w in weeks}
    views[current] = _game_of_week(current) + views[current]

    built = datetime.now(LEAGUE_TZ).strftime("%b %-d, %-I:%M %p %Z")
    info = _CARDS.get(current)
    share = share_button.row("/cfb/matchups/", share_card.matchups_line(
        current, info["pairs"], info["started"], info["final"]) if info else "")
    return (
        ui.CSS + share
        # One line: the recap teaser under it says the rest.
        + f'<p><a href="{escape(lg["url"], quote=True)}"><strong>{escape(lg["name"])}</strong></a> — every '
        "matchup, live while games are on.</p>"
        + _recap_teaser()
        + "<details class='section'><summary>How to read this page</summary>"
        "<p><b>GS Proj</b> is this site's own "
        "projection for the week: each player's season projection spread over "
        "his school's games, tilted by what the game model expects of this "
        "week's game, and zero on a bye. <b>Pts</b> is the projection (grey) "
        "until a player's game kicks off, then his Yahoo points with the expected final "
        "under them, then <i>final</i>. <b>Med</b> is each "
        "team's margin against the week's median score - the league plays a second game "
        "against it every week - live once games are on, on projection before. <b>Yahoo</b> is "
        "Yahoo's own projection for the player (Rotowire's numbers, read from the league's "
        "team pages), whose starters add up to the Yahoo team total in each header; the "
        "start/sit advice runs on GS Proj. A player past our board's depth shows "
        "&mdash; under GS Proj; there but still plays. While games are on, points, stat lines "
        "and each source's expected final and win chance refresh in place about once a minute. Ahead of "
        "kickoff a roster whose bench "
        "out-projects a starter gets the swap spelled out under the table. "
        f"Rebuilt several times a day (last: {built}); finished weeks stay on "
        'record. Standings and waivers are on the <a href="/cfb/league/">league '
        'dashboard</a>, season-long roster strength on the '
        '<a href="/cfb/league/power/">power rankings</a>.</p></details>'
        + ui.week_switch(weeks, current, views) + accuracy_section(datas)
        + ui.MEDIAN_TRACKER_JS + ui.LIVE_JS)


# The week each week_view drew, for the page's link-preview card: which week
# is current is only known once body() has looked at them all.
_CARDS: dict = {}


def _game_of_week(week: int) -> str:
    """The week's biggest game by playoff odds (gordstats.stakes), from what the
    power page left - until the week is final."""
    info = _CARDS.get(week)
    teams = stakes.read(WEB_DIR / "stakes.json", week)
    if not info or info["final"] or not teams:
        return ""
    ranked = stakes.games(teams)
    if not ranked:
        return ""
    return stakes.callout(week, teams, names=info["names"],
                          anchor=info["anchors"].get(ranked[0][0], ""),
                          more="<a href='/cfb/league/power/#stakes'>Every team's stakes &rarr;</a>")


def card() -> dict | None:
    """The current week's link-preview card (gordstats.share_card)."""
    info = _CARDS.get(_CARDS.get("current"))
    if not info:
        return None
    return share_card.matchups("cfb-matchups", "CFB Fantasy", _CARDS["current"], info["pairs"],
                               info["started"], info["final"], _CARDS.get("league", ""),
                               info["asof"])


def generate():
    html = body()
    write_page(OUTPUT, f"CFB League Matchups {SEASON}", html, image=card())


if __name__ == "__main__":
    generate()
