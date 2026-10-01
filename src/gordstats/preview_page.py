"""
A preview page for one game, any sport: /cfb/game/<ESPN id>/,
/nfl/game/<ESPN id>/ and /cbb/game/<theScore id>/.

The schedule pages already carry every book's line, the movement, the implied
numbers, the form and the weather for each game. What none of them has is the
matchup itself - this offence against that defence, unit by unit - so that is
what a preview is for, with our pick on top. In order:

    header      both teams (logo, rank, record), kickoff in Eastern time, TV,
                the venue or neutral site, the weather when it is outdoors
    the call    GordStats' pick, margin and win chance beside the book's line
                and total, ESPN's view, the watch score, and one sentence
                saying where the two disagree - the numbers the schedule and
                the watch guide already compute, never a second model
    units       each offence against the other defence as butterfly bars on
                national percentile, and the biggest mismatch said in words
    players     a few per team to watch, with their EPA rank
    form        the last few results, with the margin against our pre-game line
    links       both team pages, the schedule, Share

Shared the way gordstats.watch_page and gordstats.stats_page are: each
sport's adapter (cfb.site.previews, nfl.site.previews,
cbb.render.render_previews) builds its games in the one shape below, and
everything else is here once.

A game, as the adapters build it (plain text unless marked):

    sport, id, label ("Week 5"), state (pre / in / post), status (ESPN's
    detail once under way), ko (kickoff, a UTC timestamp), tk (time known),
    tv, venue, place, note (a bowl's name), neutral
    weather     {icon (HTML, the adapter's own entity), text, sub} or
                {indoors: True} or None - see weather()
    away / home {name, abbr, logo (URL), rank, record, href, score} and,
                optionally, rank_text - shown in rank's place ("5 seed")
    call        {margin (home points), prob (home win chance), total,
                 spread (the book's home line), book_total, book (its name),
                 others: [(label, value, sub)], watch, tags, call_min, edge,
                 record_url} - numbers None where there are none
    units       {"away": rows, "home": rows}: the side named is the offence,
                rows from pair_units()
    style       {"away": text, "home": text}: tempo and pass lean, uncoloured
    players     {"away": [{pos, name, stat, rank}], "home": [...]}
    form        {"away": [{r, score, at, opp, vs_line}], "home": [...]}
    words       {"off": "offence", "def": "defence"} - each sport spells them
                as its stats page does
    schedule    the schedule page's URL for the game
    links       optional, more [(label, URL)] for the row at the foot
    notes       [(term, what it means)] for the folded glossary
    source      where the unit numbers come from, one line
    stats       the sport's Team Stats URL, linked under the units

    write(game, title, ...)  the page, under docs/<sport>/game/<id>/
    prune(sport, keep)       remove pages this generator wrote for other games
    exists(sport, id)        whether a preview is on disk - the one test every
                             page linking to a preview asks first
    built(sport)             every id with a preview on disk, for a page that
                             draws its games in the browser
"""
from datetime import datetime
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from gordstats import paths, share_button, share_card
from gordstats.frontmatter import add_front_matter

ET = ZoneInfo("America/New_York")

# Every page this writes carries it; prune() removes only pages that do.
MARK = "data-gs-preview"

# A gap this big in national percentile is a mismatch worth saying in words
# (40 places of a 136-team FBS, 13 of the NFL's 32).
MISMATCH = 0.3


# --------------------------------------------------------------------------- #
# Where pages live
# --------------------------------------------------------------------------- #

def url(sport: str, game_id) -> str:
    return f"/{sport}/game/{game_id}/"


def out_dir(sport: str, root: Path = None) -> Path:
    return (root or paths.DOCS) / sport / "game"


def exists(sport: str, game_id, root: Path = None) -> bool:
    """A preview is on disk for this game. The pages that link here ask this
    rather than assume, so a game that failed to build, or one outside the
    window, is never a dead link."""
    if game_id is None or str(game_id) in ("", "nan", "None"):
        return False
    return (out_dir(sport, root) / str(game_id) / "index.html").exists()


def href(sport: str, game_id, root: Path = None) -> str | None:
    """The preview's URL when it exists, else None."""
    return url(sport, game_id) if exists(sport, game_id, root) else None


def built(sport: str, root: Path = None) -> list:
    """Every game id with a preview on disk, for a page that draws its games
    in the browser and so cannot ask exists() one game at a time (the CBB
    watch guide reads the live scoreboard)."""
    base = out_dir(sport, root)
    if not base.is_dir():
        return []
    return sorted(d.name for d in base.iterdir() if d.is_dir() and exists(sport, d.name, root))


# --------------------------------------------------------------------------- #
# Numbers
# --------------------------------------------------------------------------- #

def _v(x):
    """A float, or None where a feed or pandas left a hole."""
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(f) else f


def ordinal(n) -> str:
    n = int(n)
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def possessive(name: str) -> str:
    if name.endswith(("'s", "\u2019s")):        # St. John's, Saint Mary's: already one
        return name
    return f"{name}'" if name.endswith("s") else f"{name}'s"


def percentile(rank, of) -> float:
    """1 for the best, 0 for the worst."""
    return 0.5 if not of or of <= 1 else 1 - (int(rank) - 1) / (int(of) - 1)


