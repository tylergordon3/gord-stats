"""
The profile page (docs/profile/): one place for the things attached to an
account - who is signed in, which leagues are synced, and which teams are
starred.

None of it is only here. Leagues can still be connected from any page that
shows one, and a team is still starred from the row it appears on; this is
where you go to see the lot at once and take something off.

Starred teams are stored as `sport:id` keys, which are no use to read. The
names come from docs/assets/favourite-teams.json, built by `write_index()`
from the stars the site has already rendered: every one carries its key and
the team's name, so the map falls out of the pages rather than needing a
separate source per sport.
"""
import json
import re
from html import escape

INDEX_NAME = "favourite-teams.json"
# The star markup, as gordstats.favorites writes it.
_STAR = re.compile(
    r"data-fav-for='([^']+)'[^>]*?aria-label='Follow ([^']*)'")

SPORT_LABELS = {"cfb": "College football", "cbb-men": "College basketball",
                "cbb-women": "College basketball (women)", "nfl": "NFL",
                "wnba": "WNBA"}


def write_index(docs) -> dict:
    """{sport: {id: name}} for every team the site has put a star beside."""
    index = {}
    for path in docs.rglob("*.html"):
        for key, name in _STAR.findall(path.read_text(encoding="utf-8")):
            sport, _, ident = key.partition(":")
            if not sport or not ident:
                continue
            index.setdefault(sport, {}).setdefault(ident, name)
    out = docs / "assets" / INDEX_NAME
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(index, separators=(",", ":"), sort_keys=True),
                   encoding="utf-8")
    total = sum(len(v) for v in index.values())
    print(f"Wrote favourite-team names ({total} across {len(index)} sports) -> {out}")
    return index


CSS = """<style>
.pf{max-width:760px}
.pf-card{border:1px solid #e2e8f0;border-radius:12px;padding:16px 18px;background:#fff;
  margin:0 0 14px}
.pf-card h2{margin:0 0 3px;font-size:17px}
.pf-card p{margin:0 0 11px;font-size:13.5px;color:#475569;line-height:1.5}
.pf-who{font-size:14px;color:#0f172a}
.pf-who b{font-weight:800}
.pf-row{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.pf-btn{font:inherit;font-size:13px;font-weight:700;padding:7px 15px;border-radius:8px;
  border:1px solid #cbd5e1;background:#fff;color:#334155;cursor:pointer}
.pf-btn.go{background:#2a78d6;border-color:#2a78d6;color:#fff}
.pf-btn.danger{border-color:#fecaca;color:#b91c1c}
.pf-list{list-style:none;padding:0;margin:0}
.pf-list li{display:flex;flex-wrap:wrap;gap:8px;align-items:center;
  justify-content:space-between;padding:9px 0;border-top:1px solid #e2e8f0}
.pf-list li:first-child{border-top:0}
.pf-name{font-weight:700;color:#0f172a}
.pf-meta{font-size:12px;color:#64748b}
.pf-drop{font:inherit;font-size:12.5px;padding:4px 11px;border-radius:7px;
  border:1px solid #cbd5e1;background:#fff;color:#334155;cursor:pointer}
.pf-group{margin:0 0 4px;font-size:11.5px;text-transform:uppercase;letter-spacing:.05em;
  color:#64748b;font-weight:800}
.pf-msg{font-size:13px;margin:8px 0 0}
.pf-msg.err{color:#b91c1c}
.pf-msg.ok{color:#15803d}
@media (prefers-color-scheme: dark){
  .pf-card{background:#16203a;border-color:#2b3852}
  .pf-card p,.pf-meta,.pf-group{color:#aab7c9}
  .pf-name,.pf-who{color:#f1f5f9}
  .pf-list li{border-top-color:#2b3852}
  .pf-btn,.pf-drop{background:#16203a;border-color:#2b3852;color:#dde5ef}
  .pf-btn.go{background:#2a78d6;border-color:#2a78d6;color:#fff}
  .pf-btn.danger{border-color:#7f1d1d;color:#ff9b91}
  .pf-msg.err{color:#ff9b91}
  .pf-msg.ok{color:#6ee7b7}
}
</style>"""

