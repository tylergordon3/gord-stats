"""
NFL Schedule & Scores (/nfl/schedule/): every game of the season a week at a
time, the week being played open - the twin of /cfb/schedule/, kept to what a
phone needs.

Each game is one card: both teams with their records going in, the kickoff in
the reader's own time and the network, our pick (the winner, by how much, and
how likely) beside the book's spread and total, and once it is over the score
with a tick or a cross on our winner and, where we leaned against the book,
on the spread. A lean is what the predictions page calls one - our number a
field goal or more off the book's - so the ticks here add up to its record.

What a finished game is graded on is the prediction on record before kickoff
(nfl.results.on_record), never a refit that knows the score; a game before
the archive began says so rather than borrowing one.

It is the scoreboard too. The page is rebuilt with the section; while a game
on the week on screen is on, the browser reads ESPN's NFL scoreboard (it
answers any origin) once a minute and moves the scores, the clock and, at the
final whistle, the ticks. It stops when the week's games are over and pauses
while the tab is hidden.

    python -m nfl.site.schedule
"""
from html import escape

import pandas as pd

from gordstats import logos, preview_page
from gordstats import matchup_page as ui
from gordstats.frontmatter import add_front_matter
from nfl import games as games_mod, predict, results
from nfl.config import SEASON, TZ, WEB_DIR
from nfl.site.predictions import EDGE

OUT = WEB_DIR / "schedule" / "index.html"
# The playoff rounds by ESPN's postseason week: the Super Bowl is 5 to 2025
# (4 was the Pro Bowl, never fetched) and 4 from 2026 (nfl.games).
ROUNDS = games_mod.ROUND_NAMES
REGULAR_WEEKS = 18


def week_key(week: int, seasontype: int) -> int:
    """One number per week of the season, the playoffs after the regular
    season (the Wild Card round is 19, the 2026 Super Bowl 22) - the
    predictions page's week keys, so a #wk-19 means the same round on both
    pages."""
    return int(week) + (REGULAR_WEEKS if int(seasontype) == 3 else 0)


def week_label(key: int) -> str:
    key = int(key)
    if key > REGULAR_WEEKS:
        return ROUNDS.get(key - REGULAR_WEEKS, f"Playoffs {key - REGULAR_WEEKS}")
    return f"Week {key}"


# In nfl.games now, where the predictions page and the prediction archive
# can reach them too (this module imports the predictions page).
_tbd = games_mod.tbd
_time_known = games_mod.time_known


def _num(v) -> str:
    """A line as a book writes it: 3, 3.5 - never 3.0."""
    v = float(v)
    return f"{v:.0f}" if v == int(v) else f"{v:.1f}"


def _signed(v) -> str:
    """A side's line: -3.5, +7, or pk."""
    v = float(v)
    return "pk" if abs(v) < 0.05 else ("+" if v > 0 else "-") + _num(abs(v))


def _records(frame: pd.DataFrame) -> dict:
    """{game id: (away record, home record)} going into each game, from the
    season's own results. ESPN's record on the schedule is today's, which on
    a week-2 card would be a week-10 record. The regular season's record:
    a playoff game is not counted into the next round's, as ESPN shows it."""
    wins, losses, ties = {}, {}, {}

    def say(team) -> str:
        w, l, t = wins.get(team, 0), losses.get(team, 0), ties.get(team, 0)
        return f"{w}-{l}" + (f"-{t}" if t else "")

    out = {}
    for _, g in frame.sort_values("date").iterrows():
        home, away = str(g["home_id"]), str(g["away_id"])
        out[str(g["game_id"])] = (say(away), say(home))
        if not g["played"] or int(g.get("seasontype", 2)) != 2:
            continue
        margin = g["home_score"] - g["away_score"]
        if margin == 0:
            ties[home], ties[away] = ties.get(home, 0) + 1, ties.get(away, 0) + 1
        else:
            winner, loser = (home, away) if margin > 0 else (away, home)
            wins[winner] = wins.get(winner, 0) + 1
            losses[loser] = losses.get(loser, 0) + 1
    return out


