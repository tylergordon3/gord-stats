"""
The look shared by the weekly matchup pages (cfb.site.matchups,
fantasy.site.matchups): the scoreboard table, the matchup header, the
roster tables and the week switcher. Each section renders its own rows -
the leagues score different things - but a matchup should read the same
way on both pages, so the classes and the styling live here once.
"""
import pandas as pd

CSS = """<style>
.mu-wrap{margin:8px 0 18px}
/* The fantasy section's stylesheet sizes tables inside .table-scroll to their
   content; the scoreboard should span the page on both sections. */
table.mu-board,.table-scroll table.mu-board{width:100%;border-collapse:collapse;font-size:14px}
table.mu-board th{background:#eef2f7;color:#334155;padding:7px 10px;text-align:center;
  font-size:12px;text-transform:uppercase;letter-spacing:.03em;white-space:nowrap;
  border:1px solid #e2e8f0}
table.mu-board td{padding:6px 10px;border:1px solid #eef2f7;color:#0f172a;background:#fff;
  text-align:center;white-space:nowrap;font-variant-numeric:tabular-nums}
/* The figures take only the width they need (width:1% on an auto-layout
   table) and the two team cells split the rest; max-width:0 lets a team cell
   shrink below its content, so on a narrow screen the names truncate (the
   full name is in the link's title) instead of pushing the right-hand team
   off the page. */
table.mu-board td:not(.mu-t),table.mu-board th:not(:first-child):not(:last-child){width:1%}
table.mu-board td.mu-t{text-align:left}
/* Only the outer two: the NFL page's disagreement and accuracy lists put a
   second text cell (the roster) mid-row, and at max-width:0 it collapsed. */
table.mu-board td.mu-t:first-child,table.mu-board td.mu-t:last-child{max-width:0}
table.mu-board td.mu-t a{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
table.mu-board td.mu-t.r{text-align:right}
@media (max-width:900px){table.mu-board th,table.mu-board td{padding:6px 6px}
  table.mu-board.started .mu-proj{display:none}}
table.mu-board td.mu-vs{color:#94a3b8;font-size:11px}
table.mu-board tbody tr:nth-child(even) td{background:#f8fafc}
table.mu-board td b.lead{color:#1a7f4b}
/* The matchup title in a section summary: below the phone breakpoint the
   site lays summaries out as flex boxes, which drops the spaces around a
   bare "vs" - so it carries its own margins. */
.mu-vs-sum{margin:0 .35em;color:#94a3b8;font-weight:400}
/* The scoreboard on a phone: one card per matchup, a line per side, instead
   of a nine-column table that truncates the names and scrolls sideways. */
.mu-cards{display:none}
.mu-card{display:block;border:1px solid #e2e8f0;border-radius:10px;background:#fff;
  padding:4px 10px;margin:0 0 8px;color:inherit;text-decoration:none}
.mu-cs{display:flex;align-items:center;gap:8px;padding:5px 0}
.mu-cs+.mu-cs{border-top:1px solid #eef2f7}
.mu-cs img.mu-tlogo{width:24px;height:24px}
.mu-cs .nm{flex:1;min-width:0;font-weight:600;font-size:14px;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.mu-cs .num{font-weight:800;font-size:15px;font-variant-numeric:tabular-nums;min-width:44px;
  text-align:right}
.mu-cs .num.proj{font-weight:600;color:#475569}
.mu-cs .wp{min-width:36px;text-align:right;font-size:12px;color:#64748b;
  font-variant-numeric:tabular-nums}
.mu-cs .med{min-width:40px;text-align:right;font-size:12px;font-variant-numeric:tabular-nums;
  color:#64748b}
/* Against the median: green above it, red below, on the cards and in the table. */
.mu-med-up{color:#1a7f4b!important}
.mu-med-down{color:#b3382c!important}
.mu-median{font-size:13px;color:#475569;margin:2px 0 8px}
@media (max-width:700px){
  .mu-board-wrap{display:none}
  .mu-cards{display:block;margin:6px 0 12px}
  /* Lists styled as scoreboards (the NFL page's disagreements): the
     scoreboard's shrink-to-fit team cells collapse a player column to
     nothing here, so the text cells get their width back and wrap, and the
     per-source columns give way to the consensus and the gap. */
  table.mu-dis td.mu-t,table.mu-dis td.mu-t:first-child{max-width:none;white-space:normal;
    overflow-wrap:anywhere}
  table.mu-dis .mu-src{display:none}
  table.mu-dis th,table.mu-dis td{padding:6px 5px;font-size:12.5px}
}
.mu-head{display:grid;grid-template-columns:1fr auto 1fr;gap:12px;align-items:center;
  margin:6px 0 10px}
.mu-side{display:flex;align-items:center;gap:10px;min-width:0}
.mu-side.r{flex-direction:row-reverse;text-align:right}
.mu-side .nm{font-weight:700;font-size:16px;overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap}
.mu-side .rec{font-size:12px;color:#64748b;margin-left:6px;font-weight:400}
.mu-side .num{font-size:26px;font-weight:700;line-height:1.1;font-variant-numeric:tabular-nums}
.mu-side .num.lead{color:#1a7f4b}
.mu-side .sub{font-size:12px;color:#64748b;white-space:nowrap;font-style:italic}
.mu-side .sub b{color:#334155}
.mu-mid{text-align:center;color:#94a3b8;font-size:12px;text-transform:uppercase;
  letter-spacing:.06em;white-space:nowrap}
.mu-wp{height:6px;border-radius:3px;background:#e2e8f0;overflow:hidden;margin:6px 0 2px;
  display:flex}
.mu-wp i{display:block;height:100%;background:#2f6db5}
.mu-wp i.b{background:#c0392b}
.mu-wp-lbl{display:flex;justify-content:space-between;font-size:11px;color:#64748b;
  margin-bottom:8px}
/* Two rosters side by side only while each can have ~600px - nine columns
   need that to read without a scrollbar. Narrower (half a laptop screen, a
   tablet, a phone) and they stack; min(100%,...) keeps a phone from
   overflowing the single column. */
.mu-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,600px),1fr));
  gap:14px;align-items:start}
/* min-width:0 on the grid items, or a wide roster table sets the column width
   and the right-hand roster runs off the page instead of scrolling. */
.mu-grid>div{min-width:0}
/* Side by side, the two rosters mirror each other so both teams' points meet
   in the middle: the left table runs Stats ... Game, Player, Slot, Pts and the
   right one Pts, Slot, Player, Game ... Stats. Done by laying the left table
   out right-to-left (which reverses its columns) and setting each cell back
   to left-to-right so the text reads normally. A container query keys it to
   the grid actually being two columns; stacked, both read the normal way. */
.mu-grid{container-type:inline-size}
@container (min-width:1214px){
  .mu-grid>div:first-child table.mu-roster{direction:rtl}
  .mu-grid>div:first-child table.mu-roster th,
  .mu-grid>div:first-child table.mu-roster td{direction:ltr}
  .mu-grid>div:first-child table.mu-roster td.mu-p,
  .mu-grid>div:first-child table.mu-roster td.mu-g,
  .mu-grid>div:first-child table.mu-roster td.mu-s,
  .mu-grid>div:first-child table.mu-roster tr.sep td{text-align:right}
  .mu-grid>div:first-child table.mu-roster img.mu-logo{margin:0 0 0 5px}
  /* The player cell mirrors too: label, then name, then logo on the outside. */
  .mu-grid>div:first-child table.mu-roster .mu-pc{flex-direction:row-reverse;
    justify-content:flex-start}
  .mu-grid>div:first-child table.mu-roster td.mu-p .nm{display:inline-flex;
    flex-direction:row-reverse;align-items:center}
  .mu-grid>div:first-child .mu-swap{text-align:right}
}
.mu-pc{display:inline-flex;align-items:center;flex-wrap:wrap;gap:0 4px;max-width:100%}
/* Stacked rosters need a name over each table; the side-by-side layout
   already has the header above. */
.mu-grid>div>.mu-who{display:none;font-weight:700;font-size:14px;margin:6px 0 4px}
@media (max-width:1150px){.mu-grid>div>.mu-who{display:block}}
/* On a phone the header keeps two columns, each side's score under its own
   team - the layout the Yahoo and Sleeper apps use - with the win bar
   spanning both beneath. Logo on top like an avatar, then the name, the big
   number and the projection line, mirrored on the right. */
@media (max-width:700px){
  .mu-head{grid-template-columns:1fr 1fr;gap:10px;align-items:start}.mu-mid{display:none}
  .mu-side{flex-direction:column;align-items:flex-start;gap:3px}
  .mu-side.r{flex-direction:column;align-items:flex-end;text-align:right}
  .mu-side>div{min-width:0;max-width:100%}
  /* Names wrap to two lines rather than truncating, at a fixed height so
     the two scores stay level whatever the names' lengths. */
  .mu-side .nm{font-size:13.5px;max-width:100%;white-space:normal;overflow-wrap:anywhere;
    display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;
    line-height:1.25;min-height:2.5em}
  .mu-side .num{font-size:28px;line-height:1.05}
  .mu-side .sub{white-space:normal;font-size:11px;line-height:1.3}
  img.mu-tlogo{width:30px;height:30px}}

/* ---- paired view: the two rosters as one column, for a phone ----
   Two six-column tables cannot sit side by side at 390px. They stack, which
   puts the opponent's quarterback three thousand pixels below yours, and each
   still scrolls sideways inside its own container. Below 700px the tables are
   replaced by one row per lineup slot - your player, the slot, theirs - which
   is the layout every fantasy app settled on, because the question the page
   answers is who is winning this slot. */
.mu-pair{display:none}
@media (max-width:700px){
  .mu-grid{display:none}
  .mu-pair{display:block;margin:8px 0 4px}
}
.mu-pr{display:grid;grid-template-columns:1fr 40px 1fr;align-items:stretch;
  gap:0;border-bottom:1px solid #eef2f7}
.mu-pr.bench{background:#f8fafc}
.mu-pr.total{background:#eef2f7;font-weight:700;border-bottom:none;margin-top:2px}
.mu-pp{display:flex;align-items:center;gap:6px;min-width:0;padding:6px 4px}
/* The right-hand side mirrors so both teams' points meet in the middle,
   beside the slot, which is what makes the comparison readable at a glance. */
.mu-pr>.mu-pp:last-child{flex-direction:row-reverse;text-align:right}
.mu-pp.empty{visibility:hidden}
/* The name block takes the slack, so the figures sit in a fixed column at
   the slot's edge and line up down the page. */
.mu-pn{flex:1 1 auto;min-width:0;display:flex;flex-direction:column;line-height:1.25}
.mu-pr>.mu-pp:last-child .mu-pn{align-items:flex-end}
.mu-pcol{flex:none;min-width:46px;display:flex;flex-direction:column;align-items:flex-end;
  line-height:1.15}
.mu-pr>.mu-pp:last-child .mu-pcol{align-items:flex-start}
/* The game, under the position: opponent and kickoff, then the live score
   and clock, then the final - the same span the live poll rewrites in the
   table, so it carries the same pulsing dot while the game is on. */
.mu-pn .mu-g{font-size:10px;color:#64748b;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;max-width:100%}
.mu-pn .mu-g .live{color:#b3382c;font-weight:700}
.mu-pn .mu-g .live::before{content:"";display:inline-block;width:6px;height:6px;
  border-radius:50%;background:#b3382c;margin-right:4px;vertical-align:1px;
  animation:mu-pulse 1.4s ease-in-out infinite}
.mu-pn .mu-g .fin{color:#64748b}
.mu-pn .mu-g .bye{font-style:italic;color:#94a3b8}
/* The projection under the points; italic once it is a live expected final. */
.mu-pp .mu-gs{font-size:10px;color:#64748b;font-variant-numeric:tabular-nums}
.mu-pp .mu-gs.live{font-style:italic}
/* The name truncates rather than wrapping: a wrapped name makes rows different
   heights and the two sides stop lining up, which is the whole point. */
.mu-pn .nm{font-size:12.5px;font-weight:600;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;max-width:100%}
.mu-pn .mu-pm{font-size:10px;color:#64748b;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;max-width:100%}
.mu-pp .mu-pts{font-size:14px;font-weight:700;font-variant-numeric:tabular-nums;
  flex:none;text-align:right;color:#0f172a}
.mu-pr>.mu-pp:last-child .mu-pts{text-align:left}
.mu-pr.bench .mu-pts{font-weight:600;color:#475569}
.mu-pslot{display:flex;align-items:center;justify-content:center;font-size:10px;
  font-weight:700;color:#64748b;background:#f1f5f9;letter-spacing:.02em}
.mu-pr.bench .mu-pslot{color:#94a3b8}
.mu-pr.total .mu-pslot{background:transparent}
/* The site stylesheet frames every img - border, padding, shadow, pale
   background - which turned each 14px school mark into a boxed thumbnail
   twice the intended size and ate the width the name needed. The roster table
   resets the same properties for the same reason. */
.mu-pair img.mu-logo{width:14px;height:14px;object-fit:contain;margin:0 4px 0 0;
  border:none;padding:0;box-shadow:none;background:none;border-radius:0;
  vertical-align:middle}
/* The bench stays in view under the starters, behind a quiet divider. */
.mu-pbench-h{font-size:10px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;
  color:#94a3b8;padding:9px 4px 3px}
.mu-pair .inj{font-size:9px;font-weight:700;color:#b3382c;margin-left:3px}
.mu-pair .mu-hint{font-size:9px;font-weight:700;margin-left:3px;border-radius:3px;padding:0 3px}
.mu-pair .mu-hint.in{background:#d5efdd;color:#1a7f4b}
.mu-pair .mu-hint.out{background:#fde2dd;color:#b3382c}
table.mu-roster{width:100%;border-collapse:collapse;font-size:13px}
table.mu-roster th{background:#eef2f7;color:#334155;padding:5px 7px;text-align:center;
  font-size:11px;text-transform:uppercase;letter-spacing:.03em;white-space:nowrap;
  border:1px solid #e2e8f0}
table.mu-roster td{padding:4px 7px;border:1px solid #eef2f7;color:#0f172a;background:#fff;
  text-align:center;white-space:nowrap;font-variant-numeric:tabular-nums;vertical-align:middle}
table.mu-roster td.mu-p,table.mu-roster td.mu-g,table.mu-roster td.mu-s{text-align:left}
table.mu-roster td.mu-slot{font-weight:700;color:#64748b;font-size:11px}
/* No min-width: before kickoff every stat line is empty and the column
   should cost nothing; once lines arrive the cell wraps to what is left. */
table.mu-roster td.mu-s{color:#64748b;font-size:12px;white-space:normal}
table.mu-roster td.mu-g{font-size:12px;color:#334155}
/* A player whose game is on: a pulsing dot on the game cell, a tint on
   the row (and on the paired phone cell), in both themes. */
table.mu-roster td.mu-g .live{color:#b3382c;font-weight:700;white-space:nowrap}
table.mu-roster td.mu-g .live::before{content:"";display:inline-block;width:7px;height:7px;
  border-radius:50%;background:#b3382c;margin-right:5px;vertical-align:1px;
  animation:mu-pulse 1.4s ease-in-out infinite}
@keyframes mu-pulse{0%,100%{opacity:1}50%{opacity:.25}}
table.mu-roster tr.live td{background:#fff5f4}
table.mu-roster tr.live td.mu-pts{background:#ffe9e6}
.mu-pr .mu-pp.live{background:#fff5f4}
.mu-pr .mu-pp.live .mu-pts .mu-now::after{content:"";display:inline-block;width:6px;height:6px;
  border-radius:50%;background:#b3382c;margin-left:4px;vertical-align:1px;
  animation:mu-pulse 1.4s ease-in-out infinite}
table.mu-roster td.mu-g .fin{color:#64748b}
table.mu-roster td.mu-g .bye{color:#94a3b8;font-style:italic}
table.mu-roster tr.bench td{background:#f8fafc;color:#475569}
table.mu-roster tr.bench td.mu-slot{color:#94a3b8}
table.mu-roster tr.sep td{background:#f1f5f9;color:#475569;font-weight:700;font-size:11px;
  text-align:left;text-transform:uppercase;letter-spacing:.04em;padding:3px 7px}
table.mu-roster tr.total td{background:#eef2f7;font-weight:700}
/* The score is the point of the page: bigger, bolder, on its own tint, at
   the inner edge of each roster where the two meet. */
table.mu-roster td.mu-pts,table.mu-roster th.mu-pts{background:#e8f0fb;
  border-right-color:#d5e0f0;min-width:52px}
table.mu-roster td.mu-pts{font-size:15px;font-weight:700;color:#0f172a}
table.mu-roster tr.bench td.mu-pts{background:#eef3fa;font-weight:600;color:#475569}
table.mu-roster tr.total td.mu-pts{background:#d9e6f7;font-size:16px}
table.mu-roster th.mu-pts{color:#1e3a8a}
/* The player cell may break only between the name and its label: logo and
   name are one unbreakable unit, the label another. */
table.mu-roster td.mu-p{white-space:normal;min-width:150px}
table.mu-roster td.mu-p .nm{font-weight:600;white-space:nowrap;display:inline-block}
table.mu-roster td.mu-p .mu-lbl{white-space:nowrap;display:inline-block}
/* Own names for the small labels: custom.css has a global .meta that styles
   any element carrying it as a block. */
table.mu-roster td.mu-p .mu-meta{font-size:11px;color:#64748b;margin-left:4px}
table.mu-roster td.mu-p .inj{font-size:10px;font-weight:700;color:#b3382c;margin-left:4px}
table.mu-roster td.mu-p .mu-hint{font-size:10px;font-weight:700;margin-left:4px;
  border-radius:3px;padding:0 4px}
table.mu-roster td.mu-p .mu-hint.in{background:#d5efdd;color:#1a7f4b}
table.mu-roster td.mu-p .mu-hint.out{background:#fde2dd;color:#b3382c}
/* The scoreboard-styled tables (the NFL page's disagreements and accuracy
   lists) carry the same logos; without this they got the theme's figure
   styling and rendered at full size. */
/* A projection that has become an expected final mid-game reads in italics. */
.mu-side .sub b.live{font-style:italic}
/* The hybrid score cell (score_cell): the figure, then a small line under it -
   proj before kickoff, the live expected final, or final. */
.mu-pts .mu-now{display:block}
.mu-pts .mu-now.proj{color:#94a3b8;font-style:italic;font-weight:600}
.mu-pts .mu-exp{display:block;font-size:10px;font-weight:600;color:#64748b;line-height:1.1;
  white-space:nowrap}
.mu-pts .mu-exp:empty{display:none}
.mu-pts .mu-exp.live{font-style:italic;color:#b3382c}
table.mu-roster img.mu-logo,table.mu-board img.mu-logo{width:18px;height:18px;
  object-fit:contain;vertical-align:middle;
  margin:0 5px 0 0;border:none;padding:0;box-shadow:none;background:none;border-radius:0;
  filter:drop-shadow(0 0 1px rgba(255,255,255,.7))}
img.mu-tlogo{width:34px;height:34px;border-radius:50%;flex:none;border:none;padding:0;
  box-shadow:none;margin:0}
table.mu-board img.mu-tlogo{width:20px;height:20px;vertical-align:middle;margin:0 6px 0 0}
table.mu-board td.mu-t.r img.mu-tlogo{margin:0 0 0 6px}
.mu-note{font-size:13px;color:#4a5a68;margin:4px 0 10px}
.mu-swap{font-size:12px;color:#334155;margin:4px 0 0}
.mu-swap b{color:#1a7f4b}
.mu-wrap details.section>summary{font-size:15px}
@media (prefers-color-scheme: dark){
  table.mu-board th,table.mu-roster th{background:#223052;color:#dde5ef;border-color:#2b3852}
  table.mu-board td,table.mu-roster td{background:#16203a;border-color:#2b3852;color:#dde5ef}
  table.mu-board tbody tr:nth-child(even) td{background:#1b2540}
  .mu-card{background:#16203a;border-color:#2b3852}
  .mu-cs+.mu-cs{border-color:#2b3852}
  .mu-cs .num.proj{color:#c5cfdc}
  .mu-cs .wp,.mu-cs .med,.mu-median{color:#aab7c9}
  .mu-med-up{color:#6ee7b7!important}
  .mu-med-down{color:#ff9b91!important}
  table.mu-board td b.lead,.mu-side .num.lead,.mu-swap b{color:#8ff0bd}
  table.mu-roster tr.bench td{background:#1b2540;color:#aab7c9}
  table.mu-roster tr.sep td{background:#223052;color:#aab7c9}
  table.mu-roster tr.total td{background:#223052}
  table.mu-roster td.mu-pts,table.mu-roster th.mu-pts{background:#1e2c52;border-right-color:#2f4070}
  table.mu-roster td.mu-pts{color:#ffffff}
  table.mu-roster tr.bench td.mu-pts{background:#1b2848;color:#aab7c9}
  table.mu-roster tr.total td.mu-pts{background:#27407a}
  table.mu-roster th.mu-pts{color:#bcd0ff}
  table.mu-roster td.mu-slot,table.mu-roster td.mu-s,table.mu-roster td.mu-p .mu-meta{color:#aab7c9}
  table.mu-roster td.mu-g{color:#dde5ef}
  table.mu-roster td.mu-g .live{color:#ffb4ab}
  table.mu-roster td.mu-g .live::before,.mu-pr .mu-pp.live .mu-pts .mu-now::after{background:#ffb4ab}
  .mu-pts .mu-now.proj{color:#7c8ba1}
  .mu-pts .mu-exp{color:#aab7c9}
  .mu-pts .mu-exp.live{color:#ffb4ab}
  table.mu-roster tr.live td{background:#2a1f26}
  table.mu-roster tr.live td.mu-pts{background:#3a262b}
  .mu-pr .mu-pp.live{background:#2a1f26}
  .mu-pn .mu-g,.mu-pn .mu-g .fin,.mu-pp .mu-gs{color:#aab7c9}
  .mu-pn .mu-g .live{color:#ffb4ab}
  .mu-pn .mu-g .live::before{background:#ffb4ab}
  table.mu-roster td.mu-g .fin,table.mu-roster td.mu-g .bye{color:#aab7c9}
  table.mu-roster td.mu-p .inj{color:#ffb4ab}
  table.mu-roster td.mu-p .mu-hint.in{background:#123c2e;color:#8ff0bd}
  table.mu-roster td.mu-p .mu-hint.out{background:#4a1f1a;color:#ffb4ab}
  .mu-side .rec,.mu-side .sub,.mu-wp-lbl,.mu-mid{color:#aab7c9}
  .mu-side .sub b{color:#dde5ef}
  .mu-wp{background:#2b3852}
  .mu-note{color:#aab7c9}
  .mu-swap{color:#dde5ef}
  .mu-pr{border-bottom-color:#2b3852}
  .mu-pr.bench{background:#1b2540}
  .mu-pr.total{background:#223052}
  .mu-pslot{background:#223052;color:#aab7c9}
  .mu-pn .mu-pm{color:#aab7c9}
  .mu-pp .mu-pts{color:#ffffff}
  .mu-pr.bench .mu-pts{color:#aab7c9}
  .mu-pbench>summary{color:#dde5ef}
}
</style>"""

