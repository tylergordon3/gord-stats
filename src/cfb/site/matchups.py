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

from cfb import predict, projections, schools as schools_mod, weekly, yahoo
from cfb.config import LEAGUE_TZ, SEASON, WEB_DIR
from cfb.site import write_page
from gordstats import matchup_page as ui

OUTPUT = WEB_DIR / "matchups" / "index.html"
LOGO = "https://a.espncdn.com/i/teamlogos/ncaa/500/{team_id}.png"

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
    return f'<img class="mu-logo" src="{LOGO.format(team_id=escape(str(tid)))}" alt="" loading="lazy">'


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
    return pd.Series({"opp": g["opp"], "opp_rank": g.get("opp_rank"), "home": g["home"],
                      "kickoff": g["date"], "state": g["state"],
                      "score_for": g["score_for"], "score_against": g["score_against"]})


def player_row(p: dict, wk: pd.DataFrame, by_team: dict, to_school: dict, espn: dict,
               hint: str = "") -> str:
    pid = p["yahoo_id"]
    g = game_for(p, wk, by_team, to_school, espn)
    proj = wk.loc[pid, "proj_week"] if pid in wk.index else None
    bench = p["slot"] in _BENCH
    inj = (f'<span class="inj" title="{escape(p.get("injury_note") or p.get("status_full") or "")}">'
           f'{escape(p["status"])}</span>' if p.get("status") else "")
    tag = {"in": '<span class="mu-hint in" title="Projects into the best lineup">start</span>',
           "out": '<span class="mu-hint out" title="A bench player projects higher">sit</span>'
           }.get(hint, "")
    return (f'<tr class="{"bench" if bench else "starter"}" data-pid="{escape(pid)}">'
            f"<td class=\"mu-pts\"><b>{ui.fmt(p.get('points'))}</b></td>"
            f'<td class="mu-slot">{escape(p["slot"])}</td>'
            f'<td class="mu-p"><span class="mu-pc"><span class="nm">'
            f'{_school_logo(p["team_full"], to_school, espn)}{escape(p["player"])}</span> '
            f'<span class="mu-lbl"><span class="mu-meta">{escape(p["pos"])} · {escape(p["team"])}'
            f'</span>{inj}{tag}</span></span></td>'
            f'<td class="mu-g">{game_cell(g)}</td>'
            f"<td>{ui.fmt(proj)}</td>"
            f'<td class="mu-s">{escape(stat_line(p.get("stats") or {}, p["pos"]))}</td></tr>')