def _call(g, record: dict, now: pd.Timestamp) -> dict | None:
    """The numbers a card shows: home margin, home win chance, the book's
    home line and total. A game that has kicked off shows what was on record
    before kickoff; one still to come, today's model and today's line. None
    where there is nothing honest to show."""
    if _tbd(g):
        return None
    rec = record.get(str(g["game_id"]))
    kicked = g["date"] <= now or bool(g["played"]) or g.get("state") in ("in", "post")
    if kicked:
        if rec is None:
            return None
        src = {"margin": rec["pred_margin"], "prob": rec["home_win_prob"],
               "spread": rec["market_spread"], "total": rec["market_total"]}
    else:
        src = {"margin": g["pred_margin"], "prob": g["home_win_prob"],
               "spread": g.get("book_spread"), "total": g.get("book_total")}
    if src["margin"] is None or pd.isna(src["margin"]):
        return None
    return {k: (None if v is None or pd.isna(v) else float(v)) for k, v in src.items()}


def _lean(call: dict) -> str:
    """"home", "away" or "" - the side our number likes against the book's
    line, where the two are a lean apart."""
    if not call or call["spread"] is None:
        return ""
    edge = call["margin"] + call["spread"]            # our margin less the book's
    if abs(edge) < EDGE:
        return ""
    return "home" if edge > 0 else "away"


def _grades(g, call: dict) -> tuple:
    """(our winner, our lean against the spread) on a final: True, False,
    None for a tie or a push, "" where there was no call."""
    if not call or not g["played"]:
        return "", ""
    margin = float(g["home_score"] - g["away_score"])
    win = None if margin == 0 else (call["margin"] > 0) == (margin > 0)
    ats = ""
    lean = _lean(call)
    if lean:
        cover = margin + call["spread"]
        ats = None if cover == 0 else (lean == "home") == (cover > 0)
    return win, ats


def _mark(state, kind: str) -> str:
    """The pill after a call: filled on a final, empty (for the live script
    to fill) before one."""
    if state == "":
        return f"<span class='ns-mk' data-mk='{kind}'></span>"
    if state is None:
        return f"<span class='ns-mk push' data-mk='{kind}'>{'tie' if kind == 'win' else 'push'}</span>"
    return (f"<span class='ns-mk {'ok' if state else 'no'}' data-mk='{kind}'>"
            f"{'&#10003;' if state else '&#10007;'}</span>")


def _team(g, side: str, record: str, won: bool) -> str:
    tbd = str(g[f"{side}_id"]).startswith("-")
    logo = "" if tbd else logos.img("nfl", g[f"{side}_abbr"], 28)
    score = g[f"{side}_score"]
    pts = "" if g.get("state") == "pre" or score is None or pd.isna(score) else f"{int(score)}"
    return (f"<div class='ns-t{' ns-win' if won else ''}' data-side='{side}'>"
            f"{logo or '<span class=ns-nologo></span>'}"
            f"<span class='ns-nm'>{escape(str(g[side]))}</span>"
            + ("" if tbd or not record else f"<span class='ns-rec'>{escape(record)}</span>")
            + f"<span class='ns-pts'>{pts}</span></div>")


def _when(g) -> str:
    """The top line's left half: the status once a game has started, the
    kickoff before. The kickoff is written in Eastern time here and rewritten
    in the reader's own by the script."""
    state = g.get("state") or "pre"
    if state != "pre":
        detail = escape(str(g.get("detail") or ("Final" if state == "post" else "Live")))
        return f"<span class='ns-when{' ns-live' if state == 'in' else ''}'>{detail}</span>"
    if not _time_known(g):
        return "<span class='ns-when'>Time TBD</span>"
    kick = g["date"].tz_convert(TZ)
    return f"<span class='ns-when' data-lt='1'>{kick:%-I:%M %p} ET</span>"


