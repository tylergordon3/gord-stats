"""
Matchup strength, shared by /cfb/strength/ and /fantasy/strength/: whose
schedule helps from here, and which defences are worth attacking.

Each sport rates its defences position by position - fantasy points allowed
against par, 1.00 being par (cfb.defense; fantasy.league.defense) - and hands
the ratings here:

  * price()            every roster's next weeks: each player's opponent rated
                       at his own position, weighted by what he is projected to
                       be worth, so a schedule is only easy in the places a
                       roster actually starts somebody.
  * schedule_table()   those rows, easiest first.
  * defense_table()    the ratings themselves, toughest first: rank 1 gives up
                       the least, the last place the most - the convention the
                       team dashboards use for their opponent cells.

The NFL page also redraws the schedule for a reader's own league, in the
browser. SCHEDULE_JS is price() and schedule_table() again, step for step and
down to the markup, so the two halves of that page cannot drift apart
(tests/test_strength_page.py runs both over one league and compares).
"""
from html import escape

import pandas as pd

from gordstats import roster_page

# How many weeks ahead the schedule looks. Past this the rosters that own these
# players will have changed anyway.
WEEKS_AHEAD = 6

CSS = """<style>
table.st{width:100%;border-collapse:collapse;font-size:14px}
table.st th{background:#eef2f7;color:#334155;padding:6px 9px;text-align:center;font-size:12px;
  text-transform:uppercase;letter-spacing:.03em;white-space:nowrap;border:1px solid #e2e8f0}
table.st td{padding:5px 9px;border:1px solid #eef2f7;color:#0f172a;background:#fff;
  text-align:center;white-space:nowrap}
table.st td.st-name{text-align:left;font-weight:600}
table.st tbody tr:nth-child(even) td{background:#f8fafc}
table.st td:first-child,table.st th:first-child{position:sticky;left:0;z-index:1}
.st-note{font-size:13px;color:#4a5a68;margin:6px 0 12px;line-height:1.55}
.st-rk{display:inline-block;min-width:18px;text-align:right;color:#64748b;font-size:12px;
  margin-right:6px}
.st-scroll{overflow-x:auto}
/* Below: only the NFL page uses these (logos, bye counts, the reader's team). */
table.st img.st-logo{display:inline-block;width:16px;height:16px;object-fit:contain;
  vertical-align:-3px;margin:0 5px 0 0;border:none;padding:0;box-shadow:none;background:none;
  border-radius:0;filter:drop-shadow(0 0 1px rgba(255,255,255,.7))}
.st-bye{display:block;font-size:12px;line-height:1.2;color:#475569;font-weight:400}
table.st tr.st-mine td.st-name{box-shadow:inset 3px 0 0 var(--accent,#C2410C)}
table.st tr.st-mine td{font-weight:700}
.st-tn{display:inline-block;max-width:150px;overflow:hidden;text-overflow:ellipsis;
  vertical-align:bottom}
.st-wait{font-size:13px;color:#64748b}
@media (max-width:560px){
  table.st.st-fit{font-size:13px}
  table.st.st-fit th,table.st.st-fit td{padding:5px 6px}
  table.st.st-fit .st-tn{max-width:104px}
}
@media (prefers-color-scheme: dark){
  table.st th{background:#223052;color:#dde5ef;border-color:#2b3852}
  table.st td{background:#16203a;border-color:#2b3852;color:#dde5ef}
  table.st tbody tr:nth-child(even) td{background:#1b2540}
  .st-note{color:#aab7c9}
  .st-rk{color:#aab7c9}
  .st-bye,.st-wait{color:#aab7c9}
}
</style>"""


def heat(value, low=0.85, high=1.15) -> str:
    """Green where a schedule or a defence gives points up, red where it does
    not - the same direction in both tables, and the dashboards' scale."""
    if value is None or pd.isna(value):
        return ""
    return roster_page.heat(float(value), low, high)


def _num(value) -> str:
    return "&mdash;" if value is None or pd.isna(value) else f"{value:.2f}"


def _wrap(head: str, body: list, fit: bool = False, sticky: bool = False) -> str:
    cls = "st st-fit" if fit else "st"
    # data-sticky-head: assets/js/stickyhead.js keeps a copy of the column
    # names in view down a long table (the college one is 139 rows).
    attr = " data-sticky-head" if sticky else ""
    return (f"<div class='st-scroll'><table class='{cls}'{attr}>"
            f"<thead>{head}</thead><tbody>{''.join(body)}</tbody></table></div>")


