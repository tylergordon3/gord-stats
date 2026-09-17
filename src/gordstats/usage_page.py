"""
The look and the table behaviour both usage pages share (/cfb/usage/ and
/fantasy/usage/): the stylesheet, the filter-and-sort script, and the cell
helpers.

Rows carry data-team / data-conf / data-pos / data-own / data-name; cells
carry data-v, the number a column sorts on. The page hands the script a JSON
config: `mine` and `teams` (fantasy team key -> name), `storage` (the
localStorage key its section's team dashboard writes "my team" under) and
`sort` (the column the table opens sorted on).
"""
from html import escape

import pandas as pd

CSS = """<style>
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
table.us td.us-name{text-align:left;font-weight:600}
table.us td.us-team{text-align:left;color:#475569}
table.us td.us-own{text-align:left;font-size:12.5px;color:#475569}
table.us tbody tr:nth-child(even) td{background:#f8fafc}
table.us tbody tr.us-break td{border-top:2px solid #94a3b8}
table.us tbody tr.us-mine td.us-own{color:#b45309;font-weight:700}
.us-fa{display:inline-block;padding:1px 7px;border-radius:9px;background:#dcfce7;color:#166534;
  font-weight:700;font-size:11.5px}
.us-bar{display:inline-block;width:52px;height:7px;border-radius:4px;background:#e2e8f0;
  vertical-align:middle;margin-right:6px;overflow:hidden}
.us-bar i{display:block;height:100%;background:#2a78d6}
.us-controls{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0}
.us-controls label{font-size:12.5px;color:#475569;white-space:nowrap}
.us-controls select,.us-controls input[type=search]{font:inherit;font-size:13px;padding:5px 8px;
  border:1px solid #cbd5e1;border-radius:8px;background:#fff;color:#0f172a;max-width:170px}
.us-controls button{font:inherit;font-size:12.5px;padding:5px 10px;border-radius:8px;
  border:1px solid #cbd5e1;background:#f8fafc;color:#334155;cursor:pointer}
.us-count{font-size:12.5px;color:#64748b;margin-left:auto}
.us-note{font-size:13px;color:#4a5a68;margin:6px 0 12px;line-height:1.55}
.us-scroll{overflow-x:auto;max-height:70vh;overflow-y:auto}
.us-lead{font-size:12px;color:#64748b}
@media (prefers-color-scheme: dark){
  table.us th{background:#223052;color:#dde5ef;border-color:#2b3852}
  table.us th[data-k]:hover{background:#2b3852}
  table.us td{background:#16203a;border-color:#2b3852;color:#dde5ef}
  table.us tbody tr:nth-child(even) td{background:#1b2540}
  table.us tbody tr.us-break td{border-top-color:#64748b}
  table.us td.us-team,table.us td.us-own,.us-note,.us-lead,.us-controls label,.us-count{color:#aab7c9}
  table.us tbody tr.us-mine td.us-own{color:#ffb457}
  .us-fa{background:#14532d;color:#bbf7d0}
  .us-bar{background:#2b3852}
  .us-controls select,.us-controls input[type=search],.us-controls button{background:#16203a;
    color:#dde5ef;border-color:#2b3852}
}
</style>"""