def _card(g, call: dict | None, records: dict) -> str:
    gid = str(g["game_id"])
    away_rec, home_rec = records.get(gid, ("", ""))
    played = bool(g["played"])
    home_won = played and g["home_score"] > g["away_score"]
    away_won = played and g["away_score"] > g["home_score"]
    where = ""
    if g.get("neutral") and g.get("place") and not _tbd(g):
        where = f"<span class='ns-at'>{escape(str(g['place']).split(',')[0])}</span>"
    tv = escape(str(g.get("tv") or "").split(",")[0].strip())
    top = (f"<div class='ns-top'><span class='ns-l'>{_when(g)}{where}</span>"
           + (f"<span class='ns-tv'>{tv}</span>" if tv else "") + "</div>")
    teams = (_team(g, "away", away_rec, away_won) + _team(g, "home", home_rec, home_won))

    rows = []
    win, ats = _grades(g, call)
    lean = _lean(call)
    if call:
        home_fav = call["margin"] > 0
        fav = g["home"] if home_fav else g["away"]
        prob = call["prob"] if home_fav else 1 - call["prob"]
        rows.append(f"<div class='ns-c'><span class='ns-lab'>GordStats</span>"
                    f"<span class='ns-v'><b>{escape(str(fav))} by {abs(call['margin']):.1f}</b>"
                    f" &middot; {prob:.0%}</span>{_mark(win, 'win')}</div>")
        book = []
        if call["spread"] is not None:
            if abs(call["spread"]) < 0.05:
                book.append("Pick'em")
            else:
                book_fav = g["home"] if call["spread"] < 0 else g["away"]
                book.append(f"{escape(str(book_fav))} -{_num(abs(call['spread']))}")
        if call["total"] is not None:
            book.append(f"O/U {_num(call['total'])}")
        if book:
            rows.append(f"<div class='ns-c'><span class='ns-lab'>Book</span>"
                        f"<span class='ns-v'>{' &middot; '.join(book)}</span></div>")
        if lean:
            side = g[lean]
            line = call["spread"] if lean == "home" else -call["spread"]
            rows.append(f"<div class='ns-c ns-lean'><span class='ns-lab'>Lean</span>"
                        f"<span class='ns-v'><b>{escape(str(side))} {_signed(line)}</b></span>"
                        f"{_mark(ats, 'ats')}</div>")
    elif played and not _tbd(g):
        rows.append("<div class='ns-c'><span class='ns-lab'>GordStats</span>"
                    "<span class='ns-v ns-none'>No pick on record</span></div>")
    # The game's preview page (nfl.site.previews, built before this page),
    # only where one is on disk.
    preview = preview_page.href("nfl", gid)
    if preview:
        rows.append(f"<div class='ns-c ns-pv'><span class='ns-lab'>Preview</span>"
                    f"<span class='ns-v'><a href='{preview}'>Unit vs unit, players &rarr;</a>"
                    "</span></div>")

    attrs = (f" id='g-{gid}' data-state='{escape(str(g.get('state') or 'pre'))}'"
             f" data-ko='{g['date']:%Y-%m-%dT%H:%M:%SZ}' data-tk='{int(_time_known(g))}'")
    if call:
        attrs += f" data-pm='{call['margin']:.2f}'"
        if call["spread"] is not None:
            attrs += f" data-sp='{call['spread']:g}'"
        attrs += f" data-lean='{lean}'"
    calls = f"<div class='ns-calls'>{''.join(rows)}</div>" if rows else ""
    return f"<article class='ns-g'{attrs}>{top}{teams}{calls}</article>"


