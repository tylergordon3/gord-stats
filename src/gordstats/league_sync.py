"""
"Sync my league": the page where a reader attaches their own fantasy league
to their account (docs/fantasy/sync/).

The site's own league is baked into the build. This is how a reader attaches
theirs instead: they give their Sleeper username, Sleeper says which leagues
that account is in, and all of them are stored against their account with the
name of their team in each.

The username is the way in because the league-id flow asked people to dig a
sixteen-digit number out of a URL, once per league, which is where it lost
them. The id is still accepted for anyone who wants one league only.

Sleeper, and ESPN leagues set public, by id or web address - ESPN has no
keyless way to list an account's leagues. No credentials are involved: Sleeper's
API is keyless, and ESPN's answers a public league to anyone.
Yahoo was offered here briefly: its public API serves only leagues set public,
and a private one needs OAuth and stored refresh tokens - a change in what a
leaked database would cost, for leagues nobody has asked for. It came out
again.

The page is inert on a deploy without accounts (`/api/me` says
`configured: false`), the same rule the rest of the account UI follows.
"""
from gordstats.frontmatter import add_front_matter

CSS = """<style>
.ls-wrap{max-width:720px}
.ls-card{border:1px solid #e2e8f0;border-radius:12px;padding:16px 18px;background:#fff;
  margin:0 0 14px}
.ls-card h2{margin:0 0 3px;font-size:17px}
.ls-card p{margin:0 0 11px;font-size:13.5px;color:#475569;line-height:1.5}
.ls-row{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.ls-row input{font:inherit;font-size:14px;padding:8px 10px;border:1px solid #cbd5e1;
  border-radius:8px;min-width:210px;flex:1}
.ls-row button{font:inherit;font-size:14px;font-weight:700;padding:8px 16px;border-radius:8px;
  border:1px solid #2a78d6;background:#2a78d6;color:#fff;cursor:pointer}
.ls-row button[disabled]{opacity:.55;cursor:default}
.ls-msg{font-size:13px;margin:9px 0 0;line-height:1.45}
.ls-msg.err{color:#b91c1c}
.ls-msg.ok{color:#15803d}
.ls-msg.warn{color:#a16207}
.ls-list{list-style:none;padding:0;margin:0}
.ls-list li{display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:space-between;
  padding:10px 0;border-top:1px solid #e2e8f0}
.ls-list li:first-child{border-top:0}
.ls-name{font-weight:700;color:#0f172a}
.ls-meta{font-size:12px;color:#64748b}
.ls-drop{font:inherit;font-size:12.5px;padding:5px 11px;border-radius:7px;border:1px solid #cbd5e1;
  background:#fff;color:#334155;cursor:pointer}
.ls-gate{font-size:14px;color:#475569}
@media (prefers-color-scheme: dark){
  .ls-card{background:#16203a;border-color:#2b3852}
  .ls-card p,.ls-meta,.ls-gate{color:#aab7c9}
  .ls-name{color:#f1f5f9}
  .ls-list li{border-top-color:#2b3852}
  .ls-row input,.ls-drop{background:#16203a;border-color:#2b3852;color:#dde5ef}
  .ls-msg.err{color:#ff9b91}
  .ls-msg.ok{color:#6ee7b7}
  .ls-msg.warn{color:#fcd34d}
}
</style>"""

