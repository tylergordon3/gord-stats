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

The Home page carries a "Tonight" card (teaser()) on days both sports play.

    python -m gordstats.watch_all
"""
import json

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

ADAPTER_JS = """<script>
(function(){
  var SPORTS=__SPORTS__, SLOTS=__SLOTS__, BREAKS=__BREAKS__, NIGHT_ENDS=__NIGHT__;
  var host=document.getElementById('wg-host');

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
        g.oid=g0.id; g.id=s.key+':'+g0.id; g.sport=s.key; g.badge=s.badge;
        g.tags=[s.badge].concat(g0.tags||[]);
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
      host.innerHTML='<p class="wg-note wg-empty">No college or NFL games in the next week.</p>';
      return;
    }
    games.sort(function(a,b){ return Date.parse(a.ko)-Date.parse(b.ko); });

    // The reader's players from both leagues as one team, and this week's
    // opponents' as the other - the engine knows one roster at a time.
    var me={n:'Your teams', p:[], opp:'them'}, them={n:'Your opponent', p:[]};
    SPORTS.forEach(function(s){
      var k=null;
      try{ k=localStorage.getItem(s.team); }catch(e){}
      var r=k&&rosters[s.key+':'+k];
      if(!r) return;
      me.p=me.p.concat(r.p);
      var o=r.opp&&rosters[r.opp];
      if(o) them.p=them.p.concat(o.p);
    });
    var mine=me.p.length>0;

    GSWatch({generated:newest, slots:SLOTS, games:games,
             rosters:mine?{me:me, them:them}:{}}, {
      team:function(){ return mine?'me':''; },
      link:'/watch/',
      hint:'Star teams on the <a href="/cfb/power/">CFB</a> and <a href="/nfl/power/">NFL</a> '
        +'rankings, and pick your teams on each fantasy league\\u2019s Team tab, to put your '
        +'games first.',
      staleHtml:'This guide has not been rebuilt for a few days; the '
        +'<a href="/cfb/watch/">CFB</a> and <a href="/nfl/watch/">NFL</a> guides say why.',
      blowout:function(g){
        var s=SPORTS.filter(function(x){ return x.key===g.sport; })[0];
        return s?s.blowout:21;
      },
      quadShared:function(g){ return g.sport==='nfl'; },
      quadNote:'NFL games are counted as available, as with Sunday Ticket.',
      stars:function(){
        var set={}, list=[], nfl={};
        try{ list=JSON.parse(localStorage.getItem('gs:favorites')||'[]')||[]; }catch(e){}
        list.forEach(function(k){
          if(typeof k!=='string') return;
          if(k.indexOf('cfb:')===0) set['cfb:'+k.slice(4)]=1;
          else if(k.indexOf('nfl:')===0) nfl[k.slice(4)]=1;
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
  });
})();
</script>"""


HOW = ("College and pro football together, each window's games best first by the watch score "
       "both sports' guides use: ESPN's matchup quality (0-100, how good the teams are and how "
       "close it should be), nudged for big games. Starred teams go first, and games with "
       "players from your fantasy teams in either league move up. During the day a close game "
       "late, an overtime or an underdog ahead in the second half jumps the queue.")


def adapter_js() -> str:
    return (ADAPTER_JS
            .replace("__SPORTS__", json.dumps(SPORTS))
            .replace("__SLOTS__", json.dumps(watch_page.slot_hours(SLOTS)))
            .replace("__BREAKS__", json.dumps([[k, before] for k, _l, before in SLOTS]))
            .replace("__NIGHT__", str(watch_page.NIGHT_ENDS)))


def body() -> str:
    return watch_page.body(None, cfb_watch.LIVE_JS + nfl_watch.LIVE_JS + adapter_js(), HOW,
                           "/watch/", "What to watch tonight, college and pro")


def generate() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(add_front_matter(
        body(), "Watch Guide", "College and pro football, window by window", updated=False,
        description="Every college and NFL game of the day in one guide, grouped by kickoff "
                    "and ranked by how much it is worth watching - with live scores."),
        encoding="utf-8")
    print(f"Wrote all-sports watch guide -> {OUT}")


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
<section class="gs-tonight" id="gs-tonight" hidden></section>
<script>
(function(){
  var box=document.getElementById('gs-tonight'); if(!box) return;
  var SPORTS=[['CFB','/cfb/watch/games.json'],['NFL','/nfl/watch/games.json']];
  var today=new Date().toLocaleDateString('en-CA',{timeZone:'America/New_York'});
  function esc(v){ return String(v==null?'':v).replace(/[&<>"]/g,function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
  Promise.all(SPORTS.map(function(s){
    return fetch(s[1]).then(function(r){ return r.ok?r.json():null; }).catch(function(){ return null; });
  })).then(function(ds){
    var rows=[], sports=0;
    ds.forEach(function(d, i){
      var gs=((d&&d.games)||[]).filter(function(g){ return g.day===today&&g.state!=='post'; });
      if(gs.length) sports++;
      gs.forEach(function(g){ rows.push({s:SPORTS[i][0], g:g}); });
    });
    // Only on a day both sports play: otherwise each sport's own guide is the page.
    if(sports<2) return;
    // In kickoff order: this card is what is on tonight, the guide ranks it.
    rows.sort(function(a,b){ return Date.parse(a.g.ko)-Date.parse(b.g.ko); });
    var top=rows.slice(0,4).map(function(x){
      var t=new Date(x.g.ko).toLocaleTimeString(undefined,{hour:'numeric',minute:'2-digit'});
      return '<li><b>'+x.s+'</b>'+esc(x.g.a.nm)+' at '+esc(x.g.h.nm)
        +'<span>'+(x.g.tk?t:'TBA')+(x.g.tv?' &middot; '+esc(x.g.tv):'')+'</span></li>';
    }).join('');
    box.innerHTML='<h2>Tonight</h2><ul>'+top+'</ul>'
      +'<a class="all" href="/watch/">All '+rows.length+' games, college and pro &rarr;</a>';
    box.hidden=false;
  });
})();
</script>"""


def teaser() -> str:
    """The Home page's Tonight card: hidden unless both sports play today."""
    return TEASER


if __name__ == "__main__":
    generate()