def _summary(block: pd.DataFrame, calls: dict) -> str:
    """The week's record in one line, once any of it is final: winners
    picked, and the leans against the spread."""
    wins = losses = ats_w = ats_l = 0
    for _, g in block.iterrows():
        win, ats = _grades(g, calls.get(str(g["game_id"])))
        if win is True:
            wins += 1
        elif win is False:
            losses += 1
        if ats is True:
            ats_w += 1
        elif ats is False:
            ats_l += 1
    if not (wins + losses):
        return ""
    out = f"Picked <b>{wins} of {wins + losses}</b> winners"
    if ats_w + ats_l:
        out += f" &middot; leans <b>{ats_w}-{ats_l}</b> against the spread"
    return f"<p class='ns-sum'>{out}</p>"


def _byes(block: pd.DataFrame, teams: dict) -> str:
    playing = set(block["home_id"].astype(str)) | set(block["away_id"].astype(str))
    off = sorted(name for tid, name in teams.items() if tid not in playing)
    if not off:
        return ""
    return f"<p class='ns-bye'><b>Bye</b> {escape(', '.join(off))}</p>"


def _week_view(key: int, block: pd.DataFrame, calls: dict, records: dict,
               teams: dict) -> str:
    """One week: its record line, then the games under a heading per day."""
    first = block.iloc[0]
    days = []
    local = block["date"].dt.tz_convert(TZ)
    for day, games in block.groupby(local.dt.date, sort=True):
        cards = "".join(_card(g, calls.get(str(g["game_id"])), records)
                        for _, g in games.sort_values(["date", "game_id"]).iterrows())
        days.append(f"<h3 class='ns-day'>{day:%A, %b %-d}</h3>"
                    f"<div class='ns-grid'>{cards}</div>")
    byes = _byes(block, teams) if key <= REGULAR_WEEKS else ""
    return (f"<div class='ns-wk' data-key='{key}' data-season='{SEASON}' "
            f"data-st='{int(first['seasontype'])}' data-wk='{int(first['week'])}'>"
            + _summary(block, calls) + "".join(days) + byes + "</div>")


def body(now: pd.Timestamp = None, frame: pd.DataFrame = None,
         record: pd.DataFrame = None) -> str:
    now = now if now is not None else pd.Timestamp.now(tz="UTC")
    if frame is None:
        frame, _model, _names = predict.season()
    if record is None:
        record = results.on_record(SEASON)
    record = {str(r["game_id"]): r for _, r in record.iterrows()}
    frame = frame.copy()
    frame["key"] = [week_key(w, s) for w, s in zip(frame["week"], frame["seasontype"])]
    records = _records(frame)
    calls = {str(g["game_id"]): _call(g, record, now) for _, g in frame.iterrows()}
    teams = {}
    for side in ("home", "away"):
        for tid, name in zip(frame[f"{side}_id"].astype(str), frame[side]):
            if not tid.startswith("-"):
                teams.setdefault(tid, str(name))

    week, seasontype = predict.current_week(frame, now)
    current = str(week_key(week, seasontype))
    views, keys = {}, []
    for key, block in frame.groupby("key", sort=True):
        keys.append(str(key))
        views[str(key)] = _week_view(int(key), block, calls, records, teams)
    switch = ui.week_switch(keys, current, views)
    for key in keys:
        if int(key) > REGULAR_WEEKS:
            switch = switch.replace(f'id="wk-tab-{key}">{key}</button>',
                                    f'id="wk-tab-{key}">{escape(week_label(key))}</button>')
    note = ("<p class='ns-note'><b>Lean</b> is where our number is a field goal or more off "
            "the book's: the side we would take. A finished game is graded on the pick and "
            "the line on record before kickoff; the season's record is on "
            "<a href='/nfl/'>NFL Predictions</a>.</p>")
    return _CSS + "<div class='ns'>" + switch + note + "</div>" + _JS


