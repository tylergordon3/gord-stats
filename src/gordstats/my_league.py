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

from gordstats import league_api

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
  // This site's own league, every season of it. Picked by id - synced from
  // an account, or typed in - it is still this league, and gets the built
  // pages rather than the plainer ones drawn in the browser for somebody
  // else's (site_league_js has already said so before anything painted).
  var SITE=__SITE_IDS__;
  function isSite(id){ return !!id && SITE.indexOf(String(id))>=0; }
  function save(v){
    if(v && isSite(v.id)) v.site=true;
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
      html+='<option value="'+k+'">'+names[k].replace(/[&<>"']/g,function(c){
        return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];})+'</option>';
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

  // Each load() is numbered, and only the newest may save or draw: the page's
  // own league is read at once and the account's answer can ask for another
  // before the first comes back - a late first answer used to write itself
  // over the second.
  var loads=0;
  function load(id,quiet){
    var mine=++loads;
    msg(quiet?'':'Reading the league\\u2026');
    var path='/league/'+encodeURIComponent(id);
    return Promise.all([GSAPI.get(path+'/rosters'), GSAPI.get(path+'/users'),
                        GSAPI.get(path)]).then(function(out){
      if(mine!==loads) return false;                 // a newer pick took over
      if(!out[0]||!out[1]) throw new Error('not found');
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
      var before=String((saved()||{}).id||'');
      save(GSAPI.isEspn(id)?{id:id, name:label, provider:'espn'}:{id:id, name:label});
      apply(held,names,label);
      msg('');
      // Pages that render the league from this key read it once, at load, so
      // whenever the saved league changes they are drawn again - not only
      // when there was none before, which left the bar naming the account's
      // league over a page still showing the one this browser had.
      // (Only if it was kept: with storage blocked a reload shows the same
      // page again, and would again ask for the reload.)
      if(!owns && before!==String(id) && String((saved()||{}).id||'')===String(id))
        location.reload();
      return true;
    }).catch(function(e){
      if(mine!==loads) return false;
      if(e && e.name==='TypeError' && window.console) console.error('[my-league]', e);
      // In the words of the site the league is on: ESPN's private-league
      // advice for a league ESPN refused, not "check the id".
      msg(GSAPI.isPrivate(id) ? GSAPI.PRIVATE
          : GSAPI.isEspn(id) ? 'Could not read that league from ESPN. Check the id, or try again in a minute.'
          : 'Could not read that league. Check the id.','err');
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
    return String(v==null?'':v).replace(/[&<>"']/g,function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});
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

  /** Whose league a shared link is showing, with the two ways out of it:
   *  keep it, or go back to their own (or this site's). */
  function drawVisit(label){
    var own=GSVisit.own()||{};
    var theirs=!!(own.id&&!own.site&&!isSite(own.id));
    bar.className='ml-bar ml-vis';
    bar.innerHTML='<span class="ml-label">Shared with you</span><span class="ml-who"></span>'
      +'<button type="button" class="ml-keep" id="ml-keep">Use this league</button>'
      +'<button type="button" id="ml-back">'+(theirs?'Back to yours':'This site\u2019s league')
      +'</button><span class="ml-msg" id="ml-msg"></span>';
    bar.querySelector('.ml-who').textContent=label||'A shared league';
    document.getElementById('ml-keep').addEventListener('click',keep);
    document.getElementById('ml-back').addEventListener('click',function(){
      GSVisit.end();
      location.reload();
    });
  }

  /** "Use this league": the shared league becomes this browser's saved one,
   *  and the account's too when there is one (the same best-effort POST as
   *  connecting by username), or the account's list would put the reader
   *  back on its first league on the next page. */
  function keep(){
    var v=GSVisit.keep();
    if(!v) return;
    var row={provider:v.provider==='espn'?'espn':'sleeper', league_id:String(v.id),
             name:v.name||'', lineage_id:String(v.id)};
    if(SYNCED.length && !SYNCED.some(function(l){ return String(l.league_id)===row.league_id; })){
      SYNCED=[row].concat(SYNCED);
      saveList(SYNCED);
    }
    if(signedIn) fetch('/api/leagues',{method:'POST',credentials:'same-origin',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({provider:row.provider, league_id:row.league_id})})
      .catch(function(){ /* best effort */ });
    draw(v.name);
  }

  function visiting(){ return !!(window.GSVisit&&GSVisit.league()); }

  function draw(label){
    if(visiting()){ drawVisit(label||(GSVisit.league()||{}).name); return; }
    bar.className='ml-bar';
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
    // nothing to pick between, so it is named with a way back - unless it is
    // this site's own, which is what is on screen anyway.
    if(label && !isSite(cur.id)){
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
        + '<span class="ml-or">or paste a Sleeper or ESPN league id</span>'
      : '<span class="ml-label">Your Sleeper username, or an ESPN league id</span>';
    // The placeholders say what the labels say, because a phone drops the
    // labels to keep the bar to one line (see the CSS).
    bar.innerHTML=out
      +'<input id="ml-id" type="text" autocapitalize="none" autocorrect="off" '
      +'spellcheck="false" placeholder="'+(signedIn===false?'or paste a league id'
                                           :'Sleeper username or ESPN league id')+'" '
      +'aria-label="'+(signedIn===false?'Sleeper or ESPN league id'
                    :'Sleeper username, or a Sleeper or ESPN league id')+'">'
      +'<button type="button" id="ml-go">'+(signedIn===false?'Show':'Connect')+'</button>'
      +'<span class="ml-msg" id="ml-msg"></span>';
    function go(){
      var btn=document.getElementById('ml-go');
      var v=(document.getElementById('ml-id').value||'').trim();
      if(!v){
        msg(signedIn===false?'Paste a league id \u2014 the number in its web address.'
                            :'Enter your Sleeper username or an ESPN league id.','err');
        return;
      }
      btn.disabled=true;
      var done=function(){ btn.disabled=false; };
      // A league id or web address - Sleeper's or ESPN's - or a username.
      var ref=GSAPI.parseRef(v);
      if(ref && ref.id) load(ref.id).then(done);
      else if(ref) espn(ref).then(done);
      else connect(v).then(done);
    }
    document.getElementById('ml-go').addEventListener('click',go);
    document.getElementById('ml-id').addEventListener('keydown',function(e){
      if(e.key==='Enter') go();
    });
  }

  /** An ESPN league by its id: this season's, or last season's if it has not
   *  been renewed yet. ESPN answers only a league set public, and says so,
   *  which is worth passing on - the fix is one setting, not a login. */
  function espn(ref){
    msg('Asking ESPN\u2026');
    return GSAPI.resolve(ref.league, ref.season).then(function(res){
      if(res.id) return load(res.id);
      msg(res.error==='private' ? GSAPI.PRIVATE
        : res.error==='missing' ? 'ESPN has no football league with that id.'
        : 'Could not reach ESPN. Try again in a minute.', 'err');
      return false;
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
  // This site's own league is already what every built page shows.
  if(have&&have.id&&!isSite(have.id)){ draw(have.name); load(have.id,true); }
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
      // Signed out answers 200 with signedIn:false (a 401 was a console
      // error on every page); the 401 check above stays for older deploys.
      if(d && d.signedIn===false) signedIn=false;
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
      var groups=leagues(d.leagues.filter(function(l){
        return l.provider==='sleeper' || l.provider==='espn';}));
      var fromAccount=groups.map(function(g){ return g.current; });
      if(fromAccount.length){ SYNCED=fromAccount; saveList(SYNCED); }
      if(!SYNCED.length) return;
      // A league shared by link is what this visit is for: the account's own
      // leagues wait until the reader goes back to them.
      if(visiting()){ draw(); return; }
      // "Show this site's league" was a choice a signed-in reader with a
      // league of their own can no longer make, so an old one is not honoured
      // - they are put back on their own league instead.
      if(have&&have.site&&!isSite(have.id)) have=null;
      // Keep showing whatever this browser already had, if the account knows
      // it - in any of its seasons: last season's id, saved before the
      // league renewed, is that league, and moves on to its newest season
      // rather than to whichever league the account lists first.
      var chosen=SYNCED.filter(function(l){
        return have&&String(l.league_id)===String(have.id);})[0];
      if(!chosen && have && have.id){
        var g=groups.filter(function(x){
          return x.seasons.some(function(l){ return String(l.league_id)===String(have.id); });
        })[0];
        if(g) chosen=g.current;
      }
      chosen=chosen||SYNCED[0];
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
        // The bar above already has the Sign in button; a second one here
        // made three sign-in offers on one phone screen.
        return '<p class="'+cls+'">Paste a league id above, or sign in, to see your '
          + 'league\u2019s '+noun+'.</p>';
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
JS = league_api.JS + JS.replace("__SITE_IDS__", repr(_site_ids()))
