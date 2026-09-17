"""
Usage (docs/cfb/usage/): who is getting the carries, the targets and the catches.

The projection pages answer "how good is this player". This answers the
question a college fantasy league actually argues about on a Tuesday - which
back is ahead in a committee, who the ball is going to now, and whether
anybody in the league owns him yet - because a season projection divided by
twelve games cannot see a backfield split 60/40 in September and 80/20 in
November.

Everything here is per game, from cfb.usage: carries, targets and catches
against the team's own totals, over the last three played weeks and over the
season, with PPA (CFBD's predicted points added) as the efficiency column.
cfb.ownership says which fantasy team holds each player, so the table filters
to one roster, to the free agents, or to a whole conference's backfields.

    python -m cfb.site.usage
"""
import json
from html import escape

import pandas as pd

from cfb import espn, ownership, players, schools as schools_mod, usage as usage_mod, yahoo
from cfb.config import MY_TEAM, SEASON, WEB_DIR
from cfb.site import write_page

RECENT_WEEKS = 3
MIN_TOUCHES = 4                 # below this a share is one carry of noise
POSITIONS = ("QB", "RB", "WR", "TE")

_CSS = """<style>
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
_JS = """{% raw %}<script>
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
  try{var saved=localStorage.getItem('cfbMyTeam'); if(saved&&CFG.teams[saved]) mine=saved;}catch(e){}
  var mineOpt=el.own.querySelector('option[value="mine"]');
  if(mineOpt) mineOpt.textContent='My team'+(CFG.teams[mine]?' ('+CFG.teams[mine]+')':'');
  rows.forEach(function(r){ if(mine&&r.dataset.own===mine) r.classList.add('us-mine'); });

  var sortCol=6, sortAsc=false;                       // carry share, high first
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
    var o=el.own.value,c=el.conf.value,t=el.team.value,p=el.pos.value,
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
  el.conf.addEventListener('change',function(){schools();draw();});
  el.find.addEventListener('input',draw);
  document.getElementById('us-reset').addEventListener('click',function(){
    el.own.value=el.conf.value=el.team.value=el.pos.value=el.find.value='';
    el.group.checked=false; schools(); draw();});
  fromHash(); schools(); draw();
})();
</script>{% endraw %}"""


def _bar(share) -> str:
    if share is None or pd.isna(share):
        return "&mdash;"
    pct = max(0.0, min(float(share), 1.0))
    return (f"<span class='us-bar'><i style='width:{pct * 100:.0f}%'></i></span>"
            f"{pct:.0%}")


def _pct(value) -> str:
    return "&mdash;" if value is None or pd.isna(value) else f"{float(value):.0%}"


def _v(value, digits: int = 4) -> str:
    """A cell's sort key: blank for a missing number, so it sorts last."""
    return "" if value is None or pd.isna(value) else f"{round(float(value), digits):g}"


def _num(value, fmt: str = "{:.0f}") -> str:
    return f"<td data-v='{_v(value)}'>{fmt.format(value)}</td>"


def _conferences() -> dict:
    """CFBD school name -> this season's conference. ESPN's FPI pull knows the
    current alignment; the school bridge is a season behind, so it only fills
    in a school ESPN has not got."""
    espn_conf, ids = espn.conferences(), schools_mod.espn_ids()
    old = schools_mod.conferences()
    return {school: espn_conf.get(str(ids.get(school))) or old.get(school) or ""
            for school in old}


