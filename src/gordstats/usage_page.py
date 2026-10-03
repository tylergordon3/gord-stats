"""
The look and the table behaviour both usage pages share (/cfb/usage/ and
/fantasy/usage/): the column list, the stylesheet, the filter-and-sort
script, and the cell helpers.

A page describes its table once, as a list of `Col`s: the header, the views
the column shows in, how it sorts, and its role (rank, name, team, owner,
season). Everything that depends on a column's position is generated from
that list - the header row, which columns each view hides, which ones a phone
drops, and how the player and school cells are set - as `:nth-child` rules in
`css(columns)`. So a body cell is a bare `<td>`: the view classes it used to
carry ("v-overall v-rb v-wr v-te" on every one) were 46% of the college page.
The owner cell alone keeps its class, because the "Show my league" override
(gordstats.my_league) finds it by that class.

Rows carry data-team / data-conf / data-pos / data-own; a numeric cell carries
data-v, the number it sorts on, only where that differs from the text it shows
("55%" sorts on 0.5512, "76" on itself). A share bar is drawn by the stylesheet
from the cell's `--w`, not by two elements of its own. The page hands the
script a JSON config: `mine` and `teams` (fantasy team key -> name), `storage`
(the localStorage key its section's team dashboard writes "my team" under) and
`sort` (the column the table opens sorted on).
"""
from html import escape
from string import Template
from typing import NamedTuple

import pandas as pd

VIEW_KEYS = ("overall", "rb", "wr", "te")


class Col(NamedTuple):
    """One column of a usage table.

    `views` is the space-separated view keys it shows in; `key` is how a tap
    on its header sorts ("text", "n", or "" for not at all); `role` is one of
    rank / name / team / own / lead (the grey season share), or "".
    """
    label: str
    views: str
    key: str = ""
    role: str = ""
    field: str = ""
    title: str = ""


def head(columns) -> str:
    """The header row. A header keeps its role class (the frozen name column,
    the owner and season columns a phone drops): there are twenty of them."""
    out = []
    for c in columns:
        attrs = ""
        if c.key:
            attrs += f' data-k="{c.key}"'
        if c.role:
            attrs += f' class="us-{c.role}"'
        if c.field:
            attrs += f' data-field="{escape(c.field, quote=True)}"'
        if c.title:
            attrs += f' title="{escape(c.title, quote=True)}"'
        out.append(f"<th{attrs}>{c.label}</th>")
    return "<tr>" + "".join(out) + "</tr>"


def sort_index(columns, field: str) -> int:
    """The position of the column whose header names `field`."""
    return next(i for i, c in enumerate(columns) if c.field == field)


def _pos(i: int) -> str:
    """The pseudo-class for 0-based column `i`. The first column gets
    :first-child, which Chromium answers without counting siblings."""
    return ":first-child" if i == 0 else f":nth-child({i + 1})"


def _nth(tags, indexes) -> str:
    """`table.us td:nth-child(3),...` for 0-based column `indexes`."""
    return ",".join(f"table.us{{scope}} {t}{_pos(i)}" for i in indexes for t in tags)


def _views_rule(columns) -> str:
    """Each view hides the columns it has no use for - header and body alike,
    because one selector names both."""
    sels = []
    for view in VIEW_KEYS:
        hide = [i for i, c in enumerate(columns) if view not in c.views.split()]
        sels.append(_nth(("th", "td"), hide).replace("{scope}", f".view-{view}"))
    sels = [s for s in sels if s]
    return (",\n".join(sels) + "{display:none}") if sels else ""


def _role(columns, role):
    return [i for i, c in enumerate(columns) if c.role == role]


