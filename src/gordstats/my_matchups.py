"""
"Your league this week" on the NFL matchups page.

The built page is this league's: its cards, its median tracker, its four
projection sources scored against each other, all of it out of an archive the
Pi writes. None of that exists for someone else's league, and pretending
otherwise would mean rebuilding the archive per reader.

What does exist, keyless and CORS-open, is Sleeper's own view of any league:
who plays whom this week, each side's starters, and every player's points as
they land. That is the part of this page people actually watch on a Sunday,
so that is what this renders - beside the built page rather than inside it,
because the two are not the same object and blending them would be a lie
about where the numbers came from.

Names come from /fantasy/players-index.json, written by
fantasy.site.players_index: about 100 KB, fetched only when someone is looking
at their own league.

Projections come from /fantasy/week-projections.json rather than from Sleeper
directly: asked cross-origin, Sleeper's projections endpoint answers with every
player id mapped to an empty object - the stats are stripped - where the same
URL from a server returns them. The build downloads that set anyway, so it
writes the numbers out as about 6 KB instead.
"""

CSS = """<style>
.mm{margin:10px 0 18px}
.mm-head{display:flex;flex-wrap:wrap;gap:9px;align-items:baseline;margin:0 0 10px}
.mm-head h2{margin:0;font-size:18px}
.mm-note{font-size:12.5px;color:#64748b;margin:0 0 11px;line-height:1.5}
.mm-grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(min(320px,100%),1fr))}
.mm-card{border:1px solid #e2e8f0;border-radius:12px;background:#fff;padding:13px 15px}
.mm-vs{display:grid;grid-template-columns:1fr auto 1fr;gap:8px;align-items:center;
  margin:0 0 10px}
.mm-team{font-weight:800;font-size:14.5px;color:#0f172a;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.mm-team.r{text-align:right}
.mm-pts{font-size:21px;font-weight:800;color:#0f172a;font-variant-numeric:tabular-nums}
.mm-mid{font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em}
.mm-lead{color:#15803d}
.mm-rows{display:grid;grid-template-columns:1fr auto 1fr;gap:3px 8px;font-size:12.5px}
.mm-p{display:flex;gap:6px;align-items:baseline;min-width:0}
.mm-p.r{justify-content:flex-end;text-align:right}
.mm-nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#334155}
.mm-pos{font-size:10.5px;color:#94a3b8;font-weight:700}
.mm-v{font-variant-numeric:tabular-nums;font-weight:700;color:#0f172a;min-width:34px}
.mm-slot{font-size:10.5px;color:#94a3b8;text-align:center;font-weight:700}
.mm-btn{font:inherit;font-size:12.5px;padding:5px 12px;border-radius:999px;
  border:1px solid #cbd5e1;background:#fff;color:#334155;cursor:pointer}
.mm-btn[disabled]{opacity:.55;cursor:default}
@media (prefers-color-scheme: dark){
  .mm-card{background:#16203a;border-color:#2b3852}
  .mm-team,.mm-pts,.mm-v{color:#f1f5f9}
  .mm-nm{color:#c3cfdd}
  .mm-note,.mm-pos,.mm-mid,.mm-slot{color:#8fa0b8}
  .mm-lead{color:#6ee7b7}
  .mm-btn{background:#16203a;border-color:#2b3852;color:#dde5ef}
}
</style>"""