# --------------------------------------------------------------------------- #
# Defence vs position
# --------------------------------------------------------------------------- #

def defense_table(rows: list, positions, titles: dict = None, fit: bool = True) -> str:
    """The league-wide table. `rows` are (label html, {position: rating},
    overall rating), toughest first; the label is already escaped. `titles`
    puts a tooltip on a position's header.

    Fit (the phone padding) by default: at 390px the college table's All
    column ran 9px past the screen on the wider padding (2026-10-02)."""
    titles = titles or {}
    body = []
    for rank, (label, values, overall) in enumerate(rows, 1):
        cells = "".join(f"<td style='{heat(values.get(pos))}'>{_num(values.get(pos))}</td>"
                        for pos in positions)
        body.append(f"<tr><td class='st-name'><span class='st-rk'>{rank}</span>"
                    f"{label}</td>{cells}"
                    f"<td style='{heat(overall)}'>{overall:.2f}</td></tr>")
    head = ("<tr><th>Defense</th>"
            + "".join(f"<th title='{escape(titles[p], quote=True)}'>{p}</th>" if p in titles
                      else f"<th>{p}</th>" for p in positions)
            + "<th>All</th></tr>")
    return _wrap(head, body, fit, sticky=True)


# --------------------------------------------------------------------------- #
# Schedule ahead
# --------------------------------------------------------------------------- #

def price(players: list, weeks: list, opponent: dict, ratings: dict) -> list:
    """Each roster's weeks, easiest schedule first.

    players   [{key, label, team, pos, weight, starter?}] - `key` is the roster,
              `label` its name (text), `team` what `opponent` is keyed on, and
              `weight` what the player is projected to be worth. `starter`
              marks the players whose byes the NFL page counts.
    opponent  {(team, week): the team he faces}; no entry is a bye, and a bye
              has no matchup to price, so it is left out of that week.
    ratings   {team: {position: rating or None}}

    -> [{key, label, weeks: {week: rating or None}, byes: {week: starters off},
         mean}], rosters with nothing to price dropped. Ties keep name order.
    """
    groups = {}
    for p in players:
        groups.setdefault(p["key"], []).append(p)
    order = sorted(groups, key=lambda k: (str(groups[k][0]["label"]), str(k)))
    rows = []
    for key in order:
        group = groups[key]
        per_week, byes = {}, {}
        for week in weeks:
            total = weight = 0.0
            off = 0
            for p in group:
                opp = opponent.get((p["team"], week))
                if not opp:
                    off += 1 if p.get("starter") else 0
                    continue
                rating = (ratings.get(opp) or {}).get(p["pos"])
                if rating is None:
                    continue
                total += rating * p["weight"]
                weight += p["weight"]
            per_week[week] = (total / weight) if weight else None
            byes[week] = off
        got = [v for v in per_week.values() if v is not None]
        if got:
            rows.append({"key": key, "label": group[0]["label"], "weeks": per_week,
                         "byes": byes, "mean": sum(got) / len(got)})
    rows.sort(key=lambda r: -r["mean"])
    return rows


def bye_note(n: int) -> str:
    return f"<span class='st-bye'>{n} bye{'' if n == 1 else 's'}</span>" if n else ""


def schedule_table(rows: list, weeks: list, byes: bool = False, keyed: bool = False,
                   fit: bool = False) -> str:
    """price()'s rows as a table. `byes` adds each week's count of starters on
    a bye under the rating; `keyed` marks each row with its roster
    (data-key), for the script that picks out the reader's own team; `fit`
    is the phone-first layout - tighter cells, and the average the table is
    ranked on beside the name rather than six weeks off the right edge."""
    body = []
    for rank, r in enumerate(rows, 1):
        cells = "".join(
            f"<td style='{heat(r['weeks'][w])}'>{_num(r['weeks'][w])}"
            + (bye_note(r["byes"][w]) if byes else "") + "</td>"
            for w in weeks)
        attrs = f" data-key='{escape(str(r['key']), quote=True)}'" if keyed else ""
        # Keyed rows are a fantasy league's team names, which run long: they
        # are clipped to a width and carried whole in the tooltip.
        name = (f"<td class='st-name' title='{escape(str(r['label']), quote=True)}'>"
                f"<span class='st-rk'>{rank}</span>"
                f"<span class='st-tn'>{escape(str(r['label']))}</span></td>" if keyed
                else f"<td class='st-name'><span class='st-rk'>{rank}</span>"
                     f"{escape(str(r['label']))}</td>")
        mean = f"<td style='{heat(r['mean'])}'><b>{r['mean']:.2f}</b></td>"
        body.append(f"<tr{attrs}>{name}{mean}{cells}</tr>" if fit
                    else f"<tr{attrs}>{name}{cells}{mean}</tr>")
    weeks_head = "".join(f"<th>Wk {w}</th>" for w in weeks)
    head = (f"<tr><th>Team</th><th>Avg</th>{weeks_head}</tr>" if fit
            else f"<tr><th>Team</th>{weeks_head}<th>Average</th></tr>")
    return _wrap(head, body, fit)