JS = """<script>
(function(){
  function show(w){
    var views=document.querySelectorAll('.wk-view');
    for(var i=0;i<views.length;i++){views[i].style.display='none';}
    var v=document.getElementById('wk-view-'+w);if(!v)return;
    v.style.display='';
    var btns=document.querySelectorAll('.wk-btn');
    for(var j=0;j<btns.length;j++){btns[j].classList.remove('active');}
    var b=document.getElementById('wk-tab-'+w);if(b)b.classList.add('active');
    if(history.replaceState){history.replaceState(null,'','#wk-'+w);}
  }
  window.show_wk=show;
  var m=(location.hash||'').match(/^#wk-(\\d+)$/);
  if(m&&document.getElementById('wk-view-'+m[1]))show(m[1]);
})();
</script>"""


def fmt(v, dec: int = 1) -> str:
    """A number, or an em dash for nothing."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{float(v):.{dec}f}"


def score_cell(pts, proj, state, exp=None, mark_proj: bool = False) -> str:
    """Inner HTML of a .mu-pts cell - one figure that is always the one that
    matters: the projection before kickoff (grey, marked proj), the points
    with the live expected final under them while the game is on, the points
    marked final after it; `mark_proj` labels the projection (the totals -
    on a player row the grey italic says it). `state` is the game's pre/in/post, "bye", or None
    when no game is known. LIVE_JS rewrites the cell the same way."""
    if state == "post":
        return f'<b class="mu-now">{fmt(pts or 0)}</b><span class="mu-exp">final</span>'
    if state == "in":
        sub = f"&rarr; {fmt(exp)}" if exp is not None else "live"
        return f'<b class="mu-now">{fmt(pts or 0)}</b><span class="mu-exp live">{sub}</span>'
    if state == "bye" and not pts:
        return '<b class="mu-now proj">&mdash;</b><span class="mu-exp">bye</span>'
    if pts:
        return f'<b class="mu-now">{fmt(pts)}</b><span class="mu-exp"></span>'
    return (f'<b class="mu-now proj">{fmt(proj)}</b>'
            f'<span class="mu-exp">{"proj" if mark_proj and proj is not None else ""}</span>')


def week_switch(weeks: list, current: int, views: dict) -> str:
    """The week buttons and one view per week, the current one showing.
    `.view-switch` styling is the site's (custom.css)."""
    buttons = "".join(
        f'<button class="wk-btn{" active" if w == current else ""}" '
        f"onclick=\"show_wk('{w}')\" id=\"wk-tab-{w}\">{w}</button>" for w in weeks)
    divs = "".join(
        f'<div id="wk-view-{w}" class="wk-view"'
        f'{"" if w == current else " style=\'display:none\'"}>{views[w]}</div>' for w in weeks)
    switch = ("" if len(weeks) == 1 else
              '<div class="pin-bar"><div class="view-switch">'
              f'<span class="switch-label">Week:</span>{buttons}</div></div>')
    return f'<div class="mu-wrap">{switch}<div id="mu-weeks">{divs}</div></div>' + JS


