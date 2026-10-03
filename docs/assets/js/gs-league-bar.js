/* The league bar (#ml-bar) and window.GSLeague.
   Source file, loaded by gordstats.my_league (JS_TAG); see gordstats.js_assets. */
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
  // Every season's id (fantasy.config.LEAGUE_IDS), set by the page (GSCFG).
  var SITE=((window.GSCFG||{}).siteLeagues||[]).map(String);
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
    msg(quiet?'':'Reading the league\u2026');
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
    return l.team_name ? (name+' — '+l.team_name) : name;
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
      +'<button type="button" id="ml-back">'+(theirs?'Back to yours':'This site’s league')
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
            ? '<option value="site"'+(here?'':' selected')+'>This site\u2019s league</option>'
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
        +'<button type="button" id="ml-clear">Show this site\u2019s league</button>'
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
        msg(signedIn===false?'Paste a league id — the number in its web address.'
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
    msg('Asking ESPN…');
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
    msg('Asking Sleeper…');
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
          + 'league’s '+noun+'.</p>';
      }
      return '<p class="'+cls+'">Pick a league above, or '
        + '<a href="/fantasy/sync/">connect yours</a>, to see its '+noun+'.</p>';
    }
  };
})();
