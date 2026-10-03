"""
The trade analyzer, shared by both fantasy leagues (/fantasy/trade/ and
/cfb/trade/): pick a deal between two teams and see what it does to both
seasons - points a week, projected record, playoff and title odds - before
and after.

Most trade tools price players on a chart and add up the two sides. This asks
the question a manager actually has: does this make *my* season better? A
running back is worth more to a team starting a backup at RB than to one with
three, and a playoff spot is worth more to a 3-2 team than to a 5-0 one. So
each league's own rest-of-season simulation is run twice, as the rosters are
and as they would be, and the page shows the difference.

Two things make that difference honest:

  * **The same luck both times.** Both runs draw the same numbers for the
    same players (and, in the college league, the same team-week scatter), so
    a player who gets hurt in week 9 of simulated season 412 gets hurt there
    whoever owns him. What is left between the runs is the trade.
  * **Rosters stay legal.** A team taking more players than it sends drops
    its lowest-projected bench player; one sending more signs the best free
    agent at the position it gave up. The page names both.

This module is the page: the pickers, the player lists and the result. Each
league supplies an adapter, `window.GSTradeAdapter`, with two calls:

    load()          -> Promise of {league, teams: [{id, name}], mine,
                       players: {pid: {name, short, pos, ppw, tag}},
                       rosters: {teamId: [pid]}, before: {teamId: Stat},
                       note, sims, unit}
    evaluate(trade) -> Promise of {after: {teamId: Stat},
                       moves: {teamId: [html]}}
    remember(teamId)   optional: store the reader's team
    candidates(teamId) optional, with pickup: the free agents worth trying
    pickup(teamId, pid) -> Promise of {before: Stat, after: Stat, drop: pid}
                       one free agent added (the worst bench player dropped
                       when the roster is full), the same luck both ways

With the last two the page has a second mode, Pick up (#pickup): every
candidate played out for the reader's team, ranked by what he does to the
title odds - the waiver wire priced in playoff chances rather than points.

where trade is {a, b, give: [pid from a], get: [pid from b]} and a Stat is
{ppw, wins, losses, playoffs, title}.

The adapters: fantasy.site.trade (the NFL league and any reader's Sleeper or
ESPN league, on gordstats.my_power's simulation) and cfb.site.trade (the
Yahoo college league, on a port of cfb.league_sim).
"""

from gordstats import js_assets, share_button