def board_cards(rows: list, started: bool, final: bool) -> str:
    """The scoreboard as cards, for a phone: `rows` is [(anchor, a, b)] with
    each side a dict of name, logo (html), key, pts, gs and wp (0-1 or None).
    Carries the same data-sb / data-wpl hooks as the table, so the live poll
    moves both."""
    cards = []
    for anchor, a, b in rows:
        def side(s):
            if started:
                v = s.get("pts")
                num = (f'<span class="num" data-sb="{s["key"]}" '
                       f'data-val="{v if v is not None else ""}">{fmt(v)}</span>')
            else:
                num = f'<span class="num proj" title="GordStats projection">{fmt(s.get("gs"))}</span>'
            wp = s.get("wp")
            wp_html = ("" if final or wp is None else
                       f'<span class="wp" data-wpl="{s["key"]}">{wp * 100:.0f}%</span>')
            med = s.get("med")
            med_html = ("" if med is None else
                        f'<span class="med {"mu-med-up" if med > 0 else "mu-med-down" if med < 0 else ""}" '
                        f'data-vsmed="{s["key"]}" title="against the week\'s median">{med:+.1f}</span>')
            return (f'<div class="mu-cs">{s.get("logo") or ""}<span class="nm">{s["name"]}</span>'
                    f"{num}{med_html}{wp_html}</div>")
        cards.append(f'<a class="mu-card" href="#{anchor}">{side(a)}{side(b)}</a>')
    return f'<div class="mu-cards">{"".join(cards)}</div>'


