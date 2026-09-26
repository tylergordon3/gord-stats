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
"""

CSS = """<style>
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
  .ml-bar{gap:6px}
  .ml-bar .ml-label{flex:1 1 100%;font-size:12.5px}
  .ml-bar input{min-width:0;flex:1}
  .ml-bar select{flex:1;min-width:0;max-width:none}
  .ml-bar button{white-space:nowrap}
  .ml-bar .ml-msg{flex:1 1 100%}
  .ml-bar .ml-or{flex:1 1 100%}
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
}
</style>"""

JS = """{% raw %}<script>
(function(){
  var KEY='gsSleeperLeague';          // {id, name} of the league being shown
  var LIST='gsSleeperLeagues';        // every league this browser knows about
  var bar=document.getElementById('ml-bar');
  if(!bar) return;
  // The usage table is the thing whose ownership can be re-pointed. On the
  // matchups page there is none: the league is picked here and a different
  // script draws it, so everything below is guarded rather than assumed.
  var table=document.querySelector('table.us');
  var sel=document.getElementById('us-own');
  var owns=!!(table&&sel&&table.tBodies[0]);
  var rows=owns?Array.prototype.slice.call(table.tBodies[0].rows):[];
  // The league the page was built with, kept so "show this site's league"
  // can put everything back without a reload.
  var BUILT=rows.map(function(r){return r.dataset.own||'';});
  var builtOptions=owns?sel.innerHTML:'';

  function saved(){
    try{ return JSON.parse(localStorage.getItem(KEY)||'null'); }catch(e){ return null; }
  }
  // The leagues found for this browser, kept beside the chosen one. Without
  // this, connecting by username signed out found four leagues and then lost
  // three of them on the next page load: the list only existed in memory, and
  // /api/leagues has nothing to say to someone who is not signed in.
  function savedList(){
    try{ return JSON.parse(localStorage.getItem(LIST)||'[]')||[]; }catch(e){ return []; }
  }
  function saveList(rows){
    try{
      if(rows&&rows.length) localStorage.setItem(LIST,JSON.stringify(rows));
      else localStorage.removeItem(LIST);
    }catch(e){}
  }
  function save(v){
    try{ v?localStorage.setItem(KEY,JSON.stringify(v)):localStorage.removeItem(KEY); }
    catch(e){}
  }
  function msg(text,cls){
    var el=document.getElementById('ml-msg');
    el.textContent=text||''; el.className='ml-msg'+(cls?' '+cls:'');
  }

  function apply(held,names,label){
    if(!owns){ draw(label); return; }
    rows.forEach(function(r){
      var own=held[r.dataset.pid]||'';
      r.dataset.own=own;
      var cell=r.querySelector('td.us-own');
      if(cell) cell.innerHTML=own
        ? names[own].replace(/[&<>]/g,function(c){
            return {'&':'&amp;','<':'&lt;','>':'&gt;'}[c];})
        : '<span class="us-fa">FA</span>';
    });
    // The Fantasy filter is a list of this league's teams, so it is rebuilt
    // from the same maps rather than left pointing at the old one.
    var keys=Object.keys(names).sort(function(a,b){
      return names[a].toLowerCase()<names[b].toLowerCase()?-1:1;});
    var html='<option value="">Everyone</option>'
      +'<option value="fa">Free agents</option>'
      +'<option value="held">Rostered</option><optgroup label="Teams">';
    keys.forEach(function(k){
      html+='<option value="'+k+'">'+names[k].replace(/[&<>"]/g,function(c){
        return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];})+'</option>';
    });
    sel.innerHTML=html+'</optgroup>';
    rows.forEach(function(r){ r.classList.remove('us-mine'); });
    sel.value='';
    sel.dispatchEvent(new Event('change'));
    draw(label);
  }

  function restore(){
    if(owns){
      rows.forEach(function(r,i){ r.dataset.own=BUILT[i]; });
      sel.innerHTML=builtOptions;
      sel.value='';
      sel.dispatchEvent(new Event('change'));
    }
    save({site:true});
    location.reload();   // the built cells are the simplest thing to put back
  }

  function load(id,quiet){
    msg(quiet?'':'Reading the league\\u2026');
    return Promise.all([
      fetch('https://api.sleeper.app/v1/league/'+encodeURIComponent(id)+'/rosters'),
      fetch('https://api.sleeper.app/v1/league/'+encodeURIComponent(id)+'/users'),
      fetch('https://api.sleeper.app/v1/league/'+encodeURIComponent(id))
    ]).then(function(rs){
      if(!rs[0].ok||!rs[1].ok) throw new Error('not found');
      return Promise.all(rs.map(function(r){return r.ok?r.json():null;}));
    }).then(function(out){
      var rosters=out[0]||[], users=out[1]||[], league=out[2]||{};
      var byUser={};
      users.forEach(function(u){
        var team=(u.metadata&&u.metadata.team_name)||u.display_name||'Team';
        var mgr=u.display_name||'';
        byUser[u.user_id]=(mgr&&team.indexOf(mgr)<0)?(team+' ('+mgr+')'):team;
      });
      var held={}, names={};
      rosters.forEach(function(ro){
        var key=String(ro.roster_id);
        names[key]=byUser[ro.owner_id]||('Team '+key);
        (ro.players||[]).forEach(function(pid){ held[String(pid)]=key; });
      });
      if(!Object.keys(names).length) throw new Error('empty');
      var label=league.name||('League '+id);
      var first=!(saved()||{}).id;
      save({id:id, name:label});
      apply(held,names,label);
      msg('');
      // Pages that render the league from this key read it once, at load.
      if(!owns&&first) location.reload();
      return true;
    }).catch(function(){
      msg('Could not read that league. Check the id.','err');
      return false;
    });
  }

  // Leagues synced to the account, filled in once /api/leagues answers. More
  // than one is normal for anybody in two, and picking the first silently left
  // the rest unreachable.
  var SYNCED=savedList();

  // Whether there is an account behind this browser. Learned from the
  // /api/leagues call below rather than a second request: it answers 401 when
  // nobody is signed in, 503 when this deploy has no accounts at all, and 200
  // with the leagues when there is somebody. `null` until it answers, which is
  // why nothing is drawn as signed-out until we actually know.
  var signedIn=null;

  function esc(v){
    return String(v==null?'':v).replace(/[&<>"]/g,function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});
  }

  /** "League - Your Team": two leagues named the same thing are otherwise the
   *  same entry twice, and people do name them the same thing.
   *
   *  Not called `label`: draw() takes a parameter by that name, which shadowed
   *  this inside the one function that needs it. */
  function leagueLabel(l){
    var name=l.name||('League '+l.league_id);
    return l.team_name ? (name+' \u2014 '+l.team_name) : name;
  }

  /** Labels for a set of leagues, guaranteed to differ from one another.
   *
   *  The team name is what usually separates two leagues called the same
   *  thing, and it is there for anything synced since team names were stored.
   *  A row from before that has none, so the season and then the tail of the
   *  id are added until the entries are actually distinguishable - an option
   *  list with the same words twice is a choice nobody can make.
   */
  function labelsFor(list){
    var out=list.map(leagueLabel);
    var seen={};
    out.forEach(function(v){ seen[v]=(seen[v]||0)+1; });
    return out.map(function(v,i){
      if(seen[v]<2) return v;
      var l=list[i];
      var extra=l.season||('#'+String(l.league_id).slice(-4));
      return v+' ('+extra+')';
    }).map(function(v,i,all){
      // Still equal? Only an id can separate them.
      var again={};
      all.forEach(function(x){ again[x]=(again[x]||0)+1; });
      return again[v]<2 ? v : v+' #'+String(list[i].league_id).slice(-4);
    });
  }

  /** One entry per league, newest season first.
   *
   *  A synced league is one row per season, so a reader in four leagues with a
   *  few years of history each has a dozen rows - listing them raw would be a
   *  dozen near-identical picker entries. They group on lineage_id, which is
   *  the oldest league id in the chain and therefore stable as seasons are
   *  added. */
  function leagues(rows){
    var groups={};
    rows.forEach(function(l){
      var key=l.lineage_id||l.league_id;
      (groups[key]=groups[key]||[]).push(l);
    });
    return Object.keys(groups).map(function(k){
      var seasons=groups[k].slice().sort(function(a,b){
        return String(b.season||'').localeCompare(String(a.season||''));});
      return {current:seasons[0], seasons:seasons};
    });
  }

  function draw(label){
    var cur=saved()||{};
    // A picker whenever there are leagues to pick between, whatever is on
    // screen right now - and this site's league is one of the choices rather
    // than a door that only opens one way.
    //
    // It used to appear only while a league of the reader's own was already
    // showing, so anyone who had pressed "Show this site's league" was left
    // with a username box for ever: signed in, leagues synced, and no way back
    // to them but typing the name in again.
    if(SYNCED.length){
      var here=String(cur.id||'');
      var labels=labelsFor(SYNCED);
      // Somebody signed in with a league of their own is here for that
      // league, and offering this site's alongside it only invites the
      // question of whose numbers are on screen. It stays in the list for a
      // reader with nothing synced - it is the whole site for them - and
      // comes back if the account turns out to be signed out.
      var offerSite=(signedIn===false);
      bar.innerHTML='<label>League <select id="ml-pick">'
        + (offerSite
            ? '<option value="site"'+(here?'':' selected')+'>This site\\u2019s league</option>'
            : '')
        + SYNCED.map(function(l,i){
            return '<option value="'+esc(l.league_id)+'"'
              + ((String(l.league_id)===here
                  || (!offerSite && !here && i===0))?' selected':'') + '>'
              + esc(labels[i]) + '</option>';
          }).join('')
        + '</select></label><span class="ml-msg" id="ml-msg"></span>';
      document.getElementById('ml-pick').addEventListener('change',function(){
        var want=this.value;
        if(want==='site'){ restore(); return; }
        var chosen=SYNCED.filter(function(l){
          return String(l.league_id)===String(want);})[0];
        if(!chosen) return;
        save({id:chosen.league_id, name:leagueLabel(chosen)});
        // Pages that render from the stored key read it once, at load.
        if(owns) load(chosen.league_id); else location.reload();
      });
      return;
    }
    // A league entered by id, which the account does not know about: there is
    // nothing to pick between, so it is named with a way back.
    if(label){
      bar.innerHTML='Showing <span class="ml-who"></span> '
        +'<button type="button" id="ml-clear">Show this site\\u2019s league</button>'
        +'<span class="ml-msg" id="ml-msg"></span>';
      bar.querySelector('.ml-who').textContent=label;
      document.getElementById('ml-clear').addEventListener('click',restore);
      return;
    }
    // Connecting happens here rather than on a settings page: a reader who
    // wants their own league is already looking at a page that would show it.
    //
    // What is offered depends on whether there is an account. Finding every
    // league from a username is a sync - it belongs to somebody - so signed
    // out that is a sign-in prompt, and a league id, which needs nobody and
    // lives in this browser, stays open to everyone. One field either way,
    // because a username and an id cannot be mistaken for each other: an id is
    // a long run of digits and a username is not.
    var out=signedIn===false
      ? '<span class="ml-label">Your leagues, on every device</span>'
        + '<a class="ml-in" href="/api/auth/login?next='
        + encodeURIComponent(location.pathname+location.search) + '">Sign in</a>'
        + '<span class="ml-or">or paste a league id</span>'
      : '<span class="ml-label">Your Sleeper username</span>';
    bar.innerHTML=out
      +'<input id="ml-id" type="text" autocapitalize="none" autocorrect="off" '
      +'spellcheck="false" placeholder="'+(signedIn===false?'league id':'username')+'" '
      +'aria-label="'+(signedIn===false?'Sleeper league id':'Sleeper username, or a league id')+'">'
      +'<button type="button" id="ml-go">'+(signedIn===false?'Show':'Connect')+'</button>'
      +'<span class="ml-msg" id="ml-msg"></span>';
    function go(){
      var btn=document.getElementById('ml-go');
      var v=(document.getElementById('ml-id').value||'').trim();
      if(!v){
        msg(signedIn===false?'Paste a league id — the long number in its URL.'
                            :'Enter your Sleeper username.','err');
        return;
      }
      btn.disabled=true;
      var done=function(){ btn.disabled=false; };
      if(/^[0-9]{6,32}$/.test(v)) load(v).then(done);       // a league id
      else connect(v).then(done);                           // a username
    }
    document.getElementById('ml-go').addEventListener('click',go);
    document.getElementById('ml-id').addEventListener('keydown',function(e){
      if(e.key==='Enter') go();
    });
  }

  /** Every league a Sleeper account is in, found from the username.
   *
   *  Resolved in the browser so it works signed out - the league is then kept
   *  in this browser like a starred team. Signing in only adds persistence,
   *  so the POST is a best-effort extra rather than the thing that makes it
   *  work.
   */
  function connect(username){
    if(signedIn===false){
      msg('Sign in first — finding every league from a username saves them to '
          +'your account.','err');
      return Promise.resolve(false);
    }
    msg('Asking Sleeper\u2026');
    var API='https://api.sleeper.app/v1';
    return fetch(API+'/user/'+encodeURIComponent(username))
      .then(function(r){ return r.ok?r.json():null; })
      .then(function(user){
        if(!user||!user.user_id) throw new Error('no user');
        return fetch(API+'/state/nfl').then(function(r){return r.json();})
          .then(function(st){
            return fetch(API+'/user/'+user.user_id+'/leagues/nfl/'
                         +(st&&st.season||new Date().getFullYear()))
              .then(function(r){ return r.ok?r.json():[]; });
          });
      })
      .then(function(lgs){
        if(!lgs||!lgs.length) throw new Error('no leagues');
        SYNCED=lgs.map(function(l){
          return {provider:'sleeper', league_id:String(l.league_id),
                  name:l.name, season:String(l.season||''),
                  lineage_id:String(l.league_id)};
        });
        saveList(SYNCED);
        // Persist to the account when there is one; the page does not wait on
        // it, and nothing breaks when it is not there.
        fetch('/api/leagues',{method:'POST',credentials:'same-origin',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({provider:'sleeper', username:username})})
          // The endpoint is the authority - it answers 401 to anyone without a
          // session - so this is belt and braces over the check in connect().
          .catch(function(){ /* best effort */ });
        msg('');
        draw(leagueLabel(SYNCED[0]));
        return load(SYNCED[0].league_id, true);
      })
      .catch(function(){
        msg('Sleeper has no NFL leagues for that username this season.','err');
        return false;
      });
  }

  var have=saved();
  if(have&&have.id){ draw(have.name); load(have.id,true); }
  else draw(null);

  // A league synced to the account wins over whatever this browser remembers,
  // so a second device shows the same thing without being told again.
  var accountReady = fetch('/api/leagues',{credentials:'same-origin'})
    .then(function(r){
      // The status is the answer, not a failure to handle. 401 is "nobody is
      // signed in"; 503 is "this deploy has no accounts at all", which is not
      // the same thing and must not become a sign-in link that goes nowhere.
      if(r.status===401) signedIn=false;
      else if(r.ok) signedIn=true;
      return r.ok?r.json():null;
    })
    .then(function(d){
      var mine=d&&d.leagues&&d.leagues.length;
      if(!mine){
        // No account, or an account with nothing synced - and the bar reads
        // differently now that we know which. A signed-out reader is offered
        // a sign-in rather than a username box that cannot sync, and this
        // site's league goes back in the picker for anyone who may want it.
        // The saved name is passed so a league entered by id keeps its label.
        var cur=saved()||{};
        draw(cur.id?(cur.name||null):null);
        return;
      }
      // One entry per league, not one per season.
      // The account is the better answer when there is one: it has the team
      // names and the season history this browser's own list does not.
      var fromAccount=leagues(d.leagues.filter(function(l){
        return l.provider==='sleeper';})).map(function(g){ return g.current; });
      if(fromAccount.length){ SYNCED=fromAccount; saveList(SYNCED); }
      if(!SYNCED.length) return;
      // "Show this site's league" was a choice a signed-in reader with a
      // league of their own can no longer make, so an old one is not honoured
      // - they are put back on their own league instead.
      if(have&&have.site) have=null;
      // Keep showing whatever this browser already had, if the account knows
      // it; otherwise the first synced league.
      var chosen=SYNCED.filter(function(l){
        return have&&String(l.league_id)===String(have.id);})[0] || SYNCED[0];
      if(!have||String(have.id)!==String(chosen.league_id)){
        draw(leagueLabel(chosen));
        load(chosen.league_id,true);
      } else {
        draw(leagueLabel(chosen));               // redraw, now with the picker
      }
    })
    // A network failure here is expected (signed out, or no accounts on this
    // deploy) and says nothing. A TypeError is a bug in the lines above, and
    // swallowing it cost an afternoon - so it goes to the console.
    .catch(function(e){
      if(e && e.name !== 'TypeError') return;
      if(window.console) console.error('[my-league]', e);
    });

  /** The empty state for a section that has no league to show.
   *
   *  Shared because there are four of these and they were four copies of the
   *  same sentence, which is how three of them come to say "connect yours"
   *  and one "sync yours". What it says depends on whether there is an
   *  account to connect to, and that is not known at first paint - so the
   *  caller draws it, waits on `ready`, and draws it again.
   */
  window.GSLeague = {
    ready: accountReady,
    signedIn: function(){ return signedIn; },
    empty: function(cls, noun){
      if(signedIn===false){
        return '<p class="'+cls+'">Sign in to see your league\u2019s '+noun+'. '
          + '<a class="ml-in" href="/api/auth/login?next='
          + encodeURIComponent(location.pathname+location.search)
          + '">Sign in</a></p>';
      }
      return '<p class="'+cls+'">Pick a league above, or '
        + '<a href="/fantasy/sync/">connect yours</a>, to see its '+noun+'.</p>';
    }
  };
})();
</script>{% endraw %}"""


def bar() -> str:
    """The control itself; the script fills it in."""
    return CSS + "<div class='ml-bar' id='ml-bar'></div>"


def takeover(mine: str, built: str) -> str:
    """One of two blocks, chosen before the page paints.

    League Home and Analytics both hold two versions of themselves: this
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