def fmt(value, kind: str) -> str:
    """A figure as a row shows it - shorter than the stats table's, for a phone."""
    v = _v(value)
    if v is None:
        return "&mdash;"
    if kind == "pct":
        return f"{v * 100:.0f}%"
    if kind == "epa":
        return f"{0.0 if round(v, 2) == 0 else v:+.2f}"
    if kind == "pct1":                          # basketball's shares differ in tenths
        return f"{v * 100:.1f}%"
    if kind == "num2":
        return f"{v:.2f}"
    return f"{v:.1f}"


def rank_table(rows: list, better: dict, id_key: str = "id") -> dict:
    """{team id: {key: (value, rank, of)}} for every key in `better`
    ({key: "high" | "low"}), 1 the best; teams without a figure are left out
    of that key's ranking rather than ranked last."""
    out = {}
    for key, way in better.items():
        have = [r for r in rows if _v(r.get(key)) is not None and r.get(id_key) is not None]
        have.sort(key=lambda r: float(r[key]), reverse=way == "high")
        for i, r in enumerate(have, 1):
            out.setdefault(str(r[id_key]), {})[key] = (float(r[key]), i, len(have))
    return out


def pair_units(specs: list, off: dict, dfn: dict) -> list:
    """One offence against one defence: a row per spec where both sides have
    a figure. `specs` are {label, off, def, fmt, off_phrase, def_phrase};
    `off` and `dfn` the two teams' rank_table() entries."""
    rows = []
    for s in specs:
        a, b = (off or {}).get(s["off"]), (dfn or {}).get(s["def"])
        if a is None or b is None:
            continue
        rows.append({"label": s["label"], "fmt": s.get("fmt", "num2"), "off": a, "def": b,
                     "off_phrase": s.get("off_phrase"), "def_phrase": s.get("def_phrase")})
    return rows


def records_going_in(games: list) -> dict:
    """{game id: (away record, home record)} before each game, from the
    season's own results: `games` are dicts with game_id, date, home_id,
    away_id, home_score, away_score and played (a real final). A record
    today would be a different number on last week's preview."""
    wins, losses, ties = {}, {}, {}

    def say(team) -> str:
        w, l, t = wins.get(team, 0), losses.get(team, 0), ties.get(team, 0)
        return f"{w}-{l}" + (f"-{t}" if t else "")

    out = {}
    for g in sorted(games, key=lambda g: pd.Timestamp(g["date"])):
        home, away = str(g["home_id"]), str(g["away_id"])
        out[str(g["game_id"])] = (say(away), say(home))
        if not g.get("played"):
            continue
        margin = float(g["home_score"]) - float(g["away_score"])
        if margin == 0:
            ties[home], ties[away] = ties.get(home, 0) + 1, ties.get(away, 0) + 1
        else:
            win, lose = (home, away) if margin > 0 else (away, home)
            wins[win] = wins.get(win, 0) + 1
            losses[lose] = losses.get(lose, 0) + 1
    return out


def recent_form(games: list, team_id, before, n: int = 4) -> list:
    """The last `n` finished games of one team before `before`, newest first,
    in the form rows' shape. `games` are dicts with date, home_id, away_id,
    home, away, home_score, away_score, played and pred_margin (our home
    margin on record before kickoff, or None)."""
    team_id = str(team_id)
    before = pd.Timestamp(before)
    mine = [g for g in games if g.get("played") and pd.Timestamp(g["date"]) < before
            and team_id in (str(g["home_id"]), str(g["away_id"]))]
    mine.sort(key=lambda g: pd.Timestamp(g["date"]), reverse=True)
    out = []
    for g in mine[:n]:
        home = str(g["home_id"]) == team_id
        pf, pa = ((g["home_score"], g["away_score"]) if home else (g["away_score"], g["home_score"]))
        pf, pa = int(pf), int(pa)
        line = _v(g.get("pred_margin"))
        if line is not None and not home:
            line = -line
        out.append({"r": "W" if pf > pa else ("L" if pf < pa else "T"), "score": f"{pf}-{pa}",
                    "at": "vs" if home or g.get("neutral") else "at",
                    "opp": str(g["away"] if home else g["home"]),
                    "vs_line": None if line is None else (pf - pa) - line})
    return out


def weather(wx: dict | None, icon: str = "", text: str = "") -> dict | None:
    """The forecast line out of a feed's block ({temp, precip (chance of rain,
    %), wind, gust, indoors}); `icon` is the adapter's entity for the
    conditions and `text` their name. None when there is nothing to say."""
    if not wx:
        return None
    if wx.get("indoors"):
        return {"indoors": True}
    main = []
    temp = _v(wx.get("temp"))
    if temp is not None:
        main.append(f"{temp:.0f}°")
    if text:
        main.append(text)
    sub = []
    rain = _v(wx.get("precip"))
    if rain is not None and rain > 0:
        sub.append(f"rain {rain:.0f}%")
    wind, gust = _v(wx.get("wind")), _v(wx.get("gust"))
    if wind is not None and wind >= 10:
        sub.append(f"wind {wind:.0f} mph")
    elif gust is not None and gust >= 10:
        sub.append(f"gusts {gust:.0f} mph")
    if not main and not sub:
        return None
    return {"icon": icon, "text": " ".join(main), "sub": " · ".join(sub)}


# --------------------------------------------------------------------------- #
# The page, part by part
# --------------------------------------------------------------------------- #

def _n(v) -> str:
    """A line as a book writes it: 3, 3.5 - never 3.0."""
    return f"{v:.0f}" if float(v) == int(v) else f"{v:.1f}"


def _by(v) -> str:
    """A margin to read aloud, to the tenth the schedule cards show: 4.1, 7, 12.5."""
    return f"{abs(float(v)):.1f}".removesuffix(".0")