# The stylesheet, with the column-dependent parts left as placeholders:
#   $views      the per-view hiding rule
#   $phonehide  the owner and season columns, dropped on a phone
#   $lead       the season columns' smaller type
#   $rank $name $team   one body cell each (td:nth-child(n))
_CSS = Template("""<style>
table.us{width:100%;border-collapse:collapse;font-size:14px}
table.us th{background:#eef2f7;color:#334155;padding:6px 9px;text-align:center;font-size:12px;
  text-transform:uppercase;letter-spacing:.03em;white-space:nowrap;border:1px solid #e2e8f0;
  position:sticky;top:0;z-index:2}
table.us th[data-k]{cursor:pointer;user-select:none}
table.us th[data-k]:hover{background:#e2e8f0}
table.us th.us-on::after{content:" \\25BE";color:#2a78d6}
table.us th.us-on.us-asc::after{content:" \\25B4"}
table.us td{padding:5px 9px;border:1px solid #eef2f7;color:#0f172a;background:#fff;
  text-align:center;white-space:nowrap}
table.us $name{text-align:left;font-weight:600}
table.us $team{text-align:left;color:#475569}
table.us td.us-own{text-align:left;font-size:12.5px;color:#475569}
table.us tbody tr:nth-child(even) td{background:#f8fafc}
table.us tbody tr.us-break td{border-top:2px solid #94a3b8}
$views
table.us tbody tr.us-mine td.us-own{color:#b45309;font-weight:700}
.us-fa{display:inline-block;padding:1px 7px;border-radius:9px;background:#dcfce7;color:#166534;
  font-weight:700;font-size:11.5px}
/* A share's bar: the track and the fill are one pseudo-element, painted from
   the cell's --w. Two elements per bar were a sixth of the college table. */
table.us tbody td[style]::before{content:"";display:inline-block;width:52px;height:7px;
  border-radius:4px;vertical-align:middle;margin-right:6px;
  background:linear-gradient(#2a78d6,#2a78d6) 0 0/var(--w) 100% no-repeat,#e2e8f0}
/* Position views. The page is read one position at a time - a back's carry
   share and a receiver's target share are different questions - so the view
   picks both the rows and the columns, and a column a view does not want is
   hidden rather than left blank. Cell indexes are untouched, so sorting still
   works off the same positions. */
.us-views{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:0 0 8px}
.uv-btn{font:inherit;font-size:13px;font-weight:700;padding:6px 15px;border-radius:999px;
  border:1px solid #cbd5e1;background:#fff;color:#334155;cursor:pointer}
.uv-btn:hover{background:#f1f5f9}
.uv-btn.on{background:#2a78d6;border-color:#2a78d6;color:#fff}
.us-qual{font-size:12.5px;color:#475569;white-space:nowrap}
table.us $rank{font-weight:700;color:#334155;font-variant-numeric:tabular-nums}
table.us tr.us-thin td{color:var(--gs-muted,#5d6b7e)}
table.us tr.us-thin $name{font-weight:500}
table.us tr.us-thin $rank::after{content:"\\2013"}
.us-minnote{font-size:12px;color:#64748b;margin:0 0 8px}
/* One team's room, in a position view: how the carries or the targets are
   actually split. The table can be read for this, but a backfield is a
   question about proportions and proportions want a picture. */
.us-chart{margin:0 0 12px;padding:13px 15px;border:1px solid #e2e8f0;border-radius:10px;
  background:#fff}
.us-chart h3{margin:0 0 2px;font-size:15px;color:#0f172a}
.us-chart .uc-sub{font-size:12px;color:#64748b;margin:0 0 10px}
.uc-row{display:grid;grid-template-columns:minmax(84px,30%) 1fr auto;gap:9px;
  align-items:center;margin:0 0 6px;font-size:13px}
.uc-name{color:#0f172a;font-weight:600;overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap}
.uc-track{height:13px;border-radius:4px;background:#e2e8f0;overflow:hidden}
.uc-track i{display:block;height:100%;background:#2a78d6}
.uc-row.uc-thin .uc-track i{background:#94a3b8}
.uc-val{font-variant-numeric:tabular-nums;color:#334155;font-weight:700;min-width:38px;
  text-align:right}
.uc-rest .uc-name,.uc-rest .uc-val{color:#64748b;font-weight:600}
/* On a phone the table scrolls sideways, so what sits in the first few columns
   is what gets read. The owner and the grey season columns are reference, not
   the point, and between them they pushed the share itself off the screen. */
@media (max-width:560px){
  $phonehide
  table.us{font-size:13px}
  table.us th,table.us td{padding:5px 7px}
  table.us tbody td[style]::before{width:34px}
  /* Thumb-sized: the view buttons were 32px and the sort headers 29px. */
  .uv-btn{padding:5px 13px;min-height:40px}
  table.us th[data-k]{padding-top:11px;padding-bottom:11px}
  .us-controls select,.us-controls button{min-height:40px}
}
.us-controls{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0}
.us-controls label{font-size:12.5px;color:#475569;white-space:nowrap}
.us-controls select,.us-controls input[type=search]{font:inherit;font-size:13px;padding:5px 8px;
  border:1px solid #cbd5e1;border-radius:8px;background:#fff;color:#0f172a;max-width:170px}
.us-controls button{font:inherit;font-size:12.5px;padding:5px 10px;border-radius:8px;
  border:1px solid #cbd5e1;background:#f8fafc;color:#334155;cursor:pointer}
.us-count{font-size:12.5px;color:#64748b}
.us-pinrow{display:flex;align-items:center;gap:10px}
.us-filt{display:none}
.us-note{font-size:13px;color:#4a5a68;margin:6px 0 12px;line-height:1.55}
.us-scroll{overflow-x:auto;max-height:70vh;overflow-y:auto}
.us-lead{font-size:12px;color:#64748b}
$lead
/* Phones. Three things made the table a trap there: its own 70vh vertical
   scroller nested inside the page's (under the pinned filters, about nine rows
   showed, and a swipe scrolled the box or the page depending on where it
   landed); the filter stack, pinned, stood 146-250px tall; and a sideways
   swipe to reach the shares carried the player's name off the screen. So on a
   phone the table is as tall as its rows and the page does the scrolling, the
   filters fold behind one button whose label counts the ones in force, and
   the player column stays put while the numbers slide under it. */
@media (max-width:700px){
  .us-scroll{max-height:none;overflow-y:visible}
  .us-pin{flex-direction:column;align-items:stretch;padding:4px 10px}
  .us-pinrow{order:-1;min-height:44px}
  .us-filt{display:inline-flex;align-items:center;gap:6px;min-height:40px;font:inherit;
    font-size:14px;font-weight:700;padding:0 16px;border-radius:999px;border:1px solid #cbd5e1;
    background:#fff;color:#334155;cursor:pointer}
  .us-filt::after{content:"\\25BE"}
  .us-filt[aria-expanded=true]::after{content:"\\25B4"}
  .us-filt.us-some{border-color:#2a78d6;color:#1d4ed8}
  .us-pinrow .us-count{margin-left:auto;font-size:13px}
  .us-pin .us-controls{display:none;padding:2px 0 8px;gap:10px 12px}
  .us-pin.us-open .us-controls{display:flex}
  .us-controls select,.us-controls input[type=search]{font-size:16px;min-height:40px;max-width:200px}
  .us-controls button{min-height:40px;font-size:14px;padding:0 14px}
  table.us .us-name,table.us $name{position:sticky;left:0;z-index:1;box-shadow:inset -1px 0 0 #cbd5e1}
  table.us th.us-name{z-index:3}
  /* "Florida International" alone was a third of the screen; the shares are
     what the page is for, so the school gives way to them. */
  table.us $team{max-width:92px;overflow:hidden;text-overflow:ellipsis}
}
@media (prefers-color-scheme: dark){
  table.us th{background:#223052;color:#dde5ef;border-color:#2b3852}
  table.us th[data-k]:hover{background:#2b3852}
  table.us td{background:#16203a;border-color:#2b3852;color:#dde5ef}
  table.us tbody tr:nth-child(even) td{background:#1b2540}
  table.us tbody tr.us-break td{border-top-color:#64748b}
  table.us $team,table.us td.us-own,.us-note,.us-lead,.us-controls label,.us-count{color:#aab7c9}
  table.us tbody tr.us-mine td.us-own{color:#ffb457}
  .us-fa{background:#14532d;color:#bbf7d0}
  table.us tbody td[style]::before{background:linear-gradient(#2a78d6,#2a78d6) 0 0/var(--w) 100% no-repeat,#2b3852}
  .us-controls select,.us-controls input[type=search],.us-controls button,.us-filt{
    background:#16203a;color:#dde5ef;border-color:#2b3852}
  .us-filt.us-some{border-color:#8ab4ff;color:#8ab4ff}
  .uv-btn{background:#16203a;border-color:#2b3852;color:#dde5ef}
  .uv-btn:hover{background:#1b2540}
  .uv-btn.on{background:#2a78d6;border-color:#2a78d6;color:#fff}
  .us-qual,.us-minnote{color:#aab7c9}
  .us-chart{background:#16203a;border-color:#2b3852}
  .us-chart h3{color:#f1f5f9}
  .us-chart .uc-sub,.uc-rest .uc-name,.uc-rest .uc-val{color:#aab7c9}
  .uc-name,.uc-val{color:#dde5ef}
  .uc-track{background:#2b3852}
  table.us $rank{color:#dde5ef}
  table.us tr.us-thin td{color:#6b7a91}
}
@media (max-width:700px) and (prefers-color-scheme: dark){
  table.us .us-name,table.us $name{box-shadow:inset -1px 0 0 #3a4a6b}
}
</style>""")