JS = """{% raw %}<script>
(function(){
  // The same keys the rest of the site uses - assets/js/favorites.js owns
  // the first, my_league.js the second. Guessing either would have shown
  // an empty page rather than failing.
  var FAV='gs:favorites', LIST='gsSleeperLeagues';
  var who=document.getElementById('pf-who');
  var favSlot=document.getElementById('pf-favs');
  if(!who) return;

  function esc(v){
    return String(v==null?'':v).replace(/[&<>"]/g,function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});
  }
  function readFavs(){
    try{ return JSON.parse(localStorage.getItem(FAV)||'[]')||[]; }catch(e){ return []; }
  }
  function writeFavs(list){
    try{ localStorage.setItem(FAV, JSON.stringify(list)); }catch(e){}
  }

  var NAMES={};
  fetch('/assets/favourite-teams.json')
    .then(function(r){ return r.ok?r.json():{}; })
    .then(function(d){ NAMES=d||{}; drawFavs(); })
    .catch(function(){ drawFavs(); });

  var LABELS={"cfb":"College football","cbb-men":"College basketball",
              "cbb-women":"College basketball (women)","nfl":"NFL","wnba":"WNBA"};

  function drawFavs(){
    var keys=readFavs();
    if(!keys.length){
      favSlot.innerHTML='<p class="pf-meta">No teams followed yet. The star '
        +'beside a team on any rankings or schedule page follows it.</p>';
      return;
    }
    var bySport={};
    keys.forEach(function(k){
      var i=k.indexOf(':');
      if(i<0) return;
      var sport=k.slice(0,i), id=k.slice(i+1);
      (bySport[sport]=bySport[sport]||[]).push({key:k, id:id,
        name:((NAMES[sport]||{})[id])||id});
    });
    var html='';
    Object.keys(bySport).sort().forEach(function(sport){
      var rows=bySport[sport].sort(function(a,b){
        return a.name.toLowerCase()<b.name.toLowerCase()?-1:1;});
      html+='<div class="pf-group">'+esc(LABELS[sport]||sport)+'</div><ul class="pf-list">'
        + rows.map(function(t){
            return '<li><span class="pf-name">'+esc(t.name)+'</span>'
              +'<button class="pf-drop" data-key="'+esc(t.key)+'">Unfollow</button></li>';
          }).join('')
        +'</ul>';
    });
    favSlot.innerHTML=html;
    Array.prototype.forEach.call(favSlot.querySelectorAll('.pf-drop'),function(b){
      b.addEventListener('click',function(){
        // Through favorites.js, which owns the list. Writing localStorage
        // directly would not survive: it holds the list in a variable, the
        // storage event only fires for other documents, and its next push
        // would put the removed team back.
        if(window.GSFavorites) window.GSFavorites.remove(b.dataset.key);
        else {
          var keep=readFavs().filter(function(k){ return k!==b.dataset.key; });
          writeFavs(keep);
        }
        drawFavs();
      });
    });
  }

  fetch('/api/me',{credentials:'same-origin'})
    .then(function(r){ return r.json(); })
    .then(function(me){
      if(!me.configured){
        who.innerHTML='<span class="pf-meta">Accounts are not enabled on this '
          +'deployment. Leagues and followed teams are kept in this browser.</span>';
        return;
      }
      if(!me.signedIn){
        who.innerHTML='<div class="pf-row"><a class="pf-btn go" href="/api/auth/login'
          +'?next='+encodeURIComponent(location.pathname)+'">Sign in with Google</a>'
          +'<span class="pf-meta">Signing in carries your leagues and followed '
          +'teams between devices. Everything works without it, in this browser.</span></div>';
        return;
      }
      who.innerHTML='<div class="pf-row"><span class="pf-who">Signed in as <b>'
        +esc(me.email)+'</b></span>'
        +'<a class="pf-btn" href="/api/auth/logout?next=/profile/">Sign out</a></div>';
    })
    .catch(function(){
      who.innerHTML='<span class="pf-meta">Could not reach the server.</span>';
    });
})();
</script>{% endraw %}"""


def body(league_sync_body: str) -> str:
    return (CSS
            + "<div class='pf'>"
            + "<div class='pf-card'><h2>Account</h2><div id='pf-who'>"
              "<span class='pf-meta'>Checking…</span></div></div>"
            + "<div class='pf-card'><h2>Followed teams</h2>"
              "<p>Starred anywhere on the site, and kept here. The star beside a "
              "team on a rankings or schedule page is the same list.</p>"
              "<div id='pf-favs'></div></div>"
            # The league half sits in a card like the rest rather than
            # trailing off the bottom of the page with no heading.
            + "<div class='pf-card'><h2>Your leagues</h2>"
              "<p>Connected leagues follow you between devices when you are "
              "signed in, and are kept in this browser when you are not. You "
              "can also connect one from the bar on any league page.</p>"
            + league_sync_body
            + "</div></div>" + JS)