_CSS = """<style>
.ns{--ns-card:#fff;--ns-line:#e2e8f0;--ns-ink:#0f172a;--ns-soft:#334155;
  --ns-mute:var(--gs-muted,#5d6b7e);--ns-live:#c2410c;--ns-disc:transparent;
  --ns-ok:#166534;--ns-ok-bg:#dcfce7;--ns-no:#991b1b;--ns-no-bg:#fee2e2;
  --ns-push:#475569;--ns-push-bg:#e2e8f0}
@media (prefers-color-scheme:dark){
  .ns{--ns-card:#1b2540;--ns-line:#2b3852;--ns-ink:#e3eaf4;--ns-soft:#cbd5e1;
    --ns-mute:#94a3b8;--ns-live:#ffb457;--ns-disc:#e8edf4;
    --ns-ok:#bbf7d0;--ns-ok-bg:#14532d;--ns-no:#fecaca;--ns-no-bg:#5f1d1d;
    --ns-push:#cbd5e1;--ns-push-bg:#2b3852}
}
/* A day's games under one heading, so a card only needs its time. */
.ns h3.ns-day{font-size:13px;font-weight:800;text-transform:uppercase;letter-spacing:.06em;
  color:var(--ns-soft);margin:18px 0 8px;padding:0;border:0;text-align:left}
.ns-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(320px,100%),1fr));gap:10px}
.ns-g{background:var(--ns-card);border:1px solid var(--ns-line);border-radius:12px;
  padding:10px 12px 9px;min-width:0;scroll-margin-top:80px}
.ns-top{display:flex;justify-content:space-between;align-items:baseline;gap:10px;
  font-size:12.5px;color:var(--ns-mute);margin:0 0 3px;white-space:nowrap}
.ns-top .ns-l{min-width:0;overflow:hidden;text-overflow:ellipsis}
.ns-when{font-weight:700;color:var(--ns-soft);font-variant-numeric:tabular-nums}
.ns-when.ns-live{color:var(--ns-live)}
.ns-when.ns-live::before{content:"";display:inline-block;width:7px;height:7px;border-radius:50%;
  background:var(--ns-live);margin:0 6px 1px 0;vertical-align:middle}
.ns-at::before{content:" \u00b7 "}
.ns-tv{font-weight:600;flex:none}
.ns-t{display:flex;align-items:center;gap:10px;min-height:38px}
/* The theme frames every <img>; a logo is just a mark here. */
.ns-t img{width:28px;height:28px;object-fit:contain;flex:none;border:0;padding:0;margin:0;
  box-shadow:none;background:none;border-radius:0}
.ns-nologo{width:28px;height:28px;flex:none}
.ns-nm{font-size:16.5px;font-weight:600;color:var(--ns-ink);white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;min-width:0}
.ns-rec{font-size:12.5px;color:var(--ns-mute);font-variant-numeric:tabular-nums;flex:none}
.ns-pts{margin-left:auto;font-size:21px;font-weight:700;color:var(--ns-mute);
  font-variant-numeric:tabular-nums;flex:none}
.ns-t.ns-win .ns-nm,.ns-t.ns-win .ns-pts{color:var(--ns-ink);font-weight:800}
.ns-calls{border-top:1px solid var(--ns-line);margin-top:5px;padding-top:6px;display:grid;gap:4px}
.ns-c{display:flex;align-items:center;gap:8px;font-size:13.5px;color:var(--ns-soft);
  font-variant-numeric:tabular-nums;min-height:22px}
.ns-lab{flex:0 0 84px;font-size:11.5px;font-weight:800;text-transform:uppercase;
  letter-spacing:.05em;color:var(--ns-mute)}
.ns-v{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
/* The preview link is one short line: padded out to a thumb-sized target,
   the negative margin giving the room back so the card does not grow. */
.ns-pv .ns-v{overflow:visible}
.ns-pv .ns-v a{display:inline-block;position:relative;padding:12px 8px;margin:-12px -8px}
.ns-c b{color:var(--ns-ink);font-weight:700}
.ns-none{color:var(--ns-mute)}
.ns-mk{margin-left:auto;font-size:12px;font-weight:800;line-height:1;padding:4px 8px;
  border-radius:999px;flex:none}
.ns-mk:empty{display:none}
.ns-mk.ok{color:var(--ns-ok);background:var(--ns-ok-bg)}
.ns-mk.no{color:var(--ns-no);background:var(--ns-no-bg)}
.ns-mk.push{color:var(--ns-push);background:var(--ns-push-bg);text-transform:uppercase;font-size:10.5px}
.ns-sum{font-size:14px;color:var(--ns-soft);margin:10px 0 0}
.ns-sum b{color:var(--ns-ink);font-weight:700}
.ns-bye{font-size:13px;color:var(--ns-mute);margin:16px 0 0;line-height:1.5}
.ns-bye b{color:var(--ns-soft);margin-right:4px}
.ns-note{font-size:12.5px;color:var(--ns-mute);margin:22px 0 0;line-height:1.5}
/* Near-black marks (the Raiders, the Saints) vanish on the dark card; the
   same soft disc the home page's college logos sit on. */
@media (prefers-color-scheme:dark){
  .ns-t img{background:var(--ns-disc);border-radius:50%;padding:2px;box-sizing:border-box}
}
@media (max-width:560px){
  .ns-g{padding:9px 11px 8px}
  .ns h3.ns-day{margin:14px 0 7px}
}
</style>"""