def roster_table(players: list[dict], lg: dict, wk: pd.DataFrame, to_school: dict,
                 espn: dict, final: bool, key: str = "",
                 by_team: dict = None) -> tuple[str, float, float]:
    """One roster in lineup order. Returns (html, projected starters, points)."""
    by_team = by_team or {}
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
    rows = [player_row(p, wk, by_team, to_school, espn, hints.get(p["yahoo_id"]))
            for p in starters]
    rows.append(f'<tr class="total"><td class="mu-pts" data-tpts="{escape(key)}">{pts_total:.1f}</td>'
                f'<td></td><td class="mu-p">Starters</td><td></td>'
                f"<td>{proj_total:.1f}</td><td></td></tr>")
    if bench:
        rows.append('<tr class="sep"><td colspan="6">Bench</td></tr>')
        rows.extend(player_row(p, wk, by_team, to_school, espn, hints.get(p["yahoo_id"]))
                    for p in bench)
    html = (f'<div class="table-scroll" data-roster="{escape(key)}"><table class="mu-roster"><thead><tr>'
            "<th class='mu-pts' title='Points actually scored this week, from Yahoo (live while games are on)'>Pts</th>"
            "<th>Slot</th><th>Player</th><th>Game</th>"
            "<th title='GordStats projection for this week'>GS Proj</th>"
            "<th>Stats</th>"
            f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>{swaps}')
    return html, proj_total, pts_total


# --------------------------------------------------------------------------- #
# A matchup, a week, the page
# --------------------------------------------------------------------------- #

def _team_logo(t: dict) -> str:
    return (f'<img class="mu-tlogo" src="{escape(t["logo"])}" alt="" loading="lazy">'
            if t.get("logo") else "")


def _record(t: dict) -> str:
    w, l, ti = (int(t.get(k) or 0) for k in ("wins", "losses", "ties"))
    return f"{w}-{l}" + (f"-{ti}" if ti else "")


def matchup_section(m: dict, data: dict, lg: dict, wk: pd.DataFrame, to_school: dict,
                    espn: dict, teams: dict, anchor: str,
                    by_team: dict = None) -> tuple[str, list[dict]]:
    """One matchup in full. Returns (html, [summary per side])."""
    final = m.get("status") == yahoo.STATUS_FINAL
    started = m.get("status") != "preevent"
    sides = []
    for t in m["teams"]:
        html, proj_total, pts_total = roster_table(
            data["rosters"].get(t["team_key"], []), lg, wk, to_school, espn, final,
            key=t["team_key"], by_team=by_team)
        sides.append({"team": teams.get(t["team_key"], {"name": t["name"]}),
                      "name": t["name"], "key": t["team_key"], "html": html,
                      "gs": proj_total, "pts": pts_total if started else None,
                      "yproj": t.get("projected"), "wp": t.get("win_probability")})
    a, b = sides
    lead = (None if not started or a["pts"] == b["pts"]
            else ("a" if (a["pts"] or 0) > (b["pts"] or 0) else "b"))

    def side_html(s, which):
        big = ui.fmt(s["pts"]) if started else ui.fmt(s["gs"])
        cls = " lead" if lead == which else ""
        sub = (f"Yahoo proj <b>{ui.fmt(s['yproj'])}</b> · GordStats <b>{ui.fmt(s['gs'])}</b>"
               if started else f"Yahoo proj <b>{ui.fmt(s['yproj'])}</b>")
        return (f'<div class="mu-side {"r" if which == "b" else ""}">{_team_logo(s["team"])}'
                f'<div><div class="nm">{escape(s["name"])}'
                f'<span class="rec">{_record(s["team"])}</span></div>'
                f'<div class="num{cls}" data-num="{escape(s["key"])}" data-mu="{anchor}" '
                f'data-val="{s["pts"] if s["pts"] is not None else ""}">{big}</div>'
                f'<div class="sub">{sub}</div></div></div>')

    wp_a = a["wp"] if a["wp"] is not None else 0.5
    wp_b = b["wp"] if b["wp"] is not None else 1 - wp_a
    wp = "" if final else ui.win_bar(wp_a, wp_b, "Yahoo", a["key"], b["key"])
    mid = "Final" if final else ("Live" if started else "Preview")
    gs_edge = a["gs"] - b["gs"]
    edge = (f"GordStats has <b>{escape(a['name'] if gs_edge >= 0 else b['name'])}</b> "
            f"by {abs(gs_edge):.1f} on projection ({ui.fmt(a['gs'])}–{ui.fmt(b['gs'])})."
            if not final else
            f"GordStats projected {ui.fmt(a['gs'])}–{ui.fmt(b['gs'])} going in.")
    body = (f'<div class="mu-head">{side_html(a, "a")}<div class="mu-mid">{mid}</div>'
            f'{side_html(b, "b")}</div>{wp}<p class="mu-note">{edge}</p>'
            f'<div class="mu-grid"><div><div class="mu-who">{escape(a["name"])}</div>{a["html"]}</div>'
            f'<div><div class="mu-who">{escape(b["name"])}</div>{b["html"]}</div></div>')
    head = (f'{escape(a["name"])} {ui.fmt(a["pts"]) if started else ""} '
            f'<span style="color:#94a3b8">vs</span> '
            f'{ui.fmt(b["pts"]) if started else ""} {escape(b["name"])}')
    html = (f'<details class="section" open id="{anchor}"><summary>{head}</summary>'
            f"{body}</details>")
    return html, sides


def week_board(rows: list[tuple], started: bool, final: bool) -> str:
    """The scoreboard: one row per matchup linking down to the full view."""
    cells = []
    for anchor, a, b in rows:
        def num(s, other, key):
            v = s.get(key)
            o = other.get(key)
            lead = v is not None and o is not None and v > o
            attr = (f' data-sb="{escape(s["key"])}" data-val="{v if v is not None else ""}"'
                    if key == "pts" else "")
            return f"<td{attr}>{'<b class=lead>' if lead else ''}{ui.fmt(v)}{'</b>' if lead else ''}</td>"
        pts = (num(a, b, "pts") + num(b, a, "pts")) if started else ""
        wp = "" if final else (f"<td>{ui.fmt((a['wp'] or 0) * 100, 0)}%</td>"
                               f"<td>{ui.fmt((b['wp'] or 0) * 100, 0)}%</td>")
        cells.append(
            f'<tr><td class="mu-t"><a href="#{anchor}">{_team_logo(a["team"])}'
            f'{escape(a["name"])}</a></td>'
            + (num(a, b, "pts") if started else "")
            + num(a, b, "yproj") + num(a, b, "gs")
            + (f"<td>{ui.fmt((a['wp'] or 0) * 100, 0)}%</td>" if not final else "")
            + '<td class="mu-vs">vs</td>'
            + (f"<td>{ui.fmt((b['wp'] or 0) * 100, 0)}%</td>" if not final else "")
            + num(b, a, "gs") + num(b, a, "yproj")
            + (num(b, a, "pts") if started else "")
            + f'<td class="mu-t r"><a href="#{anchor}">{escape(b["name"])}'
              f'{_team_logo(b["team"])}</a></td></tr>')
    pts_h = "<th>Pts</th>" if started else ""
    wp_h = "<th title='Yahoo win probability'>Win%</th>" if not final else ""
    return ('<div class="table-scroll"><table class="mu-board"><thead><tr>'
            f"<th>Team</th>{pts_h}<th title='Yahoo projected total'>Yahoo Proj</th>"
            f"<th title='GordStats projected total for the lineup as set'>GS Proj</th>{wp_h}"
            f"<th></th>{wp_h}<th>GS Proj</th><th>Yahoo Proj</th>{pts_h}<th>Team</th>"
            f'</tr></thead><tbody>{"".join(cells)}</tbody></table></div>')


def week_view(data: dict, lg: dict, board: pd.DataFrame, frame: pd.DataFrame,
              to_school: dict, espn: dict, teams: dict) -> str:
    week = int(data["week"])
    wk = weekly.week_projections(data["week_start"], data["week_end"],
                                 board=board, league=lg, frame=frame)
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
    state = ("Final" if final else "In progress" if started else "Not started")
    fetched = data.get("fetched")
    asof = ""
    if fetched and started and not final:
        asof = (' <span class="mu-asof">· Yahoo points as of '
                + datetime.fromisoformat(fetched).astimezone(LEAGUE_TZ)
                .strftime("%a %-I:%M %p") + "</span>")
    # The week still being played polls Yahoo through the site's own proxy
    # (functions/api/cfb-matchups.js): a minute apart while games are on,
    # five minutes before they start.
    live = ("" if final else
            "<script>window.MU_LIVE={fetch:function(){return fetch('/api/cfb-matchups?week="
            f"{week}&_='+Date.now()).then(function(r){{return r.json();}});}},"
            f"interval:{60000 if started else 300000}}};</script>")
    return (f"<p><strong>Week {week}</strong> · {start:%b %-d} – {end:%b %-d}"
            + (" (playoffs)" if data.get("is_playoffs") else "")
            + f" · {state}{asof}</p>"
            + week_board(rows, started, final) + "".join(sections) + live)


def body() -> str:
    lg = yahoo.league()
    weeks = yahoo.archived_weeks()
    if not weeks:
        return (ui.CSS + "<p>No matchups yet — the page fills in on the first "
                "rebuild once Yahoo has scheduled week 1.</p>")
    frame, _model, _names = predict.season()
    board = projections.value_board(frame=frame)
    to_school = schools_mod.yahoo_school()
    espn = schools_mod.espn_ids()
    teams = {t["team_key"]: t for t in lg["teams"]}

    datas = {w: yahoo.week_matchups(w) for w in weeks}
    current = max(w for w in weeks if not yahoo.week_final(datas[w])) \
        if any(not yahoo.week_final(d) for d in datas.values()) else weeks[-1]
    views = {w: week_view(datas[w], lg, board, frame, to_school, espn, teams) for w in weeks}

    built = datetime.now(LEAGUE_TZ).strftime("%b %-d, %-I:%M %p %Z")
    return (
        ui.CSS
        + f'<p><a href="{lg["url"]}"><strong>{lg["name"]}</strong></a> — every '
        "matchup with both rosters in full, live while games are on.</p>"
        "<details class='section'><summary>How to read this page</summary>"
        "<p><b>GS Proj</b> is this site's own "
        "projection for the week: each player's season projection spread over "
        "his school's games, tilted by what the game model expects of this "
        "week's game, and zero on a bye. <b>Pts</b> is the points actually scored "
        "so far, as Yahoo scores them, with the stat line behind them. Yahoo projects a team "
        "total but no player-by-player number for the college game, so the "
        "player column is ours alone; a player past the board's depth shows "
        "&mdash; there but still plays. While games are on, points, stat lines "
        "and Yahoo's win odds refresh in place about once a minute. Ahead of "
        "kickoff a roster whose bench "
        "out-projects a starter gets the swap spelled out under the table. "
        f"Rebuilt several times a day (last: {built}); finished weeks stay on "
        'record. Standings and waivers are on the <a href="/cfb/league/">league '
        'dashboard</a>, season-long roster strength on the '
        '<a href="/cfb/league-power/">power rankings</a>.</p></details>'
        + ui.week_switch(weeks, current, views) + ui.LIVE_JS)


def generate():
    write_page(OUTPUT, f"CFB League Matchups {SEASON}", body())


if __name__ == "__main__":
    generate()