def win_bar(wp_a: float, wp_b: float, source: str, key_a: str = "", key_b: str = "") -> str:
    """Two-colour probability bar with the percentages under it. The keys let
    the live script move it as the source's probability changes."""
    return (f'<div class="mu-wp"><i data-wp="{key_a}" style="width:{wp_a * 100:.0f}%"></i>'
            f'<i class="b" data-wp="{key_b}" style="width:{wp_b * 100:.0f}%"></i></div>'
            f'<div class="mu-wp-lbl"><span><span data-wpl="{key_a}">{wp_a * 100:.0f}%</span> '
            f'({source})</span><span data-wpl="{key_b}">{wp_b * 100:.0f}%</span></div>')


# Game-state helpers a page's own MU_LIVE fetch can lean on: read ESPN's
# scoreboard (it allows browser fetches) into {game id: {state, detail,
# home/away scores}}, render a game's text from one side, and fold the
# states into a points payload by the data-gid / data-side each row carries.
LIVE_GAMES_JS = """
function muGameText(state,score,opp,detail){
  var sc=(score!==undefined&&score!==null&&opp!==undefined&&opp!==null)?' '+score+'\u2013'+opp:'';
  if(state==='in')return 'Live'+sc+(detail?' \u00b7 '+detail:'');
  if(state==='post')return 'Final'+sc;
  return null;}
function muGames(url){
  return fetch(url).then(function(r){return r.json();}).then(function(d){
    var games={};(d.events||[]).forEach(function(e){var c=(e.competitions||[])[0];if(!c)return;var st=c.status||{};
      var home=null,away=null;(c.competitors||[]).forEach(function(x){if(x.homeAway==='home')home=x;else away=x;});
      games[String(e.id)]={state:(st.type||{}).state||'pre',detail:(st.type||{}).shortDetail,
        period:st.period,clock:st.displayClock,home:home&&home.score,away:away&&away.score};});
    return games;}).catch(function(){return {};});}
function muElapsed(g){
  if(!g||g.state==='pre')return 0;if(g.state==='post')return 1;if(!g.period)return .5;if(g.period>4)return .95;
  var m=String(g.clock||'0:00').split(':'),left=(parseInt(m[0],10)||0)+((parseInt(m[1],10)||0)/60);
  return Math.min(Math.max(((g.period-1)*15+(15-left))/60,0),1);}
// Expected finals from the rows themselves: each starter's points so far plus
// the unplayed share of the projection on his row (data-proj), by his game's
// clock; the side's total follows. Written into the payload as players[pid].live
// and teams[key].gs_live, which the live updater already knows how to draw.
function muLiveProjections(payload,games){
  var teams=(payload&&payload.teams)||{};
  var wraps=document.querySelectorAll('[data-roster]');
  for(var i=0;i<wraps.length;i++){var wrap=wraps[i],key=wrap.getAttribute('data-roster'),t=teams[key];
    if(!t||!t.players)continue;
    var rows=wrap.querySelectorAll('tr.starter[data-pid]');if(!rows.length)continue;
    var total=0,any=false;
    for(var j=0;j<rows.length;j++){var tr=rows[j],pid=tr.getAttribute('data-pid'),p=t.players[pid];
      var proj=parseFloat(tr.getAttribute('data-proj'));if(isNaN(proj))proj=0;
      var g=games[tr.getAttribute('data-gid')],done=muElapsed(g);
      var pts=(p&&p.points!==undefined&&p.points!==null)?p.points:null;
      if(pts===null){total+=proj*(1-done);continue;}
      var e=pts+proj*(1-done);total+=e;any=true;
      if(g&&g.state!=='pre')p.live=e;}
    if(any)t.gs_live=total;}
  return payload;}
// The week's median for a page whose feed brings only points: of the sides'
// points once anyone has scored, of the live expected totals as the
// projection, and each side's margin against whichever applies.
function muMedian(payload){
  var teams=(payload&&payload.teams)||{};var ks=Object.keys(teams);if(ks.length<2)return payload;
  function median(a){a=a.slice().sort(function(x,y){return x-y;});var m=a.length>>1;return a.length%2?a[m]:(a[m-1]+a[m])/2;}
  var pts=ks.map(function(k){return teams[k].points;}).filter(function(v){return v!==null&&v!==undefined;});
  var projs=ks.map(function(k){return teams[k].gs_live;}).filter(function(v){return v!==null&&v!==undefined;});
  var started=pts.some(function(p){return p>0;});
  var medNow=(started&&pts.length===ks.length)?median(pts):null;
  var medProj=projs.length===ks.length?median(projs):null;
  ks.forEach(function(k){var t=teams[k];
    if(medNow!==null&&t.points!==null&&t.points!==undefined)t.vs_median=t.points-medNow;
    else if(medProj!==null&&t.gs_live!==null&&t.gs_live!==undefined)t.vs_median=t.gs_live-medProj;});
  payload.median={now:medNow,proj:medProj};return payload;}
function muMergeGames(payload,games){
  var teams=(payload&&payload.teams)||{};
  var els=document.querySelectorAll('[data-pid][data-gid]');
  for(var i=0;i<els.length;i++){var el=els[i];
    var g=games[el.getAttribute('data-gid')];if(!g)continue;
    var key=el.getAttribute('data-roster')||(el.closest('[data-roster]')||{}).getAttribute&&el.closest('[data-roster]').getAttribute('data-roster');
    if(!key)continue;var pid=el.getAttribute('data-pid');
    var t=teams[key]=teams[key]||{players:{}};t.players=t.players||{};
    var p=t.players[pid]=t.players[pid]||{};
    var mine=el.getAttribute('data-side')==='home'?g.home:g.away,theirs=el.getAttribute('data-side')==='home'?g.away:g.home;
    p.state=g.state;p.game=muGameText(g.state,mine,theirs,g.detail);}
  return {teams:teams};}
"""