def _rows(recent: pd.DataFrame, season: pd.DataFrame, conf: dict) -> str:
    """One row per player: the recent share with its bar, the season share
    beside it in grey, and the raw counts behind both."""
    whole = season.set_index(["team", "athlete_id"])
    out = []
    for _, r in recent.iterrows():
        key = (r["team"], r["athlete_id"])
        season_row = whole.loc[key] if key in whole.index else None

        def was(col):
            return None if season_row is None else season_row[col]

        yards = r["rush_yds"] + r["rec_yds"]
        tds = r["rush_td"] + r["rec_td"]
        per_game = r["fpts"] / r["games"] if r["games"] else None
        catch = r["rec"] / r["targets"] if r["targets"] > 0 else None
        owned = bool(r["team_key"])
        own = (escape(str(r["owner"])) if owned else "<span class='us-fa'>FA</span>")
        out.append(
            f'<tr data-team="{escape(str(r["team"]), quote=True)}"'
            f' data-conf="{escape(conf.get(r["team"], ""), quote=True)}"'
            f' data-pos="{escape(str(r["pos"]), quote=True)}"'
            f' data-own="{escape(str(r["team_key"]), quote=True)}"'
            f' data-name="{escape(str(r["player"]).lower(), quote=True)}">'
            f'<td class="us-name">{escape(str(r["player"]))}</td>'
            f'<td class="us-team">{escape(str(r["team"]))}</td>'
            f'<td>{escape(str(r["pos"]))}</td>'
            f'<td class="us-own">{own}</td>'
            + _num(r["games"]) + _num(r["carries"])
            + f'<td data-v="{_v(r["car_share"])}">{_bar(r["car_share"])}</td>'
            f'<td class="us-lead" data-v="{_v(was("car_share"))}">{_pct(was("car_share"))}</td>'
            + _num(r["targets"])
            + f'<td data-v="{_v(r["tgt_share"])}">{_bar(r["tgt_share"])}</td>'
            f'<td class="us-lead" data-v="{_v(was("tgt_share"))}">{_pct(was("tgt_share"))}</td>'
            + _num(r["rec"])
            + f'<td data-v="{_v(r["rec_share"])}">{_pct(r["rec_share"])}</td>'
            f'<td data-v="{_v(catch)}">{_pct(catch)}</td>'
            + _num(yards) + _num(tds)
            + f'<td data-v="{_v(per_game)}">'
            + ("&mdash;" if per_game is None or pd.isna(per_game) else f"{per_game:.1f}") + "</td>"
            f'<td data-v="{_v(r["ppa"])}">'
            + ("&mdash;" if pd.isna(r["ppa"]) else f"{r['ppa']:+.2f}") + "</td></tr>")
    return "".join(out)


def _options(values, labels: dict = None, data: dict = None) -> str:
    labels, data = labels or {}, data or {}
    return "".join(
        f'<option value="{escape(str(v), quote=True)}"'
        + (f' data-conf="{escape(data[v], quote=True)}"' if v in data else "")
        + f'>{escape(str(labels.get(v, v)))}</option>' for v in values)