CSS = """<style>
.tr{margin:6px 0 24px}
/* Most of a screen is held for the analyzer until it draws: drawn into an empty
   div - and through a one-line "Reading the league..." first - it carried "How
   it works" up and down the first screen (layout shift 0.12-0.2, the
   2026-10-02 check). The script drops the hold once it has drawn or given up. */
.tr-wait{min-height:80vh}
.tr-teams{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:0 0 12px}
.tr-teams label{display:flex;flex-direction:column;gap:3px;font-size:12px;font-weight:600;
  color:#64748b;min-width:0}
.tr-teams select{font-size:15px;min-height:40px;padding:4px 8px;border:1px solid #cbd5e1;
  border-radius:8px;background:#fff;color:#0f172a;min-width:0;width:100%}
.tr-sides{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.tr-side{min-width:0}
.tr-side h3{font-size:13px;margin:0 0 4px;color:#475569;font-weight:700;
  text-transform:uppercase;letter-spacing:.03em}
.tr-list{display:flex;flex-direction:column;border:1px solid #e2e8f0;border-radius:10px;
  overflow:hidden}
.tr-p{display:flex;align-items:center;gap:6px;min-height:40px;padding:3px 8px;border:0;
  border-top:1px solid #eef2f7;background:#fff;color:#0f172a;font:inherit;font-size:14px;
  text-align:left;cursor:pointer;width:100%}
.tr-p:first-child{border-top:0}
.tr-p[aria-pressed="true"]{background:#dbeafe;box-shadow:inset 3px 0 0 #2563eb}
.tr-pos{flex:none;width:30px;font-size:12px;font-weight:700;text-align:center;border-radius:4px;
  padding:2px 0;background:#e2e8f0;color:#334155}
.tr-name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tr-short{display:none}
/* The injury tag and next-man-up chip sit in line on a desktop; a phone moves
   them to a line of their own under the name (below), or a long chip
   ("+4.9 Achane out") squeezes the name to nothing. */
.tr-chips{display:contents}
.tr-tag{flex:none;font-size:12px;font-weight:700;color:#b91c1c}
.tr-boost{flex:none;font-size:12px;font-weight:700;padding:1px 5px;border-radius:4px;
  white-space:nowrap}
.tr-boost.up{color:#15803d;background:#dcfce7}.tr-boost.down{color:#b91c1c;background:#fee2e2}
.tr-ppw{flex:none;font-size:13px;color:#475569;font-variant-numeric:tabular-nums}
.tr-out{margin:14px 0 0}
.tr-msg{font-size:14px;color:#475569;margin:0}
.tr-now{font-size:13px;color:#475569;margin:6px 0 0}
.tr-verdict{font-size:16px;font-weight:700;margin:0 0 2px}
.tr-verdict+.tr-now{margin:0 0 10px}
.tr-verdict .up{color:#15803d}.tr-verdict .down{color:#b91c1c}
.tr-cards{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.tr-card{border:1px solid #e2e8f0;border-radius:10px;padding:10px 12px;min-width:0}
.tr-card h3{font-size:14px;margin:0 0 6px;overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap}
.tr-you{display:inline-block;font-size:11px;font-weight:700;color:#fff;background:#2563eb;
  border-radius:4px;padding:1px 5px;margin:0 6px 0 0;vertical-align:1px}
.tr h3{text-align:left}
.tr .tr-t{display:table;width:100%;margin:0;border:0;border-collapse:collapse;font-size:14px;
  font-variant-numeric:tabular-nums}
/* The theme paints every th dark and boxes every td; this table is four
   numbers a row and wants neither. */
.tr .tr-t th,.tr .tr-t td{background:none;border:0;box-shadow:none;color:inherit}
.tr .tr-t th{text-align:left;font-weight:600;color:#64748b;font-size:12.5px;padding:3px 0}
.tr .tr-t td{text-align:right;padding:3px 0 3px 6px;white-space:nowrap}
.tr .tr-t thead th{text-align:right;font-size:11px;font-weight:600;color:#64748b;
  text-transform:uppercase;letter-spacing:.03em;padding:0 0 2px 6px}
.tr .tr-t td.tr-was{color:#64748b}
.tr .tr-t td.tr-d{font-weight:700;min-width:38px}
.tr .tr-t td.up{color:#15803d}.tr .tr-t td.down{color:#b91c1c}
.tr .tr-t td.flat{color:#64748b;font-weight:400}
.tr-moves{margin:8px 0 0;padding:0 0 0 16px;font-size:12.5px;color:#475569;line-height:1.45}
.tr-note{font-size:12.5px;color:#64748b;line-height:1.5;margin:10px 0 0}
.tr-clear{font:inherit;font-size:13px;border:0;background:none;color:#2563eb;cursor:pointer;
  padding:8px 0;min-height:40px}
.tr-acts{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin:8px 0 0}
.tr-mode{display:inline-flex;border:1px solid #cbd5e1;border-radius:999px;overflow:hidden;
  margin:0 0 12px}
.tr-mode button{min-height:40px;padding:0 18px;border:0;background:#fff;color:#475569;
  font:inherit;font-size:14px;font-weight:700;cursor:pointer}
.tr-mode button[aria-pressed=true]{background:#0f172a;color:#fff}
.tr-teams.tr-one{grid-template-columns:minmax(0,1fr)}
.tr-pk-wrap{border:1px solid #e2e8f0;border-radius:10px;overflow-x:auto}
.tr .tr-pk{display:table;width:100%;margin:0;border:0;border-collapse:collapse;font-size:14px;
  font-variant-numeric:tabular-nums}
.tr .tr-pk th,.tr .tr-pk td{background:none;border:0;box-shadow:none;color:inherit;
  padding:7px 8px;border-top:1px solid #eef2f7}
.tr .tr-pk thead th{border-top:0;font-size:11px;font-weight:600;color:#64748b;
  text-transform:uppercase;letter-spacing:.03em;text-align:right}
.tr .tr-pk thead th:first-child,.tr .tr-pk thead th:nth-child(2){text-align:left}
.tr .tr-pk td.tr-pk-p{min-width:0}
.tr-pk-in{display:flex;align-items:center;gap:6px;min-width:0}
.tr .tr-pk td.tr-pk-drop,.tr .tr-pk td.tr-pk-fail{color:#64748b;font-size:13px;max-width:30vw;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tr-pk-sub{display:none}
.tr .tr-pk td.tr-d{text-align:right;font-weight:700}
.tr .tr-pk td.up{color:#15803d}.tr .tr-pk td.down{color:#b91c1c}
.tr .tr-pk td.flat{color:#64748b;font-weight:400}
@media (max-width:640px){
  .tr-sides,.tr-cards{gap:8px}
  .tr-p{font-size:13px;padding:3px 6px;gap:5px}
  .tr-pos{width:28px}
  .tr-full{display:none}.tr-short{display:inline}
  .tr-cards{grid-template-columns:1fr}
  /* Name and points on the first line, the tag and chip on a second one
     lined up under the name: the name keeps its room in a 170px column. */
  .tr-p,.tr-pk-in{flex-wrap:wrap;align-content:center;row-gap:2px}
  .tr-name{min-width:5em}
  .tr-p .tr-chips,.tr-pk-in .tr-chips{display:flex;flex-wrap:wrap;gap:2px 5px;order:3;
    flex:0 0 100%;padding-left:33px;box-sizing:border-box;align-items:baseline}
  .tr-p .tr-boost,.tr-pk-in .tr-boost{white-space:normal;flex:0 1 auto;min-width:0}
  /* Pick up: Drop leaves its column for a line under the player, so the
     Playoffs and Title columns - the answer - fit a phone. */
  .tr .tr-pk th.tr-pk-drop,.tr .tr-pk td.tr-pk-drop{display:none}
  .tr-pk-sub{display:inline;font-size:12.5px;color:#64748b;white-space:nowrap}
  .tr .tr-pk th,.tr .tr-pk td{padding:7px 6px}
}
@media (prefers-color-scheme: dark){
  .tr-teams label,.tr-side h3,.tr-msg,.tr-now,.tr-moves,.tr-note,.tr .tr-t th,.tr-ppw{color:#aab7c9}
  .tr-teams select{background:#0f172a;color:#e2e8f0;border-color:#334155}
  .tr-list,.tr-card{border-color:#334155}
  .tr-p{background:#0f172a;color:#e2e8f0;border-top-color:#1e293b}
  .tr-p[aria-pressed="true"]{background:#1e3a5f;box-shadow:inset 3px 0 0 #60a5fa}
  .tr-pos{background:#1e293b;color:#cbd5e1}
  .tr-tag{color:#fca5a5}
  .tr-boost.up{color:#4ade80;background:#14532d}.tr-boost.down{color:#fca5a5;background:#450a0a}
  .tr .tr-t td.tr-was{color:#94a3b8}
  .tr .tr-t td.up,.tr-verdict .up{color:#4ade80}.tr .tr-t td.down,.tr-verdict .down{color:#f87171}
  .tr-clear{color:#60a5fa}
  .tr-mode{border-color:#334155}.tr-mode button{background:#0f172a;color:#aab7c9}
  .tr-mode button[aria-pressed=true]{background:#e2e8f0;color:#0f172a}
  .tr-pk-wrap{border-color:#334155}
  .tr .tr-pk th,.tr .tr-pk td{border-top-color:#1e293b}
  .tr .tr-pk thead th,.tr .tr-pk td.tr-pk-drop,.tr .tr-pk td.tr-pk-fail,.tr-pk-sub{color:#aab7c9}
  .tr .tr-pk td.up{color:#4ade80}.tr .tr-pk td.down{color:#f87171}
  /* An unchanged figure ("+-0.0") kept its light-theme grey: 3.4:1 here. */
  .tr .tr-pk td.flat,.tr .tr-t td.flat{color:#94a3b8}
}
</style>"""


# The code is docs/assets/js/gs-trade.js (gordstats.js_assets): JS is it inline,
# for the browser tests; JS_TAG is what the pages carry.
JS = js_assets.inline("gs-trade.js")
JS_TAG = js_assets.tag("gs-trade.js")


def section(path: str, host_id: str = "tr-host", league: bool = False) -> str:
    """The page's slot for the analyzer; the adapter's script fills it. The
    Share button it hands the deal to is a template: the script sets its
    address (the page plus the deal) each time a deal is played, and `league`
    adds the reader's league to it (gordstats.share_button)."""
    return (CSS + f"<div class='tr tr-wait' id='{host_id}'></div>"
            + "<template id='tr-share'>"
            + share_button.button(path, label="Send this trade", league=league)
            + "</template>")


def start(host_id: str = "tr-host") -> str:
    """Runs the analyzer once the adapter is defined - include it last."""
    return ("<script>window.GSTrade(document.getElementById('" + host_id
            + "'), window.GSTradeAdapter);</script>")