# The live updater. A page that wants it sets window.MU_LIVE before this runs:
#   { fetch: function -> Promise of { teams: { key: { points, projected,
#            win_probability, players: { pid: { points, line } } } } },
#     interval: ms between polls }
# and marks its markup: any element with data-pid holding a .mu-pts cell (a
# table row in the wide layout, a div in the paired phone one; only rows
# add to the starters total, or both layouts would count each player) (.mu-s for
# the stat line) inside [data-roster=key]; [data-num=key][data-mu=anchor] on
# the header number; [data-sb=key] on scoreboard points; [data-tpts=key] on
# the starters total; [data-wp=key] / [data-wpl=key] on the win bar; .mu-asof
# for the stamp. Anything the page lacks is simply skipped.
LIVE_JS = """<script>
(function(){
  var cfg=window.MU_LIVE;if(!cfg||!cfg.fetch)return;
  var timer=null;
  function fmt(v){return (v===null||v===undefined||isNaN(v))?'\u2014':(Math.round(v*10)/10).toFixed(1);}
  function each(sel,fn){var els=document.querySelectorAll(sel);for(var i=0;i<els.length;i++)fn(els[i]);}
  // score_cell in the browser; null leaves a pre-game projection standing.
  function score(p){var st=p.state,pts=p.points;
    if(st==='post')return '<b class="mu-now">'+fmt(pts||0)+'</b><span class="mu-exp">final</span>';
    if(st==='in'){var e=(p.hexp!==undefined&&p.hexp!==null)?p.hexp:p.live;
      return '<b class="mu-now">'+fmt(pts||0)+'</b><span class="mu-exp live">'+((e!==undefined&&e!==null)?'\u2192 '+fmt(e):'live')+'</span>';}
    if(pts)return '<b class="mu-now">'+fmt(pts)+'</b><span class="mu-exp"></span>';
    return null;}
  function apply(data){
    var teams=(data&&data.teams)||{};var keys=Object.keys(teams);if(!keys.length)return false;
    keys.forEach(function(key){
      var t=teams[key];var pts=t.points;
      var roster=document.querySelector('[data-roster="'+key+'"]');
      // A payload can carry game states without points (the points feed
      // failed, the scoreboard did not): then only the indicators move.
      var scored=false;
      if(roster&&t.players){
        var total=0;
        // Not tr[data-pid]: the phone layout renders the same players as
        // divs, and both views are in the DOM with one hidden by CSS. Only
        // table rows add to the total, or every starter would count twice.
        each('[data-roster="'+key+'"] [data-pid], [data-pid][data-roster="'+key+'"]',function(el){
          var p=t.players[el.getAttribute('data-pid')];if(!p)return;
          if(p.points!==undefined&&p.points!==null)scored=true;
          // The score cell: points, and under them the live expected final
          // (points so far plus the unplayed share of the projection) or
          // final. The GS column stays the pre-game projection.
          var c=el.querySelector('.mu-pts'),h=c&&score(p);if(h)c.innerHTML=h;
          // The indicator: the row lights up while his game is on, and the
          // game cell carries the score and clock.
          if(p.state){el.classList.toggle('live',p.state==='in');
            var g=el.querySelector('.mu-g');
            if(g&&p.game){var sp=g.querySelector('.live,.fin');
              if(!sp){sp=document.createElement('span');g.insertBefore(document.createTextNode(' '),g.firstChild);g.insertBefore(sp,g.firstChild);}
              sp.className=p.state==='in'?'live':'fin';sp.textContent=p.game;}}
          if(p.line!==undefined&&p.line!==null){var s=el.querySelector('.mu-s');if(s)s.textContent=p.line;}
          if(el.tagName==='TR'&&el.classList.contains('starter'))total+=(p.points||0);
        });
        if((pts===null||pts===undefined)&&scored)pts=total;
      }
      if(pts===null||pts===undefined)return;
      each('[data-num="'+key+'"]',function(el){el.textContent=fmt(pts);el.setAttribute('data-val',pts);});
      each('[data-sb="'+key+'"]',function(el){el.innerHTML=fmt(pts);el.setAttribute('data-val',pts);});
      each('[data-tpts="'+key+'"]',function(el){el.textContent=fmt(pts);el.classList.remove('proj');});
      var he=(t.hexp!==undefined&&t.hexp!==null)?t.hexp:t.gs_live;
      if(he!==undefined&&he!==null)each('[data-thexp="'+key+'"]',function(el){
        if(el.textContent!=='final'){el.innerHTML='\u2192 '+fmt(he);el.classList.add('live');}});
      if(t.gs_live!==undefined&&t.gs_live!==null){each('[data-tgs="'+key+'"]',function(el){el.textContent=fmt(t.gs_live);el.classList.add('live');});}
      if(t.vs_median!==undefined&&t.vs_median!==null){each('[data-vsmed="'+key+'"]',function(el){
        var v=t.vs_median;el.textContent=(v>0?'+':'')+(Math.round(v*10)/10).toFixed(1);
        el.classList.toggle('mu-med-up',v>0);el.classList.toggle('mu-med-down',v<0);});}
      if(t.win_probability!==null&&t.win_probability!==undefined){
        var pc=(t.win_probability*100).toFixed(0)+'%';
        each('[data-wp="'+key+'"]',function(el){el.style.width=pc;});
        each('[data-wpl="'+key+'"]',function(el){el.textContent=pc;});
      }
    });
    // The leader in each matchup, by the numbers just written.
    var byMu={};
    each('[data-num][data-mu]',function(el){var m=el.getAttribute('data-mu');(byMu[m]=byMu[m]||[]).push(el);});
    Object.keys(byMu).forEach(function(m){
      var els=byMu[m];if(els.length!==2)return;
      var a=parseFloat(els[0].getAttribute('data-val')),b=parseFloat(els[1].getAttribute('data-val'));
      if(isNaN(a)||isNaN(b))return;
      els[0].classList.toggle('lead',a>b);els[1].classList.toggle('lead',b>a);
      var sb=document.querySelectorAll('[data-sb]');
    });
    each('[data-sb]',function(el){
      var row=el.parentNode;var cells=row.querySelectorAll('[data-sb]');if(cells.length!==2)return;
      var a=parseFloat(cells[0].getAttribute('data-val')),b=parseFloat(cells[1].getAttribute('data-val'));
      if(isNaN(a)||isNaN(b))return;
      cells[0].innerHTML=a>b?'<b class=lead>'+fmt(a)+'</b>':fmt(a);
      cells[1].innerHTML=b>a?'<b class=lead>'+fmt(b)+'</b>':fmt(b);
    });
    if(data.median){
      if(data.median.now!==null&&data.median.now!==undefined)each('[data-median-now]',function(el){el.textContent=fmt(data.median.now);});
      if(data.median.proj!==null&&data.median.proj!==undefined)each('[data-median-proj]',function(el){el.textContent=fmt(data.median.proj);});
    }
    var d=new Date();var h=d.getHours()%12||12,mn=('0'+d.getMinutes()).slice(-2);
    each('.mu-asof',function(el){el.textContent=' \u00b7 live, points as of '+h+':'+mn+(d.getHours()<12?' AM':' PM');});
    return true;
  }
  function poll(){
    if(document.hidden){timer=setTimeout(poll,cfg.interval||60000);return;}
    cfg.fetch().then(function(data){apply(data);timer=setTimeout(poll,cfg.interval||60000);})
      .catch(function(){timer=setTimeout(poll,120000);});
  }
  document.addEventListener('visibilitychange',function(){if(!document.hidden){clearTimeout(timer);poll();}});
  timer=setTimeout(poll,cfg.delay||8000);
})();
</script>"""