def _signed(v) -> str:
    v = round(float(v) * 2) / 2
    return "pk" if abs(v) < 0.25 else ("+" if v > 0 else "-") + _n(abs(v))


def _kick(game) -> str:
    ko = game.get("ko")
    if ko is None:
        return ""
    t = pd.Timestamp(ko)
    t = (t.tz_localize("UTC") if t.tzinfo is None else t).tz_convert(ET)
    day = f"{t:%a, %b %-d}"
    return f"{day} &middot; {t:%-I:%M %p} ET" if game.get("tk", True) else f"{day} &middot; time TBA"


def _team(game, side: str) -> str:
    t = game[side]
    rank = t.get("rank")
    # `rank_text` stands in for "#5" where the number is something else - a
    # tournament seed ("5 seed").
    mark = escape(t["rank_text"]) if t.get("rank_text") else (f"#{int(rank)}" if rank else "")
    logo = (f"<img src='{escape(t['logo'], quote=True)}' alt='' width='56' height='56' "
            "loading='lazy' decoding='async'>" if t.get("logo") else "<span class='pv-nologo'></span>")
    name = (f"<span class='pv-nm'>{f'<span class=pv-rk>{mark}</span> ' if mark else ''}"
            f"{escape(t['name'])}</span>")
    rec = f"<span class='pv-rec'>{escape(t['record'])}</span>" if t.get("record") else ""
    inner = logo + name + rec
    if t.get("href"):
        return f"<a class='pv-team' href='{escape(t['href'], quote=True)}'>{inner}</a>"
    return f"<div class='pv-team'>{inner}</div>"


def header(game) -> str:
    away, home = game["away"], game["home"]
    state = game.get("state") or "pre"
    scored = state in ("in", "post") and _v(away.get("score")) is not None \
        and _v(home.get("score")) is not None
    if scored:
        status = escape(game.get("status") or ("Final" if state == "post" else "Live"))
        mid = (f"<div class='pv-mid pv-score'><b>{int(away['score'])}</b>"
               f"<span>&ndash;</span><b>{int(home['score'])}</b>"
               f"<small class='{'pv-live' if state == 'in' else ''}'>{status}</small></div>")
    else:
        mid = f"<div class='pv-mid'><span>{'vs' if game.get('neutral') else 'at'}</span></div>"
    when = [x for x in (_kick(game), escape(game.get("tv") or "")) if x]
    venue, place = game.get("venue") or "", game.get("place") or ""
    if place and place in venue:                # "Memorial Stadium (Bloomington, IN)"
        place = ""
    where = [escape(x) for x in (game.get("note"), venue, place) if x]
    if game.get("neutral") and where and not game.get("note"):
        where.insert(0, "Neutral site")
    wx = game.get("weather")
    wx_line = ""
    if wx and wx.get("indoors"):
        wx_line = "<p class='pv-wx'>Indoors</p>"
    elif wx:
        wx_line = (f"<p class='pv-wx'>{wx.get('icon') or ''} {escape(wx.get('text') or '')}"
                   + (f" <span>&middot; {escape(wx['sub'])}</span>" if wx.get("sub") else "")
                   + "</p>")
    return ("<div class='pv-head'>" + _team(game, "away") + mid + _team(game, "home") + "</div>"
            + (f"<p class='pv-when'>{' &middot; '.join(when)}</p>" if when else "")
            + (f"<p class='pv-where'>{' &middot; '.join(where)}</p>" if where else "")
            + wx_line)


def _mark(ok) -> str:
    """A tick, a cross or a push once the game is over; nothing before."""
    if ok is None:
        return "<span class='pv-mk push'>push</span>"
    return (f"<span class='pv-mk {'ok' if ok else 'no'}'>"
            f"{'&#10003;' if ok else '&#10007;'}</span>")


def _lean_text(name: str, line: float, gap: float, call: dict) -> str:
    strong = abs(gap) >= (call.get("edge") or 3.0)
    return (f"{'a lean' if strong else 'a slight lean'} to "
            f"<b>{escape(name)} {_signed(line)}</b>")


