"""
The all-sports watch guide (docs/watch/): college and pro football on one
screen, for the nights both are on - a Thursday with a college game beside
Thursday Night Football, Thanksgiving, the December Saturdays.

Each sport's guide already ranks its own games on the same 0-100 scale (ESPN's
matchup quality, nudged - gordstats.watch_page), so the two can be ranked
together. Rather than build the games a second time, this page is a shell:
each guide writes its games beside itself (docs/cfb/watch/games.json,
docs/nfl/watch/games.json, watch_page.write_games) and the browser merges
them - so this page is exactly as fresh as the two guides, whichever was
rebuilt last, with no build order to keep.

What the merge does:

  * windows: the day re-cut into one set of Eastern kickoff windows (the two
    guides cut it differently), so a 7:00 college kickoff and an 8:15 NFL one
    land in the same prime-time window and the same quadbox;
  * keys: game ids, team keys and fantasy-roster keys prefixed by sport, so a
    college team and an NFL team can never be taken for each other;
  * the reader: starred teams from both rankings pages, and the fantasy
    players of both leagues at once - the Yahoo team picked on /cfb/roster/
    and the Sleeper one on /fantasy/roster/, with this week's opponents';
  * live scores: each sport's own fetcher (GSWatchLive.cfb / .nfl, from the
    sport guides), asked only for its own games;
  * the quadbox: a college game never shares a broadcast channel; NFL games
    are taken as available, as on the NFL guide (Sunday Ticket).

College basketball joins once it has games (CBB below): its guide is built
in the browser from the live scoreboard Worker, so for this page it also
writes docs/cbb/watch/games.json - the best PER_DAY games of each league for
today and tomorrow (cbb.render.render_watch.games), men's tagged CBB and
women's WCBB, ids theScore's (one sequence for both leagues). Its live scores
come from the Worker (GSWatchLive.cbb, cbb.render.render_watch.LIVE_JS),
which also refreshes the file's states when the page opens - the file is as
old as the last daily run, and a slate runs noon to midnight. Whether it is
in is decided when the page is built (cbb_on): out of season, or with the
file absent or past, these pages are football's alone, fetching nothing more.

The Home page carries a "Tonight" card (teaser()) on days two sports play,
drawn by the build from the same files (tonight()) so the page does not jump
when its script redraws it.

    python -m gordstats.watch_all
"""
import json
from datetime import datetime
from html import escape
from pathlib import Path

import pandas as pd

from cbb.render import render_watch as cbb_watch
from cfb.site import watch as cfb_watch
from gordstats import paths, watch_page
from gordstats.frontmatter import add_front_matter
from nfl.site import watch as nfl_watch

OUT = paths.DOCS / "watch" / "index.html"

# One set of windows for both sports, Eastern: what a football day is.
SLOTS = [("early", "Early", 15.0), ("afternoon", "Afternoon", 19.0),
         ("prime", "Prime time", 22.5), ("late", "Late night", 99.0)]

SPORTS = [
    {"key": "cfb", "badge": "CFB", "data": "/cfb/watch/games.json", "link": "/cfb/schedule/",
     "blowout": 21, "team": "cfbMyTeam"},
    {"key": "nfl", "badge": "NFL", "data": "/nfl/watch/games.json", "link": "/nfl/",
     "blowout": 17, "team": "nflMyTeam"},
]
# Basketball, on the days it has games: a close finish is 6, not 8, and a
# game is over in about 2.5 hours (render_watch's). No fantasy team.
CBB = {"key": "cbb", "badge": "CBB", "data": "/cbb/watch/games.json", "link": "/cbb/watch/",
       "blowout": cbb_watch.BLOWOUT, "close": cbb_watch.CLOSE, "team": None,
       "hours": cbb_watch.GAME_HOURS}
# Home's Tonight card takes basketball's best few, not a 60-game slate.
CBB_TONIGHT = 2