def css(columns=()) -> str:
    """The stylesheet for a table of `columns`.

    Every rule that depends on where a column sits is written against its
    position, from the same list that renders the header, so a header and
    its body cells cannot disagree about whether a column is showing. With no
    columns (a page with nothing to show yet) the role rules fall back to the
    old class names and nothing is hidden.
    """
    def one(role):
        at = _role(columns, role)
        return f"td{_pos(at[0])}" if at else f"td.us-{role}"

    drop = _role(columns, "own") + _role(columns, "lead")
    lead = _role(columns, "lead")
    return _CSS.substitute(
        views=_views_rule(columns),
        phonehide=(_nth(("th", "td"), drop).replace("{scope}", "") + "{display:none}"
                   if drop else ""),
        # The season share's smaller type. `.us-lead` above still carries it
        # for the header; for a body cell it is the only rule that sets a
        # size, so the position's extra specificity changes nothing else.
        # And its grey, which the page's own words promise ("the season share
        # beside it in grey") and no rule had delivered since the cells lost
        # their classes - in both themes, at the muted token's contrast.
        lead=((lambda sel: sel + "{font-size:12px;color:var(--gs-muted,#5d6b7e)}"
               "@media (prefers-color-scheme: dark){" + sel + "{color:#aab7c9}}")(
                  _nth(("td",), lead).replace("{scope}", "")) if lead else ""),
        rank=one("rank"), name=one("name"), team=one("team"))