JS = """{% raw %}<script>
(function(){
  var gate=document.getElementById('ls-gate'), main=document.getElementById('ls-main');
  var list=document.getElementById('ls-list');

  function esc(v){
    return String(v==null?'':v).replace(/[&<>"]/g,function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});
  }
  function msg(where,text,cls){
    var el=document.getElementById(where);
    el.textContent=text||''; el.className='ls-msg'+(cls?' '+cls:'');
  }
  /** A sync that ran out of room says so (functions/api/leagues.js
   *  `unfinished`): the account's league cap, or the Sleeper calls one sync
   *  may make. Shown with the success line rather than left for the reader
   *  to notice a league or a season missing. */
  function done(where, text, d){
    var note=(d && d.complete===false && d.unfinished && d.unfinished.note) || '';
    msg(where, text+(note?' '+note:''), note?'warn':'ok');
  }
  function when(iso){
    if(!iso) return '';
    var d=new Date(iso);
    return isNaN(d)?'':d.toLocaleString([], {month:'short', day:'numeric',
      hour:'numeric', minute:'2-digit'});
  }
  /** One entry per league, its seasons folded in - a league with four years
   *  of history is four rows, and listing them raw reads as four leagues. */
  function grouped(rows){
    var g={};
    rows.forEach(function(l){
      var key=l.lineage_id||l.league_id;
      (g[key]=g[key]||[]).push(l);
    });
    return Object.keys(g).map(function(k){
      var seasons=g[k].slice().sort(function(a,b){
        return String(b.season||'').localeCompare(String(a.season||''));});
      return {top:seasons[0], seasons:seasons};
    });
  }

  function render(rows){
    if(!rows.length){
      list.innerHTML='<li><span class="ls-meta">No league synced yet.</span></li>';
      return;
    }
    list.innerHTML='';
    grouped(rows).forEach(function(group){
      var l=group.top, n=group.seasons.length;
      var span='';
      if(n>1){
        var oldest=group.seasons[n-1].season, newest=l.season;
        span=n+' seasons &middot; '+esc(oldest)+'\u2013'+esc(newest);
      } else {
        span=esc(l.season||'');
      }
      var li=document.createElement('li');
      var left=document.createElement('div');
      left.innerHTML='<div class="ls-name">'+esc(l.name||l.league_id)+'</div>'
        +'<div class="ls-meta">'+(l.team_name?esc(l.team_name)+' &middot; ':'')
        +span+' &middot; synced '+when(l.last_synced_at)+'</div>';
      var drop=document.createElement('button');
      drop.className='ls-drop'; drop.textContent='Remove';
      drop.title='Removes every season of this league';
      drop.addEventListener('click',function(){
        drop.disabled=true;
        fetch('/api/leagues?provider='+encodeURIComponent(l.provider)
              +'&league_id='+encodeURIComponent(l.league_id),
              {method:'DELETE', credentials:'same-origin'})
          .then(function(){ load(); });
      });
      li.appendChild(left); li.appendChild(drop); list.appendChild(li);
    });
  }
  function load(){
    fetch('/api/leagues',{credentials:'same-origin'})
      .then(function(r){return r.json().then(function(d){return {s:r.status,d:d};});})
      .then(function(res){
        // The table arrives in a migration applied by hand, so the endpoint
        // can be live before it exists. Say that, rather than an empty list.
        if(res.d && res.d.migrating){
          main.hidden=true; gate.hidden=false;
          gate.textContent=res.d.error;
          return;
        }
        render((res.d && res.d.leagues)||[]);
      })
      .catch(function(){});
  }
  function add(provider,inputId,msgId,btn){
    var value=(document.getElementById(inputId).value||'').trim();
    if(!value){ msg(msgId,'Enter a league id first.','err'); return; }
    // An ESPN web address carries the id (and maybe the season) as a query.
    var id=/[?&]leagueId=(\\d{1,12})/.exec(value), yr=/[?&]seasonId=(\\d{4})/.exec(value);
    if(provider==='espn' && id) value=yr?('espn:'+yr[1]+':'+id[1]):id[1];
    btn.disabled=true; msg(msgId,'Checking with '+provider+'\\u2026');
    fetch('/api/leagues',{method:'POST',credentials:'same-origin',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({provider:provider, league_id:value})})
      .then(function(r){return r.json().then(function(d){return {s:r.status,d:d};});})
      .then(function(res){
        btn.disabled=false;
        if(res.s===429){
          msg(msgId,'Just refreshed \\u2014 try again in '
            +(res.d.retry_after||60)+'s.','err');
          return;
        }
        if(res.d.migrating){ msg(msgId,res.d.error,'err'); return; }
        if(!res.d.ok){ msg(msgId,res.d.error||'That did not work.','err'); return; }
        done(msgId,'Synced '+(res.d.league.name||'the league')
          +(res.d.synced>1?' and its '+(res.d.synced-1)+' earlier season'
            +(res.d.synced===2?'':'s'):'')+'.', res.d);
        document.getElementById(inputId).value='';
        load();
      })
      .catch(function(){ btn.disabled=false; msg(msgId,'Network error.','err'); });
  }

  function findAll(btn){
    var name=(document.getElementById('ls-user').value||'').trim();
    if(!name){ msg('ls-user-msg','Enter your Sleeper username first.','err'); return; }
    btn.disabled=true; msg('ls-user-msg','Asking Sleeper\u2026');
    fetch('/api/leagues',{method:'POST',credentials:'same-origin',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({provider:'sleeper', username:name})})
      .then(function(r){return r.json().then(function(d){return {s:r.status,d:d};});})
      .then(function(res){
        btn.disabled=false;
        if(res.s===429){
          msg('ls-user-msg','Just refreshed \u2014 try again in '
            +(res.d.retry_after||60)+'s.','err');
          return;
        }
        if(!res.d.ok){ msg('ls-user-msg',res.d.error||'That did not work.','err'); return; }
        var found=res.d.leagues_found||res.d.synced;
        done('ls-user-msg','Found '+found+' league'+(found===1?'':'s')
          +(res.d.synced>found
            ? ', '+res.d.synced+' seasons in all' : '')+'.', res.d);
        document.getElementById('ls-user').value='';
        load();
      })
      .catch(function(){ btn.disabled=false; msg('ls-user-msg','Network error.','err'); });
  }

  // Inert unless this deploy has accounts and the reader is signed in - the
  // same rule the header's account control follows.
  fetch('/api/me',{credentials:'same-origin'})
    .then(function(r){return r.json();})
    .then(function(me){
      if(!me.configured){ gate.textContent=
        'Accounts are not enabled on this deployment yet.'; return; }
      if(!me.signedIn){ gate.innerHTML=
        'Sign in (top right) to attach a league to your account.'; return; }
      gate.hidden=true; main.hidden=false;
      document.getElementById('ls-sleeper-go').addEventListener('click',function(){
        add('sleeper','ls-sleeper','ls-sleeper-msg',this);});
      document.getElementById('ls-espn-go').addEventListener('click',function(){
        add('espn','ls-espn','ls-espn-msg',this);});
      document.getElementById('ls-user-go').addEventListener('click',function(){
        findAll(this);});
      document.getElementById('ls-user').addEventListener('keydown',function(e){
        if(e.key==='Enter') findAll(document.getElementById('ls-user-go'));});
      load();
    })
    .catch(function(){ gate.textContent='Could not reach the server.'; });
})();
</script>{% endraw %}"""