# The tracker's arithmetic and markup, run on every view at load and again by
# the live poll with fresh points. Winning the median game is finishing in the
# top half, so each team's line is how many teams have to pass it (or it has to
# pass) and how many still can.
def median_tracker(teams: list, week: int, started: bool, final: bool,
                   ext: dict = None) -> str:
    """The median game at a glance, as a JSON blob MEDIAN_TRACKER_JS renders.

    `teams` is one dict per side - {k, name, logo, pts, exp, left} where `left`
    is the starters still to finish, each {n, r, live, pos, p} - and `ext` the
    {"max": {pos: pts}, "min": {pos: pts}} the ceilings and floors are drawn
    from. Both leagues build those from their own feeds; everything after this
    is the same arithmetic, so it lives once.
    """
    import json
    from html import escape as _escape
    if len(teams) < 3:
        return ""
    blob = _escape(json.dumps({"started": started, "final": final, "teams": teams,
                               "ext": ext or {}}, separators=(",", ":")))
    return (f'<details class="section mu-medt-sec" open><summary>Median Tracker</summary>'
            f'<div class="mu-medt" data-medt-week="{week}" data-medt=\'{blob}\'></div>'
            "</details>")


# The starters a live payload still has to come: read off the rows the page
# already marks up (data-nm / data-pos / data-proj / data-gid), so a page whose
# feed carries only points can still drive the tracker.
LIVE_LEFT_JS = """
function muTrackerLeft(payload,games){
  var teams=(payload&&payload.teams)||{};
  var wraps=document.querySelectorAll('[data-roster]');
  for(var i=0;i<wraps.length;i++){var wrap=wraps[i],key=wrap.getAttribute('data-roster'),t=teams[key];
    if(!t)continue;
    var rows=wrap.querySelectorAll('tr.starter[data-pid]');if(!rows.length)continue;
    var left=[];
    for(var j=0;j<rows.length;j++){var tr=rows[j],pid=tr.getAttribute('data-pid');
      var g=games[tr.getAttribute('data-gid')];if(!g||g.state==='post')continue;
      var proj=parseFloat(tr.getAttribute('data-proj'));if(isNaN(proj))proj=0;
      var p=(t.players||{})[pid]||{};
      left.push({n:tr.getAttribute('data-nm')||'',pos:tr.getAttribute('data-pos')||'',
                 r:Math.round(proj*(1-muElapsed(g))*10)/10,live:g.state==='in',
                 p:p.points||0});}
    t.left=left;}
  return payload;}
"""