JS = """{% raw %}<script>
(function(){
  var KEY='gsSleeperLeague';
  var host=document.getElementById('mm-host');
  if(!host) return;
  var WEEK=parseInt(host.dataset.week||'0',10);
  var built=document.getElementById('mm-built');
  var INDEX=null, PROJ=null;

  function saved(){
    try{ return JSON.parse(localStorage.getItem(KEY)||'null'); }catch(e){ return null; }
  }
  function esc(s){
    return String(s==null?'':s).replace(/[&<>"]/g,function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});
  }
  function num(v){ return (v==null||isNaN(v))?'-':(Math.round(v*10)/10).toFixed(1); }

  function players(){
    if(INDEX) return Promise.resolve(INDEX);
    return fetch('/fantasy/players-index.json')
      .then(function(r){return r.ok?r.json():{};})
      .then(function(d){ INDEX=d||{}; return INDEX; })
      .catch(function(){ INDEX={}; return INDEX; });
  }

  function render(league, rows, names, index){
    var by={};
    rows.forEach(function(r){
      if(r.matchup_id==null) return;
      (by[r.matchup_id]=by[r.matchup_id]||[]).push(r);
    });
    var ids=Object.keys(by).sort(function(a,b){return a-b;});
    if(!ids.length){
      host.innerHTML='<p class="mm-note">Sleeper has no week '+WEEK
        +' matchups for this league yet.</p>';
      return;
    }
    var html='<div class="mm-grid">';
    ids.forEach(function(mid){
      var pair=by[mid], a=pair[0], b=pair[1];
      if(!b){ b={roster_id:null, points:0, starters:[], players_points:{}}; }
      // Sleeper's `points` is the real score. Before kickoff it is zero for
      // everyone, which is true but useless, so a side that has not played
      // shows what its starters are projected to score - and the label says
      // which of the two you are looking at.
      var ap=a.points||0, bp=b.points||0;
      var live=(ap>0||bp>0);
      if(!live){ ap=projected(a); bp=projected(b); }
      html+='<div class="mm-card"><div class="mm-vs">'
        +'<div class="mm-team">'+esc(names[a.roster_id]||('Roster '+a.roster_id))+'</div>'
        +'<div class="mm-mid">vs</div>'
        +'<div class="mm-team r">'+esc(names[b.roster_id]||('Roster '+b.roster_id))+'</div>'
        +'</div><div class="mm-vs">'
        +'<div class="mm-pts'+(ap>bp?' mm-lead':'')+'">'+num(ap)+'</div>'
        +'<div class="mm-mid">'+(live?'pts':'proj')+'</div>'
        +'<div class="mm-pts r'+(bp>ap?' mm-lead':'')+'" style="text-align:right">'
        +num(bp)+'</div></div>';

      var la=a.starters||[], lb=b.starters||[];
      var n=Math.max(la.length, lb.length);
      html+='<div class="mm-rows">';
      for(var i=0;i<n;i++){
        html+=side(la[i], a, index, false)
           +'<div class="mm-slot">'+(i+1)+'</div>'
           +side(lb[i], b, index, true);
      }
      html+='</div></div>';
    });
    host.innerHTML=html+'</div>';
  }

  function projected(row){
    return (row.starters||[]).reduce(function(t,pid){
      var v=PROJ?PROJ[String(pid)]:null;
      return t+(v||0);
    },0);
  }

  function side(pid, row, index, right){
    if(!pid||pid==='0') return '<div class="mm-p'+(right?' r':'')+'"></div>';
    var meta=index[String(pid)]||[pid,''];
    var pts=(row.players_points||{})[String(pid)];
    // Before kickoff every points figure is zero, so show the projection there
    // instead once it has been asked for - otherwise the card is a wall of 0.0.
    var shown=pts;
    if(PROJ&&(!pts)) shown=PROJ[String(pid)];
    var val='<span class="mm-v">'+num(shown)+'</span>';
    var nm='<span class="mm-nm">'+esc(meta[0])+'</span>'
      +'<span class="mm-pos">'+esc(meta[1])+'</span>';
    return '<div class="mm-p'+(right?' r':'')+'">'
      +(right?val+nm:nm+val)+'</div>';
  }

  function show(league){
    var id=league.id;
    host.innerHTML='<p class="mm-note">Reading '+esc(league.name||'your league')+'\\u2026</p>';
    if(built) built.hidden=true;
    Promise.all([
      fetch('https://api.sleeper.app/v1/league/'+encodeURIComponent(id)+'/matchups/'+WEEK)
        .then(function(r){return r.ok?r.json():[];}),
      fetch('https://api.sleeper.app/v1/league/'+encodeURIComponent(id)+'/rosters')
        .then(function(r){return r.ok?r.json():[];}),
      fetch('https://api.sleeper.app/v1/league/'+encodeURIComponent(id)+'/users')
        .then(function(r){return r.ok?r.json():[];}),
      players(),
      projections()
    ]).then(function(out){
      var rows=out[0]||[], rosters=out[1]||[], users=out[2]||[], index=out[3]||{};
      var byUser={};
      users.forEach(function(u){
        var team=(u.metadata&&u.metadata.team_name)||u.display_name||'Team';
        var mgr=u.display_name||'';
        byUser[u.user_id]=(mgr&&team.indexOf(mgr)<0)?(team+' ('+mgr+')'):team;
      });
      var names={};
      rosters.forEach(function(ro){
        names[ro.roster_id]=byUser[ro.owner_id]||('Roster '+ro.roster_id);
      });
      render(league, rows, names, index);
    }).catch(function(){
      host.innerHTML='<p class="mm-note">Could not read that league from Sleeper.</p>';
    });
  }

  function projections(){
    if(PROJ) return Promise.resolve(PROJ);
    return fetch('/fantasy/week-projections.json')
      .then(function(r){return r.ok?r.json():{};})
      .then(function(d){ PROJ=d||{}; return PROJ; })
      .catch(function(){ PROJ={}; return PROJ; });
  }

  var have=saved();
  if(!have||!have.id||have.site) return;      // the built league is the default
  var bar=document.getElementById('mm-bar');
  if(bar){
    bar.innerHTML='<h2>'+esc(have.name||'Your league')+' &middot; week '+WEEK+'</h2>'
      +'<span class="mm-note">Live points from Sleeper; a starter yet to play '
      +'shows this week\u2019s projection.</span>';
  }
  show(have);
})();
</script>{% endraw %}"""


def section(week: int, year: int) -> str:
    """The container the script fills, and the note explaining what it is."""
    return (CSS + f"<div class='mm' id='mm-wrap'>"
            f"<div class='mm-head' id='mm-bar'></div>"
            f"<div id='mm-host' data-week='{int(week)}' data-year='{int(year)}'></div>"
            "</div>")