def verdict(game) -> str:
    """One sentence: our pick against the book's, and what that adds up to.
    Past tense once the game is over, with the marks."""
    call = game.get("call") or {}
    margin = _v(call.get("margin"))
    if margin is None:
        return ""
    away, home = game["away"]["name"], game["home"]["name"]
    done = game.get("state") == "post" and _v(game["home"].get("score")) is not None \
        and _v(game["away"].get("score")) is not None
    final = (float(game["home"]["score"]) - float(game["away"]["score"])) if done else None
    verb = "had" if done else "likes"
    fav = home if margin > 0 else away
    if abs(margin) < 0.5:
        ours = f"GordStats {'had' if done else 'calls'} it a coin flip"
    else:
        ours = f"GordStats {verb} <b>{escape(fav)} by {_by(margin)}</b>"
        if done and final is not None:
            ours += _mark(None if final == 0 else (final > 0) == (margin > 0))
    spread = _v(call.get("spread"))
    if spread is None:
        prob = _v(call.get("prob"))
        chance = "" if prob is None or abs(margin) < 0.5 else \
            f", {max(prob, 1 - prob):.0%} to win"
        return f"<p class='pv-verdict'>{ours}{chance}. No book line yet.</p>"
    book_fav = home if spread < 0 else away
    if abs(spread) < 0.25:
        book = "the book calls it a pick'em"
    elif book_fav == fav and abs(margin) >= 0.5:
        book = f"the book by {_by(spread)}"
    else:
        book = f"the book {'had' if done else 'has'} {escape(book_fav)} by {_by(spread)}"
    gap = margin + spread                               # > 0: we like home more than the book
    call_min = call.get("call_min", 0.5)
    if abs(gap) >= call_min:
        lean_home = gap > 0
        line = spread if lean_home else -spread
        tail = ": " + _lean_text(home if lean_home else away, line, gap, call)
        if done and final is not None:
            cover = (final + spread) * (1 if lean_home else -1)
            tail += _mark(None if cover == 0 else cover > 0)
    else:
        tail = " &mdash; they agree, no lean"
    out = f"<p class='pv-verdict'>{ours}, {book}{tail}.</p>"
    leaned = abs(gap) >= call_min
    total, book_total = _v(call.get("total")), _v(call.get("book_total"))
    if total is not None and book_total is not None and abs(total - book_total) >= call_min:
        leaned = True
        over = total > book_total
        strong = abs(total - book_total) >= (call.get("edge") or 3.0)
        mark = ""
        if done:
            pts = float(game["home"]["score"]) + float(game["away"]["score"])
            mark = _mark(None if pts == book_total else (pts > book_total) == over)
        out += (f"<p class='pv-verdict pv-v2'>On the total, GordStats "
                f"{'said' if done else 'says'} {total:.0f} to the "
                f"book's {_n(book_total)}: {'a lean' if strong else 'a slight lean'} to the "
                f"<b>{'Over' if over else 'Under'}</b>{mark}.</p>")
    if leaned and call.get("record_url"):
        out += (f"<p class='pv-fine'>A lean is a disagreement with the book, not a tip &mdash; "
                f"<a href='{escape(call['record_url'], quote=True)}'>how ours have done</a>.</p>")
    return out


def _tile(label: str, value: str, sub: str = "", cls: str = "") -> str:
    return (f"<div class='pv-tile{(' ' + cls) if cls else ''}'><span class='pv-tl'>{label}</span>"
            f"<b>{value}</b>" + (f"<small>{sub}</small>" if sub else "") + "</div>")


def call_block(game) -> str:
    """The verdict, the win-chance bar, and a tile each for us, the book,
    the other opinions and the watch score."""
    call = game.get("call") or {}
    away, home = game["away"], game["home"]
    ab, hb = escape(away.get("abbr") or away["name"]), escape(home.get("abbr") or home["name"])
    tiles = []
    margin, prob = _v(call.get("margin")), _v(call.get("prob"))
    total = _v(call.get("total"))
    if margin is not None:
        fav = hb if margin > 0 else ab
        sub = []
        if prob is not None:
            sub.append(f"{max(prob, 1 - prob):.0%} to win")
        if total is not None:
            home_pts, away_pts = (total + margin) / 2, (total - margin) / 2
            sub.append(f"{ab} {away_pts:.0f}&ndash;{hb} {home_pts:.0f}")
        tiles.append(_tile("GordStats", "Coin flip" if abs(margin) < 0.5
                           else f"{fav} by {_by(margin)}", " &middot; ".join(sub), "pv-ours"))
    spread, book_total = _v(call.get("spread")), _v(call.get("book_total"))
    if spread is not None or book_total is not None:
        line = ("Pick'em" if spread is not None and abs(spread) < 0.25 else
                f"{hb if spread < 0 else ab} -{_n(abs(spread))}" if spread is not None else "&mdash;")
        tiles.append(_tile(escape(call.get("book") or "Book"), line,
                           f"O/U {_n(book_total)}" if book_total is not None else ""))
    for label, value, sub in call.get("others") or []:
        tiles.append(_tile(escape(label), escape(value), escape(sub or "")))
    watch = _v(call.get("watch"))
    if watch is not None:
        tags = call.get("tags") or []
        tiles.append(_tile("Watch score", f"{min(100, round(watch))}",
                           " &middot; ".join(escape(t) for t in tags), "pv-watch"))
    bar = ""
    if prob is not None:
        # The figures sit above the bar, not in it: a 97% favourite leaves
        # the other side a sliver no label fits in.
        fa, fh = ("", " fav") if prob >= 0.5 else (" fav", "")
        bar = (f"<div class='pv-wpl'><span class='{fa.strip()}'>{ab} {1 - prob:.0%}</span>"
               f"<span>win chance</span><span class='{fh.strip()}'>{hb} {prob:.0%}</span></div>"
               f"<div class='pv-wp' role='img' aria-label='GordStats win chance: {ab} "
               f"{1 - prob:.0%}, {hb} {prob:.0%}'><span class='pv-wpa{fa}' style='width:"
               f"{(1 - prob) * 100:.1f}%'></span><span class='pv-wph{fh}'></span></div>")
    if not tiles and not bar:
        return ""
    return ("<section class='pv-sec pv-call'><h2>The call</h2>" + verdict(game) + bar
            + f"<div class='pv-tiles'>{''.join(tiles)}</div></section>")


def _side_rank(cell, cls: str, kind: str) -> str:
    """A side's national rank, its figure under it."""
    value, rank, of = cell
    return (f"<span class='pv-rr {cls}' title='{ordinal(rank)} of {of}'>"
            f"<b>{ordinal(rank)}</b><small>{fmt(value, kind)}</small></span>")


