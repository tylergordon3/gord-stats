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
.ml-msg{font-size:12.5px}
.ml-msg.err{color:#b91c1c}
/* The input takes the whole row at its default width and pushes the button
   to a third line. On a phone this control is one line of label and one of
   input-plus-button. */
@media (max-width:560px){
  .ml-bar{gap:6px}
  .ml-bar .ml-label{flex:1 1 100%;font-size:12.5px}
  .ml-bar input{min-width:0;flex:1}
  .ml-bar button{white-space:nowrap}
  .ml-bar .ml-msg{flex:1 1 100%}
}
@media (prefers-color-scheme: dark){
  .ml-bar{color:#aab7c9}
  .ml-who{color:#f1f5f9}
  .ml-bar button,.ml-bar input{background:#16203a;border-color:#2b3852;color:#dde5ef}
  .ml-bar button:hover{background:#1b2540}
  .ml-msg.err{color:#ff9b91}
}
</style>"""

JS = """{% raw %}<script>
(function(){
  var KEY='gsSleeperLeague';          // {id, name} of the league being shown
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
  var SYNCED=[];

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
    if(label){
      if(SYNCED.length>1){
        var here=String((saved()||{}).id||'');
        bar.innerHTML='<label>League <select id="ml-pick">'
          + SYNCED.map(function(l){
              return '<option value="'+esc(l.league_id)+'"'
                + (String(l.league_id)===here?' selected':'') + '>'
                + esc(leagueLabel(l)) + '</option>';
            }).join('')
          + '</select></label>'
          + '<button type="button" id="ml-clear">Show this site\\u2019s league</button>'
          + '<span class="ml-msg" id="ml-msg"></span>';
        document.getElementById('ml-pick').addEventListener('change',function(){
          var want=this.value;
          var chosen=SYNCED.filter(function(l){
            return String(l.league_id)===String(want);})[0];
          if(!chosen) return;
          save({id:chosen.league_id, name:leagueLabel(chosen)});
          // Pages that render from the stored key read it once, at load.
          if(owns) load(chosen.league_id); else location.reload();
        });
      } else {
        bar.innerHTML='Showing <span class="ml-who"></span> '
          +'<button type="button" id="ml-clear">Show this site\\u2019s league</button>'
          +'<span class="ml-msg" id="ml-msg"></span>';
        bar.querySelector('.ml-who').textContent=label;
      }
      document.getElementById('ml-clear').addEventListener('click',restore);
      return;
    }
    bar.innerHTML='<span class="ml-label">Your Sleeper league</span>'
      +'<input id="ml-id" type="text" inputmode="numeric" '
      +'placeholder="league id" aria-label="Sleeper league id">'
      +'<button type="button" id="ml-go">Show mine</button>'
      +'<span class="ml-msg" id="ml-msg"></span>';
    document.getElementById('ml-go').addEventListener('click',function(){
      var v=(document.getElementById('ml-id').value||'').trim();
      if(!/^[0-9]{6,32}$/.test(v)){
        msg('A Sleeper league id is the long number in the league\\u2019s web address.','err');
        return;
      }
      this.disabled=true;
      var btn=this;
      load(v).then(function(){ btn.disabled=false; });
    });
  }

  var have=saved();
  if(have&&have.id){ draw(have.name); load(have.id,true); }
  else draw(null);

  // A league synced to the account wins over whatever this browser remembers,
  // so a second device shows the same thing without being told again.
  fetch('/api/leagues',{credentials:'same-origin'})
    .then(function(r){return r.ok?r.json():null;})
    .then(function(d){
      if(!d||!d.leagues) return;
      // One entry per league, not one per season.
      SYNCED=leagues(d.leagues.filter(function(l){return l.provider==='sleeper';}))
        .map(function(g){ return g.current; });
      if(!SYNCED.length) return;
      if(have&&have.site) return;          // they asked for this site's league
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
})();
</script>{% endraw %}"""


def bar() -> str:
    """The control itself; the script fills it in."""
    return CSS + "<div class='ml-bar' id='ml-bar'></div>"