# The two functions above, for a league that only exists in the browser.
# Same arithmetic in the same order, same markup: `esc` is html.escape with
# quote=True, `heat` is gordstats.roster_page.heat.
SCHEDULE_JS = """{% raw %}<script>
window.GSStrength=(function(){
  'use strict';
  function esc(v){
    return String(v==null?'':v).replace(/[&<>"']/g,function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#x27;'}[c];});
  }
  function heat(v,low,high){
    if(v==null||v!==v) return '';
    low=low==null?0.85:low; high=high==null?1.15:high;
    var t=Math.min(Math.max((v-low)/Math.max(high-low,1e-9),0),1);
    var c=t<0.5?[211,47,47]:[46,125,50];
    return 'background:rgba('+c[0]+','+c[1]+','+c[2]+','
      +(Math.abs(t-0.5)*2*0.45).toFixed(2)+')';
  }
  function num(v){ return (v==null||v!==v)?'&mdash;':v.toFixed(2); }
  function cmp(a,b){ return a<b?-1:(a>b?1:0); }

  /** price(): `opponent(team, week)` is the team he faces, or '' on a bye. */
  function price(players, weeks, opponent, ratings){
    var groups={}, order=[];
    players.forEach(function(p){
      if(!groups[p.key]){ groups[p.key]=[]; order.push(p.key); }
      groups[p.key].push(p);
    });
    order.sort(function(a,b){
      return cmp(String(groups[a][0].label),String(groups[b][0].label))||cmp(String(a),String(b));
    });
    var rows=[];
    order.forEach(function(key){
      var group=groups[key], per={}, byes={}, got=[];
      weeks.forEach(function(week){
        var total=0, weight=0, off=0;
        group.forEach(function(p){
          var opp=opponent(p.team, week);
          if(!opp){ off+=p.starter?1:0; return; }
          var rating=(ratings[opp]||{})[p.pos];
          if(rating==null) return;
          total+=rating*p.weight;
          weight+=p.weight;
        });
        per[week]=weight?total/weight:null;
        byes[week]=off;
        if(per[week]!=null) got.push(per[week]);
      });
      if(got.length){
        var sum=0;
        got.forEach(function(v){ sum+=v; });
        rows.push({key:key, label:group[0].label, weeks:per, byes:byes, mean:sum/got.length});
      }
    });
    rows.sort(function(a,b){ return b.mean-a.mean; });
    return rows;
  }

  function byeNote(n){
    return n?"<span class='st-bye'>"+n+' bye'+(n===1?'':'s')+'</span>':'';
  }

  /** schedule_table(rows, weeks, byes=true, keyed=true, fit=true). */
  function table(rows, weeks){
    var body=rows.map(function(r,i){
      var cells=weeks.map(function(w){
        return "<td style='"+heat(r.weeks[w])+"'>"+num(r.weeks[w])+byeNote(r.byes[w])+'</td>';
      }).join('');
      return "<tr data-key='"+esc(r.key)+"'><td class='st-name' title='"+esc(r.label)
        +"'><span class='st-rk'>"+(i+1)+"</span><span class='st-tn'>"+esc(r.label)+'</span></td>'
        +"<td style='"+heat(r.mean)+"'><b>"+r.mean.toFixed(2)+'</b></td>'+cells+'</tr>';
    }).join('');
    var head='<tr><th>Team</th><th>Avg</th>'
      +weeks.map(function(w){ return '<th>Wk '+w+'</th>'; }).join('')+'</tr>';
    return "<div class='st-scroll'><table class='st st-fit'><thead>"+head+'</thead><tbody>'
      +body+'</tbody></table></div>';
  }

  /** Bold the reader's own team: the row whose roster is `key`. */
  function mark(root, key){
    if(!root||key==null) return;
    Array.prototype.forEach.call(root.querySelectorAll('tr[data-key]'),function(tr){
      tr.classList.toggle('st-mine', tr.getAttribute('data-key')===String(key));
    });
  }

  return {price:price, table:table, heat:heat, mark:mark};
})();
</script>{% endraw %}"""
