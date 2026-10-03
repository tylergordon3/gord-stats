"""
"Show my league" on the NFL usage page.

The page is built around one league: every row carries who owns that player in
*this* site's league, and the Fantasy filter narrows to a roster or to the free
agents. All of that is the same question for a reader with their own league,
and the answer is one keyless Sleeper call away - rosters and users - so the
ownership column is re-pointed in the browser rather than rebuilt on the Pi.

Local first, like the stars: a league id typed here is kept in localStorage and
works signed out. Signing in and syncing the league on /fantasy/sync/ is what
makes it follow you to another device. That ordering is deliberate - the
account is a convenience, not a gate, and the page must stay useful without
one.

Only the ownership changes. Snap shares, carries and targets are properties of
the NFL, not of anyone's league, so nothing else on the page moves.

A league shared by link. The Share button on a reader's page sends the address
with `?league=<id>` (gordstats.share_button). Whoever opens it sees that league
for the visit - this tab, until it is closed or they choose otherwise - and
their own saved league is left alone: site_league_js answers every page's read
of the saved league with the shared one while the visit lasts, so no page has
to know. The bar says whose league it is, with "Use this league" to keep it
(the browser's saved league then, and the account's when signed in) and a way
back to their own.
"""

from gordstats import js_assets, league_api

CSS = """<style>
/* Its line is held while the script has not drawn it: drawn into an empty div it
   pushed every fantasy page down 34px a moment after it painted (the 2026-10-02
   layout-shift check). 40px on a phone, where its controls are thumb-sized. */
.ml-bar:empty{min-height:34px}
.ml-bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0 0 9px;
  font-size:13px;color:#475569}
.ml-who{font-weight:700;color:#0f172a}
.ml-bar button{font:inherit;font-size:12.5px;padding:5px 12px;border-radius:999px;
  border:1px solid #cbd5e1;background:#fff;color:#334155;cursor:pointer}
.ml-bar button:hover{background:#f1f5f9}
.ml-bar input{font:inherit;font-size:13px;padding:6px 9px;border:1px solid #cbd5e1;
  border-radius:8px;min-width:180px}
/* The league picker. It had no rule at all, so it rendered as the operating
   system's own dropdown - a white box on a dark page, beside controls that
   are all rounded and slate. Styled like every other select on these pages
   (.mt-pick, .dr-bar, .wv-bar), with the arrow drawn rather than left to the
   platform, because a native arrow stays dark on a dark control. */
.ml-bar select{font:inherit;font-size:13px;padding:6px 26px 6px 10px;
  border:1px solid #cbd5e1;border-radius:8px;background:#fff;color:#0f172a;
  cursor:pointer;max-width:min(100%,420px);
  -webkit-appearance:none;-moz-appearance:none;appearance:none;
  background-image:url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 8'%3E%3Cpath fill='%2364748b' d='M1 1.5 6 6.5l5-5'/%3E%3C/svg%3E");
  background-repeat:no-repeat;background-position:right 9px center;
  background-size:10px 7px}
.ml-bar select:hover{border-color:#94a3b8}
.ml-bar select:focus-visible{outline:2px solid var(--accent,#C2410C);outline-offset:1px}
.ml-bar label{display:inline-flex;align-items:center;gap:7px;min-width:0}
.ml-msg{font-size:12.5px}
.ml-msg.err{color:#b91c1c}
/* A league shared by link: its name gives way before either button does. */
.ml-bar.ml-vis .ml-who{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ml-bar button.ml-keep{font-weight:700;border-color:var(--accent,#C2410C);color:var(--accent,#C2410C)}
/* The sign-in offer sits where the username box would be, so it is styled as
   the primary thing on the row and the league id as the alternative. */
.ml-in{font:inherit;font-size:12.5px;font-weight:600;padding:5px 12px;
  border-radius:999px;border:1px solid transparent;background:var(--accent,#C2410C);
  color:#fff;text-decoration:none;white-space:nowrap}
.ml-in:hover{filter:brightness(1.08)}
.ml-or{font-size:12.5px;color:#64748b}
/* The input takes the whole row at its default width and pushes the button
   to a third line. On a phone this control is one line of label and one of
   input-plus-button. */
@media (max-width:560px){
  /* One line, not four: the labels go (the placeholder carries them) and
     what is left - Sign in, the id box, Show - shares the row at a size a
     thumb can hit. It was 136px of chrome above every fantasy page. */
  .ml-bar{gap:6px;flex-wrap:nowrap}
  .ml-bar:empty{min-height:40px}
  .ml-bar .ml-label,.ml-bar .ml-or{display:none}
  .ml-bar:has(.ml-msg:not(:empty)){flex-wrap:wrap}
  .ml-bar input{min-width:0;flex:1;min-height:40px;box-sizing:border-box;font-size:16px}
  .ml-bar select{flex:1;min-width:0;max-width:none;min-height:40px}
  .ml-bar button,.ml-bar .ml-in{white-space:nowrap;min-height:40px;box-sizing:border-box;
    display:inline-flex;align-items:center}
  .ml-bar .ml-msg{flex:1 1 100%}
  .ml-bar .ml-msg:empty{display:none}
  .ml-bar.ml-vis .ml-who{flex:1 1 0}
}
@media (prefers-color-scheme: dark){
  .ml-bar{color:#aab7c9}
  .ml-who{color:#f1f5f9}
  .ml-bar button,.ml-bar input{background:#16203a;border-color:#2b3852;color:#dde5ef}
  .ml-bar button:hover{background:#1b2540}
  .ml-bar select{background-color:#16203a;border-color:#2b3852;color:#dde5ef;
    background-image:url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 8'%3E%3Cpath fill='%23aab7c9' d='M1 1.5 6 6.5l5-5'/%3E%3C/svg%3E")}
  .ml-bar select:hover{border-color:#3d4d6b}
  /* The open list is drawn by the platform, which reads these two. */
  .ml-bar select option{background:#16203a;color:#dde5ef}
  .ml-or{color:#94a3b8}
  .ml-msg.err{color:#ff9b91}
  .ml-bar button.ml-keep{border-color:#fb923c;color:#fdba74}
}
</style>"""