def body() -> str:
    return (CSS + "<div class='ls-wrap'>"
            "<p class='ls-gate' id='ls-gate'>Loading…</p>"
            "<div id='ls-main' hidden>"

            "<div class='ls-card'><h2>Your synced leagues</h2>"
            "<ul class='ls-list' id='ls-list'></ul></div>"

            "<div class='ls-card'><h2>Find my leagues</h2>"
            "<p>Your Sleeper username - the one you sign in with. Every NFL "
            "league that account is in is added at once, each with its earlier "
            "seasons and your team name in each of them. Nothing is asked of "
            "your Sleeper account: this is read through Sleeper's public API, "
            "and no password or token is involved.</p>"
            "<div class='ls-row'><input id='ls-user' type='text' "
            "autocapitalize='none' autocorrect='off' spellcheck='false' "
            "placeholder='sleeper username' aria-label='Sleeper username'>"
            "<button id='ls-user-go' type='button'>Find my leagues</button></div>"
            "<p class='ls-msg' id='ls-user-msg'></p></div>"

            "<details class='ls-card'><summary>Add one league by id instead"
            "</summary>"
            "<p>The id is the long number in that league's web address: "
            "<code>sleeper.com/leagues/<strong>1234567890123456</strong>/team</code>."
            "</p>"
            "<div class='ls-row'><input id='ls-sleeper' type='text' "
            "inputmode='numeric' placeholder='Sleeper league id' "
            "aria-label='Sleeper league id'>"
            "<button id='ls-sleeper-go' type='button'>Add it</button></div>"
            "<p class='ls-msg' id='ls-sleeper-msg'></p></details>"

            "<div class='ls-card'><h2>An ESPN league</h2>"
            "<p>Paste the league's web address, or the <code>leagueId</code> number in "
            "it: <code>fantasy.espn.com/football/league?leagueId=<strong>123456</strong></code>. "
            "Its earlier seasons come with it. ESPN only shows a league its commissioner "
            "has made public (League Manager, Basic Settings) - no ESPN login is asked "
            "for or kept.</p>"
            "<div class='ls-row'><input id='ls-espn' type='text' "
            "autocapitalize='none' autocorrect='off' spellcheck='false' "
            "placeholder='ESPN league id or address' aria-label='ESPN league id or web address'>"
            "<button id='ls-espn-go' type='button'>Add it</button></div>"
            "<p class='ls-msg' id='ls-espn-msg'></p></div>"

            "<p class='ls-meta'>A league can be re-synced every five minutes. "
            "Removing it deletes the row; deleting your account takes every "
            "synced league with it. Once a league is here, "
            "<a href='/fantasy/matchups/'>Matchups</a>, "
            "<a href='/fantasy/roster/'>My Team</a> and "
            "<a href='/fantasy/usage/'>Usage</a> all read yours instead of "
            "this site's.</p>"
            "</div></div>" + JS)


def generate(out, title: str = "Sync your league") -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(add_front_matter(body(), title,
                                    "Attach your own fantasy league to your account"),
                   encoding="utf-8")
    print(f"Wrote {title} -> {out}")