def unit_rows(rows: list) -> str:
    out = []
    for r in rows:
        po, pd_ = percentile(*r["off"][1:]), percentile(*r["def"][1:])
        edge = po - pd_
        oc = "win" if edge > 0.05 else ("even" if edge > -0.05 else "lose")
        dc = "win" if edge < -0.05 else ("even" if edge < 0.05 else "lose")
        out.append(
            "<div class='pv-ur'>"
            f"<div class='pv-ul'>{escape(r['label'])}</div>"
            + _side_rank(r["off"], "o", r["fmt"])
            + f"<span class='pv-bl'><i class='o {oc}' style='width:{max(po, 0.03) * 100:.0f}%'></i></span>"
            + f"<span class='pv-br'><i class='d {dc}' style='width:{max(pd_, 0.03) * 100:.0f}%'></i></span>"
            + _side_rank(r["def"], "d", r["fmt"]) + "</div>")
    return "".join(out)


def mismatches(game) -> list:
    """The biggest edge on each side of the ball, worded, biggest first:
    [(size, html)] - only where it is a mismatch (MISMATCH)."""
    found = []
    for off_side, def_side in (("away", "home"), ("home", "away")):
        best = None
        for r in (game.get("units") or {}).get(off_side) or []:
            if not r.get("off_phrase") or not r.get("def_phrase"):
                continue
            edge = percentile(*r["off"][1:]) - percentile(*r["def"][1:])
            if best is None or abs(edge) > abs(best[0]):
                best = (edge, r)
        if best is None or abs(best[0]) < MISMATCH:
            continue
        edge, r = best
        o, d = game[off_side]["name"], game[def_side]["name"]
        off_txt = f"{escape(possessive(o))} {escape(r['off_phrase'])} ({ordinal(r['off'][1])})"
        def_txt = f"{escape(possessive(d))} {escape(r['def_phrase'])} ({ordinal(r['def'][1])})"
        text = (f"<b>{off_txt}</b> meets {def_txt}." if edge > 0 else
                f"<b>{def_txt}</b> meets {off_txt}.")
        found.append((abs(edge), text))
    return sorted(found, key=lambda x: -x[0])


def units_block(game) -> str:
    units = game.get("units") or {}
    if not units.get("away") and not units.get("home"):
        return ""
    words = game.get("words") or {"off": "offence", "def": "defence"}
    said = mismatches(game)
    lead = ("<ul class='pv-mm'>" + "".join(f"<li>{t}</li>" for _s, t in said) + "</ul>" if said
            else "<p class='pv-note'>No unit has a big edge over the one it faces.</p>")
    parts = []
    for off_side, def_side in (("away", "home"), ("home", "away")):
        rows = units.get(off_side) or []
        if not rows:
            continue
        o, d = game[off_side], game[def_side]
        oname, dname = escape(o.get("abbr") or o["name"]), escape(d.get("abbr") or d["name"])
        style = (game.get("style") or {}).get(off_side)
        parts.append(
            "<div class='pv-unit'>"
            f"<h3>{escape(o['name'])} {words['off']} <span>vs</span> {escape(d['name'])} "
            f"{words['def']}</h3>"
            f"<div class='pv-uh'><span class='o'>{oname} {words['off'][:3]}</span>"
            f"<span class='d'>{dname} {words['def'][:3]}</span></div>"
            + unit_rows(rows)
            + (f"<p class='pv-style'>{escape(o['name'])}: {escape(style)}</p>" if style else "")
            + "</div>")
    source = escape(game.get("source") or "")
    if game.get("stats"):
        source += (f" Every team: <a href='{escape(game['stats'], quote=True)}'>Team Stats</a>.")
    return ("<section class='pv-sec'><h2>Unit vs unit</h2>" + lead
            + "<p class='pv-note'>National rank on each side, 1st the best; the longer bar has the "
            "edge.</p>" + "".join(parts)
            + (f"<p class='pv-fine'>{source.strip()}</p>" if source else "") + "</section>")


def players_block(game) -> str:
    players = game.get("players") or {}
    cols = []
    for side in ("away", "home"):
        rows = players.get(side) or []
        if not rows:
            continue
        items = "".join(
            f"<li><span class='pv-pos'>{escape(p.get('pos') or '')}</span>"
            f"<span class='pv-pn'>{escape(p['name'])}</span>"
            f"<small>{escape(p.get('stat') or '')}"
            + (f" &middot; <b>{escape(p['rank'])}</b>" if p.get("rank") else "")
            + "</small></li>" for p in rows)
        cols.append(f"<div class='pv-col'><h3>{escape(game[side]['name'])}</h3>"
                    f"<ul class='pv-pl'>{items}</ul></div>")
    if not cols:
        return ""
    return ("<section class='pv-sec'><h2>Players to watch</h2>"
            f"<div class='pv-cols'>{''.join(cols)}</div></section>")