CSS = css()

# Filters read data-* off each row; sorting reads data-v off each cell (or the
# number the cell shows, where they are the same), so the table sorts on the
# number rather than on "55%". The filter state lives in the URL hash, which is
# how the team dashboard links straight to one backfield.
JS = """{% raw %}<script>
(function(){
  var table=document.querySelector('table.us'); if(!table) return;
  var CFG=JSON.parse(document.getElementById('us-cfg').textContent);
  var body=table.tBodies[0], rows=Array.prototype.slice.call(body.rows);
  var heads=Array.prototype.slice.call(table.tHead.rows[0].cells);
  var el={own:document.getElementById('us-own'),conf:document.getElementById('us-conf'),
    team:document.getElementById('us-team'),pos:document.getElementById('us-pos'),
    find:document.getElementById('us-find'),group:document.getElementById('us-group'),
    count:document.getElementById('us-count'),qual:document.getElementById('us-qual'),
    minnote:document.getElementById('us-minnote')};
  function colOf(cls){
    for(var i=0;i<heads.length;i++) if(heads[i].classList.contains(cls)) return i;
    return -1;
  }
  var rankCol=colOf('us-rank');
  // Numeric columns: a cell without data-v sorts on the number it shows.
  var NUM=heads.map(function(h){return h.dataset.k==='n';});
  // --- position views ------------------------------------------------------
  // Each view names the positions it keeps, the column it opens sorted by, and
  // the minimum a player needs before he is ranked. Below that minimum a row
  // still shows - leaving a back out entirely hides the fact that he exists -
  // but it is greyed and carries a dash instead of a rank.
  var VIEWS=CFG.views||[], view=VIEWS.length?VIEWS[0]:null;
  var viewBtns=Array.prototype.slice.call(document.querySelectorAll('.uv-btn'));
  function fieldCol(name){
    for(var i=0;i<heads.length;i++) if(heads[i].dataset.field===name) return i;
    return null;
  }
  function qualified(r){
    if(!view||!view.min) return true;
    return (+r.dataset[view.min.field]||0)>=view.min.n;
  }
  function inView(r){
    return !view||!view.pos||view.pos.indexOf(r.dataset.pos)>=0;
  }
  function rankCell(r){ return rankCol>=0?r.cells[rankCol]:null; }
  // Rank is over every qualified player in the view, not over what the other
  // filters leave on screen: "7th in carry share" should not become "1st"
  // because the table was narrowed to one team.
  function rankView(){
    if(!view) return;
    var key=view.sort?fieldCol(view.sort):null;
    var pool=rows.filter(function(r){return inView(r)&&qualified(r);});
    if(key!==null) pool.sort(function(a,b){
      var x=val(a,key),y=val(b,key);
      if(x===null||y===null) return (x===null)-(y===null);
      return y-x;});
    var rank=new Map();
    pool.forEach(function(r,i){rank.set(r,String(i+1));});
    rows.forEach(function(r){
      var c=rankCell(r), t=rank.get(r)||'';
      if(c&&c.textContent!==t) c.textContent=t;
      r.classList.toggle('us-thin',inView(r)&&!qualified(r));
    });
  }
  // One team's split, drawn when a position view is narrowed to a single team:
  // the question "who has this backfield" is about proportions, and reading
  // proportions off a sorted column is work the page can do for you.
  var chart=document.createElement('div');
  chart.className='us-chart'; chart.style.display='none';
  var scroll=table.closest('.us-scroll')||table;
  scroll.parentNode.insertBefore(chart,scroll);
  function drawChart(visible){
    var t=el.team.value;
    if(!view||!view.pos||!t||!view.sort){chart.style.display='none';return;}
    var key=fieldCol(view.sort);
    if(key===null){chart.style.display='none';return;}
    var ranked=visible.filter(function(r){return val(r,key)!==null;})
      .sort(function(a,b){return val(b,key)-val(a,key);});
    if(ranked.length<2){chart.style.display='none';return;}
    var top=ranked.slice(0,6), sum=0;
    ranked.forEach(function(r){sum+=val(r,key);});
    var rest=ranked.slice(6).reduce(function(a,r){return a+val(r,key);},0);
    var html='<h3>'+t+' &middot; '+view.label+'</h3>'
      +'<p class="uc-sub">'+heads[key].textContent.trim()
      +' over these weeks. '+(sum<0.98?('These '+ranked.length+' account for '
        +Math.round(sum*100)+'% of the team&rsquo;s; the rest went to players outside '
        +'this view.'):'')+'</p>';
    top.forEach(function(r){
      var share=val(r,key);
      html+='<div class="uc-row'+(qualified(r)?'':' uc-thin')+'">'
        +'<span class="uc-name">'+r.cells[nameCol].textContent+'</span>'
        +'<span class="uc-track"><i style="width:'+Math.round(share*100)+'%"></i></span>'
        +'<span class="uc-val">'+Math.round(share*100)+'%</span></div>';
    });
    if(rest>0.005) html+='<div class="uc-row uc-rest"><span class="uc-name">'
      +(ranked.length-6)+' more</span><span class="uc-track"><i style="width:'
      +Math.round(rest*100)+'%"></i></span><span class="uc-val">'
      +Math.round(rest*100)+'%</span></div>';
    chart.innerHTML=html; chart.style.display='';
  }
  var nameCol=(function(){
    var i=colOf('us-name'); if(i>=0) return i;
    for(i=0;i<heads.length;i++) if(/player/i.test(heads[i].textContent)) return i;
    return 1;
  })();
  // The find box matches on the player's name, read once off his cell.
  function nameOf(r){
    if(r._name===undefined) r._name=r.cells[nameCol].textContent.toLowerCase();
    return r._name;
  }
  function applyView(key,skipDraw){
    for(var i=0;i<VIEWS.length;i++) if(VIEWS[i].key===key) view=VIEWS[i];
    table.className='us view-'+view.key;
    viewBtns.forEach(function(b){b.classList.toggle('on',b.dataset.view===view.key);});
    var c=view.sort?fieldCol(view.sort):null;
    if(c!==null){sortCol=c; sortAsc=false;}
    if(el.minnote) el.minnote.textContent=view.min?view.min.label:'';
    if(el.qual) el.qual.parentNode.style.display=view.min?'':'none';
    rankView();
    if(!skipDraw) draw();
  }
  var mine=CFG.mine;
  try{var saved=localStorage.getItem(CFG.storage||'cfbMyTeam'); if(saved&&CFG.teams[saved]) mine=saved;}catch(e){}
  var mineOpt=el.own.querySelector('option[value="mine"]');
  if(mineOpt) mineOpt.textContent='My team'+(CFG.teams[mine]?' ('+CFG.teams[mine]+')':'');
  rows.forEach(function(r){ if(mine&&r.dataset.own===mine) r.classList.add('us-mine'); });

  var sortCol=CFG.sort||0, sortAsc=false;
  // A numeric cell's value never changes, so it is read once per row; a text
  // cell is read each time (the owner column is re-pointed by "Show my league").
  function val(r,i){
    var k=r._k||(r._k=[]);
    if(k[i]!==undefined) return k[i];
    var c=r.cells[i], v=c.dataset.v;
    if(v===undefined){
      if(!NUM[i]) return c.textContent.toLowerCase();
      v=c.textContent;
    }
    return (k[i]=(v===''?null:+v));
  }
  function cmp(i,asc){return function(a,b){
    var x=val(a,i), y=val(b,i);
    if(x===null||y===null) return (x===null)-(y===null);   // blanks last either way
    if(x<y) return asc?-1:1; if(x>y) return asc?1:-1; return 0;};}
  function draw(){
    var by=cmp(sortCol,sortAsc), sorted=rows.slice().sort(by);
    if(el.group.checked) sorted.sort(function(a,b){
      return a.dataset.team<b.dataset.team?-1:a.dataset.team>b.dataset.team?1:0;});
    var o=el.own.value,c=el.conf?el.conf.value:'',t=el.team.value,
        p=el.pos?el.pos.value:'',
        q=(el.find.value||'').toLowerCase(), shown=0, last=null;
    var onlyQual=el.qual&&el.qual.checked&&view&&view.min;
    // Rows already in their place stay put: a filter or a search changes
    // which rows show, not their order, and moving all of them made the
    // browser lay the whole table out again on every keystroke.
    var at=body.firstChild;
    sorted.forEach(function(r){
      var d=r.dataset, own=d.own;
      var ok=inView(r)&&(!onlyQual||qualified(r))
        &&(!o||(o==='fa'?!own:o==='held'?!!own:o==='mine'?own===mine:own===o))
        &&(!c||d.conf===c)&&(!t||d.team===t)&&(!p||d.pos===p)&&(!q||nameOf(r).indexOf(q)>=0);
      var disp=ok?'':'none';
      if(r.style.display!==disp) r.style.display=disp;
      r.classList.toggle('us-break',ok&&el.group.checked&&last!==null&&last!==d.team);
      if(ok){shown++; last=d.team;}
      if(r===at) at=r.nextSibling; else body.insertBefore(r,at);
    });
    el.count.textContent=shown+' player'+(shown===1?'':'s');
    // The folded filters still say how many are narrowing the table, so a
    // short list is never a mystery on a phone.
    var nf=[o,c,t,p,q,el.group.checked].filter(Boolean).length;
    if(filt){filt.textContent='Filters'+(nf?' \\u00b7 '+nf:''); filt.classList.toggle('us-some',!!nf);}
    drawChart(sorted.filter(function(r){return r.style.display!=='none';}));
    heads.forEach(function(h,i){h.classList.toggle('us-on',i===sortCol);
      h.classList.toggle('us-asc',i===sortCol&&sortAsc);});
    var bits=[];
    if(view&&VIEWS.length&&view.key!==VIEWS[0].key) bits.push('view='+view.key);
    [['own',o],['conf',c],['team',t],['pos',p]].forEach(function(kv){
      if(kv[1]) bits.push(kv[0]+'='+encodeURIComponent(kv[1]));});
    if(el.group.checked) bits.push('group=1');
    history.replaceState(null,'',bits.length?'#'+bits.join('&'):location.pathname+location.search);
  }
  heads.forEach(function(h,i){
    if(!h.dataset.k) return;
    h.addEventListener('click',function(){
      if(sortCol===i) sortAsc=!sortAsc; else {sortCol=i; sortAsc=h.dataset.k==='text';}
      draw();});
  });
  // A conference narrows the school list to its own members.
  function schools(){
    if(!el.conf) return;
    var c=el.conf.value, keep=el.team.value;
    Array.prototype.forEach.call(el.team.options,function(op){
      op.hidden=!!(c&&op.value&&op.dataset.conf!==c);});
    if(keep&&c&&el.team.selectedOptions[0].dataset.conf!==c) el.team.value='';
  }
  function fromHash(){
    location.hash.replace(/^#/,'').split('&').forEach(function(kv){
      var i=kv.indexOf('='); if(i<0) return;
      var k=kv.slice(0,i), v=decodeURIComponent(kv.slice(i+1));
      if(k==='group') el.group.checked=v==='1';
      else if(k==='view') applyView(v,true);
      else if(el[k]&&el[k].tagName==='SELECT') el[k].value=v;
    });
  }
  viewBtns.forEach(function(b){
    b.addEventListener('click',function(){applyView(b.dataset.view);});});
  // Phones only: the button is hidden on a desktop, where the filters sit open.
  var filt=document.getElementById('us-filt');
  if(filt) filt.addEventListener('click',function(){
    var pin=filt.closest('.us-pin'), open=!pin.classList.contains('us-open');
    pin.classList.toggle('us-open',open);
    filt.setAttribute('aria-expanded',open?'true':'false');
  });
  if(el.qual) el.qual.addEventListener('change',draw);
  [el.own,el.team,el.pos,el.group].forEach(function(x){
    if(x) x.addEventListener('change',draw);});
  if(el.conf) el.conf.addEventListener('change',function(){schools();draw();});
  el.find.addEventListener('input',draw);
  document.getElementById('us-reset').addEventListener('click',function(){
    el.own.value=el.team.value=el.find.value='';
    if(el.pos) el.pos.value=''; if(el.conf) el.conf.value='';
    if(el.qual) el.qual.checked=false;
    el.group.checked=false; schools();
    if(VIEWS.length) applyView(VIEWS[0].key); else draw();});
  if(VIEWS.length) applyView(VIEWS[0].key,true);
  fromHash(); schools();
  if(VIEWS.length) rankView();
  draw();
})();
</script>{% endraw %}"""