def cbb_on(now=None) -> bool:
    """Whether college basketball's games.json (render_watch.write_games) has
    a game from the guide's today (watch_page.game_day) on."""
    try:
        data = json.loads((cbb_watch.OUT.parent / "games.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    today = watch_page.game_day(pd.Timestamp(now or datetime.now(watch_page.ET)))
    return any(str(g.get("day") or "") >= today for g in (data or {}).get("games") or [])


def sports(now=None) -> list:
    """The sports on these pages: football's two, and basketball when it has games."""
    return SPORTS + [CBB] if cbb_on(now) else SPORTS


def _words(on: list) -> dict:
    """What the page says, by whether basketball is in."""
    hoops = any(s["key"] == "cbb" for s in on)
    return {
        "empty": ("No games in the next week." if hoops
                  else "No college or NFL games in the next week."),
        "hint": ('Star teams on the <a href="/cfb/power/">CFB</a>'
                 + (', <a href="/nfl/power/">NFL</a> and <a href="/cbb/power/">CBB</a>' if hoops
                    else ' and <a href="/nfl/power/">NFL</a>')
                 + ' rankings, and pick your teams on each fantasy league\u2019s Team tab, '
                 'to put your games first.'),
        "subtitle": ("Football and basketball, window by window" if hoops
                     else "College and pro football, window by window"),
        "description": ("Every college and NFL game of the day and the best of college "
                        "basketball in one guide, grouped by start time and ranked by how much "
                        "it is worth watching - with live scores." if hoops else
                        "Every college and NFL game of the day in one guide, grouped by kickoff "
                        "and ranked by how much it is worth watching - with live scores."),
        "share": ("What to watch tonight, football and basketball" if hoops
                  else "What to watch tonight, college and pro"),
    }

ADAPTER_JS = """<script>
(function(){
  var SPORTS=__SPORTS__, SLOTS=__SLOTS__, BREAKS=__BREAKS__, NIGHT_ENDS=__NIGHT__, WORDS=__WORDS__;
  var host=document.getElementById('wg-host');
  function sportOf(g){ return SPORTS.filter(function(x){ return x.key===g.sport; })[0]; }

  function hourET(t){
    var parts=new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',
      hour:'numeric',minute:'numeric',hourCycle:'h23'}).formatToParts(new Date(t));
    var h=0, m=0;
    parts.forEach(function(p){ if(p.type==='hour') h=+p.value; if(p.type==='minute') m=+p.value; });
    return h+m/60;
  }
  /** This page's window for a kickoff (watch_page.slot, in the browser). */
  function slotOf(g){
    if(!g.tk) return 'tba';
    var h=hourET(g.ko);
    if(h<NIGHT_ENDS) return BREAKS[BREAKS.length-1][0];
    for(var i=0;i<BREAKS.length;i++) if(h<BREAKS[i][1]) return BREAKS[i][0];
    return BREAKS[BREAKS.length-1][0];
  }
  function read(url){
    return fetch(url).then(function(r){ return r.ok?r.json():null; })
      .catch(function(){ return null; });
  }

  Promise.all(SPORTS.map(function(s){ return read(s.data); })).then(function(ds){
    var games=[], rosters={}, newest=null, season={}, bySport={};
    ds.forEach(function(d, i){
      if(!d) return;
      var s=SPORTS[i];
      season[s.key]=d.season;
      if(d.generated&&(!newest||Date.parse(d.generated)>Date.parse(newest))) newest=d.generated;
      (d.games||[]).forEach(function(g0){
        var g=JSON.parse(JSON.stringify(g0));
        g.oid=g0.id; g.id=s.key+':'+g0.id; g.sport=s.key; g.badge=g0.badge||s.badge;
        g.tags=[g.badge].concat(g0.tags||[]);
        g.slot=slotOf(g0);
        g.href=g0.href||s.link;
        ['h','a'].forEach(function(x){
          var t=g[x]; if(!t) return;
          t.k=s.key+':'+String(t.k!=null?t.k:t.id);
        });
        games.push(g);
        (bySport[s.key]=bySport[s.key]||[]).push(g);
      });
      Object.keys(d.rosters||{}).forEach(function(k){
        var r=d.rosters[k];
        rosters[s.key+':'+k]={n:r.n, opp:r.opp!=null?s.key+':'+r.opp:null,
          p:(r.p||[]).map(function(p){ return [p[0], p[1], s.key+':'+p[2], p[3]]; })};
      });
    });
    if(!games.length){
      host.innerHTML='<p class="wg-note wg-empty">'+WORDS.empty+'</p>';
      return;
    }
    games.sort(function(a,b){ return Date.parse(a.ko)-Date.parse(b.ko); });

    // The reader's players from both leagues as one team, and this week's
    // opponents' as the other - the engine knows one roster at a time.
    var me={n:'Your teams', p:[], opp:'them'}, them={n:'Your opponent', p:[]};
    SPORTS.forEach(function(s){
      var k=null;
      if(!s.team) return;
      try{ k=localStorage.getItem(s.team); }catch(e){}
      var r=k&&rosters[s.key+':'+k];
      if(!r) return;
      me.p=me.p.concat(r.p);
      var o=r.opp&&rosters[r.opp];
      if(o) them.p=them.p.concat(o.p);
    });
    var mine=me.p.length>0;

    var D={generated:newest, slots:SLOTS, games:games, rosters:mine?{me:me, them:them}:{}};
    var W=GSWatch(D, {
      team:function(){ return mine?'me':''; },
      link:'/watch/',
      hint:WORDS.hint,
      staleHtml:'This guide has not been rebuilt for a few days; the '
        +'<a href="/cfb/watch/">CFB</a> and <a href="/nfl/watch/">NFL</a> guides say why.',
      blowout:function(g){ var s=sportOf(g); return s?s.blowout:21; },
      close:function(g){ var s=sportOf(g); return (s&&s.close)||8; },
      quadShared:function(g){ return g.sport==='nfl'; },
      quadNote:'NFL games are counted as available, as with Sunday Ticket.',
      stars:function(){
        var set={}, list=[], nfl={};
        try{ list=JSON.parse(localStorage.getItem('gs:favorites')||'[]')||[]; }catch(e){}
        list.forEach(function(k){
          if(typeof k!=='string') return;
          if(k.indexOf('cfb:')===0) set['cfb:'+k.slice(4)]=1;
          else if(k.indexOf('nfl:')===0) nfl[k.slice(4)]=1;
          else if(/^cbb-(wo)?men:/.test(k)) set['cbb:'+k]=1;      // render_watch's team keys
        });
        // NFL stars are ESPN ids; the guide knows a team by its key.
        (bySport.nfl||[]).forEach(function(g){
          [g.h,g.a].forEach(function(t){ if(t&&nfl[t.id]) set[t.k]=1; });
        });
        return set;
      },
      /* Each sport's own fetcher, on its own games under their own ids. */
      live:function(now){
        var out={};
        return Promise.all(SPORTS.map(function(s){
          var fn=window.GSWatchLive&&GSWatchLive[s.key];
          var mine=now.filter(function(g){ return g.sport===s.key; })
            .map(function(g){ var c={}; for(var k in g) c[k]=g[k]; c.id=g.oid; return c; });
          if(!fn||!mine.length) return null;
          return Promise.resolve(fn(mine, {season:season[s.key]})).then(function(map){
            Object.keys(map||{}).forEach(function(id){ out[s.key+':'+id]=map[id]; });
          }).catch(function(){});
        })).then(function(){ return out; });
      }
    });
    // Basketball's file is as old as the last daily run, and its slate runs
    // from noon to midnight: what has tipped or finished since comes from
    // the feed, once, as the page opens (the engine asks only for games on
    // now, so a 1:00 tip left "pre" would sit under Early all evening).
    var hoops=(bySport.cbb||[]).map(function(g){ var c={}; for(var k in g) c[k]=g[k]; c.id=g.oid; return c; });
    if(W&&hoops.length&&window.GSWatchLive&&GSWatchLive.cbb){
      Promise.resolve(GSWatchLive.cbb(hoops)).then(function(map){
        var moved=false;
        bySport.cbb.forEach(function(g){
          var L=map&&map[g.oid]; if(!L||!L.state) return;
          if(L.state!==g.state){ g.state=L.state; moved=true; }
          if(L.home!=null&&L.home!==g.h.sc){ g.h.sc=L.home; moved=true; }
          if(L.away!=null&&L.away!==g.a.sc){ g.a.sc=L.away; moved=true; }
        });
        if(moved) W.update(D);
      }).catch(function(){});
    }
  });
})();
</script>"""




def adapter_js(on: list = None) -> str:
    on = SPORTS if on is None else on
    words = _words(on)
    return (ADAPTER_JS
            .replace("__SPORTS__", json.dumps(on))
            .replace("__SLOTS__", json.dumps(watch_page.slot_hours(SLOTS)))
            .replace("__BREAKS__", json.dumps([[k, before] for k, _l, before in SLOTS]))
            .replace("__NIGHT__", str(watch_page.NIGHT_ENDS))
            .replace("__WORDS__", json.dumps({"empty": words["empty"], "hint": words["hint"]})))


def body(on: list = None) -> str:
    """The page for the sports `on` (sports(), by default)."""
    on = sports() if on is None else on
    hoops = any(s["key"] == "cbb" for s in on)
    live = cfb_watch.LIVE_JS + nfl_watch.LIVE_JS + (cbb_watch.live_js() if hoops else "")
    return watch_page.body(None, live + adapter_js(on), "watch-guide", "/watch/",
                           _words(on)["share"])


def generate() -> None:
    on = sports()
    words = _words(on)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(add_front_matter(
        body(on), "Watch Guide", words["subtitle"], updated=False,
        description=words["description"]),
        encoding="utf-8")
    print(f"Wrote all-sports watch guide -> {OUT}"
          + (" (with college basketball)" if len(on) > len(SPORTS) else ""))


# --------------------------------------------------------------------------- #
# Home's "Tonight" card
# --------------------------------------------------------------------------- #

TEASER = """<style>
.gs-tonight{border:1px solid #e2e8f0;border-left:4px solid #C2410C;border-radius:12px;
  padding:10px 14px;margin:0 0 14px;background:#fff}
.gs-tonight h2{font-size:15px;margin:0 0 4px;text-align:left;text-transform:uppercase;
  letter-spacing:.05em;color:#C2410C}
.gs-tonight ul{list-style:none;margin:0;padding:0}
.gs-tonight li{font-size:14.5px;line-height:1.5;color:#0f172a;display:flex;gap:8px;
  align-items:baseline}
.gs-tonight li b{font-size:11px;letter-spacing:.04em;color:#475569;min-width:30px}
.gs-tonight li span{color:#475569;font-size:13px;margin-left:auto;white-space:nowrap}
.gs-tonight a.all{display:inline-flex;align-items:center;min-height:40px;font-weight:700;
  font-size:14px;color:#C2410C}
@media (prefers-color-scheme: dark){
  .gs-tonight{background:#16203a;border-color:#2b3852;border-left-color:#fb923c}
  .gs-tonight h2,.gs-tonight a.all{color:#fb923c}
  .gs-tonight li{color:#f1f5f9}.gs-tonight li b,.gs-tonight li span{color:#c3cfdd}
}
</style>
<section class="gs-tonight" id="gs-tonight"__HIDDEN__>__CARD__</section>
<script>
(function(){
  var box=document.getElementById('gs-tonight'); if(!box) return;
  // [badge, games.json, best few only, hours a game lasts, kind] (teaser()).
  var SPORTS=__TSPORTS__;
  // The guide's day runs to __NIGHT__ AM Eastern (watch_page.NIGHT_ENDS): at
  // half past midnight Saturday's late games are still tonight's.
  var today=new Date(Date.now()-__NIGHT__*3600e3)
    .toLocaleDateString('en-CA',{timeZone:'America/New_York'});
  function esc(v){ return String(v==null?'':v).replace(/[&<>"']/g,function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
  Promise.all(SPORTS.map(function(s){
    return fetch(s[1]).then(function(r){ return r.ok?r.json():null; }).catch(function(){ return null; });
  })).then(function(ds){
    // Nothing read (offline): the card as the build drew it stands.
    if(!ds.some(function(d){ return d; })) return;
    var rows=[], sports=0, count=0, kinds={}, best=null, now=Date.now();
    ds.forEach(function(d, i){
      var s=SPORTS[i];
      // A file is as old as the last daily run: a basketball game (s[3], the
      // hours a game lasts) whose tip is further back than that has finished
      // since, and one with no time yet may have too.
      var gs=((d&&d.games)||[]).filter(function(g){ return g.day===today&&g.state!=='post'
        &&(!s[3]||(g.tk&&Date.parse(g.ko)+s[3]*3600e3>=now)); });
      if(gs.length){ sports++; kinds[s[4]]=1; }
      count+=gs.length;
      // Basketball's slate is dozens of games: its best few (s[2]), by watch score.
      if(s[2]) gs=gs.slice().sort(function(a,b){ return b.score-a.score; }).slice(0,s[2]);
      gs.forEach(function(g, j){
        var x={s:g.badge||s[0], g:g}; rows.push(x);
        if(s[2]&&j===0) best=x;
      });
    });
    // Only on a day two sports play: otherwise each sport's own guide is the page.
    // (The build draws the card when it finds two; past midnight's 4 AM the
    // day has moved on, and it goes.)
    if(sports<2){ box.hidden=true; box.innerHTML=''; return; }
    // In kickoff order: this card is what is on tonight, the guide ranks it.
    var order=function(a,b){ return Date.parse(a.g.ko)-Date.parse(b.g.ko); };
    rows.sort(order);
    var top=rows.slice(0,4);
    // Basketball's best keeps a place when football's kickoffs fill the four.
    if(best&&top.indexOf(best)<0){ top[top.length-1]=best; top.sort(order); }
    top=top.map(function(x){
      var t=new Date(x.g.ko).toLocaleTimeString('en-US',{hour:'numeric',minute:'2-digit'});
      return '<li><b>'+x.s+'</b>'+esc(x.g.a.nm)+' at '+esc(x.g.h.nm)
        +'<span>'+(x.g.tk?t:'TBA')+(x.g.tv?' &middot; '+esc(x.g.tv):'')+'</span></li>';
    }).join('');
    box.innerHTML='<h2>Tonight</h2><ul>'+top+'</ul>'
      +'<a class="all" href="/watch/">All '+count+' games, '
      +(kinds.basketball?'football and basketball':'college and pro')+' &rarr;</a>';
    box.hidden=false;
  });
})();
</script>"""


def _text(v) -> str:
    """A name for Home's body, which Jekyll runs Liquid over: escaped, and
    its braces as entities, so no name can open a Liquid tag."""
    return escape(str(v if v is not None else "")).replace("{", "&#123;").replace("}", "&#125;")


def tonight(on: list, now=None, docs: Path = None) -> str:
    """The card's inside as its script draws it (TEASER), from the games files
    this build finds under `docs` - so on a night two sports play the card is
    on the page as it loads, not pushed in above everything else after it
    (in basketball season that is most nights). '' when fewer than two play;
    the script decides again in the browser either way, its times in the
    reader's own clock where these are Eastern."""
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz=watch_page.ET)
    if now.tzinfo is None:
        now = now.tz_localize(watch_page.ET)
    today = watch_page.game_day(now)
    rows, sports, count, kinds, best = [], 0, 0, set(), None

    def kick(g):
        try:
            t = pd.Timestamp(g.get("ko"))
        except (TypeError, ValueError):
            t = pd.NaT
        return pd.Timestamp.max.tz_localize("UTC") if pd.isna(t) else t
    for s in on:
        try:
            data = json.loads((Path(docs or paths.DOCS) / s["data"].lstrip("/"))
                              .read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        hours, few = s.get("hours") or 0, CBB_TONIGHT if s["key"] == "cbb" else 0
        gs = [g for g in (data or {}).get("games") or []
              if g.get("day") == today and g.get("state") != "post"
              and (not hours or (g.get("tk") and kick(g) + pd.Timedelta(hours=hours) >= now))]
        if gs:
            sports += 1
            kinds.add("basketball" if s["key"] == "cbb" else "football")
        count += len(gs)
        if few:
            gs = sorted(gs, key=lambda g: -(g.get("score") or 0))[:few]
        for j, g in enumerate(gs):
            rows.append((g.get("badge") or s["badge"], g))
            if few and j == 0:
                best = rows[-1]
    if sports < 2:
        return ""
    rows.sort(key=lambda x: kick(x[1]))
    top = rows[:4]
    if best is not None and best not in top:
        top[-1] = best
        top.sort(key=lambda x: kick(x[1]))
    items = "".join(
        f"<li><b>{_text(b)}</b>{_text(g['a']['nm'])} at {_text(g['h']['nm'])}<span>"
        + (kick(g).tz_convert(watch_page.ET).strftime("%-I:%M %p") if g.get("tk") else "TBA")
        + (f" &middot; {_text(g['tv'])}" if g.get("tv") else "") + "</span></li>"
        for b, g in top)
    return (f"<h2>Tonight</h2><ul>{items}</ul><a class=\"all\" href=\"/watch/\">All {count} games, "
            f"{'football and basketball' if 'basketball' in kinds else 'college and pro'} &rarr;</a>")


def teaser(on: list = None, now=None, docs: Path = None) -> str:
    """The Home page's Tonight card: shown when two of the sports `on`
    (sports(), by default) play today - drawn by the build (tonight()) and
    kept current by its script."""
    on = sports(now) if on is None else on
    rows = [[s["badge"], s["data"], CBB_TONIGHT if s["key"] == "cbb" else 0,
             s.get("hours") or 0, "basketball" if s["key"] == "cbb" else "football"] for s in on]
    card = tonight(on, now, docs)
    return (TEASER.replace("__NIGHT__", str(watch_page.NIGHT_ENDS))
            .replace("__TSPORTS__", json.dumps(rows))
            .replace("__HIDDEN__", "" if card else " hidden").replace("__CARD__", card))


if __name__ == "__main__":
    generate()