def form_block(game) -> str:
    form = game.get("form") or {}
    cols = []
    any_line = any(f.get("vs_line") is not None for side in ("away", "home")
                   for f in form.get(side) or [])
    for side in ("away", "home"):
        rows = form.get(side) or []
        if not rows:
            continue
        items = []
        for f in rows:
            line = f.get("vs_line")
            vs = ""
            if any_line:
                vs = ("<span class='pv-vl'>&mdash;</span>" if line is None else
                      f"<span class='pv-vl {'up' if line >= 0.5 else ('down' if line <= -0.5 else '')}'>"
                      f"{'+' if round(line) > 0 else ('&minus;' if round(line) < 0 else '')}"
                      f"{abs(round(line))}</span>")
            items.append(f"<li><span class='pv-r {escape(f['r']).lower()}'>{escape(f['r'])}</span>"
                         f"<span class='pv-fs'>{escape(f['score'])}</span>"
                         f"<span class='pv-fo'>{escape(f['at'])} {escape(f['opp'])}</span>{vs}</li>")
        cols.append(f"<div class='pv-col'><h3>{escape(game[side]['name'])}</h3>"
                    f"<ul class='pv-fl'>{''.join(items)}</ul></div>")
    if not cols:
        return ""
    note = ("<p class='pv-note'>The last column is the margin against our line before "
            "kickoff: + beat it, &minus; fell short.</p>" if any_line else "")
    return ("<section class='pv-sec'><h2>Recent form</h2>"
            f"<div class='pv-cols'>{''.join(cols)}</div>{note}</section>")


def links_block(game, title: str) -> str:
    links = [(game[side]["name"], game[side]["href"]) for side in ("away", "home")
             if game[side].get("href")]
    if game.get("schedule"):
        links.append(("Schedule", game["schedule"]))
    links += list(game.get("links") or [])      # a sport's own: [(label, URL)]
    row ="".join(f"<a href='{escape(h, quote=True)}'>{escape(n)} &rarr;</a>" for n, h in links)
    notes = game.get("notes") or []
    gloss = ("<details class='pv-gloss'><summary>What these numbers mean</summary><dl>"
             + "".join(f"<dt>{escape(t)}</dt><dd>{escape(d)}</dd>" for t, d in notes)
             + "</dl></details>") if notes else ""
    return ((f"<nav class='pv-links'>{row}</nav>" if row else "") + gloss
            + share_button.row(url(game["sport"], game["id"]), title))


def body(game, title: str = "") -> str:
    """The page body for one game."""
    title = title or f"{game['away']['name']} {'vs' if game.get('neutral') else 'at'} " \
        f"{game['home']['name']}"
    return (CSS + f"<div class='pv' {MARK}='{escape(str(game['id']), quote=True)}'>"
            + header(game) + call_block(game) + units_block(game) + players_block(game)
            + form_block(game) + links_block(game, title) + "</div>")


def title(game) -> str:
    """"Texas at Georgia", or "vs" on a neutral field - plain text."""
    return (f"{game['away']['name']} {'vs' if game.get('neutral') else 'at'} "
            f"{game['home']['name']}")


SPORT_NAMES = {"cfb": "College football", "nfl": "NFL", "cbb": "College basketball"}


def _card_slug(sport: str, game_id) -> str:
    return f"{sport}-game-{game_id}"


def _cards_here(root: Path = None) -> bool:
    """Whether pages written under `root` (or the site's docs) are the site's
    own, the place share_card keeps its images - not a test's temp folder."""
    try:
        return share_card.OUT_DIR.resolve().is_relative_to(Path(root or paths.DOCS).resolve())
    except (OSError, ValueError):
        return False


def card(game) -> dict | None:
    """The link preview a chat shows for this game (gordstats.share_card):
    the matchup and kickoff, our call, the book's, and the lean if there is
    one - or the final score once it is over."""
    call = game.get("call") or {}
    away, home = game["away"]["name"], game["home"]["name"]
    rows = []
    if game.get("state") == "post" and _v(game["home"].get("score")) is not None \
            and _v(game["away"].get("score")) is not None:
        hs, as_ = float(game["home"]["score"]), float(game["away"]["score"])
        win, lose = (home, away) if hs >= as_ else (away, home)
        rows.append(("Final", f"{win} {_n(max(hs, as_))}, {lose} {_n(min(hs, as_))}", ""))
    margin, prob = _v(call.get("margin")), _v(call.get("prob"))
    if margin is not None:
        pick = "Coin flip" if abs(margin) < 0.5 else \
            f"{home if margin > 0 else away} by {_by(margin)}"
        rows.append(("GS", pick, "" if prob is None else f"{max(prob, 1 - prob):.0%}"))
    spread, book_total = _v(call.get("spread")), _v(call.get("book_total"))
    if spread is not None:
        book = "Pick'em" if abs(spread) < 0.25 else \
            f"{home if spread < 0 else away} -{_n(abs(spread))}"
        rows.append(("Line", book, "" if book_total is None else f"O/U {_n(book_total)}"))
        gap = None if margin is None else margin + spread
        if gap is not None and abs(gap) >= call.get("call_min", 0.5):
            lean_home = gap > 0
            strong = abs(gap) >= (call.get("edge") or 3.0)
            rows.append(("Lean", f"{home if lean_home else away} "
                                 f"{_signed(spread if lean_home else -spread)}",
                         "" if strong else "slight"))
    sub = _kick(game).replace("&middot;", "·")
    if game.get("tv"):
        sub += f" · {game['tv']}"
    kicker = SPORT_NAMES.get(game["sport"], game["sport"].upper())
    if game.get("label"):
        kicker += f" · {game['label']}"
    return share_card.ranked(_card_slug(game["sport"], game["id"]), kicker,
                             f"{away} {'v' if game.get('neutral') else 'at'} {home}", sub,
                             rows, alt=f"{away} at {home}: GordStats' call")


def write(game, subtitle: str = "", description: str = "", root: Path = None,
          updated: datetime | bool = True) -> Path:
    """Write one game's page; returns its path. The link-preview card is
    drawn only for the site's own docs (_cards_here)."""
    name = title(game)
    path = out_dir(game["sport"], root) / str(game["id"]) / "index.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    image = card(game) if _cards_here(root) else None
    path.write_text(add_front_matter(body(game, name), escape(name), subtitle or None,
                                     description=description or None, updated=updated,
                                     image=image),
                    encoding="utf-8")
    return path