# Filters read data-* off each row; sorting reads data-v off each cell, so the
# table sorts on the number rather than on "55%". The filter state lives in the
# URL hash, which is how the team dashboard links straight to one backfield.
JS = """{% raw %}<script>
(function(){
  var table=document.querySelector('table.us'); if(!table) return;
  var CFG=JSON.parse(document.getElementById('us-cfg').textContent);
  var body=table.tBodies[0], rows=Array.prototype.slice.call(body.rows);
  var heads=Array.prototype.slice.call(table.tHead.rows[0].cells);
  var el={own:document.getElementById('us-own'),conf:document.getElementById('us-conf'),
    team:document.getElementById('us-team'),pos:document.getElementById('us-pos'),
    find:document.getElementById('us-find'),group:document.getElementById('us-group'),
    count:document.getElementById('us-count')};
  var mine=CFG.mine;
  try{var saved=localStorage.getItem(CFG.storage||'cfbMyTeam'); if(saved&&CFG.teams[saved]) mine=saved;}catch(e){}
  var mineOpt=el.own.querySelector('option[value="mine"]');
  if(mineOpt) mineOpt.textContent='My team'+(CFG.teams[mine]?' ('+CFG.teams[mine]+')':'');
  rows.forEach(function(r){ if(mine&&r.dataset.own===mine) r.classList.add('us-mine'); });

  var sortCol=CFG.sort||0, sortAsc=false;
  function val(r,i){
    var c=r.cells[i], v=c.dataset.v;
    if(v===undefined) return c.textContent.toLowerCase();
    return v===''?null:+v;
  }
  function cmp(i,asc){return function(a,b){
    var x=val(a,i), y=val(b,i);
    if(x===null||y===null) return (x===null)-(y===null);   // blanks last either way
    if(x<y) return asc?-1:1; if(x>y) return asc?1:-1; return 0;};}
  function draw(){
    var by=cmp(sortCol,sortAsc), sorted=rows.slice().sort(by);
    if(el.group.checked) sorted.sort(function(a,b){
      return a.dataset.team<b.dataset.team?-1:a.dataset.team>b.dataset.team?1:0;});
    var o=el.own.value,c=el.conf?el.conf.value:'',t=el.team.value,p=el.pos.value,
        q=(el.find.value||'').toLowerCase(), shown=0, last=null;
    sorted.forEach(function(r){
      var d=r.dataset, own=d.own;
      var ok=(!o||(o==='fa'?!own:o==='held'?!!own:o==='mine'?own===mine:own===o))
        &&(!c||d.conf===c)&&(!t||d.team===t)&&(!p||d.pos===p)&&(!q||d.name.indexOf(q)>=0);
      r.style.display=ok?'':'none';
      r.classList.toggle('us-break',ok&&el.group.checked&&last!==null&&last!==d.team);
      if(ok){shown++; last=d.team;}
      body.appendChild(r);
    });
    el.count.textContent=shown+' player'+(shown===1?'':'s');
    heads.forEach(function(h,i){h.classList.toggle('us-on',i===sortCol);
      h.classList.toggle('us-asc',i===sortCol&&sortAsc);});
    var bits=[];
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
      else if(el[k]&&el[k].tagName==='SELECT') el[k].value=v;
    });
  }
  [el.own,el.team,el.pos,el.group].forEach(function(x){x.addEventListener('change',draw);});
  if(el.conf) el.conf.addEventListener('change',function(){schools();draw();});
  el.find.addEventListener('input',draw);
  document.getElementById('us-reset').addEventListener('click',function(){
    el.own.value=el.team.value=el.pos.value=el.find.value=''; if(el.conf) el.conf.value='';
    el.group.checked=false; schools(); draw();});
  fromHash(); schools(); draw();
})();
</script>{% endraw %}"""


def bar(share) -> str:
    if share is None or pd.isna(share):
        return "&mdash;"
    pct = max(0.0, min(float(share), 1.0))
    return (f"<span class='us-bar'><i style='width:{pct * 100:.0f}%'></i></span>"
            f"{pct:.0%}")


def pct(value) -> str:
    return "&mdash;" if value is None or pd.isna(value) else f"{float(value):.0%}"


def v(value, digits: int = 4) -> str:
    """A cell's sort key: blank for a missing number, so it sorts last."""
    return "" if value is None or pd.isna(value) else f"{round(float(value), digits):g}"


def num(value, fmt: str = "{:.0f}") -> str:
    return f"<td data-v='{v(value)}'>{fmt.format(value)}</td>"


def options(values, labels: dict = None, data: dict = None) -> str:
    labels, data = labels or {}, data or {}
    return "".join(
        f'<option value="{escape(str(v), quote=True)}"'
        + (f' data-conf="{escape(data[v], quote=True)}"' if v in data else "")
        + f'>{escape(str(labels.get(v, v)))}</option>' for v in values)