_JS = """<script>
(function(){
  var BOARD='https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard';
  var GAME_MS=4.5*3600e3, timer=null, looked={};

  // Kickoffs in the reader's own clock. The page says Eastern; a reader
  // elsewhere gets their zone named, and the day too where it differs from
  // the heading's.
  function localTimes(root){
    var els=(root||document).querySelectorAll('.ns-g[data-state="pre"] .ns-when[data-lt]');
    for(var i=0;i<els.length;i++){
      try{
        var d=new Date(els[i].closest('.ns-g').getAttribute('data-ko'));
        var t=d.toLocaleTimeString('en-US',{hour:'numeric',minute:'2-digit',timeZoneName:'short'});
        if(d.toLocaleDateString('en-US',{timeZone:'America/New_York'})!==d.toLocaleDateString('en-US'))
          t=d.toLocaleDateString('en-US',{weekday:'short'})+' '+t;
        els[i].textContent=t;
      }catch(e){}
    }
  }
  function shown(){
    var vs=document.querySelectorAll('.wk-view');
    for(var i=0;i<vs.length;i++) if(vs[i].style.display!=='none') return vs[i];
    return null;
  }
  function games(v){ return v?[].slice.call(v.querySelectorAll('.ns-g')):[]; }
  function kicked(g){ return g.getAttribute('data-tk')==='1'&&Date.parse(g.getAttribute('data-ko'))<=Date.now(); }
  function on(g){
    var st=g.getAttribute('data-state');
    return st==='in'||(st!=='post'&&kicked(g)&&Date.now()<Date.parse(g.getAttribute('data-ko'))+GAME_MS);
  }
  function stale(g){ return g.getAttribute('data-state')!=='post'&&kicked(g); }

  function setMark(g,kind,state){
    var el=g.querySelector('.ns-mk[data-mk="'+kind+'"]'); if(!el||state===undefined) return;
    el.className='ns-mk'+(state===null?' push':state?' ok':' no');
    el.textContent=state===null?(kind==='win'?'tie':'push'):state?'\\u2713':'\\u2717';
  }
  // Our winner, and our lean against the spread, graded the way the build
  // grades them - on the numbers the card was built with.
  function grade(g,home,away){
    var m=home-away, pm=parseFloat(g.getAttribute('data-pm')), sp=parseFloat(g.getAttribute('data-sp'));
    var lean=g.getAttribute('data-lean');
    if(!isNaN(pm)) setMark(g,'win',m===0?null:(pm>0)===(m>0));
    if(lean&&!isNaN(sp)){ var c=m+sp; setMark(g,'ats',c===0?null:(lean==='home')===(c>0)); }
  }
  function apply(ev){
    var g=document.getElementById('g-'+ev.id); if(!g) return;
    var c=(ev.competitions||[])[0]||{};
    // The clock and quarter are on the competition's status, not its type.
    var s=c.status||ev.status||{}, t=s.type||{}, st=t.state||'pre';
    if(st==='pre') return;
    var pts={};
    (c.competitors||[]).forEach(function(x){
      pts[x.homeAway]=parseInt(x.score||'0',10);
      var row=g.querySelector('.ns-t[data-side="'+x.homeAway+'"] .ns-pts');
      if(row) row.textContent=x.score||'0';
    });
    ['home','away'].forEach(function(side){
      var other=side==='home'?'away':'home';
      var row=g.querySelector('.ns-t[data-side="'+side+'"]');
      if(row) row.classList.toggle('ns-win',pts[side]>pts[other]);
    });
    var w=g.querySelector('.ns-when');
    if(w){
      w.removeAttribute('data-lt');
      w.textContent=t.shortDetail||(st==='post'?'Final':'Q'+(s.period||'')+' '+(s.displayClock||''));
      w.classList.toggle('ns-live',st==='in');
    }
    g.setAttribute('data-state',st);
    if(st==='post'&&t.completed!==false) grade(g,pts.home,pts.away);
  }
  function sleep(){
    clearTimeout(timer); timer=null;
    if(document.hidden) return;
    var gs=games(shown());
    if(gs.some(on)){ timer=setTimeout(poll,60e3); return; }
    // Nothing on: wake for the week's next kickoff, if it is today.
    var next=gs.filter(function(g){ return g.getAttribute('data-state')==='pre'&&g.getAttribute('data-tk')==='1'; })
      .map(function(g){ return Date.parse(g.getAttribute('data-ko')); })
      .filter(function(t){ return t>Date.now(); }).sort()[0];
    if(next&&next-Date.now()<864e5) timer=setTimeout(poll,next-Date.now()+30e3);
  }
  function poll(){
    clearTimeout(timer); timer=null;
    var v=shown(), wk=v&&v.querySelector('.ns-wk');
    if(!wk||document.hidden) return;
    var key=wk.getAttribute('data-key'), gs=games(v);
    // A week looked at after its games began gets one read even if they are
    // long over: the page may have been built before they finished.
    if(!(gs.some(on)||(!looked[key]&&gs.some(stale)))){ sleep(); return; }
    fetch(BOARD+'?dates='+wk.getAttribute('data-season')+'&seasontype='+wk.getAttribute('data-st')
          +'&week='+wk.getAttribute('data-wk'))
      .then(function(r){ return r.ok?r.json():null; })
      .then(function(d){ looked[key]=1; ((d&&d.events)||[]).forEach(apply); })
      .catch(function(){})
      .then(sleep);
  }
  // Keep the week on screen in view in its row of buttons: on a phone the
  // row scrolls, and week 14 would otherwise open off to the right.
  function centre(){
    var b=document.querySelector('.wk-btn.active'), row=b&&b.parentNode;
    if(!row||row.scrollWidth<=row.clientWidth) return;
    var at=b.getBoundingClientRect().left-row.getBoundingClientRect().left+row.scrollLeft;
    row.scrollLeft=Math.max(0,at-(row.clientWidth-b.offsetWidth)/2);
  }
  var show=window.show_wk;
  if(show) window.show_wk=function(w){ show(w); poll(); };
  document.addEventListener('visibilitychange',function(){
    if(document.hidden){ clearTimeout(timer); timer=null; } else poll();
  });
  localTimes();
  centre();
  poll();
})();
</script>"""


def generate() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(add_front_matter(
        body(), f"NFL Schedule & Scores {SEASON}", "Every game, our pick beside the book's",
        description="Every NFL game of the season: kickoff, TV, GordStats' pick beside the "
                    "book's line, and live scores."),
        encoding="utf-8")
    print(f"Wrote NFL schedule -> {OUT}")


if __name__ == "__main__":
    generate()