def views_bar(views: list) -> str:
    """The Overall / RB / WR / TE buttons, plus the qualifying controls.

    `views` is the same list handed to the script in the config: dicts with
    `key`, `label`, optionally `pos` (the positions the view keeps), `sort`
    (the th data-field it opens sorted by) and `min` ({field, n, label}).
    """
    btns = "".join(
        f"<button type='button' class='uv-btn{' on' if i == 0 else ''}' "
        f"data-view=\"{escape(str(v['key']), quote=True)}\">"
        f"{escape(str(v['label']))}</button>"
        for i, v in enumerate(views))
    return ("<div class='us-views'>" + btns
            + "<label class='us-qual'><input id='us-qual' type='checkbox'> "
              "Qualified only</label></div>"
            "<p class='us-minnote' id='us-minnote'></p>")


def pin(controls: str) -> str:
    """The pinned filter card around a page's `controls` (the labelled selects,
    the find box, the group toggle and the Reset button).

    On a phone they fold behind one Filters button, with the player count
    beside it so a folded card still says what the filters left; on a desktop
    the button is hidden and the controls sit open as before.
    """
    return ("<div class='pin-bar us-pin'>"
            f"<div class='us-controls' id='us-ctl'>{controls}</div>"
            "<div class='us-pinrow'><button type='button' class='us-filt' id='us-filt' "
            "aria-expanded='false' aria-controls='us-ctl'>Filters</button>"
            "<span class='us-count' id='us-count'></span></div></div>")