def bar() -> str:
    """The control itself; the script fills it in."""
    return CSS + "<div class='ml-bar' id='ml-bar'></div>"


def _site_ids() -> list:
    from fantasy.config import LEAGUE_IDS
    return sorted(set(str(v) for v in LEAGUE_IDS.values()))


def site_league_js() -> str:
    """Runs first on every fantasy page, before anything reads the saved
    league.

    A saved league that is this site's own - synced from an account or picked
    by id - is marked as such, so every page shows its built version. Without
    it the site's own manager, having synced the league he runs, got the
    browser-drawn pages meant for a stranger's league: League Home lost its
    all-time metrics and team profiles to a plainer history, and every other
    page its archive-backed half.

    And a league shared by link (`?league=<id>`, see the top of this module)
    is shown for the visit: kept in sessionStorage, and handed to every read
    of the saved league (localStorage 'gsSleeperLeague') while it lasts, so
    the pages - several of which read the key themselves - all show it and
    none writes it over the reader's own. Saving that same league (the bar
    names it once read) stays in the visit; saving any other is the reader
    choosing, which ends the visit and is kept. `window.GSVisit` is the bar's
    handle on it: league(), own() (the reader's real saved league), keep()
    and end()."""
    return "{% raw %}<script>" + _SITE_JS.replace("__IDS__", repr(_site_ids())) \
        + "</script>{% endraw %}"