def body() -> str:
    frame = usage_mod.load()
    if frame.empty:
        return (_CSS + "<p>No games have been played yet — this page fills in once "
                "<code>python -m cfb.usage</code> has a week to read.</p>")
    fbs = set(schools_mod.load()["schools"])
    frame = frame[frame["team"].isin(fbs)].copy()
    lg = yahoo.league()
    frame["fpts"] = players.fantasy_points(frame, lg)
    weeks = sorted(int(w) for w in frame["week"].unique())
    recent_weeks = weeks[-RECENT_WEEKS:]

    recent = usage_mod.shares(frame, weeks=RECENT_WEEKS)
    season = usage_mod.shares(frame)
    recent = recent[recent["pos"].isin(POSITIONS)]
    recent = recent[(recent["carries"] + recent["targets"] + recent["rec"]) >= MIN_TOUCHES]
    recent = recent.sort_values(["car_share", "tgt_share"], ascending=False)
    recent = ownership.attach(recent)

    conf = _conferences()
    teams = sorted(recent["team"].unique())
    confs = sorted({conf.get(t) for t in teams if conf.get(t)})
    league_teams = {t["team_key"]: t["name"] for t in lg["teams"]}
    mine = next((k for k, n in league_teams.items() if n == MY_TEAM), "")
    by_name = sorted(league_teams, key=lambda k: league_teams[k].lower())
    controls = (
        "<div class='pin-bar'><div class='us-controls'>"
        "<label>Fantasy <select id='us-own'><option value=''>Everyone</option>"
        "<option value='mine'>My team</option><option value='fa'>Free agents</option>"
        "<option value='held'>Rostered</option>"
        f"<optgroup label='Teams'>{_options(by_name, league_teams)}</optgroup></select></label>"
        f"<label>Conference <select id='us-conf'><option value=''>All</option>"
        f"{_options(confs)}</select></label>"
        f"<label>School <select id='us-team'><option value=''>All</option>"
        f"{_options(teams, data=conf)}</select></label>"
        f"<label>Position <select id='us-pos'><option value=''>All</option>"
        f"{_options(POSITIONS)}</select></label>"
        "<label>Find <input id='us-find' type='search' placeholder='player'></label>"
        "<label title='Keep each school together, sorted inside by the chosen column'>"
        "<input id='us-group' type='checkbox'> Group by school</label>"
        "<button id='us-reset' type='button'>Reset</button>"
        "<span class='us-count' id='us-count'></span>"
        "</div></div>")

    span = (f"week {recent_weeks[0]}" if len(recent_weeks) == 1
            else f"weeks {recent_weeks[0]}&ndash;{recent_weeks[-1]}")
    head = ("<tr><th data-k='text'>Player</th><th data-k='text'>School</th>"
            "<th data-k='text'>Pos</th><th data-k='text'>Fantasy</th><th data-k='n'>G</th>"
            "<th data-k='n'>Car</th><th data-k='n'>Car share</th>"
            "<th data-k='n' class='us-lead'>Season</th>"
            "<th data-k='n'>Tgt</th><th data-k='n'>Tgt share</th>"
            "<th data-k='n' class='us-lead'>Season</th>"
            "<th data-k='n'>Rec</th><th data-k='n'>Rec share</th>"
            "<th data-k='n' title='Catches per target'>Catch%</th>"
            "<th data-k='n'>Yds</th><th data-k='n'>TD</th>"
            "<th data-k='n' title='League fantasy points per game played'>FPts/G</th>"
            "<th data-k='n'>PPA</th></tr>")
    cfg = json.dumps({"mine": mine, "teams": league_teams}).replace("</", "<\\/")
    return (
        _CSS
        + f"<p>Every FBS skill player's share of his own team's carries, targets and catches "
        f"over the last three played weeks (<strong>{span}</strong>), with the season share "
        "beside it, and who in the league owns him. The two share columns together are the "
        "backfield answer: a back at 55% of the carries over three weeks against 40% on the "
        "season is taking the job.</p>"
        "<details class='section'><summary>How to use this page</summary>"
        "<p class='us-note'><strong>Click any column</strong> to sort by it, again to "
        "reverse. <strong>Fantasy</strong> narrows the table to one roster, to everybody "
        "rostered, or to the <span class='us-fa'>FA</span> free agents; <em>My team</em> is "
        "the roster chosen on the <a href='/cfb/roster/'>team dashboard</a>. For a whole "
        "conference's backfields, pick the conference, set Position to RB and tick "
        "<strong>Group by school</strong>: each school stays together, its backs ordered by "
        "the column you sorted on, with free agents flagged in green. The filters live in "
        "the page address, so a filtered view can be bookmarked or shared.</p>"
        "<p class='us-note'>Carries, receptions and yards are the box scores; the "
        "denominators are the team's own players added up, so a share cannot exceed what "
        "the team ran. <strong>Targets</strong> are not published anywhere as a stat — "
        "they are counted out of the play-by-play text, matching the intended receiver "
        "inside his own team by jersey number and surname, then by initial and surname, so "
        "a pass whose receiver cannot be matched counts for the team but not for a player. "
        "<strong>Rec share</strong> is his catches out of the team's. <strong>FPts/G</strong> "
        "is the league's scoring on passing, rushing and receiving (interceptions and "
        "fumbles are not in this feed). <strong>PPA</strong> is CollegeFootballData's "
        "predicted points added per play, the efficiency number beside the volume ones. "
        "Snap counts do not exist free for college football; share of touches is the honest "
        "substitute. A player counts as a free agent when no roster in the league holds "
        "him.</p></details>"
        + controls
        + f"<div class='us-scroll'><table class='us'><thead>{head}</thead>"
        f"<tbody>{_rows(recent, season, conf)}</tbody></table></div>"
        + f"<script type='application/json' id='us-cfg'>{cfg}</script>" + _JS)


def generate():
    write_page(WEB_DIR / "usage" / "index.html", "CFB Usage", body(),
               subtitle=f"{SEASON} — carry, target and catch share, and who owns them")


if __name__ == "__main__":
    generate()