MEDIAN_TRACKER_JS = """<style>
.mu-medt-top{font-size:13px;color:#475569;margin:2px 0 6px}
.mu-medt-row{display:flex;align-items:flex-start;gap:8px;padding:6px 8px;border-left:3px solid #1a7f4b;
  background:#fff;border-bottom:1px solid #eef2f7}
.mu-medt-row.down{border-left-color:#b3382c}
.mu-medt-row.lock.up{background:#e6f4ec}
.mu-medt-row.lock.down{background:#fbe9e7}
.mu-medt-row .rk{width:16px;flex:none;font-size:12px;color:#94a3b8;padding-top:3px;text-align:right}
.mu-medt-row img.mu-tlogo{width:24px;height:24px}
.mu-medt-row .mid{flex:1;min-width:0}
.mu-medt-row .nm{font-weight:600;font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mu-medt-row .st{font-size:12px;font-weight:600;color:#1a7f4b}
.mu-medt-row.down .st{color:#b3382c}
.mu-medt-need{font-size:12px;color:#334155}
.mu-medt-ps{font-size:11px;color:#64748b;line-height:1.35}
.mu-medt-ps .lv{color:#b3382c;font-style:italic}
.mu-medt-row .fig{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.mu-medt-row .fig b{display:block;font-size:15px}
.mu-medt-row .fig span{font-size:11px;color:#64748b}
.mu-medt-line{display:flex;align-items:center;gap:8px;margin:4px 0;font-size:11px;font-weight:700;
  color:#64748b;text-transform:uppercase;letter-spacing:.04em}
.mu-medt-line:before,.mu-medt-line:after{content:"";flex:1;border-top:2px dashed #94a3b8}
@media (prefers-color-scheme: dark){
  .mu-medt-row{background:#16203a;border-bottom-color:#2b3852}
  .mu-medt-row.lock.up{background:#173a2e}
  .mu-medt-row.lock.down{background:#3d1f24}
  .mu-medt-row .st{color:#6ee7b7}.mu-medt-row.down .st{color:#ff9b91}
  .mu-medt-top,.mu-medt-need{color:#c5cfdc}.mu-medt-ps,.mu-medt-row .fig span{color:#aab7c9}
  .mu-medt-ps .lv{color:#ff9b91}
}
</style><script>
window.muMedTrack=(function(){
  function fmt(v){return (Math.round(v*10)/10).toFixed(1);}
  function esc(s){return String(s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
  function render(el,d){
    var ts=d.teams.slice(),n=ts.length;if(n<3)return;
    // Ceiling and floor: every starter still to play at his position's best
    // (less what he already has) or worst week in league history.
    var ext=d.ext||{},hi=ext.max||{},lo=ext.min||{},top=0,bot=0;
    Object.keys(hi).forEach(function(k){top=Math.max(top,hi[k]);});
    Object.keys(lo).forEach(function(k){bot=Math.min(bot,lo[k]);});
    ts.forEach(function(t){t.rem=0;t.ceil=t.pts;t.floor=t.pts;
      t.left.forEach(function(p){t.rem+=p.r;
        var mx=(p.pos in hi)?hi[p.pos]:top,mn=(p.pos in lo)?lo[p.pos]:bot;
        t.ceil+=Math.max(mx-(p.p||0),0);t.floor+=Math.min(mn,0);});
      t.proj=t.pts+t.rem;});
    // Standing order is the scoreboard as it is: current points once games are
    // on (projection breaking ties), the projection before kickoff. The locks
    // below hold for any order - a team above is assumed to stay above.
    ts.sort(function(a,b){return d.started?(b.pts-a.pts)||(b.proj-a.proj):b.proj-a.proj;});
    var done=d.final||ts.every(function(t){return !t.left.length;});
    // Locks by rank, with cut spots above the line: the team in spot i (0-based)
    // above it drops out only if cut-i teams below it pass it, so it is locked in
    // once fewer than that can still reach its floor (a finished team's score, or
    // a record week, decides "can"); below the line it needs i-cut+1 teams above
    // to finish under it, and is locked out once fewer than that can fall to its
    // ceiling. `foes` are those teams.
    var cut=Math.ceil((n-1)/2),html=[];
    ts.forEach(function(t,i){
      if(i<cut){t.foes=ts.slice(i+1).filter(function(o){return o.ceil>=t.floor;});
        t.lock=t.foes.length<cut-i?'up':'';}
      else{t.foes=ts.slice(0,i).filter(function(o){return o.floor<=t.ceil;}).reverse();
        t.lock=t.foes.length<i-cut+1?'down':'';}});
    var byProj=ts.slice().sort(function(a,b){return b.proj-a.proj;});
    var mid=n%2?byProj[n>>1].proj:(byProj[n/2-1].proj+byProj[n/2].proj)/2;
    var now=ts.map(function(t){return t.pts;}).sort(function(a,b){return a-b;});
    var medNow=n%2?now[n>>1]:(now[n/2-1]+now[n/2])/2;
    html.push('<p class="mu-medt-top"><b>Median</b> '+(d.started&&!done?fmt(medNow)+' now · ':'')+fmt(mid)+(done?' final':' projected')+'</p>');
    ts.forEach(function(t,i){
      var others=byProj.filter(function(o){return o!==t;});
      // The median of the other n-1: with an even league, one team.
      var j=(others.length-1)>>1,rival=others[j],line=others.length%2?rival.proj:(others[j].proj+others[j+1].proj)/2;
      if(others.length%2===0)rival=null;
      var margin=t.proj-line,up=margin>=0,need=line-t.pts,who=rival?esc(rival.name):'the median';
      var status;
      // Above the line a team loses the median game once enough of the teams
      // below it pass it (4th of five spots: two); below, it wins once it passes
      // that many of the teams above. Of how many teams can still do it
      // (t.foes: a record week for those still playing, the score for the rest).
      var above=i<cut,count=above?cut-i:i-cut+1,of=t.foes.length;
      up=t.lock?t.lock==='up':above;
      var odds=above?'Loses median if '+count+' of '+of+' teams '+(count===1?'passes':'pass')
        :'Makes median if it passes '+count+' of '+of+' teams';
      if(done)status=(up?'Won':'Lost')+' the median game by '+fmt(Math.abs(margin));
      else if(t.lock==='up')status='Locked above the median'+(t.left.length?' · cannot be caught':'');
      else if(t.lock==='down')status='Locked below the median'+(t.left.length?' · even a record week falls short':'');
      else status=t.left.length?odds:'Done · '+odds.charAt(0).toLowerCase()+odds.slice(1);
      var sub='';
      if(!done&&t.left.length){
        var ps=t.left.slice().sort(function(a,b){return b.r-a.r;}).map(function(p){
          return '<span class="'+(p.live?'lv':'')+'">'+esc(p.n)+' '+fmt(p.r)+'</span>';}).join(' · ');
        sub=(t.lock?'':'<div class="mu-medt-need">'+(need>0?'Needs <b>'+fmt(need)+'</b> · ':'')+t.left.length+' left, proj '+fmt(t.rem)+' · hypothetical max '+fmt(t.ceil)+'</div>')
          +'<div class="mu-medt-ps">'+ps+'</div>';}
      if(i===cut)html.push('<div class="mu-medt-line"><span>median '+fmt(d.started&&!done?medNow:mid)+'</span></div>');
      html.push('<div class="mu-medt-row '+(up?'up':'down')+(t.lock?' lock':'')+'">'
        +'<span class="rk">'+(i+1)+'</span>'+(t.logo||'')
        +'<div class="mid"><div class="nm">'+esc(t.name)+'</div><div class="st">'+status+'</div>'+sub+'</div>'
        +'<div class="fig"><b>'+fmt(t.pts)+'</b>'+(done||!t.left.length?'':'<span>→ '+fmt(t.proj)+'</span>')+'</div></div>');
    });
    el.innerHTML=html.join('');}
  function init(){var els=document.querySelectorAll('[data-medt]');
    for(var i=0;i<els.length;i++){try{render(els[i],JSON.parse(els[i].getAttribute('data-medt')));}catch(e){}}}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
  // Live: fresh points and remaining projections from MU_LIVE.compute's teams.
  return {update:function(week,live){
    var el=document.querySelector('[data-medt-week="'+week+'"]');if(!el||!live||!live.teams)return;
    var d;try{d=JSON.parse(el.getAttribute('data-medt'));}catch(e){return;}
    var any=false;
    d.teams.forEach(function(t){var u=live.teams[t.k];if(!u||!u.left)return;any=true;
      t.pts=u.points||0;t.left=u.left;});
    if(!any)return;
    d.started=d.teams.some(function(t){return t.pts>0;});
    el.setAttribute('data-medt',JSON.stringify(d));render(el,d);}};
})();
</script>"""