def v(value, digits: int = 4) -> str:
    """A cell's sort key: blank for a missing number, so it sorts last."""
    return "" if value is None or pd.isna(value) else f"{round(float(value), digits):g}"


def _missing(value) -> bool:
    return value is None or pd.isna(value)


def cell(text: str, key: str = None, cls: str = "") -> str:
    """A body cell. `key` is its sort value, printed only where it is not the
    text itself - the script reads a numeric column's text when there is no
    data-v, so "76" needs nothing and "55%" needs its 0.5512."""
    attrs = f' class="{cls}"' if cls else ""
    if key is not None and key != text:
        attrs += f' data-v="{key}"'
    return f"<td{attrs}>{text}</td>"


def num(value, fmt: str = "{:.0f}") -> str:
    return cell(fmt.format(value), v(value))


def bar(share) -> str:
    """A share with its bar: the bar is the stylesheet's, drawn from --w."""
    if _missing(share):
        return cell("&mdash;", "")
    pct = max(0.0, min(float(share), 1.0))
    return (f'<td data-v="{v(share)}" style="--w:{pct * 100:.0f}%">{pct:.0%}</td>')


def pct(value) -> str:
    """A share without a bar, the season one beside it among them."""
    return cell("&mdash;" if _missing(value) else f"{float(value):.0%}", v(value))


def fixed(value, fmt: str) -> str:
    """A figure set to `fmt` ("{:.1f}", "{:+.2f}"), or a dash."""
    return cell("&mdash;" if _missing(value) else fmt.format(value), v(value))


def options(values, labels: dict = None, data: dict = None) -> str:
    labels, data = labels or {}, data or {}
    return "".join(
        f'<option value="{escape(str(v), quote=True)}"'
        + (f' data-conf="{escape(data[v], quote=True)}"' if v in data else "")
        + f'>{escape(str(labels.get(v, v)))}</option>' for v in values)