def prune(sport: str, keep: set, root: Path = None) -> list:
    """Remove the previews of games no longer in the window: only directories
    named for a game id, holding nothing but an index.html this module wrote
    (it carries MARK). Anything else under docs/<sport>/game/ is left alone."""
    base = out_dir(sport, root)
    if not base.is_dir():
        return []
    keep = {str(k) for k in keep}
    removed = []
    for d in sorted(base.iterdir()):
        if not d.is_dir() or not d.name.isdigit() or d.name in keep:
            continue
        files = list(d.iterdir())
        page = d / "index.html"
        if len(files) != 1 or files[0] != page:
            continue
        try:
            if MARK not in page.read_text(encoding="utf-8"):
                continue
        except OSError:
            continue
        page.unlink()
        d.rmdir()
        removed.append(d.name)
        if _cards_here(root):
            # Its link-preview card goes with it (share_card names them
            # <slug>-<10-char hash>.png), or a season would pile them up.
            slug = _card_slug(sport, d.name)
            for old in share_card.OUT_DIR.glob(f"{slug}-*.png"):
                if len(old.stem) == len(slug) + 11:
                    old.unlink()
    return removed


CSS = """<style>
.pv{--pv-line:#e2e8f0;--pv-card:#fff;--pv-ink:#0f172a;--pv-mute:#475569;--pv-soft:#5d6b7e;
  --pv-acc:#C2410C;--pv-track:#eef2f7;--pv-o:#2563eb;--pv-d:#c2410c;--pv-good:#15803d;
  --pv-bad:#b91c1c;--pv-chip:#eef2f7;--pv-live:#b3382c}
@media (prefers-color-scheme: dark){
  .pv{--pv-line:#2b3852;--pv-card:#16203a;--pv-ink:#f1f5f9;--pv-mute:#c3cfdd;--pv-soft:#aab7c9;
    --pv-acc:#fb923c;--pv-track:#223052;--pv-o:#60a5fa;--pv-d:#fb923c;--pv-good:#4ade80;
    --pv-bad:#f87171;--pv-chip:#223052;--pv-live:#ffb4ab}
}
.pv{color:var(--pv-ink);max-width:760px}
.pv b{font-weight:700}
.pv img{border:0;padding:0;margin:0;box-shadow:none;background:none;border-radius:0}
.pv-head{display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);align-items:start;
  gap:8px;margin:4px 0 8px}
.pv-team{display:flex;flex-direction:column;align-items:center;text-align:center;gap:3px;
  color:inherit;text-decoration:none;min-width:0}
a.pv-team:hover .pv-nm{text-decoration:underline}
.pv-team img,.pv-nologo{width:56px;height:56px;object-fit:contain;display:block}
.pv-nm{font-size:17px;font-weight:800;line-height:1.25;overflow-wrap:anywhere}
.pv-rk{font-size:12px;font-weight:700;color:var(--pv-soft)}
.pv-rec{font-size:13px;color:var(--pv-soft);font-variant-numeric:tabular-nums}
.pv-mid{align-self:center;display:flex;flex-direction:column;align-items:center;
  font-size:15px;font-weight:700;color:var(--pv-soft);padding-top:4px}
.pv-score{flex-direction:row;flex-wrap:wrap;justify-content:center;gap:2px 6px;
  color:var(--pv-ink);max-width:120px}
.pv-score b{font-size:28px;font-variant-numeric:tabular-nums}
.pv-score small{flex-basis:100%;text-align:center;font-size:12px;color:var(--pv-soft)}
.pv-score small.pv-live{color:var(--pv-live)}
.pv-when,.pv-where,.pv-wx{text-align:center;margin:2px 0;font-size:14px;color:var(--pv-mute)}
.pv-when{font-weight:700;color:var(--pv-ink)}
.pv-wx span{color:var(--pv-soft)}
.pv-sec{margin:22px 0 0}
.pv h2{font-size:19px;margin:0 0 8px}
.pv h3{font-size:14px;margin:14px 0 6px;color:var(--pv-ink)}
.pv-verdict{font-size:16px;line-height:1.5;margin:0 0 8px}
.pv-v2{font-size:15px}
.pv-fine{font-size:12.5px;color:var(--pv-soft);margin:4px 0 8px;line-height:1.45}
.pv-note{font-size:13px;color:var(--pv-mute);margin:4px 0 8px;line-height:1.45}
.pv-mk{display:inline-block;margin-left:5px;font-size:12px;font-weight:800;padding:0 6px;
  border-radius:999px;background:var(--pv-chip);color:var(--pv-mute);vertical-align:1px}
.pv-mk.ok{background:#dcfce7;color:#166534}.pv-mk.no{background:#fee2e2;color:#991b1b}
.pv-wpl{display:flex;justify-content:space-between;align-items:baseline;gap:8px;margin:8px 0 3px;
  font-size:13px;color:var(--pv-mute);font-variant-numeric:tabular-nums}
.pv-wpl span:nth-child(2){font-size:11.5px;color:var(--pv-soft)}
.pv-wpl .fav{font-weight:800;color:var(--pv-ink)}
.pv-wp{display:flex;height:12px;border-radius:6px;overflow:hidden;margin:0 0 10px;
  background:var(--pv-track)}
.pv-wp span{display:block;height:100%}
.pv-wph{flex:1}
.pv-wp .fav{background:var(--pv-acc)}
.pv-tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px}
.pv-tile{border:1px solid var(--pv-line);border-radius:10px;padding:8px 10px;
  background:var(--pv-card);min-width:0}
.pv-tile.pv-ours{border-left:4px solid var(--pv-acc)}
.pv-tl{display:block;font-size:12px;font-weight:700;color:var(--pv-soft)}
.pv-tile b{display:block;font-size:17px;line-height:1.3}
.pv-tile small{display:block;font-size:12.5px;color:var(--pv-mute);line-height:1.4}
.pv-mm{margin:0 0 6px;padding-left:18px;font-size:15px;line-height:1.5}
.pv-mm li{margin:2px 0}
.pv-unit{border:1px solid var(--pv-line);border-radius:12px;background:var(--pv-card);
  padding:4px 10px 8px;margin:10px 0}
.pv-unit h3{margin:8px 0 4px}
.pv-unit h3 span{font-weight:500;color:var(--pv-soft)}
.pv-uh{display:flex;justify-content:space-between;font-size:11.5px;font-weight:800;
  text-transform:uppercase;letter-spacing:.04em;margin:2px 0 2px}
.pv-uh .o{color:var(--pv-o)}.pv-uh .d{color:var(--pv-d)}
.pv-ur{display:grid;grid-template-columns:46px minmax(0,1fr) minmax(0,1fr) 46px;
  align-items:center;column-gap:4px;padding:2px 0 4px}
.pv-ul{grid-column:1 / -1;text-align:center;font-size:12.5px;font-weight:700;
  color:var(--pv-mute);line-height:1.3}
.pv-rr{font-size:13.5px;font-variant-numeric:tabular-nums;white-space:nowrap;line-height:1.15}
.pv-rr small{display:block;font-size:11.5px;color:var(--pv-soft)}
.pv-rr.o{text-align:left}.pv-rr.d{text-align:right}
.pv-bl,.pv-br{display:flex;height:10px;background:var(--pv-track)}
.pv-bl{justify-content:flex-end;border-radius:5px 0 0 5px;margin-right:1px}
.pv-br{justify-content:flex-start;border-radius:0 5px 5px 0}
.pv-bl i,.pv-br i{display:block;height:100%}
.pv-bl i{border-radius:5px 0 0 5px}.pv-br i{border-radius:0 5px 5px 0}
.pv-ur i.o{background:var(--pv-o)}.pv-ur i.d{background:var(--pv-d)}
.pv-ur i.lose{opacity:.3}.pv-ur i.even{opacity:.65}
.pv-style{font-size:12.5px;color:var(--pv-soft);margin:6px 0 0}
.pv-cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:4px 16px}
.pv-col h3{margin:8px 0 4px}
.pv-pl,.pv-fl{list-style:none;margin:0;padding:0}
.pv-pl li{display:grid;grid-template-columns:34px minmax(0,1fr);column-gap:6px;padding:6px 0;
  border-top:1px solid var(--pv-line)}
.pv-pl li:first-child,.pv-fl li:first-child{border-top:0}
.pv-pos{grid-row:1 / span 2;align-self:start;font-size:11.5px;font-weight:800;text-align:center;
  padding:2px 0;border-radius:6px;background:var(--pv-chip);color:var(--pv-mute)}
.pv-pn{font-weight:700;font-size:15px;overflow-wrap:anywhere}
.pv-pl small{grid-column:2;font-size:12.5px;color:var(--pv-mute);line-height:1.4}
.pv-fl li{display:grid;grid-template-columns:24px 56px minmax(0,1fr) 40px;align-items:center;
  column-gap:6px;padding:5px 0;border-top:1px solid var(--pv-line);font-size:14px}
.pv-r{font-size:12px;font-weight:800;text-align:center;border-radius:5px;padding:1px 0;
  background:var(--pv-chip);color:var(--pv-mute)}
.pv-r.w{background:#dcfce7;color:#166534}.pv-r.l{background:#fee2e2;color:#991b1b}
.pv-fs{font-variant-numeric:tabular-nums;font-weight:600}
.pv-fo{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--pv-mute)}
.pv-vl{text-align:right;font-variant-numeric:tabular-nums;font-weight:700;color:var(--pv-soft)}
.pv-vl.up{color:var(--pv-good)}.pv-vl.down{color:var(--pv-bad)}
.pv-links{display:flex;flex-wrap:wrap;gap:8px;margin:24px 0 8px}
.pv-links a{display:inline-flex;align-items:center;min-height:40px;padding:0 14px;
  border:1px solid var(--pv-line);border-radius:999px;background:var(--pv-card);
  color:var(--pv-ink);font-weight:700;font-size:14px;text-decoration:none}
.pv-gloss{margin:8px 0}
.pv-gloss summary{cursor:pointer;font-size:13px;color:var(--pv-soft);min-height:36px;
  display:flex;align-items:center}
.pv-gloss dt{font-weight:700;font-size:13px;margin-top:6px}
.pv-gloss dd{margin:0;font-size:13px;color:var(--pv-mute);line-height:1.45}
@media (prefers-color-scheme: dark){
  .pv-team img{background:#e8edf5;border-radius:50%;padding:4px;box-sizing:border-box}
  .pv-mk.ok,.pv-r.w{background:#14532d;color:#bbf7d0}
  .pv-mk.no,.pv-r.l{background:#7f1d1d;color:#fecaca}
}
</style>"""
