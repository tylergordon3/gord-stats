/* The weekly recap for a reader's league (/fantasy/recap/).
   Source file, loaded by gordstats.my_recap (JS_TAG); see gordstats.js_assets. */
(function(){
  var host=document.getElementById('rc-host');
  if(!host||!window.GSL||!window.GSAPI||!window.GSPlan||!window.GSRecap) return;
  var have=GSL.saved();
  if(!have||!have.id||have.site) return;          // this site's recap stands
  var R=window.GSRecap, esc=R.esc;
  var ID=String(have.id), API='/league/'+encodeURIComponent(ID);
  var ESPN=GSAPI.isEspn(ID), SITE=ESPN?'ESPN':'Sleeper';
  // The week this address is for (a /week-N/ page); 0 opens on the latest.
  var PIN=parseInt(host.dataset.week||'0',10)||0;
  var AVATAR='https://sleepercdn.com/avatars/thumbs/';
  // The recap's front page, from this page or a week's (/week-N/).
  var BASE=location.pathname.replace(/week-\d+\/?$/, '');
  // share_button.row('', '', league=True), set by the page (GSCFG).
  var SHARE=String((window.GSCFG||{}).recapShare||'');
  var CTX=null, NAME='', WEEKS=[], ROSTERS=[], CUR=0;
  // Kept for the page view: a week read once is drawn again from memory, and
  // the season columns reuse every week the reader has already opened.
  var ASKED={}, BUILT={}, TX={}, TXV={}, REST={}, DONE={};

  // Busy while anything of the week on screen is still to come: the season
  // columns, or a pickup card that lands once the transactions are read.
  function busy(on){ host.setAttribute('aria-busy', on?'true':'false'); }
  function note(html, done){
    host.innerHTML='<p class="rc-note">'+html+'</p>';
    busy(!done);
  }

  /** A week, built - or null if the site would not say. Asked with its
   *  lineups, which an ESPN league has for this week and last only unless
   *  asked; its rows also say who was on injured reserve that week. */
  function weekFor(k){
    if(ASKED[k]) return ASKED[k];
    var p=ASKED[k]=GSAPI.get(API+'/matchups/'+k, {lineups:true}).then(function(rows){
      if(!rows||!rows.length) return null;
      var ir=null;
      rows.forEach(function(r){
        if(r.reserve) (ir=ir||{})[String(r.roster_id)]=r.reserve.map(String);
      });
      var w=R.build(k, rows, CTX, ir);
      return (BUILT[k]=w.order.length?w:null);
    }).catch(function(e){
      if(e instanceof TypeError && window.console) console.error('[recap]', e);
      return null;
    });
    // A failure is not kept: the next ask tries again.
    p.then(function(w){ if(!w && ASKED[k]===p) delete ASKED[k]; });
    return p;
  }

  function txFor(leg){
    if(TX[leg]) return TX[leg];
    return (TX[leg]=GSAPI.get(API+'/transactions/'+leg).catch(function(){ return null; })
      .then(function(t){ TXV[leg]=t||null; return t; }));
  }

  /** What the week's pickups need: the week before (and the transactions
   *  that say who came in a trade), or for the first week the claims since
   *  the draft. null while any of it is still to be read. */
  function pickupsFor(k){
    var first=k<=WEEKS[0], legs=first?[k]:[k-1, k];
    if(legs.some(function(l){ return !(l in TXV); })) return DONE[k]?[]:null;
    if(legs.some(function(l){ return !TXV[l]; })) return [];    // unreadable: no award
    if(!first && !BUILT[k-1]) return DONE[k]?[]:null;
    var txs=[];
    legs.forEach(function(l){ txs=txs.concat(TXV[l]); });
    return R.pickups(BUILT[k], first?null:BUILT[k-1].held, txs);
  }

  /** The season and the pickups, once the week itself is on screen. */
  function rest(k){
    if(REST[k]) return REST[k];
    var jobs=WEEKS.filter(function(n){ return n<=k; }).map(weekFor);
    (k>WEEKS[0]?[k-1, k]:[k]).forEach(function(l){ jobs.push(txFor(l)); });
    return (REST[k]=Promise.all(jobs));
  }

  function mine(){
    var names={};
    Object.keys(CTX.teams).forEach(function(k){ names[k]=CTX.teams[k].name; });
    return GSL.myRoster({rosters:ROSTERS, names:names}, ID);
  }

  function foot(span, yours){
    var held=span.some(function(w){ return w.unplaced>0; });
    return '<p class="rc-note rc-src">From '+SITE+', as this page opened.'
      +(yours?' Your team is the row with the green edge.':'')
      +' Not here: <b>Beat</b> and <b>Missed the projection</b>, and the <b>power '
      +'risers</b> and <b>fallers</b> - they need GordStats’ projections from before '
      +'kickoff and a power-rankings history, which this site keeps for its own league only.'
      +(ESPN?'':' Sleeper does not say who was on injured reserve in a past week, so a '
        +'player on it now counts as out only in a week he scored nothing.')
      +(held?' This league starts players this site has no position for (defensive '
        +'players, mostly): they are held where they started, and the best lineup is '
        +'found around them.':'')
      +'</p>';
  }

  /** The Share button, as the built recap has it, for this league's week:
   *  the address carries the league (share.js adds ?league=<id>), so a
   *  friend opens the same league on the same week. */
  function share(k, w){
    var d=document.createElement('div');
    d.innerHTML=SHARE;
    var b=d.querySelector('.gs-share');
    if(b){
      b.setAttribute('data-url', BASE+'#week-'+k);
      b.setAttribute('data-text', NAME+' \u2014 '+R.headline(w));
    }
    return d.innerHTML;
  }

  /** A team without a picture gets its initial on its disc (see the CSS),
   *  where there are pictures beside it - with none, no disc is shown. Put
   *  in after the markup is drawn, which stays the built recap's own. */
  function initials(){
    if(host.classList.contains('rc-noav')) return;
    [].forEach.call(host.querySelectorAll('span.rc-av:empty'), function(d){
      var n=d.nextElementSibling;
      var t=String((n&&n.textContent)||'').replace(/^[^A-Za-z0-9]+/, '');
      d.textContent=t.charAt(0).toUpperCase();
      d.setAttribute('aria-hidden', 'true');
    });
  }

  /** The page's title is the built week's and its line this site's league. */
  function retitle(k){
    var h=document.querySelector('h1');
    if(h) h.textContent='NFL Week '+k+' Recap';
    var sub=document.querySelector('.page-sub');
    if(!sub && h){
      sub=document.createElement('p');
      sub.className='page-sub';
      h.insertAdjacentElement('afterend', sub);
    }
    if(sub) sub.textContent=NAME;
  }

  function draw(k){
    CUR=k;
    var w=BUILT[k];
    if(!w){
      note('Reading week '+k+'&hellip;');
      weekFor(k).then(function(got){
        if(CUR!==k) return;
        if(got) draw(k);
        else note('Could not read week '+k+' of '+esc(NAME)+' from '+SITE
                  +'. Try again in a minute.', true);
      });
      return;
    }
    var span=[], whole=true;
    WEEKS.forEach(function(n){
      if(n>k) return;
      if(BUILT[n]) span.push(BUILT[n]); else whole=false;
    });
    var pk=pickupsFor(k);
    w.pickups=pk||[];
    var settled=whole && pk!==null, yours=mine();
    host.classList.toggle('rc-noav', !Object.keys(CTX.teams).some(function(t){
      return CTX.teams[t].avatar; }));
    host.innerHTML=share(k, w)+R.view(w, WEEKS, whole?R.season(span):null,
                          {pending:!settled && !DONE[k], mine:yours, foot:foot(span, yours)});
    initials();
    busy(!settled && !DONE[k]);
    retitle(k);
    if(!settled && !DONE[k]) rest(k).then(function(){
      DONE[k]=1;
      if(CUR===k) draw(k);
    });
  }

  note('Reading '+esc(have.name||'your league')+'&hellip;');
  var asks=[GSAPI.get(API), GSL.players()];
  // ESPN's rosters are the heaviest thing it serves, and nothing here needs
  // them but the team names, which come lighter.
  if(ESPN) asks.push(null, null, GSAPI.teams(ID));
  else asks.push(GSAPI.get(API+'/rosters'), GSAPI.get(API+'/users'));
  Promise.all(asks.map(function(p){
    return Promise.resolve(p).catch(function(){ return null; });
  })).then(function(o){
    var info=o[0];
    if(!info) throw new Error('league');
    var st=info.settings||{};
    NAME=info.name||have.name||'Your league';
    ROSTERS=o[2]||[];
    var byUser={}, teams={}, reserve={}, taxi={};
    Object.keys(o[4]||{}).forEach(function(key){
      teams[key]={name:o[4][key], avatar:''};
    });
    (o[3]||[]).forEach(function(u){
      byUser[u.user_id]={name:(u.metadata&&u.metadata.team_name)||u.display_name||'Team',
        avatar:(u.metadata&&String(u.metadata.avatar).indexOf('https://sleepercdn.com/')===0&&u.metadata.avatar)||(u.avatar?AVATAR+u.avatar:'')};
    });
    ROSTERS.forEach(function(r){
      var key=String(r.roster_id);
      teams[key]=byUser[r.owner_id]||{name:'Roster '+key, avatar:''};
      reserve[key]=(r.reserve||[]).map(String);
      taxi[key]=(r.taxi||[]).map(String);
    });
    CTX={slots:info.roster_positions||[], index:o[1]||{}, teams:teams, reserve:reserve,
         taxi:taxi, median:!!st.league_average_match, playoffStart:+st.playoff_week_start||0};
    // Sleeper's own word on which weeks are over: every roster has points by
    // Monday afternoon, but a week is not over until Monday night's game is.
    var last=typeof st.last_scored_leg==='number'?st.last_scored_leg
      :Math.max(0, (+st.leg||1)-1);
    var from=Math.max(1, +st.start_week||1);
    for(var n=from; n<=last; n++) WEEKS.push(n);
    if(!WEEKS.length){
      note('No week of '+esc(NAME)+' is over yet. Its first recap is here once week '
           +from+' is.', true);
      return;
    }
    var hash=/^#week-(\d+)$/.exec(location.hash);
    var want=hash?+hash[1]:PIN;
    draw(WEEKS.indexOf(want)>=0?want:WEEKS[WEEKS.length-1]);
  }).catch(function(e){
    if(e instanceof TypeError && window.console) console.error('[recap]', e);
    note('Could not read that league. '+SITE+' may be busy &mdash; try again in a minute.',
         true);
  });

  window.addEventListener('hashchange', function(){
    var m=/^#week-(\d+)$/.exec(location.hash);
    if(m && WEEKS.indexOf(+m[1])>=0 && +m[1]!==CUR) draw(+m[1]);
  });
})();
