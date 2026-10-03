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
/* The account line is drawn once /api/me answers; "Checking..." holds the
   height of the signed-in row it usually becomes, so the cards under it stay
   put (the 2026-10-02 layout-shift check). */
#pf-who{min-height:36px}
/* On a phone both answers take two rows - the sign-in invitation, and the
   address with Sign out and Sign out everywhere (measured 70 and 72px at
   360-390px wide) - so the hold is two rows there. */
@media (max-width:520px){#pf-who{min-height:72px}}
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
/* Review submissions (Tweets of the week): the owner's, and drawn only for
   them, at the foot of the page so appearing moves nothing above it. */
.pf-tw .pf-group{margin-top:12px}
.pf-tw-item.pf-tw-item{align-items:flex-start}
.pf-tw-main{flex:1 1 260px;min-width:0}
.pf-tw-text{font-size:13.5px;line-height:1.45;color:#334155;margin-top:3px;white-space:pre-line;
  overflow-wrap:anywhere}
.pf-tw .pf-btn{min-height:40px;box-sizing:border-box}
.pf-tw a.pf-btn{display:inline-flex;align-items:center;text-decoration:none}
.pf-tw select{min-height:40px;font:inherit;font-size:16px;border:1px solid #cbd5e1;border-radius:8px;
  padding:0 8px;background:#fff;color:#334155}
@media (prefers-color-scheme: dark){
  .pf-tw-text{color:#cbd5e1}
  .pf-tw select{background:#16203a;border-color:#2b3852;color:#dde5ef}
}
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
    return String(v==null?'':v).replace(/[&<>"']/g,function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});
  }
  /** The followed teams: favorites.js's list once it is up (it owns it, and
   *  the account sync lands there), else what this browser stored. */
  function readFavs(){
    var list=[];
    if(window.GSFavorites && GSFavorites.list) list=GSFavorites.list();
    else{ try{ list=JSON.parse(localStorage.getItem(FAV)||'[]')||[]; }catch(e){} }
    return Array.isArray(list) ? list.filter(function(k){ return typeof k==='string'; }) : [];
  }
  function writeFavs(list){
    try{ localStorage.setItem(FAV, JSON.stringify(list)); }catch(e){}
  }

  // The list changes under this page: signing in brings the account's teams
  // (favorites.js syncs after this script ran), and a star elsewhere on the
  // page is the same list. favorites.js says so with this event.
  document.addEventListener('gs:favorites', function(){ drawFavs(); });

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

  // Tweets of the week: the owner reviews what readers sent in. /api/tweets
  // says whether this account is the owner, so the queue is asked for only
  // then - nobody else gets a 403 - and the card shows only when the queue
  // answers 200.
  var TW=document.getElementById('pf-tw');
  var TW_ID=/^[1-9][0-9]{0,19}$/, TW_H=/^[A-Za-z0-9_]{1,15}$/;
  function twGet(status){
    return fetch('/api/tweets?status='+status,{credentials:'same-origin'})
      .then(function(r){ return r.status===200?r.json():null; })
      .then(function(d){ return d&&d.ok&&Array.isArray(d.tweets)?d.tweets:null; });
  }
  function twItem(t, waiting){
    var url='https://x.com/'+(TW_H.test(t.handle||'')?t.handle:'i')+'/status/'+t.tweet_id;
    var sport=function(v,label){
      return '<option value="'+v+'"'+(t.sport===v?' selected':'')+'>'+label+'</option>';
    };
    var meta=[t.handle?'@'+t.handle:'', t.has_media==2?'video':t.has_media==1?'photo or video':'',
              waiting?(t.submitter?'from '+t.submitter:''):(t.votes|0)+((t.votes|0)===1?' vote':' votes'),
              !waiting&&t.sport?t.sport.toUpperCase():'']
      .filter(Boolean).join(' \u00b7 ');
    return '<li class="pf-tw-item" data-id="'+t.id+'"><div class="pf-tw-main">'
      +'<span class="pf-name">'+esc(t.author||'On X')+'</span> <span class="pf-meta">'+esc(meta)+'</span>'
      +'<div class="pf-tw-text">'+esc(t.text||'(no words - a picture or video)')+'</div></div>'
      +'<div class="pf-row">'
      +(waiting
        ?'<select class="pf-tw-sport" aria-label="Sport">'+sport('','Sport?')+sport('cfb','College')
          +sport('nfl','NFL')+'</select>'
          +'<button type="button" class="pf-btn go" data-act="approve">Approve</button>'
          +'<button type="button" class="pf-btn danger" data-act="reject">Reject</button>'
        :'<button type="button" class="pf-btn danger" data-act="remove">Remove</button>')
      +'<a class="pf-btn" href="'+esc(url)+'" target="_blank" rel="noopener noreferrer">Open on X</a>'
      +'</div></li>';
  }
  function twDraw(waiting, live){
    var good=function(t){ return t&&TW_ID.test(String(t.tweet_id))&&/^[1-9][0-9]{0,11}$/.test(String(t.id)); };
    waiting=(waiting||[]).filter(good); live=(live||[]).filter(good);
    document.getElementById('pf-tw-q').innerHTML=waiting.length
      ?waiting.map(function(t){ return twItem(t,true); }).join('')
      :'<li><span class="pf-meta">Nothing waiting.</span></li>';
    document.getElementById('pf-tw-on').innerHTML=live.length
      ?live.map(function(t){ return twItem(t,false); }).join('')
      :'<li><span class="pf-meta">Nothing approved yet.</span></li>';
  }
  function twMsg(text, cls){
    var m=document.getElementById('pf-tw-msg');
    m.className='pf-msg'+(cls?' '+cls:'');
    m.textContent=text;
  }
  function twReview(){
    if(!TW) return;
    fetch('/api/tweets',{credentials:'same-origin'})
      .then(function(r){ return r.ok?r.json():null; })
      .then(function(d){
        if(!d||d.admin!==true) return null;
        return Promise.all([twGet('pending'), twGet('approved')]);
      })
      .then(function(lists){
        if(!lists||!lists[0]) return;
        twDraw(lists[0], lists[1]);
        TW.hidden=false;
      })
      .catch(function(e){ console.error('profile: review', e); });
  }
  if(TW) TW.addEventListener('click',function(ev){
    var b=ev.target.closest&&ev.target.closest('button[data-act]');
    var li=b&&b.closest('.pf-tw-item'), id=li&&li.getAttribute('data-id');
    if(!id) return;
    var act=b.getAttribute('data-act'), body={action:act};
    var sel=li.querySelector('.pf-tw-sport');
    if(sel&&act==='approve') body.sport=sel.value||null;
    var buttons=li.querySelectorAll('button');
    [].forEach.call(buttons,function(x){ x.disabled=true; });
    fetch('/api/tweets/'+id+'/review',{method:'POST', credentials:'same-origin',
        headers:{'content-type':'application/json'}, body:JSON.stringify(body)})
      .then(function(r){
        return r.json().catch(function(){ return {}; })
          .then(function(j){ return {ok:r.ok&&!!(j&&j.ok), j:j||{}}; });
      })
      .then(function(a){
        if(!a.ok){
          twMsg(a.j.error||'That did not go through.','err');
          [].forEach.call(buttons,function(x){ x.disabled=false; });
          return null;
        }
        twMsg(act==='approve'?'Approved - it is on Home now.'
              :act==='reject'?'Turned down.':'Taken off the site.','ok');
        return Promise.all([twGet('pending'), twGet('approved')])
          .then(function(l){ twDraw(l[0], l[1]); });
      })
      .catch(function(e){
        console.error('profile: review', e);
        twMsg("Couldn't reach the server.",'err');
        [].forEach.call(buttons,function(x){ x.disabled=false; });
      });
  });

  // "Sign out everywhere" ends every session of the account, this browser's
  // included (POST /api/auth/logout-everywhere). The page then reloads, so
  // the header and every card agree it is signed out, and says what happened
  // once - the marker comes off the address straight away.
  var EVERYWHERE='signedout=everywhere';
  var gone=/[?&]signedout=everywhere(&|$)/.test(location.search);
  if(gone){
    try{ history.replaceState(null,'',location.pathname+location.hash); }catch(e){}
  }
  function everywhere(){
    var b=document.getElementById('pf-everywhere'), m=document.getElementById('pf-everywhere-msg');
    b.disabled=true; m.hidden=true;
    fetch('/api/auth/logout-everywhere',{method:'POST',credentials:'same-origin'})
      .then(function(r){
        return r.json().catch(function(){ return {}; })
          .then(function(j){ return {ok:r.ok&&!!(j&&j.ok), status:r.status, j:j||{}}; });
      })
      .then(function(a){
        // 401: this session was already ended from somewhere else - which is
        // the outcome asked for.
        if(a.ok||a.status===401){ location.replace(location.pathname+'?'+EVERYWHERE); return; }
        m.textContent=a.j.error||'That did not go through. Try again in a minute.';
        m.hidden=false; b.disabled=false;
      })
      .catch(function(e){
        console.error('profile: sign out everywhere', e);
        m.textContent="Couldn't reach the server."; m.hidden=false; b.disabled=false;
      });
  }

  fetch('/api/me',{credentials:'same-origin'})
    // Not 2xx is "could not tell" (the database did not answer), never
    // "signed out": that would offer a sign-in to a reader who is.
    .then(function(r){ if(!r.ok) throw new Error('HTTP '+r.status); return r.json(); })
    .then(function(me){
      if(!me.configured){
        who.innerHTML='<span class="pf-meta">Accounts are not enabled on this '
          +'deployment. Leagues and followed teams are kept in this browser.</span>';
        return;
      }
      if(!me.signedIn){
        who.innerHTML=(gone?'<p class="pf-msg ok" role="status">Signed out on every device.</p>':'')
          +'<div class="pf-row"><a class="pf-btn go" href="/api/auth/login'
          +'?next='+encodeURIComponent(location.pathname)+'">Sign in with Google</a>'
          +'<span class="pf-meta">Signing in carries your leagues and followed '
          +'teams between devices. Everything works without it, in this browser.</span></div>';
        return;
      }
      who.innerHTML='<div class="pf-row"><span class="pf-who">Signed in as <b>'
        +esc(me.email)+'</b></span>'
        +'<a class="pf-btn" href="/api/auth/logout?next=/profile/">Sign out</a>'
        +'<button type="button" class="pf-btn" id="pf-everywhere" title="Ends this account\\u2019s '
        +'session on every phone and computer, this one included - for a lost device or '
        +'one that isn\\u2019t yours. You can sign straight back in.">Sign out everywhere</button></div>'
        +'<p class="pf-msg err" id="pf-everywhere-msg" role="status" hidden></p>';
      document.getElementById('pf-everywhere').addEventListener('click', everywhere);
      twReview();
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
            + "</div>"
            # Only ever shown to the owner (users.is_admin), and last, so
            # drawing it moves nothing a reader is looking at.
            + "<div class='pf-card pf-tw' id='pf-tw' hidden><h2>Review submissions</h2>"
              "<p>Posts readers sent in for Tweets of the week. Approving one puts it on "
              "Home for seven days, ranked by readers' votes.</p>"
              "<div class='pf-group'>Waiting</div><ul class='pf-list' id='pf-tw-q'></ul>"
              "<div class='pf-group'>On the site now</div><ul class='pf-list' id='pf-tw-on'></ul>"
              "<p class='pf-msg' id='pf-tw-msg' role='status'></p></div>"
            + "</div>" + JS)