# site_league_js's script. The storage shim touches one key of localStorage
# and nothing else, and only while a visit is on.
_SITE_JS = r"""(function(){
  var ids=__IDS__, K='gsSleeperLeague', V='gsVisitLeague';
  try{
    var h=JSON.parse(localStorage.getItem(K)||'null');
    if(h&&h.id&&!h.site&&ids.indexOf(String(h.id))>=0){
      h.site=true; localStorage.setItem(K,JSON.stringify(h)); }
  }catch(e){}
  try{
    var LS=localStorage, SS=sessionStorage;
    var m=/[?&]league=([^&#]*)/.exec(location.search), q=null, visit=null;
    if(m){ try{ q=decodeURIComponent(m[1]); }catch(e){} }
    // Only a league id a reader could have saved: Sleeper's digits, or ESPN's.
    if(q && /^(\d{13,32}|espn:\d{4}:\d{1,12})$/.test(q)){
      var own=null, prev=null;
      try{ own=JSON.parse(LS.getItem(K)||'null'); }catch(e){}
      try{ prev=JSON.parse(SS.getItem(V)||'null'); }catch(e){}
      // Their own league, or this site's: nothing to show them but that.
      if(ids.indexOf(q)>=0 || (own&&String(own.id)===q)) SS.removeItem(V);
      else {
        visit=(prev&&String(prev.id)===q)?prev:{id:q, name:''};
        visit.visit=true;
        if(/^espn:/.test(q)) visit.provider='espn';
        SS.setItem(V, JSON.stringify(visit));
      }
    } else {
      try{ visit=JSON.parse(SS.getItem(V)||'null'); }catch(e){}
    }
    if(!visit||!visit.id) return;
    var P=Storage.prototype, get=P.getItem, set=P.setItem, rm=P.removeItem;
    function cur(){ try{ return JSON.parse(get.call(SS, V)||'null'); }catch(e){ return null; } }
    function end(){
      rm.call(SS, V);
      // The address stops saying which league, so a reload shows the choice.
      try{
        var u=new URL(location.href);
        if(u.searchParams.has('league')){
          u.searchParams.delete('league');
          history.replaceState(history.state, '', u.pathname+u.search+u.hash);
        }
      }catch(e){}
    }
    P.getItem=function(k){
      if(k===K && this===LS){ var v=cur(); if(v&&v.id) return JSON.stringify(v); }
      return get.apply(this, arguments);
    };
    P.setItem=function(k, val){
      if(k===K && this===LS){
        var v=cur();
        if(v&&v.id){
          var o=null;
          try{ o=JSON.parse(val); }catch(e){}
          if(o && String(o.id)===String(v.id)){
            if(o.name) v.name=o.name;
            if(o.provider) v.provider=o.provider;
            set.call(SS, V, JSON.stringify(v));
            return;
          }
          end();
        }
      }
      return set.apply(this, arguments);
    };
    P.removeItem=function(k){
      if(k===K && this===LS && cur()) end();
      return rm.apply(this, arguments);
    };
    window.GSVisit={
      league:cur,
      own:function(){ try{ return JSON.parse(get.call(LS, K)||'null'); }catch(e){ return null; } },
      keep:function(){
        var v=cur();
        if(!v) return null;
        end();
        var o={id:v.id, name:v.name||''};
        if(v.provider) o.provider=v.provider;
        set.call(LS, K, JSON.stringify(o));
        return o;
      },
      end:end
    };
  }catch(e){}
})();"""


def takeover(mine: str, built: str) -> str:
    """One of two blocks, chosen before the page paints.

    League Home holds two versions of itself (Analytics did too, until it
    became the Power tab on 2026-09-29): this
    league's, built on the Pi out of an archive, and the reader's, rendered in
    the browser from Sleeper. Only one of them is ever the answer to "what am
    I looking at", so only one is ever on the page.

    Read straight out of localStorage rather than waiting on /api/leagues,
    because a section that appears a second late has already been scrolled
    past - and because the account lookup redraws everything it changes
    anyway. Inline, immediately after both blocks, so neither is ever painted
    and then taken away.
    """
    return ("{% raw %}<script>(function(){"
            "var have=null;"
            "try{ have=JSON.parse(localStorage.getItem('gsSleeperLeague')||'null'); }"
            "catch(e){}"
            "var own=!!(have&&have.id&&!have.site);"
            f"var m=document.getElementById('{mine}'),"
            f" b=document.getElementById('{built}');"
            "if(m) m.hidden=!own;"
            "if(b) b.hidden=own;"
            "})();</script>{% endraw %}")


# GSAPI first: this control is on every page that reads a reader's league,
# and on some it runs before gordstats.my_league_data's script does.
# The bar's code is docs/assets/js/gs-league-bar.js (gordstats.js_assets): JS is
# it inline, for the browser tests; JS_TAG is what the pages carry. Every
# season's id of this site's league reaches it through GSCFG.
_CFG = {"siteLeagues": _site_ids()}
JS = league_api.JS + js_assets.inline("gs-league-bar.js", _CFG)
JS_TAG = league_api.JS_TAG + js_assets.tag("gs-league-bar.js", _CFG)
