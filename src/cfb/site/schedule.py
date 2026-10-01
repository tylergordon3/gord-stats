"""
The college football schedule and scoreboard, one page (docs/cfb/schedule/).

Every FBS game of the season (cfb.espn.schedule), one tab per week. Inside a
tab, live games come first, then games still to play (grouped by day), then
finished ones under a Final header, so mid-week the top of the page is what's
on or what's next, not what already happened.

It is the scoreboard too. Server-side this is a snapshot - rebuilt daily and
by the Pi's live tick (cfb.live) while games are on. The page then keeps the
current week current: a script polls ESPN's scoreboard through our Pages
Function proxy (functions/api/cfb-scores.js - ESPN strips CORS for browsers)
every ~30s during games, updating scores, clock, records, possession, down &
distance and last play, and re-sectioning rows as games kick off and finish.
No JS still gets the build-time snapshot. The old /cfb/scoreboard/ URL
redirects here.

Each game is a row: the stacked scorebox (away over home, ESPN logos, AP
ranks, the winner in bold, a conference tag underneath), kickoff and TV,
then everything the site and the market think about it -

  - the GordStats line: spread, projected total, and for games still to play
    the projected score (cfb.predict, one fit as of build time; for finished
    games the line that was on record before kickoff, from cfb.results);
  - the DraftKings line: spread, total and moneyline (cfb.gameinfo, frozen at
    kickoff, with cfb.odds as the fallback for the spread and total);
  - ESPN's FPI win chance beside ours, each naming its own favourite, and on
    a finished game each marked with whether that favourite won;
  - the forecast where ESPN has one (about ten days out): condition,
    temperature, chance of rain, gusts.

The controls sort a week by anything on the row - closest spread, highest
total, ESPN's matchup quality, biggest home underdog, worst weather, where
the model and the book disagree most, upset chance - and cut it down with
filters that stack: ranked teams, conference or non-conference games, the
Power 4, home underdogs, toss-ups, bad weather, upset watch, still to play,
one conference, or a team name. Sorting by anything but kickoff flattens the
day groups into one ranked list; the URL hash carries the state so a view
can be shared. On a phone the rows become stacked cards, folded to the
matchup, the kickoff and the GordStats and DraftKings lines, with More
unfolding the rest; only the week row stays pinned, the other controls
folded behind a Filters button.

The tab that opens first is the current week, computed at build time - the
page is rebuilt daily, so "current" stays current.

    python -m cfb.site.schedule     # rebuild the page
"""
import json
from datetime import datetime, timezone
from functools import lru_cache
from html import escape

import numpy as np
import pandas as pd

from cfb import cfbd, espn, gameinfo, predict, results
from cfb import odds as odds_mod
from cfb.config import DATA_DIR, LEAGUE_TZ, SEASON, WEB_DIR
from gordstats import favorites, logos
from cfb.site import write_page
from cfb.site.teams import team_slug

POWER4 = {"ACC", "Big 12", "Big Ten", "SEC"}
HOME_EDGE = 2.5           # points SP+ ratings are read with for a home team
_CTX = {}                 # build-time lookups the detail panels draw on
TOSS_UP = 3.0             # a spread this small is a coin flip for the badge
UPSET_WATCH = 0.35        # an underdog somebody gives this much is worth a look
PARLAY_LEGS = 3           # legs in the parlay of the day
ML_CAP = 0.65             # a moneyline the book prices likelier than this (about -185) is chalk, not a leg

_CSS = """<style>
.sc-intro{color:#475569;font-size:14px;line-height:1.55}
table.cfb-sched{width:100%;border-collapse:collapse;font-size:14px}
table.cfb-sched th{background:var(--accent-soft,#eef2f7);color:var(--accent-dark,#334155);
  padding:7px 8px;text-align:left;
  font-size:12px;text-transform:uppercase;letter-spacing:.03em;white-space:nowrap;
  border:1px solid #e2e8f0}
table.cfb-sched td{padding:6px 8px;border:1px solid #eef2f7;color:#0f172a;background:#fff;
  vertical-align:top}
table.cfb-sched tbody tr.g:nth-child(even) td{background:#f8fafc}
table.cfb-sched .rk{font-weight:700;color:#8a6d00;font-size:11.5px}
/* Identity leads and stays put while the numbers scroll; every cell carries
   an opaque background in both themes so nothing bleeds through. */
table.cfb-sched th:first-child,table.cfb-sched td.mu{position:sticky;left:0;z-index:1}
/* Day and section headers live inside the table so a sort can hide them and
   a filter can drop an emptied day. */
table.cfb-sched tr.hdr td{background:#f1f5f9;color:#475569;font-weight:700;
  font-size:13px;padding:8px 10px;border-color:#e2e8f0}
table.cfb-sched tr.hdr.sec td{background:var(--accent-soft,#e2e8f0);
  color:var(--accent-dark,#334155);font-size:11.5px;
  text-transform:uppercase;letter-spacing:.06em;padding:6px 10px}
/* The stacked scorebox: away over home, logos, ranks, the winner in bold. */
.sc-mu{display:flex;flex-direction:column;gap:2px;min-width:170px;max-width:240px}
.sc-row{display:flex;align-items:center;gap:8px}
/* The Slate remote theme frames every <img>; reset or each logo becomes a
   boxed figure and the row grows. */
table.cfb-sched .sc-row img{width:20px;height:20px;object-fit:contain;flex:none;
  border:none;padding:0;box-shadow:none;background:none;border-radius:0;margin:0}
.sc-name{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  color:#334155;font-size:14px}
/* One link per team, logo and name together. They were two links to the same
   page - the logo a nameless 18px one - and on a phone neither was a target a
   thumb could find; one link across the line is (see the phone block). */
.sc-team{display:flex;align-items:center;gap:8px;flex:1;min-width:0;
  color:inherit;text-decoration:none}
a.sc-team:hover .sc-tn{text-decoration:underline}
.sc-joiner{color:var(--gs-muted,#5d6b7e);font-size:12px}
.sc-pts{min-width:24px;text-align:right;font-variant-numeric:tabular-nums;
  font-size:15px;font-weight:600;color:var(--gs-muted,#5d6b7e)}
.sc-row.sc-win .sc-name{font-weight:700;color:#0f172a}
.sc-row.sc-win .sc-pts{color:#0f172a;font-weight:700}
.sc-rec{color:var(--gs-muted,#5d6b7e);font-size:11px;font-variant-numeric:tabular-nums;margin-left:4px}
.sc-row.sc-ball .sc-name::after{content:" \\1F3C8";font-size:11px}
/* The drive line, only while a game is on. */
.sc-live{display:none;margin-top:5px;padding-top:5px;border-top:1px dashed #e2e8f0}
tr.g[data-state="in"] .sc-live{display:block}
.sc-sit{font-size:12px;font-weight:600;color:#0f172a}
.sc-play{font-size:11.5px;color:#64748b;margin-top:1px;white-space:normal;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.sc-meta{margin-top:4px;font-size:11.5px;color:#64748b;display:flex;flex-wrap:wrap;
  gap:4px 6px;align-items:center}
/* Where: stadium over city, one line each, clipped rather than wrapped. */
.sc-venue{margin-top:3px;font-size:11px;color:var(--gs-muted,#5d6b7e);line-height:1.35;max-width:230px}
.sc-venue span{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tag{display:inline-block;padding:1px 6px;border-radius:999px;font-size:10.5px;
  font-weight:700;letter-spacing:.03em;text-transform:uppercase;line-height:1.5}
.tag-dog{background:#fef3c7;color:#92400e}
.tag-toss{background:#dbeafe;color:#1e40af}
.tag-upset{background:#fee2e2;color:#991b1b}
/* GordStats picks of the day: one folded line above the current week, the
   two cards under it. */
.gs-picks-fold{margin:6px 0 10px}
.gs-picks-fold>summary{cursor:pointer;padding:10px 14px;font-size:14px;color:#334155;
  background:#fff;border:1px solid #e2e8f0;border-radius:12px;line-height:1.35;
  box-shadow:0 1px 2px rgba(15,23,42,.05)}
.gs-picks-fold>summary b{color:#0f172a;font-weight:700}
.gs-picks-fold[open]>summary{margin-bottom:6px}
.gp-sum .gp-p{font-weight:800;color:#1a7f4b;font-variant-numeric:tabular-nums}
.gp-sum .gp-hit{color:#1a7f4b;font-weight:800}
.gp-sum .gp-miss{color:#b3382c;font-weight:800}
.gs-picks-fold>.wk-note{margin:0 0 6px}
.gs-picks{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,330px),1fr));
  gap:12px;margin:8px 0 14px}
.gs-pick{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:12px 15px 13px;
  box-shadow:0 1px 2px rgba(15,23,42,.05)}
.gs-pick .gp-label{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:#64748b;
  font-weight:700}
.gs-pick .gp-main{font-size:19px;font-weight:800;color:#0f172a;margin:4px 0 2px;line-height:1.25}
.gs-pick .gp-main a{color:inherit;text-decoration:none}
.gs-pick .gp-main a:hover{text-decoration:underline}
.gs-pick .gp-sub{font-size:12.5px;color:#475569}
.gs-pick .gp-legs{list-style:none;margin:6px 0 4px;padding:0}
.gs-pick .gp-legs li{display:flex;justify-content:space-between;gap:10px;padding:5px 0;
  border-top:1px solid #eef2f7;font-size:13.5px}
.gs-pick .gp-legs li a{color:#0f172a;text-decoration:none;font-weight:700}
.gs-pick .gp-legs li a:hover{text-decoration:underline}
.gs-pick .gp-legs .gp-game{display:block;font-size:11.5px;color:#64748b;font-weight:400}
.gs-pick .gp-p{font-weight:800;color:#1a7f4b;white-space:nowrap;font-variant-numeric:tabular-nums}
.gs-pick .gp-book{font-weight:400;color:#64748b;font-size:11.5px}
.gs-pick .gp-note{font-size:11.5px;color:#64748b;margin-top:6px}
.gs-pick .gp-hit{color:#1a7f4b;font-weight:800}
.gs-pick .gp-miss{color:#b3382c;font-weight:800}
.gs-pick .gp-missed{color:#b3382c;text-transform:none;letter-spacing:0}
.gs-pick .gp-label .gp-hit{text-transform:none;letter-spacing:0}
.tag-wx{background:#e0e7ff;color:#3730a3}
/* Kick: time over TV. */
td.t{color:#4a5a68;max-width:140px}
td.t .t-when{white-space:nowrap}
.t-tv{display:block;font-size:11.5px;color:#64748b;margin-top:2px;line-height:1.3}
.t-live{color:#0a7d33;font-weight:700}
.t-day{display:none;color:var(--gs-muted,#5d6b7e)}
table.cfb-sched.sorted .t-day{display:inline}
/* Line cells: the favourite and spread, then the small print. */
td.ln,td.fpi{white-space:nowrap;font-variant-numeric:tabular-nums}
.ln b,.fpi b{color:#0f172a;font-weight:700}
.pct{color:#334155;font-weight:600;margin-left:6px}
/* The folded phone card's two lines (GordStats, DraftKings); the table below
   carries both, so a desktop never shows these. */
.ln-sum{display:none}
/* The Lines box: one small table, the GordStats row highlighted as the pick. */
table.cfb-sched table.lnt,table.cfb-sched table.frt{border:none;border-collapse:collapse;
  width:auto;margin:0;background:none;font-size:12px;white-space:nowrap;
  font-variant-numeric:tabular-nums}
table.cfb-sched table.lnt th,table.cfb-sched table.frt th{background:none;border:none;
  border-bottom:1px solid #e2e8f0;padding:0 8px 2px 0;font-size:11px;color:var(--gs-muted,#5d6b7e);
  text-align:left;letter-spacing:.04em}
table.cfb-sched table.lnt td,table.cfb-sched table.frt td{background:none;border:none;
  padding:2px 6px 2px 0;font-size:12px;color:#334155;vertical-align:middle}
table.cfb-sched table.lnt td.k,table.cfb-sched table.frt td.k{font-weight:700;color:#64748b;
  font-size:10.5px;letter-spacing:.04em}
table.cfb-sched table.lnt tr.pick td{background:var(--accent-soft,#eef2f7)}
table.cfb-sched table.lnt tr.pick td.k{color:var(--accent-dark,#0f172a)}
table.cfb-sched table.lnt tr.pick td:first-child{border-radius:4px 0 0 4px;padding-left:4px}
table.cfb-sched table.lnt tr.pick td:last-child{border-radius:0 4px 4px 0}
table.cfb-sched table.lnt td:first-child{padding-left:4px}
.lnt b{color:#0f172a}
.mlx{font-size:11px;color:#64748b}
/* Ratings and last five under each team, inside the matchup cell. */
.sc-stat{font-size:10.5px;color:#64748b;margin:-1px 0 2px 28px;white-space:nowrap;
  font-variant-numeric:tabular-nums;display:flex;align-items:center;gap:6px}
.sc-stat b{color:#334155;font-weight:600}
.sc-stat .l5{width:14px;height:14px;line-height:14px;font-size:10px;margin-right:1px}
.call{margin-top:5px;font-size:12.5px;color:#334155}
.call b{color:#0f172a}
.call .strong b{color:var(--accent-dark,#1e40af)}
.call .mv{margin-left:3px}
.frm-scroll{overflow-x:auto;max-width:100%}
table.cfb-sched table.frt td{padding:2px 7px 2px 0}
.sub{font-size:12px;color:#64748b;margin-top:2px}
.bar{height:5px;width:64px;border-radius:3px;background:#eef2f7;overflow:hidden;margin-top:4px}
.bar i{display:block;height:100%;background:#3b82f6}
.mk{font-weight:700;margin-left:4px}
.mk.hit{color:#15803d}
.mk.miss{color:#b91c1c}
.t-wx{display:block;font-size:12px;color:#334155;margin-top:4px;white-space:nowrap}
.t-wx .sub{display:block;margin:1px 0 0;font-size:11px}
tr.g.wx-bad .t-wx{color:#3730a3;font-weight:600}
td.na{color:var(--gs-muted,#5d6b7e)}
.wk-note{font-size:13px;color:#4a5a68;margin:4px 0 10px}
/* Sort, conference, search, the Show chips and the week buttons all live in
   the pinned bar, each on its own row. The bar itself is a wrapping flex row
   (custom.css), so each block takes the full width to stack. */
.sc-pin>*{flex:1 1 100%}
.sc-pin .sc-controls,.sc-pin .sc-chips,.sc-weekrow{justify-content:center}
.sc-pin .sc-controls{margin:4px 0 2px}
.sc-pin .sc-chips{margin:2px 0 4px}
.sc-weekrow{display:flex;align-items:center;gap:8px}
.sc-filt{display:none}
@media (max-width:700px){
  /* Pinned, those rows stood 146px over every card on a phone - a sixth of
     the screen, and on the device with least of it (the 2026-09-29 phone
     audit). Only the week row stays in reach now: the rest fold behind a
     Filters button at its head, which counts the filters in force so a
     folded bar still says the list is cut down, and unfolds below it so the
     button does not move under the thumb that pressed it. The bar is still
     the one .pin-bar the layout measures into --pin-h, and it watches the
     bar's size, so the fold opening and closing is measured too. */
  .sc-pin{padding-top:4px;padding-bottom:4px}
  /* min-width:0 on the row and the fold, or the week strip's full width
     becomes the row's minimum and it runs off the bar instead of scrolling. */
  .sc-weekrow{order:-1;justify-content:flex-start;min-width:0}
  .sc-weekrow .view-switch{flex:1 1 auto;min-width:0;margin:0;flex-wrap:nowrap;overflow-x:auto}
  .sc-weekrow .view-switch button{flex:none}
  .sc-weekrow .switch-label{display:none}
  .sc-pin .sc-fold{display:none;min-width:0}
  .sc-pin.sc-open .sc-fold{display:block}
  .sc-filt{display:inline-flex;align-items:center;gap:5px;flex:none;min-height:42px;
    padding:0 13px;border:1px solid #cbd5e1;border-radius:999px;background:#fff;
    font:inherit;font-size:14px;font-weight:700;color:#334155;cursor:pointer;white-space:nowrap}
  .sc-filt::after{content:"\\25BE"}
  .sc-filt[aria-expanded=true]::after{content:"\\25B4"}
  .sc-filt.sc-some{border-color:var(--accent,#A34F0A);color:var(--accent-dark,#8A420A)}
  /* A phone cannot give three rows of chips to a pinned bar: one row that
     scrolls sideways, like the week buttons. */
  .sc-pin .sc-chips{flex-wrap:nowrap;overflow-x:auto;scrollbar-width:none;
    -webkit-overflow-scrolling:touch;padding-bottom:2px}
  .sc-pin .sc-chips::-webkit-scrollbar{display:none}
  .sc-pin .sc-chips button{white-space:nowrap;flex:none}
  /* Sort, conference and search share the row instead of scrolling it: the
     conference picker was cut mid-word and the search box sat off-screen,
     with nothing to say there was more (the 2026-09-28 phone audit). The
     labels go - each control says what it is, and the Filters button names
     the lot - and the search is 16px, under which iOS zooms the page on
     focus. */
  .sc-pin .sc-controls{flex-wrap:nowrap;min-width:0}
  .sc-pin .sc-controls .lbl,.sc-pin .sc-chips .lbl{display:none}
  .sc-pin .sc-controls .sc-select,.sc-pin .sc-controls .sc-search{flex:1 1 0;min-width:0;width:auto}
  .sc-pin .sc-controls .sc-search{font-size:16px;padding:4px 8px}
  .sc-pin .sc-select,.sc-pin .sc-search,.sc-pin .sc-chips button{min-height:40px}
  .sc-pin .sc-controls,.sc-pin .sc-chips{justify-content:flex-start}
}
.sc-controls{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:10px 0 4px}
.sc-controls .lbl,.sc-chips .lbl{font-weight:800;font-size:.72rem;text-transform:uppercase;
  letter-spacing:.04em;color:#475569}
.sc-select,.sc-search{font-size:13.5px;padding:6px 10px;border:1px solid #cbd5e1;
  border-radius:8px;background:#fff;color:#0f172a}
.sc-search{min-width:150px}
.sc-chips{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:4px 0 8px}
.sc-chips button{padding:5px 12px;cursor:pointer;border:1px solid #e2e8f0;background:#fff;
  border-radius:999px;font-size:13px;font-weight:600;color:#334155;
  box-shadow:0 1px 2px rgba(15,23,42,.04)}
.sc-chips button:hover{background:#f1f5f9}
.sc-chips button.active{background:var(--accent,#A34F0A);color:#fff;
  border-color:var(--accent-dark,#8A420A);font-weight:700}
.sc-chips button.clear{border-style:dashed;color:#64748b;font-weight:500}
.sc-legend{margin:8px 0 14px;font-size:13px;color:#475569}
.sc-legend summary{cursor:pointer;font-weight:600;color:#334155}
.sc-legend p{margin:6px 0 0}
.sc-legend ul{margin:6px 0 0 18px;padding:0}
.sc-legend li{margin:3px 0}
tr.g.hide,tr.hdr.hide{display:none}
/* The More panel: a second row per game, shown on demand. */
.det-btn{border:none;background:none;padding:0;margin-left:auto;cursor:pointer;
  font-size:11px;font-weight:700;color:#2a78d6;letter-spacing:.02em}
.det-btn:hover{text-decoration:underline}
table.cfb-sched>tbody>tr.det{display:none}
table.cfb-sched>tbody>tr.det.show{display:table-row}
table.cfb-sched tr.det td{background:#f8fafc;padding:8px 12px 10px;border-color:#e2e8f0}
.det-wrap{display:grid;grid-template-columns:minmax(260px,1.1fr) minmax(220px,.9fr);gap:8px 22px;
  font-size:12.5px;color:#334155}
.det-block h4{margin:2px 0 4px;font-size:11px;text-transform:uppercase;letter-spacing:.05em;
  color:#64748b}
/* min-width:0 on the grid items, or a wide nested table sets the column's
   minimum and the whole panel overflows the page instead of scrolling inside. */
.det-block{min-width:0}
.det-teams{grid-column:1/-1}
.det-scroll{overflow-x:auto;max-width:100%}
table.cfb-sched table.det-t{border:none;width:auto;margin:0;background:none}
table.det-t{border-collapse:collapse;font-size:12px;white-space:nowrap;
  font-variant-numeric:tabular-nums}
table.cfb-sched table.det-t th{background:none;border:none;border-bottom:1px solid #e2e8f0;
  padding:2px 8px 3px 0;font-size:10.5px;color:var(--gs-muted,#5d6b7e);text-align:left;letter-spacing:.04em}
table.cfb-sched table.det-t td{background:none;border:none;padding:3px 8px 3px 0;
  font-size:12px;color:#334155;vertical-align:middle}
table.det-t td.k{font-weight:600;color:#0f172a}
.det-line{margin:3px 0;line-height:1.45;white-space:normal}
.det-line b{color:#0f172a}
.mv{color:var(--gs-muted,#5d6b7e);font-size:11px}
.mv.up{color:#15803d}
.mv.dn{color:#b91c1c}
.best{background:#dcfce7;border-radius:3px;padding:0 3px}
.l5{display:inline-block;width:16px;height:16px;line-height:16px;text-align:center;
  border-radius:3px;font-size:10px;font-weight:700;margin-right:2px;cursor:default}
.l5.w{background:#dcfce7;color:#166534}
.l5.l{background:#fee2e2;color:#991b1b}
.lean{font-weight:600;color:#0f172a}
/* On a phone the table becomes a stack of cards: matchup on top, then one
   labelled line per figure, empty figures dropped. Same rows, same data
   attributes, so sorting and filtering are untouched. */
@media (max-width:700px){
  #cfb-weeks .table-scroll{border:none;box-shadow:none;border-radius:0;overflow:visible;
    background:transparent}
  /* The "How to read it" line is a 40px target, not a 20px one. */
  .sc-legend{margin:2px 0 8px}
  .sc-legend summary{padding:10px 0}
  /* Tighter cards: smaller logos, short labels, venue and the projected-
     score / moneyline small print moved into the More panel. */
  table.cfb-sched>tbody>tr.g{padding:6px 8px 5px;margin:6px 0}
  table.cfb-sched .sc-row img{width:18px;height:18px}
  .sc-mu{gap:0}
  /* The whole team line is the link, 36px tall: the name alone was a 15px
     target and the logo beside it an 18px one. */
  .sc-team{min-height:36px}
  /* This block used to shrink the labels below their desktop size to fit
     more in. On the device where reading is hardest that is the wrong
     trade, and it is the complaint this site started from - a tag at
     9.5px is not a size anyone reads standing in a car park. So nothing
     here goes under 12px, the W/L and weather pills under 11.5px, and a
     figure the desktop sets smaller is raised to that for a phone. The
     room it takes comes out of what a card shows folded, not the type. */
  .sc-name{font-size:14px}
  .sc-pts{font-size:15px}
  table.cfb-sched .rk,.sc-rec,.sc-joiner,.sc-play,.sc-sit{font-size:12px}
  .sc-row.sc-ball .sc-name::after{font-size:12px}
  .sc-meta{font-size:12px;margin-top:2px;gap:3px 6px}
  .sc-venue{display:none}
  .tag{font-size:11.5px;padding:0 6px}
  .sub,.t-wx .sub,.mlx,.mv{font-size:12px}
  .t-tv{font-size:12px}
  table.cfb-sched tr.hdr.sec td{font-size:12px}
  table.cfb-sched td.d .c{min-width:0}
  table.cfb-sched table.lnt td,table.cfb-sched table.frt td,
  table.cfb-sched table.lnt th,table.cfb-sched table.frt th,
  table.cfb-sched table.lnt td.k,table.cfb-sched table.frt td.k{font-size:12px}
  table.cfb-sched table.lnt td,table.cfb-sched table.frt td{padding-right:7px}
  /* Rank alone beside FPI and SP+ on a phone; the rating rides in the title
     on desktop-width screens and the whole form row then fits the card. */
  table.cfb-sched table.frt td .mv{display:none}
  .sc-stat{margin:-4px 0 4px 26px;font-size:12px}
  table.cfb-sched table.frt td{padding-right:6px}
  .l5,.sc-stat .l5{width:16px;height:16px;line-height:16px;font-size:11.5px;margin-right:1px}
  .call{font-size:13px}
  /* A 14px-tall link is not a thumb target: padding makes it about 40px,
     the negative margins keep the card's line where it was. It is the one
     way to the rest of a folded card now, so it reads at 13px. */
  .det-btn{font-size:13px;padding:13px 10px;margin:-13px -10px -13px auto}
  .det-block h4,table.cfb-sched table.det-t th,table.cfb-sched table.det-t td{font-size:12px}
  .gs-pick .gp-label,.gs-pick .gp-legs .gp-game,.gs-pick .gp-book,
  .gs-pick .gp-note{font-size:12px}
  /* The picks' jumps to their games, 15-21px tall as text: padded to a
     thumb, margined back so the cards keep their lines. */
  .gs-pick .gp-main a,.gs-pick .gp-legs li a{display:inline-block;padding:12px 0;margin:-12px 0}
  /* Folded, a card is the matchup, the kickoff and the two lines that
     matter - GordStats' and DraftKings' - with More unfolding the rest in
     place: ratings and form under each team, the forecast, every read of
     the line with the call under it, the season, and the panel below. Open,
     it carries every figure it did before. Everything open by default made
     each card about 410px, two games to a screen; folded they are under
     half that. The same `open` class the More button already sets drives
     it, so a deep link to a game (#g=) opens it unfolded. */
  table.cfb-sched>tbody>tr.g:not(.open) .sc-stat,
  table.cfb-sched>tbody>tr.g:not(.open) .t-wx,
  table.cfb-sched>tbody>tr.g:not(.open) td.frm,
  table.cfb-sched>tbody>tr.g:not(.open) td.ln>.c,
  table.cfb-sched>tbody>tr.g:not(.open) td.ln.no-sum{display:none}
  table.cfb-sched>tbody>tr.g:not(.open) td.ln:not(.no-sum){display:block}
  table.cfb-sched>tbody>tr.g:not(.open) td.ln::before{content:none}
  table.cfb-sched>tbody>tr.g:not(.open) .ln-sum{display:grid}
  .ln-sum{grid-template-columns:40px 1fr;gap:1px 4px;font-size:13px;
    font-variant-numeric:tabular-nums;white-space:nowrap}
  .ln-sum .k{font-size:12px;font-weight:700;color:var(--gs-muted,#5d6b7e);letter-spacing:.04em}
  .ln-sum b{color:#0f172a}
  .ln-sum .o{color:#475569}
  table.cfb-sched>tbody>tr.det{display:none}
  table.cfb-sched>tbody>tr.det.show{display:block}
  table.cfb-sched>tbody>tr.det>td{border:1px solid #e2e8f0;border-radius:10px;
    margin:-4px 0 8px;padding:8px 10px}
  table.det-t{width:100%}
  .det-wrap{grid-template-columns:1fr;gap:8px;font-size:12.5px}
  table.cfb-sched{border:none;background:transparent}
  table.cfb-sched,table.cfb-sched>tbody,table.cfb-sched>tbody>tr,
  table.cfb-sched>tbody>tr>td{display:block}
  table.cfb-sched>thead{display:none}
  table.cfb-sched>tbody>tr.g{border:1px solid #e2e8f0;border-radius:10px;margin:8px 0;
    padding:8px 10px 7px;background:#fff}
  table.cfb-sched>tbody>tr.g>td,table.cfb-sched>tbody>tr.g:nth-child(even)>td{border:none;
    padding:2px 0;background:transparent}
  table.cfb-sched td.mu{position:static;padding-bottom:6px;border-bottom:1px solid #eef2f7;
    margin-bottom:4px}
  /* The card's full width, not the desktop column's 240px: the score sat
     mid-card and the team link stopped short of the thumb. */
  .sc-mu{min-width:0;max-width:none}
  table.cfb-sched td.d{display:grid;grid-template-columns:40px 1fr;gap:4px;
    font-size:12px;white-space:normal;max-width:none;padding:1px 0}
  table.cfb-sched td.d::before{content:attr(data-s);font-size:12px;text-transform:uppercase;
    letter-spacing:.04em;color:var(--gs-muted,#5d6b7e);font-weight:700;padding-top:2px}
  table.cfb-sched td.na{display:none}
  .sc-venue{max-width:none}
  .t-tv{display:inline;margin:0 0 0 6px}
  .t-day{display:inline}
  .bar{display:none}
  .sub{display:inline;margin-left:6px}
  table.cfb-sched tr.hdr{margin:14px 0 2px}
  table.cfb-sched tr.hdr td{border:none;border-radius:8px}
}
@media (prefers-color-scheme: dark){
  .sc-intro{color:#aab7c9}
  table.cfb-sched th{background:var(--accent-soft,#223052);color:var(--accent-text,#dde5ef);
    border-color:#2b3852}
  table.cfb-sched td{background:#16203a;border-color:#2b3852;color:#dde5ef}
  table.cfb-sched tbody tr.g:nth-child(even) td{background:#1b2540}
  table.cfb-sched tr.hdr td{background:#223052;color:#dde5ef;border-color:#2b3852}
  table.cfb-sched tr.hdr.sec td{background:var(--accent-soft,#2b3852);
    color:var(--accent-text,#dde5ef)}
  table.cfb-sched td.t,.t-tv{color:#aab7c9}
  .sc-venue{color:#7f8ea3}
  table.cfb-sched .rk{color:#f2cc60}
  .sc-name{color:#c3cfdd}
  .sc-joiner,.sc-pts{color:#7f8ea3}
  .sc-row.sc-win .sc-name,.sc-row.sc-win .sc-pts{color:#ffffff}
  .sc-meta{color:#8fa0b8}
  .sc-rec{color:#7f8ea3}
  .sc-live{border-color:#2b3852}
  .sc-sit{color:#f1f5f9}
  .sc-play{color:#8fa0b8}
  .tag-dog{background:#4a3208;color:#fcd34d}
  .tag-toss{background:#1e3a8a;color:#bfdbfe}
  .tag-upset{background:#7f1d1d;color:#fecaca}
  .gs-pick{background:#16203a;border-color:#2b3852}
  .gs-picks-fold>summary{background:#16203a;border-color:#2b3852;color:#c3cfdd}
  .gs-picks-fold>summary b{color:#f1f5f9}
  .gp-sum .gp-p,.gp-sum .gp-hit{color:#6ee7b7}
  .gp-sum .gp-miss{color:#f87171}
  .gs-pick .gp-label,.gs-pick .gp-sub,.gs-pick .gp-note,.gs-pick .gp-book,.gs-pick .gp-legs .gp-game{color:#aab7c9}
  .gs-pick .gp-main,.gs-pick .gp-legs li a{color:#f1f5f9}
  .gs-pick .gp-legs li{border-color:#2b3852}
  .gs-pick .gp-p{color:#6ee7b7}
  .tag-wx{background:#312e81;color:#c7d2fe}
  .t-live{color:#4ade80}
  .ln b,.fpi b{color:#f1f5f9}
  .pct{color:#dde5ef}
  table.cfb-sched table.lnt th,table.cfb-sched table.frt th{color:#8fa0b8;border-color:#2b3852}
  table.cfb-sched table.lnt td,table.cfb-sched table.frt td{color:#c3cfdd}
  table.cfb-sched table.lnt td.k,table.cfb-sched table.frt td.k{color:#8fa0b8}
  table.cfb-sched table.lnt tr.pick td{background:var(--accent-soft,#223052)}
  table.cfb-sched table.lnt tr.pick td.k{color:var(--accent-text,#f1f5f9)}
  .lnt b,.call b{color:#f1f5f9}
  .mlx{color:#8fa0b8}
  .sc-stat{color:#8fa0b8}
  .sc-stat b{color:#c3cfdd}
  .call{color:#c3cfdd}
  .call .strong b{color:var(--accent-text,#bfdbfe)}
  .sub{color:#8fa0b8}
  .bar{background:#223052}
  .mk.hit{color:#4ade80}
  .mk.miss{color:#f87171}
  .gs-pick .gp-miss,.gs-pick .gp-missed{color:#f87171}
  .t-wx{color:#c3cfdd}
  tr.g.wx-bad .t-wx{color:#c7d2fe}
  td.na{color:#7f8ea3}
  .wk-note{color:#aab7c9}
  .sc-controls .lbl,.sc-chips .lbl{color:#aab7c9}
  .sc-select,.sc-search{background:#16203a;border-color:#2b3852;color:#dde5ef}
  .sc-chips button{background:#16203a;border-color:#2b3852;color:#dde5ef;box-shadow:none}
  .sc-chips button:hover{background:#223052}
  .sc-chips button.active{background:var(--accent,#A34F0A);color:#fff;
    border-color:var(--accent-dark,#8A420A)}
  .sc-chips button.clear{color:#aab7c9}
  .sc-filt{background:#16203a;border-color:#2b3852;color:#dde5ef}
  .sc-filt.sc-some{border-color:var(--accent-text,#F5A968);color:var(--accent-text,#F5A968)}
  .sc-legend{color:#aab7c9}
  .sc-legend summary{color:#dde5ef}
  .det-btn{color:#7fb3ff}
  table.cfb-sched tr.det td{background:#1b2540;border-color:#2b3852}
  .det-wrap,table.cfb-sched table.det-t td{color:#c3cfdd}
  .det-block h4,table.cfb-sched table.det-t th{color:#8fa0b8;border-color:#2b3852}
  table.det-t td.k,.det-line b,.lean{color:#f1f5f9}
  .mv{color:#7f8ea3}
  .mv.up{color:#4ade80}
  .mv.dn{color:#f87171}
  .best{background:#14532d}
  .l5.w{background:#14532d;color:#bbf7d0}
  .l5.l{background:#7f1d1d;color:#fecaca}
  @media (max-width:700px){
    table.cfb-sched>tbody>tr.g{border-color:#2b3852;background:#16203a}
    /* The desktop stripe above outranks the light phone rule that clears it,
       and drew a lighter box round every other card's cells. */
    table.cfb-sched>tbody>tr.g>td,
    table.cfb-sched>tbody>tr.g:nth-child(even)>td{background:transparent}
    table.cfb-sched td.mu{border-color:#2b3852}
    table.cfb-sched td.d::before{color:#7f8ea3}
    .ln-sum .k{color:#8fa0b8}
    .ln-sum b{color:#f1f5f9}
    .ln-sum .o{color:#aab7c9}
    table.cfb-sched>tbody>tr.det>td{border-color:#2b3852}
  }
}
</style>"""

# Without JS nothing can unfold a phone card, so none is folded: every figure
# shows as it did before the fold, and the two buttons that would do nothing
# (More, Filters) are not drawn. Same selectors as the fold, later in the page.
_NOSCRIPT = ("<noscript><style>.det-btn,.sc-filt{display:none}"
             "@media (max-width:700px){"
             "table.cfb-sched>tbody>tr.g:not(.open) .sc-stat{display:flex}"
             "table.cfb-sched>tbody>tr.g:not(.open) .t-wx{display:block}"
             "table.cfb-sched>tbody>tr.g:not(.open) td.frm,"
             "table.cfb-sched>tbody>tr.g:not(.open) td.ln:not(.na){display:grid}"
             "table.cfb-sched>tbody>tr.g:not(.open) td.ln>.c{display:block}"
             "table.cfb-sched>tbody>tr.g:not(.open) td.ln::before{content:attr(data-s)}"
             "table.cfb-sched>tbody>tr.g:not(.open) .ln-sum{display:none}}"
             "</style></noscript>")


# The page's one explanation, folded. Everything that is not the games -
# what a card shows, how the picks are set, when the page was built - lives
# here rather than above the first game, where on a phone it ran to about
# eighty words before a single score.
_LEGEND = """<details class="sc-legend"><summary>How to read it</summary>
<p>Each game carries this site's <b>GordStats</b> pick beside the <b>DraftKings</b> line.
On a phone a card opens folded to those two; <b>More</b> unfolds the rest &mdash; FPI and
SP+, the forecast, the season, every book's line. Scores update live while games are on;
the rest was rebuilt {built}.</p>
<ul>
<li><b>Lines</b> &mdash; every read of the game stacked so they can be compared: the
<b>GS</b> row is this site's <a href="/cfb/predictions/">model</a> and is highlighted because
it is the pick (favourite, projected total, and that team's win chance); <b>DK</b> is the
DraftKings spread, total and moneylines as ESPN carries them, captured before kickoff and
frozen; <b>FPI</b> is ESPN's Football Power Index favourite and win chance; <b>SP+</b> is
Bill Connelly's ratings read as a spread with home field added. Under the table is the
call, in one line: the score the model expects, then the DraftKings spread and total it
would take &mdash; <i>GordStats projects 19&ndash;34, recommend M-OH +16.5 and Under
47.5</i>. Hover either number for how far the model and the book are apart; three points
or more is a strong lean and gets the <i>Strong leans</i> filter. Within half a point it
says the model agrees with the book, and names nothing. A finished game shows what was on
record before kickoff, never a refit, with &#10003; or &#10007; on each. Read these as
where the model disagrees with the book rather than as tips: on the games scored so far it
is <b>under break-even</b> against the spread, which the
<a href="/cfb/predictions/#how-it-has-gone">predictions page</a> keeps an honest count
of.</li>
<li><b>Under each team</b> &mdash; GordStats rating (points better than an average
FBS team), FPI and SP+ rank (hover for the rating, and SP+ offence and defence ranks), and
the last five results as W/L chips with the score on hover.</li>
<li><b>Season</b> &mdash; away team over home: record, against-the-spread and over/under
records this season (counted here against the closing DraftKings line, since ESPN
publishes none for college football), and points scored and allowed per game.</li>
<li><b>Weather</b> &mdash; ESPN's AccuWeather forecast for kickoff, which appears about ten
days out: conditions, temperature, chance of rain, gusts. <i>Bad weather</i> means rain,
storms or snow, a 50%+ chance of rain, gusts of 25+ mph, or a kickoff at or below
freezing.</li>
<li><b>Tags</b> &mdash; <i>Home dog</i>: the home team is the underdog on the book's line
(the model's, if there is no book line yet). <i>Toss-up</i>: the spread is three points or
fewer. <i>Upset</i>: the favourite lost. <i>Upset watch</i> in the filters: the model or
FPI gives the underdog at least a 35% chance, or the two disagree on who is favoured.</li>
<li><b>More</b> on any game opens every book's line (DraftKings from ESPN; Bovada and
others from CollegeFootballData) with how each has moved since it opened, our archive of
the DraftKings line day by day, the implied final score and moneyline chance, and where
GordStats and SP+ lean against the number.</li>
<li><b>Sorting</b> by anything other than kickoff turns the week into one ranked list;
games without the figure being sorted on fall to the bottom. <i>Matchup quality</i> is
ESPN's 0&ndash;100 measure of how competitive and consequential a game projects to be.</li>
<li><b>Picks of the day</b> &mdash; set before the day's first kickoff, locked, and not
touched since; a later day's picks are a preview until that morning. The <i>underdog</i> is
the book's underdog the model gives the best chance, set against the moneyline with the
vig taken out. The <i>parlay</i> is the model's surest call against the book in each game,
one per game, each with the chance its own error spread gave it; the combined figure is
those multiplied. How the spread and total calls have done is on the
<a href="/cfb/predictions/">predictions page</a>.</li>
</ul></details>"""


@lru_cache(maxsize=1)
def _team_pages() -> frozenset:
    """Slugs with a built team page - the only names worth linking.

    cfb.build runs teams before schedule, so on a full build every FBS page is
    on disk by now; FCS visitors have no page and stay plain text.
    """
    d = WEB_DIR / "teams"
    return frozenset(p.name for p in d.iterdir() if p.is_dir()) if d.exists() else frozenset()


def _records(week: int) -> dict:
    """Event id -> {'home': '2-0', 'away': '1-1'} from the live feed, for the
    current week only; the page's own polling keeps them moving after that."""
    try:
        data = espn._get({"groups": espn._FBS, "dates": SEASON, "limit": 500,
                          **espn.query(week)})
    except Exception:
        return {}
    out = {}
    for event in data.get("events", []):
        comps = event.get("competitions") or [{}]
        sides = {}
        for c in comps[0].get("competitors", []):
            total = next((r.get("summary") for r in (c.get("records") or [])
                          if r.get("type") == "total"), None)
            if total:
                sides[c.get("homeAway")] = total
        if sides:
            out[str(event.get("id"))] = sides
    return out


def _abandoned(g) -> bool:
    """Cancelled/postponed games arrive as state=post with hollow 0-0 scores."""
    return any(w in (g.detail or "") for w in ("Cancel", "Postpon"))


def _v(x):
    """A scalar, or None where pandas or JSON left a hole."""
    if x is None:
        return None
    try:
        return None if pd.isna(x) else x
    except (TypeError, ValueError):
        return x


# ---------------------------------------------------------------------------
# Assembling one frame with everything a row needs.

def _model_lines(sched: pd.DataFrame) -> pd.DataFrame:
    """game_id -> gs_margin, gs_total, gs_wp, gs_home, gs_away; and the fit's
    team ratings into _CTX["ratings"] (ESPN id -> points above average).

    Games still to play get one fit as of now, the same fit the team pages
    run on. Finished games get the last prediction archived before their
    kickoff, or nothing: a line produced after the result is not a line.
    """
    cols = ["game_id", "gs_margin", "gs_total", "gs_wp", "gs_home", "gs_away"]
    frames = []
    try:
        season, _, _ = predict.season()
    except Exception as exc:                 # no history yet, or a fit that failed
        print(f"  ! model lines unavailable ({exc})")
        season = pd.DataFrame()
    done = set(sched.loc[sched["state"] == "post", "game_id"].astype(str))
    # The fit for a pending game, the archive for a finished one - by source,
    # not by membership: the archive also holds this week's games, captured
    # before kickoff, and a pending game must still show today's fit.
    if not season.empty:
        ratings = {}
        for side in ("home", "away"):
            ratings.update(dict(zip(season[f"{side}_id"].astype(str), season[f"{side}_rating"])))
        _CTX["ratings"] = {k: v for k, v in ratings.items() if not pd.isna(v)}
        pending = season[~season["game_id"].astype(str).isin(done)]
        frames.append(pd.DataFrame({
            "game_id": pending["game_id"].astype(str),
            "gs_margin": pending["pred_margin"], "gs_total": pending["pred_total"],
            "gs_wp": pending["home_win_prob"],
            "gs_home": pending["pred_home"], "gs_away": pending["pred_away"]}))
    record = results.on_record()
    if not record.empty:
        finished = record[record["game_id"].astype(str).isin(done)]
        frames.append(pd.DataFrame({
            "game_id": finished["game_id"].astype(str),
            "gs_margin": finished["pred_margin"], "gs_total": finished["pred_total"],
            "gs_wp": finished["home_win_prob"],
            # The archive stores the margin and the total, not the two scores,
            # but those determine them exactly: home = (total + margin) / 2.
            # Derived rather than left NaN so a finished game can still say
            # what the model projected, which is the whole claim being scored.
            "gs_home": (finished["pred_total"] + finished["pred_margin"]) / 2,
            "gs_away": (finished["pred_total"] - finished["pred_margin"]) / 2}))
    if not frames:
        return pd.DataFrame(columns=cols)
    out = pd.concat(frames, ignore_index=True)
    return out.drop_duplicates("game_id", keep="last")[cols]


def _frame() -> pd.DataFrame:
    df = espn.schedule().copy()
    df["game_id"] = df["game_id"].astype(str)
    df["local"] = pd.to_datetime(df["date_utc"], utc=True).dt.tz_convert(str(LEAGUE_TZ))
    for col in ("home_conf_id", "away_conf_id"):
        if col not in df.columns:
            df[col] = ""

    df = df.merge(_model_lines(df), on="game_id", how="left")

    board = odds_mod.latest(SEASON)
    bd_cols = ["bd_spread", "bd_total", "bd_book", "bd_spread_open", "bd_total_open",
               "bd_ml_home", "bd_ml_away", "bd_ml_home_open", "bd_ml_away_open"]
    if not board.empty:
        board = board.rename(columns={c: "bd_" + c for c in odds_mod._LATEST_COLS
                                      if c not in odds_mod.KEY})
        df = df.merge(board[odds_mod.KEY + bd_cols], on=odds_mod.KEY, how="left")
    for col in bd_cols + ["gs_margin", "gs_total", "gs_wp", "gs_home", "gs_away"]:
        if col not in df.columns:
            df[col] = np.nan
    _CTX.update({"form": _form(df), "fpi": _fpi_by_id(), "sp": cfbd.sp_by_id(),
                 "rec": cfbd.records(), "books": cfbd.lines(), "cfbd_wp": cfbd.pregame_wp(),
                 "line_hist": _line_history()})

    info = gameinfo.load(SEASON)
    cfbd_wx = cfbd.weather()
    confs = espn.conferences()
    rows = []
    for g in df.itertuples():
        e = info.get(g.game_id) or {}
        final = g.state == "post"
        # The summary's line is fresher than the daily odds archive while a
        # game is pending; once it is over the archive's last capture is the
        # closing line and the frozen summary entry only backs it up.
        first, second = ((_v(g.bd_spread), _v(g.bd_total)), (e.get("spread"), e.get("total")))
        if not final:
            first, second = second, first
        dk_spread = first[0] if first[0] is not None else second[0]
        dk_total = first[1] if first[1] is not None else second[1]
        rows.append({
            "dk_spread": dk_spread, "dk_total": dk_total,
            "dk_book": e.get("book") or _v(g.bd_book) or "DraftKings",
            "ml_home": e.get("ml_home") if e.get("ml_home") is not None else _v(g.bd_ml_home),
            "ml_away": e.get("ml_away") if e.get("ml_away") is not None else _v(g.bd_ml_away),
            "fpi_wp": e.get("espn_home_wp"),
            "last5_home": e.get("last5_home"), "last5_away": e.get("last5_away"),
            "mq": e.get("mq"),
            "weather": _merge_weather(e.get("weather"), cfbd_wx.get(str(g.game_id))),
            "home_conf": confs.get(str(g.home_id), ""),
            "away_conf": confs.get(str(g.away_id), ""),
        })
    extra = pd.DataFrame(rows, index=df.index)
    return pd.concat([df, extra], axis=1)


def _form(df: pd.DataFrame) -> dict:
    """ESPN team id -> this season's form from the games played: record,
    points for and against, and - against the last captured DraftKings line -
    the against-the-spread and over/under records. ESPN publishes no ATS
    record for college football, so it is counted here."""
    out = {}
    played = df[(df["state"] == "post") & df["home_score"].notna() & df["away_score"].notna()]
    played = played[(played["home_score"] + played["away_score"]) > 0]
    for g in played.itertuples():
        margin = g.home_score - g.away_score
        total = g.home_score + g.away_score
        spread, ou = _v(g.bd_spread), _v(g.bd_total)
        for side, tid, pf, pa, sign in (("home", g.home_id, g.home_score, g.away_score, 1),
                                        ("away", g.away_id, g.away_score, g.home_score, -1)):
            f = out.setdefault(str(tid), {"g": 0, "w": 0, "l": 0, "pf": 0.0, "pa": 0.0,
                                          "ats": [0, 0, 0], "ou": [0, 0, 0]})
            f["g"] += 1
            f["w" if pf > pa else "l"] += 1
            f["pf"] += pf
            f["pa"] += pa
            if spread is not None:
                cover = (margin + spread) * sign     # home covers when margin + spread > 0
                f["ats"][0 if cover > 0 else (1 if cover < 0 else 2)] += 1
            if ou is not None:
                f["ou"][0 if total > ou else (1 if total < ou else 2)] += 1
    return out


def _fpi_by_id() -> dict:
    """ESPN team id -> {rating, rank} from the cached FPI pull."""
    path = DATA_DIR / f"fpi_{SEASON}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    names = next((c.get("names") or [] for c in data.get("categories") or []
                  if c.get("name") == "fpi"), [])
    pos = {n: i for i, n in enumerate(names)}
    out = {}
    for entry in data.get("teams") or []:
        team = entry.get("team") or {}
        cat = next((c for c in entry.get("categories") or [] if c.get("name") == "fpi"), {})
        values = cat.get("values") or []
        try:
            out[str(team.get("id"))] = {"rating": float(values[pos["fpi"]]),
                                        "rank": int(values[pos["fpirank"]])}
        except (KeyError, IndexError, TypeError, ValueError):
            continue
    return out


def _line_history() -> dict:
    """(week, home_id, away_id) -> [(day, spread, total)] - one entry per capture day."""
    hist = odds_mod.history(SEASON)
    if hist.empty:
        return {}
    hist = hist.copy()
    hist["day"] = hist["captured"].str[:10]
    hist = hist.drop_duplicates(subset=odds_mod.KEY + ["day"], keep="last")
    out = {}
    for r in hist.itertuples():
        out.setdefault((int(r.week), str(r.home_id), str(r.away_id)), []).append(
            (r.day, _v(r.spread), _v(r.total)))
    return out


def _implied(ml) -> float | None:
    if ml is None:
        return None
    return 100 / (ml + 100) if ml > 0 else -ml / (-ml + 100)


def _devig(ml_home, ml_away) -> float | None:
    h, a = _implied(ml_home), _implied(ml_away)
    if h is None or a is None or h + a <= 0:
        return None
    return h / (h + a)


# ---------------------------------------------------------------------------
# Rendering.

def _side_row(g, side: str, records: dict) -> str:
    """One team's line in the scorebox: logo, rank, linked name, record, score."""
    name = str(getattr(g, side))
    tid = escape(str(getattr(g, f"{side}_id")))
    rec = records.get(str(g.game_id), {}).get(side, "")
    rec_tag = f'<span class="sc-rec">{escape(rec)}</span>' if rec else ""
    rank = getattr(g, f"{side}_rank")
    badge = "" if pd.isna(rank) else f'<span class="rk">#{int(rank)}</span> '
    joiner = ("" if side == "away"
              else f'<span class="sc-joiner">{"vs" if g.neutral else "at"}</span> ')
    slug = team_slug(name)
    logo = logos.img("ncaa", getattr(g, f"{side}_id"), 20)
    # Logo, rank and name in one link where the team has a page (an FCS
    # visitor has none, and stays plain text) - see .sc-team in _CSS.
    team = (f'{logo}<span class="sc-name">{joiner}{badge}'
            f'<span class="sc-tn">{escape(name)}</span>{rec_tag}</span>')
    team = (f'<a class="sc-team" href="/cfb/teams/{slug}/">{team}</a>'
            if slug in _team_pages() else f'<span class="sc-team">{team}</span>')

    score = getattr(g, f"{side}_score")
    other = getattr(g, "home_score" if side == "away" else "away_score")
    scored = g.state in ("in", "post") and not pd.isna(score) and not _abandoned(g)
    won = g.state == "post" and scored and score > other
    pts = f'<span class="sc-pts">{score:.0f}</span>' if scored else ""
    return (f'<div class="sc-row{" sc-win" if won else ""}" data-tid="{tid}">'
            f"{team}{pts}</div>{_stat_line(g, side)}")


def _stat_line(g, side: str) -> str:
    """GordStats rating, FPI and SP+ rank, last five - under the team's name."""
    tid = str(getattr(g, f"{side}_id"))
    bits = []
    rating = _CTX.get("ratings", {}).get(tid)
    if rating is not None:
        bits.append(f'<span title="GordStats rating: points better than an average FBS team">'
                    f"GS <b>{rating:+.1f}</b></span>")
    fpi = _CTX.get("fpi", {}).get(tid)
    if fpi:
        bits.append(f'<span title="ESPN FPI rank ({fpi["rating"]:+.1f})">FPI <b>#{fpi["rank"]}</b></span>')
    sp = _CTX.get("sp", {}).get(tid)
    if sp and sp.get("rank"):
        od = (f", offence #{sp['off_rank']}, defence #{sp['def_rank']}"
              if sp.get("off_rank") and sp.get("def_rank") else "")
        bits.append(f'<span title="SP+ rank ({sp["rating"]:+.1f}{od})">SP+ <b>#{sp["rank"]}</b></span>')
    last5 = getattr(g, f"last5_{side}")
    if last5:
        bits.append(f'<span title="Last five results">{_last5(last5)}</span>')
    return f'<div class="sc-stat">{"".join(bits)}</div>' if bits else ""


def _conf_text(g) -> str:
    home, away = g.home_conf, g.away_conf
    if home and away:
        return f"{home} game" if home == away else f"{away} vs {home}"
    if home or away:
        return f"{away or home} vs FCS"
    return ""


def _kick_cell(g) -> str:
    """Kickoff (or the clock, or Final) over the network, with the weekday
    for sorted views, where the day headers are hidden."""
    local = g.local
    day = f'<span class="t-day">{local.strftime("%a")} </span>'
    live = ""
    if _abandoned(g):
        when = escape(str(g.detail))
    elif g.state == "post":
        when = g.detail if "Final" in (g.detail or "") else "Final"
    elif g.state == "in":
        when, live = escape(str(g.detail or "Live")), " t-live"
    elif not _time_known(g):
        when = "TBD"
    else:
        when = local.strftime("%-I:%M %p")
    tv = f'<span class="t-tv">{escape(str(g.tv))}</span>' if g.tv else ""
    return (f'<td class="t d" data-l="Kick" data-s="Kick"><div class="c">{day}'
            f'<span class="t-when{live}">{when}</span>{tv}{_wx_text(g)}</div></td>')


def _time_known(g) -> bool:
    """False for a kickoff ESPN has not set (see espn._game_row). A schedule
    cached before the column existed has no attribute, and counts as known."""
    v = getattr(g, "time_valid", True)
    return v is None or pd.isna(v) or bool(v)


def _fav(g, margin) -> tuple:
    """(favourite name, favourite abbreviation, home favoured?) for a home margin."""
    home = margin >= 0
    return ((g.home, g.home_abbr, True) if home else (g.away, g.away_abbr, False))


def _line_text(g, spread) -> str:
    """'Missouri -7.5' from a home-convention spread, or 'Pick'."""
    if abs(spread) < 0.25:
        return "Pick"
    name, _, _ = _fav(g, -spread)
    return f"{escape(str(name))} {-abs(spread):.1f}".replace(".0", "")


def _mark(home_fav: bool, home_won) -> str:
    """A tick or a cross once the game is over: did this favourite win?"""
    if home_won is None:
        return ""
    hit = home_fav == home_won
    return f'<span class="mk {"hit" if hit else "miss"}">{"&#10003;" if hit else "&#10007;"}</span>'


def _tick(hit) -> str:
    """A tick, a cross, or 'push' once the result is in."""
    if hit is None:
        return '<span class="mk">push</span>'
    return f'<span class="mk {"hit" if hit else "miss"}">{"&#10003;" if hit else "&#10007;"}</span>'


def _ml(ml) -> str:
    return f"{ml:+.0f}" if ml is not None else "&mdash;"


def _sp_margin(g):
    """SP+ read as a spread: rating gap plus home field, or None."""
    sp_h = _CTX.get("sp", {}).get(str(g.home_id), {})
    sp_a = _CTX.get("sp", {}).get(str(g.away_id), {})
    if sp_h.get("rating") is None or sp_a.get("rating") is None:
        return None
    return sp_h["rating"] - sp_a["rating"] + (0 if g.neutral else HOME_EDGE)


def _wp_text(g, wp) -> str:
    _, abbr, home_fav = _fav(g, wp - 0.5)
    return f"{escape(str(abbr))} {(wp if home_fav else 1 - wp):.0%}"


def _lines_cell(g, home_won, sp_margin) -> str:
    """One box with every read of the game stacked for comparison - GordStats
    (highlighted: it is the pick), DraftKings, ESPN's FPI, SP+ - as rows of
    spread, total and win chance, then the call: the side GordStats would
    take against the DraftKings number and by how much, and Over or Under
    the posted total. On a finished game each call gets a tick or a cross."""
    margin, wp = _v(g.gs_margin), _v(g.gs_wp)
    dk_spread, dk_total = _v(g.dk_spread), _v(g.dk_total)
    gs_total, fpi = _v(g.gs_total), _v(g.fpi_wp)
    if margin is None and dk_spread is None and fpi is None and sp_margin is None:
        return '<td class="ln na no-sum d" data-l="Lines" data-s="Lines">&mdash;</td>'

    final_margin = final_total = None
    if home_won is not None:
        final_margin = float(g.home_score - g.away_score)
        final_total = float(g.home_score + g.away_score)

    def row(label, spread_txt, total_txt, win_txt, cls=""):
        return (f'<tr class="{cls}"><td class="k">{label}</td><td>{spread_txt}</td>'
                f"<td>{total_txt}</td><td>{win_txt}</td></tr>")

    rows = []
    if margin is not None:
        name, _, home_fav = _fav(g, margin)
        rows.append(row("GS", f"<b>{_line_text(g, -margin)}</b>",
                        f"{gs_total:.0f}" if gs_total is not None else "&mdash;",
                        (f"<b>{_wp_text(g, wp)}</b>" if wp is not None else "&mdash;")
                        + _mark(home_fav, home_won), "pick"))
    if dk_spread is not None or dk_total is not None:
        ml = ""
        if _v(g.ml_away) is not None or _v(g.ml_home) is not None:
            ml = (f'<span class="mlx" title="moneyline, {escape(str(g.away_abbr))} / '
                  f'{escape(str(g.home_abbr))}">ML {_ml(_v(g.ml_away))} / {_ml(_v(g.ml_home))}'
                  "</span>")
        rows.append(row("DK", _line_text(g, dk_spread) if dk_spread is not None else "&mdash;",
                        f"{dk_total:g}" if dk_total is not None else "&mdash;", ml or "&mdash;"))
    if fpi is not None:
        rows.append(row("FPI", "&mdash;", "&mdash;", _wp_text(g, fpi) + _mark(fpi >= 0.5, home_won)))
    if sp_margin is not None:
        rows.append(row("SP+", _line_text(g, -sp_margin), "&mdash;", "&mdash;"))
    table = ('<table class="lnt"><tr><th></th><th>Spread</th><th>O/U</th><th>Win</th></tr>'
             + "".join(rows) + "</table>")

    # One sentence: the score the model expects, then the two DraftKings numbers
    # it would take. The previous version led with "ATS EMU -1.5 by 0.9 · Over
    # 47.5 by 5.1 · proj 19-34", which put the jargon first, the projection
    # last, and asked the reader to work out what to do with any of it. The
    # margin of disagreement is still there, in the title, because it is the
    # thing that separates a lean worth noticing from a rounding difference.
    done = g.state == "post"
    recs = []
    agrees = False

    if margin is not None and dk_spread is not None:
        gap = margin - (-dk_spread)            # > 0: the model likes the home side vs the number
        if abs(gap) >= 0.5:
            lean_home = gap > 0
            abbr = g.home_abbr if lean_home else g.away_abbr
            number = dk_spread if lean_home else -dk_spread
            mark = ""
            if final_margin is not None:
                cover = (final_margin + dk_spread) * (1 if lean_home else -1)
                mark = _tick(None if cover == 0 else cover > 0)
            recs.append(f'<b class="{"strong" if abs(gap) >= 3 else ""}" '
                        f'title="The model and the book differ by {abs(gap):.1f} points">'
                        f"{escape(str(abbr))} {number:+g}</b>{mark}")
        else:
            agrees = True

    if gs_total is not None and dk_total is not None and abs(gs_total - dk_total) >= 0.5:
        over = gs_total > dk_total
        mark = ""
        if final_total is not None:
            mark = _tick(None if final_total == dk_total else (final_total > dk_total) == over)
        recs.append(f'<b title="The model and the book differ by '
                    f'{abs(gs_total - dk_total):.1f} points">'
                    f"{'Over' if over else 'Under'} {dk_total:g}</b>{mark}")

    projects = ""
    if _v(g.gs_home) is not None:
        # Named, not just "28-25": the row above lists the teams away-then-home
        # and so does this, but a bare pair of numbers still made the reader
        # check which way round it went before it meant anything.
        projects = (f"GordStats projected" if done else "GordStats projects") + \
                   f" <b>{escape(str(g.away_abbr))} {g.gs_away:.0f}" \
                   f"&ndash;{escape(str(g.home_abbr))} {g.gs_home:.0f}</b>"

    if recs:
        verb = "recommended" if done else "recommend"
        tail = f"{verb} " + " and ".join(recs)
        sentence = f"{projects}, {tail}" if projects else tail[0].upper() + tail[1:]
    elif projects:
        sentence = projects + ('<span class="mv"> &middot; agrees with the book</span>'
                               if agrees else "")
    else:
        sentence = ""
    call = f'<div class="call">{sentence}</div>' if sentence else ""
    summary = _lines_summary(g, home_won)
    return (f'<td class="ln d{"" if summary else " no-sum"}" data-l="Lines" data-s="Lines">'
            f'{summary}<div class="c">{table}{call}</div></td>')


def _short_line(g, spread) -> str:
    """'NMSU -2.5' from a home-convention spread: _line_text with the
    abbreviation, so a folded phone card's line never wraps."""
    if abs(spread) < 0.25:
        return "Pick"
    _, abbr, _ = _fav(g, -spread)
    number = f"{-abs(spread):.1f}".removesuffix(".0")
    return f"{escape(str(abbr))} {number}"


def _lines_summary(g, home_won) -> str:
    """The two rows of the Lines box a folded phone card keeps - GordStats'
    spread, win chance and total, DraftKings' spread and total - or "" when
    neither has a line yet. Hidden everywhere else (.ln-sum in _CSS)."""
    margin, wp, gs_total = _v(g.gs_margin), _v(g.gs_wp), _v(g.gs_total)
    dk_spread, dk_total = _v(g.dk_spread), _v(g.dk_total)
    rows = []
    if margin is not None:
        _, _, home_fav = _fav(g, margin)
        bits = [f"<b>{_short_line(g, -margin)}</b>"]
        if wp is not None:
            bits.append(f"{max(wp, 1 - wp):.0%}{_mark(home_fav, home_won)}")
        if gs_total is not None:
            bits.append(f'<span class="o">O/U {gs_total:.0f}</span>')
        rows.append(("GS", " &middot; ".join(bits)))
    if dk_spread is not None or dk_total is not None:
        bits = [_short_line(g, dk_spread)] if dk_spread is not None else []
        if dk_total is not None:
            bits.append(f'<span class="o">O/U {dk_total:g}</span>')
        rows.append(("DK", " &middot; ".join(bits)))
    if not rows:
        return ""
    return ('<div class="ln-sum">' + "".join(
        f'<span class="k">{k}</span><span>{v}</span>' for k, v in rows) + "</div>")


def _form_row(g, side: str) -> str:
    tid = str(getattr(g, f"{side}_id"))
    abbr = escape(str(getattr(g, f"{side}_abbr")))
    f = _CTX.get("form", {}).get(tid)
    rec = _CTX.get("rec", {}).get(tid, {})
    total = rec.get("total") or (f"{f['w']}-{f['l']}" if f else "&mdash;")
    if f and f["g"]:
        ppg, pa = f["pf"] / f["g"], f["pa"] / f["g"]
        ats = "-".join(str(x) for x in f["ats"][:2]) + (f"-{f['ats'][2]}" if f["ats"][2] else "")
        ou = "-".join(str(x) for x in f["ou"][:2]) + (f"-{f['ou'][2]}" if f["ou"][2] else "")
        cells = (f"<td>{ats if sum(f['ats']) else '&mdash;'}</td>"
                 f"<td>{ou if sum(f['ou']) else '&mdash;'}</td>"
                 f"<td>{ppg:.0f}&ndash;{pa:.0f}</td>")
    else:
        cells = "<td>&mdash;</td>" * 3
    return f'<tr><td class="k">{abbr}</td><td>{total}</td>{cells}</tr>'


def _form_cell(g) -> str:
    """Both teams' results this season, away over home: record, against-the-
    spread and over/under records, points for and against per game. Ratings
    and the last five sit under each name in the matchup cell."""
    return ('<td class="frm d" data-l="Season" data-s="Season"><div class="c">'
            '<div class="frm-scroll"><table class="frt"><tr><th></th>'
            '<th title="Record">Rec</th><th title="Against the spread this season">ATS</th>'
            '<th title="Over-under this season">O/U</th>'
            '<th title="Points scored and allowed per game">PF&ndash;PA</th></tr>'
            + _form_row(g, "away") + _form_row(g, "home") + "</table></div></div></td>")


def _wx_icon(cond) -> str:
    if cond is None:
        return ""
    if cond in gameinfo._SNOW:
        return "&#10052;&#65039;"                    # snowflake
    if cond in gameinfo._STORM:
        return "&#9928;&#65039;"                     # cloud with lightning and rain
    if cond in gameinfo._RAIN:
        return "&#127783;&#65039;"                   # cloud with rain
    if cond in (11, 37):
        return "&#127787;&#65039;"                   # fog
    if cond == 32:
        return "&#128168;"                           # dashing away (wind)
    if cond in (1, 2, 30, 33, 34):
        return "&#9728;&#65039;"                     # sun
    if cond in (3, 4, 5, 35, 36):
        return "&#9925;"                             # sun behind cloud
    return "&#9729;&#65039;"                         # cloud


def _merge_weather(espn_wx: dict | None, cfbd_wx: dict | None) -> dict | None:
    """One weather block out of the two feeds, which are good at different things.

    ESPN forecasts about ten days out and freezes at kickoff, so it is what a
    reader sees for an upcoming game - but it carries only a gust, and nothing
    at all for the other two thirds of the season. CFBD lands a few days out
    and keeps measuring through the game, so it supplies sustained wind, the
    indoor flag and, once a game is over, what the conditions actually were.
    """
    if not espn_wx and not cfbd_wx:
        return None
    out = dict(espn_wx or {})
    if cfbd_wx:
        if cfbd_wx.get("indoors"):
            out["indoors"] = True
        if cfbd_wx.get("wind") is not None:
            out["wind"] = cfbd_wx["wind"]
        if out.get("temp") is None and cfbd_wx.get("temp") is not None:
            out["temp"] = cfbd_wx["temp"]
        # Rain in inches, not ESPN's chance of rain: both are worth keeping,
        # and only this one says it is actually raining.
        if cfbd_wx.get("precip") is not None:
            out["rain_in"] = cfbd_wx["precip"]
        if cfbd_wx.get("snow"):
            out["snow_in"] = cfbd_wx["snow"]
        if not out.get("cond") and cfbd_wx.get("text"):
            out["text"] = cfbd_wx["text"]
    return out


def _wx_text(g) -> str:
    """The forecast line under the kickoff, or nothing when there is none."""
    wx = g.weather if isinstance(g.weather, dict) else None
    if not wx:
        return ""
    if wx.get("indoors"):
        return '<span class="t-wx">&#127967;&#65039; Indoors</span>'
    main = []
    temp = wx.get("temp")
    if temp is not None:
        main.append(f"{temp:.0f}&deg;")
    text = gameinfo.weather_text(wx) or wx.get("text") or ""
    if text:
        main.append(escape(text))
    sub = []
    if wx.get("precip") is not None and wx["precip"] > 0:
        sub.append(f"rain {wx['precip']:.0f}%")
    # Sustained wind is the number that decides whether a game plays windy;
    # ESPN only has the gust, so this is the CFBD half of the block.
    if wx.get("wind") is not None and wx["wind"] >= 10:
        sub.append(f"wind {wx['wind']:.0f} mph")
    elif wx.get("gust") is not None and wx["gust"] >= 10:
        sub.append(f"gusts {wx['gust']:.0f} mph")
    return (f'<span class="t-wx">{_wx_icon(wx.get("cond"))} {" ".join(main)}'
            + (f'<span class="sub">{" &middot; ".join(sub)}</span>' if sub else "")
            + "</span>")


def _row(g, idx: int, records: dict) -> str:
    final = g.state == "post" and not _abandoned(g)
    ranked = not (pd.isna(g.home_rank) and pd.isna(g.away_rank))
    dk_spread, gs_margin = _v(g.dk_spread), _v(g.gs_margin)
    # The book's opinion where there is one, the model's until then, drives
    # the badges; the model and FPI each show their own favourite.
    spread = dk_spread if dk_spread is not None else (
        -gs_margin if gs_margin is not None else None)
    home_won = None
    if final and _v(g.home_score) is not None and _v(g.away_score) is not None:
        home_won = bool(g.home_score > g.away_score)

    known = [wp for wp in (_v(g.gs_wp), _v(g.fpi_wp)) if wp is not None]
    home_dog = spread is not None and spread > 0.25
    toss_up = spread is not None and abs(spread) <= TOSS_UP
    upset = home_won is not None and spread is not None and abs(spread) > 0.25 \
        and (spread < 0) != home_won
    # Upset chance: the consensus underdog's best case between the model and
    # FPI, or what happened. Two that disagree on the favourite make it > 0.5.
    upset_chance = None
    if home_won is not None and spread is not None and abs(spread) > 0.25:
        upset_chance = 1.0 if upset else 0.0
    elif known and spread is not None and abs(spread) > 0.25:
        upset_chance = max((wp if spread > 0 else 1 - wp) for wp in known)
    elif known:
        upset_chance = max(min(wp, 1 - wp) for wp in known)
    wx = g.weather if isinstance(g.weather, dict) else None
    severity = gameinfo.weather_severity(wx)
    sp_margin = _sp_margin(g)
    gap = (abs(gs_margin - (-dk_spread))
           if gs_margin is not None and dk_spread is not None else None)
    total = _v(g.dk_total) if _v(g.dk_total) is not None else _v(g.gs_total)

    tags = []
    if home_dog:
        tags.append('<span class="tag tag-dog">Home dog</span>')
    if toss_up:
        tags.append('<span class="tag tag-toss">Toss-up</span>')
    if upset:
        tags.append('<span class="tag tag-upset">Upset</span>')
    if severity >= 2:
        tags.append('<span class="tag tag-wx">Weather</span>')
    conf = _conf_text(g)
    meta = ('<div class="sc-meta">' + (f"<span>{escape(conf)}</span>" if conf else "")
            + "".join(tags)
            + '<button type="button" class="det-btn" aria-expanded="false">More &#9662;</button>'
            "</div>")

    confs = "|".join(sorted({c for c in (g.home_conf, g.away_conf) if c}))
    teams = " ".join(str(x).lower() for x in (g.home, g.away, g.home_abbr, g.away_abbr))

    def attr(name, value, fmt="{:.3f}"):
        return f' data-{name}="{fmt.format(value)}"' if value is not None else ""

    classes = ["g"] + (["wx-bad"] if severity >= 2 else [])
    # The bowl's name leads where there is one ("Rose Bowl" says more than
    # the stadium does).
    where = [escape(str(x)) for x in (getattr(g, "note", ""), g.venue, g.place)
             if isinstance(x, str) and x]
    venue = ('<div class="sc-venue">' + "".join(f"<span>{x}</span>" for x in where)
             + "</div>") if where else ""
    return (
        f'<tr class="{" ".join(classes)}" id="g-{escape(str(g.game_id))}" data-i="{idx}"'
        f'{favorites.many_attr("cfb", (g.home_id, g.away_id))}'
        f' data-state="{g.state}" data-kick="{escape(str(g.date_utc))}"'
        f' data-day="{g.local.strftime("%A, %B %-d")}"'
        f' data-final="{int(final)}" data-ranked="{int(ranked)}"'
        f' data-confgame="{int(bool(g.conference_game))}"'
        f' data-p4="{int(bool({g.home_conf, g.away_conf} & POWER4))}"'
        f' data-confs="{escape(confs)}" data-teams="{escape(teams)}"'
        + attr("homedog", spread if home_dog else None, "{:.1f}")
        + attr("spread", abs(spread) if spread is not None else None, "{:.1f}")
        + attr("total", total, "{:.1f}")
        + attr("mq", _v(g.mq), "{:.1f}")
        + attr("wx", severity)
        + attr("gap", gap, "{:.1f}")
        + attr("upset", upset_chance)
        + f' data-tossup="{int(toss_up)}">'
        f'<td class="mu"><div class="sc-mu">{_side_row(g, "away", records)}'
        f'{_side_row(g, "home", records)}</div>{meta}{venue}'
        '<div class="sc-live"><div class="sc-sit"></div><div class="sc-play"></div></div></td>'
        + _kick_cell(g) + _lines_cell(g, home_won, sp_margin) + _form_cell(g)
        + "</tr>" + _detail(g, spread, gs_margin, home_won, sp_margin))


def _mv(now, opened, signed=True) -> str:
    """'opened 52.5' beside a line that has moved since the book posted it."""
    if opened is None or now is None or abs(now - opened) < 0.01:
        return ""
    return f' <span class="mv">opened {opened:+g}</span>' if signed else \
        f' <span class="mv">opened {opened:g}</span>'


def _side_line(g, spread) -> str:
    return _line_text(g, spread) if spread is not None else "&mdash;"


def _book_row(g, name, spread, spread_open, total, total_open, ml_h, ml_a,
              ml_h_open=None, ml_a_open=None) -> str:
    sp = _side_line(g, spread)
    if spread is not None and spread_open is not None and abs(spread - spread_open) > 0.01:
        # Same favourite: quote the favourite's number. Flipped: name the new one.
        sp += (_mv(-abs(spread), -abs(spread_open)) if (spread < 0) == (spread_open < 0)
               else f' <span class="mv">opened {_side_line(g, spread_open)}</span>')
    tot = ("&mdash;" if total is None else f"{total:g}") + (
        _mv(total, total_open, signed=False) if total is not None and total_open is not None
        else "")
    ml = ("&mdash;" if ml_a is None and ml_h is None else
          f"{_ml(ml_a)} / {_ml(ml_h)}")
    if ml_a_open is not None and ml_h_open is not None and (ml_a_open != ml_a or ml_h_open != ml_h):
        ml += f' <span class="mv">opened {_ml(ml_a_open)} / {_ml(ml_h_open)}</span>'
    return f'<tr><td class="k">{escape(name)}</td><td>{sp}</td><td>{tot}</td><td>{ml}</td></tr>'


def _last5(games) -> str:
    if not games:
        return "&mdash;"
    out = []
    for e in games:
        r = (e.get("r") or "").upper()[:1]
        title = escape(f"{r} {e.get('s', '')} {e.get('v', '')} {e.get('o', '')}".strip())
        out.append(f'<span class="l5 {"w" if r == "W" else "l"}" title="{title}">{r or "?"}</span>')
    return "".join(out)


def _detail(g, spread, gs_margin, home_won, sp_margin) -> str:
    """The More panel: every book and its movement, implied numbers, and
    where the model and SP+ lean against the number."""
    ha, hh = escape(str(g.away_abbr)), escape(str(g.home_abbr))
    # Books: DraftKings from ESPN's feed (frozen at kickoff), the rest from CFBD.
    rows = []
    dk_spread, dk_total = _v(g.dk_spread), _v(g.dk_total)
    if dk_spread is not None or dk_total is not None:
        rows.append(_book_row(g, "DraftKings", dk_spread, _v(g.bd_spread_open), dk_total,
                              _v(g.bd_total_open), _v(g.ml_home), _v(g.ml_away),
                              _v(g.bd_ml_home_open), _v(g.bd_ml_away_open)))
    for b in _CTX.get("books", {}).get(str(g.game_id), []):
        if b["book"] == "DraftKings" and rows:
            continue
        rows.append(_book_row(g, b["book"], b.get("spread"), b.get("spread_open"),
                              b.get("total"), b.get("total_open"),
                              b.get("ml_home"), b.get("ml_away")))
    books = ('<div class="det-scroll"><table class="det-t"><tr><th>Book</th><th>Spread</th>'
             f'<th>Total</th><th>ML {ha} / {hh}</th></tr>{"".join(rows)}</table></div>'
             if rows else '<div class="det-line">No line posted yet.</div>')

    lines = []
    hist = _CTX.get("line_hist", {}).get((int(g.week), str(g.home_id), str(g.away_id)), [])
    if len(hist) > 1:
        steps = " &middot; ".join(
            f"{pd.Timestamp(d):%b %-d} {_side_line(g, sp)}" + (f" / {t:g}" if t is not None else "")
            for d, sp, t in hist[-6:])
        lines.append(f'<div class="det-line"><b>Line by day</b> (DraftKings): {steps}</div>')
    if dk_spread is not None and dk_total is not None:
        home_pts, away_pts = (dk_total - dk_spread) / 2, (dk_total + dk_spread) / 2
        implied = f"<b>DraftKings implies</b> {ha} {away_pts:.0f}&ndash;{hh} {home_pts:.0f}"
        wp = _devig(_v(g.ml_home), _v(g.ml_away))
        if wp is not None:
            _, abbr, home_fav = _fav(g, wp - 0.5)
            implied += f"; the moneyline says {escape(str(abbr))} {(wp if home_fav else 1 - wp):.0%}"
        lines.append(f'<div class="det-line">{implied}.</div>')

    # Opinions beside the number.
    ops = []
    if gs_margin is not None:
        wp = _v(g.gs_wp)
        ops.append(f"<b>GordStats</b> {_line_text(g, -gs_margin)}"
                   + (f" &middot; {max(wp, 1 - wp):.0%}" if wp is not None else "")
                   + (f" &middot; O/U {g.gs_total:.0f}" if _v(g.gs_total) is not None else ""))
    fpi = _v(g.fpi_wp)
    if fpi is not None:
        _, abbr, home_fav = _fav(g, fpi - 0.5)
        ops.append(f"<b>FPI</b> {escape(str(abbr))} {(fpi if home_fav else 1 - fpi):.0%}")
    cw = _CTX.get("cfbd_wp", {}).get(str(g.game_id))
    if cw is not None:
        _, abbr, home_fav = _fav(g, cw - 0.5)
        ops.append(f"<b>CFBD</b> {escape(str(abbr))} {(cw if home_fav else 1 - cw):.0%}")
    if sp_margin is not None:
        ops.append(f"<b>SP+</b> {_line_text(g, -sp_margin)}")
    edges = []
    if spread is not None and abs(spread) > 0.25 and dk_spread is not None:
        for label, margin in (("GordStats", gs_margin), ("SP+", sp_margin)):
            if margin is None:
                continue
            diff = margin - (-dk_spread)
            if abs(diff) >= 0.5:
                side = hh if diff > 0 else ha
                edges.append(f"{label} leans <span class='lean'>{side}</span> by {abs(diff):.1f}")
    if dk_total is not None and _v(g.gs_total) is not None and abs(g.gs_total - dk_total) >= 0.5:
        edges.append(f"GordStats leans <span class='lean'>"
                     f"{'Over' if g.gs_total > dk_total else 'Under'}</span> by "
                     f"{abs(g.gs_total - dk_total):.1f}")
    opinions = ("".join(f'<div class="det-line">{o}</div>' for o in ops) or
                '<div class="det-line">&mdash;</div>')
    if edges:
        opinions += ('<div class="det-line"><b>Against the number:</b> '
                     + "; ".join(edges) + ". The model has no edge on the book "
                     "historically &mdash; read these as disagreements, not tips.</div>")
    where = " &middot; ".join(escape(str(x)) for x in (getattr(g, "note", ""), g.venue, g.place)
                              if isinstance(x, str) and x)
    if where:
        opinions += f'<div class="det-line mv">{where}</div>'

    return (f'<tr class="det" data-for="g-{escape(str(g.game_id))}"><td colspan="{_COLS}">'
            '<div class="det-wrap">'
            f'<div class="det-block"><h4>Lines</h4>{books}{"".join(lines)}</div>'
            f'<div class="det-block"><h4>Opinions</h4>{opinions}</div>'
            "</div></td></tr>")


_HEAD = ('<thead><tr><th>Matchup</th><th>Kick (ET) &middot; TV &middot; Weather</th>'
         '<th>Lines &middot; GordStats pick</th><th>Season</th></tr></thead>')
_COLS = 4


def _hdr(text: str, idx: int, kind: str) -> str:
    return f'<tr class="hdr {kind}"><td colspan="{_COLS}">{text}</td></tr>'


def _week_table(games: pd.DataFrame, records: dict) -> str:
    """One table for the week: game rows in kickoff order, sectioned Live /
    Still to play / Final with a day header inside each - the same layout the
    page's script rebuilds from the rows' data attributes after every sort,
    filter or live update, so a reader without JS sees the build-time version
    of exactly the same thing."""
    games = games.reset_index(drop=True)
    sections = [(state, games[games["state"] == state])
                for state in ("in", "pre", "post")]
    sections = [(st, grp) for st, grp in sections if len(grp)]
    titles = {"in": "Live", "pre": "Still to play", "post": "Final"}
    rows = []
    for state, grp in sections:
        if len(sections) > 1:
            rows.append(_hdr(titles[state], 0, "sec"))
        for day, day_games in grp.groupby(grp["local"].dt.date, sort=True):
            rows.append(_hdr(pd.Timestamp(day).strftime("%A, %B %-d"), 0, "day"))
            rows.extend(_row(g, int(g.Index), records) for g in day_games.itertuples())
    return (f'<div class="table-scroll"><table class="cfb-sched">{_HEAD}'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def _week_view(games: pd.DataFrame, records: dict, picks: str = "") -> str:
    ranked = int((games["home_rank"].notna() | games["away_rank"].notna()).sum())
    return (picks + f'<p class="wk-note"><span class="wk-count">{len(games)} games</span>, '
            f'{ranked} with a ranked team.</p>' + _week_table(games, records))


# --------------------------------------------------------------------------- #
# Picks of the day
# --------------------------------------------------------------------------- #

def _sds() -> tuple:
    """(margin sd, total sd) from the backtest: the spread of this model's own
    errors, which is what turns a lean into a probability."""
    m = predict.margin_sd()
    try:
        t = float(json.loads((DATA_DIR / "model_validation.json").read_text())
                  ["overall"].get("total_rmse") or 0) or None
    except (OSError, ValueError, KeyError):
        t = None
    return m, (t or m)


def _ml_text(ml) -> str:
    return f"{int(ml):+d}" if ml is not None else ""


PICKS_DIR = DATA_DIR / "picks" / str(SEASON)


def _day_games(df: pd.DataFrame, current: int) -> tuple:
    """The day's FBS-v-FBS games with a book spread and a model line, whatever
    their state: today's if the day has games, else the next day that does.
    (frame, date).

    FBS against FBS only, as the predictions page scores it: the model rates
    every FCS opponent as one generic FCS team, so a Montana State or a UC
    Davis reads as a 30-point mismatch it never is, and those games would
    fill every slot here with the model's blind spot.
    """
    fbs = df["home_conf"].astype(str).ne("") & df["away_conf"].astype(str).ne("")
    lined = df[(df["week"] == current) & fbs & df["dk_spread"].notna() & df["gs_margin"].notna()]
    if lined.empty:
        return lined, None
    today = datetime.now(LEAGUE_TZ).date()
    days = sorted(set(lined["local"].dt.date))
    day = next((d for d in days if d >= today), days[0])
    return lined[lined["local"].dt.date == day], day


def _compute_picks(slate: pd.DataFrame) -> dict:
    """The underdog and the parlay from a slate, as plain data - what gets
    frozen. Every leg carries what grading it later needs."""
    m_sd, t_sd = _sds()
    from scipy.stats import norm

    def kick(g):
        if not _time_known(g):
            return f"{g.local:%a} TBD"
        return f"{g.local:%a %-I:%M%p}".replace("AM", "a").replace("PM", "p")

    out = {"underdog": None, "legs": []}
    dog_best = None
    for g in slate.itertuples():
        spread, wp = float(g.dk_spread), _v(g.gs_wp)
        if wp is None or abs(spread) <= 0.25:
            continue
        home_dog = spread > 0
        p = wp if home_dog else 1 - wp
        book = _devig(_v(g.ml_home), _v(g.ml_away))
        book_p = (book if home_dog else 1 - book) if book is not None else None
        ml = _v(g.ml_home) if home_dog else _v(g.ml_away)
        if dog_best is None or p > dog_best["p"]:
            dog_best = {"game_id": str(g.game_id), "side": "home" if home_dog else "away",
                        "team": str(g.home if home_dog else g.away),
                        "opp": str(g.away if home_dog else g.home),
                        "p": round(p, 4), "book_p": round(book_p, 4) if book_p is not None else None,
                        "ml": ml, "line": abs(spread), "kick": kick(g)}
    out["underdog"] = dog_best

    legs = []
    for g in slate.itertuples():
        margin, spread = float(g.gs_margin), float(g.dk_spread)
        cands = []
        edge = margin - (-spread)
        if abs(edge) > 0.25:
            home_side = edge > 0
            line = spread if home_side else -spread
            cands.append({"kind": "spread", "side": "home" if home_side else "away",
                          "line": line, "p": float(norm.cdf(abs(edge) / m_sd)), "book": 0.5,
                          "text": f"{g.home if home_side else g.away} {line:+.1f}"})
        total, gs_total = _v(g.dk_total), _v(g.gs_total)
        if total is not None and gs_total is not None and abs(gs_total - total) > 0.25:
            over = gs_total > total
            cands.append({"kind": "total", "over": over, "total": total,
                          "p": float(norm.cdf(abs(gs_total - total) / t_sd)), "book": 0.5,
                          "text": f"{'Over' if over else 'Under'} {total:.1f}"})
        wp = _v(g.gs_wp)
        if wp is not None:
            home_side = wp >= 0.5
            p = wp if home_side else 1 - wp
            ml = _v(g.ml_home) if home_side else _v(g.ml_away)
            book = _devig(_v(g.ml_home), _v(g.ml_away))
            book_p = (book if home_side else 1 - book) if book is not None else None
            if ml is not None and book_p is not None and book_p < ML_CAP:
                cands.append({"kind": "ml", "side": "home" if home_side else "away",
                              "p": p, "book": book_p,
                              "text": f"{g.home if home_side else g.away} ML {_ml_text(ml)}"})
        if cands:
            best = max(cands, key=lambda c: c["p"])
            best.update({"game_id": str(g.game_id), "p": round(best["p"], 4),
                         "book": round(best["book"], 4),
                         "game": f"{g.away_abbr or g.away} at {g.home_abbr or g.home} · {kick(g)}"})
            legs.append(best)
    legs.sort(key=lambda c: -c["p"])
    out["legs"] = legs[:PARLAY_LEGS]
    return out


def _picks_for_day(df: pd.DataFrame, current: int) -> tuple:
    """(picks, day, locked_at): the day's picks, set once and kept.

    The first build ON the day, with every game still to come, computes the
    picks and writes them to PICKS_DIR; every build after that reads the
    file back, so the cards stop moving the moment the day's first game
    kicks off. A day found already under way with nothing on file (the very
    first deploy) is computed from what is still pending and frozen as is.

    A later day is a preview - computed on every build, never written, and
    locked_at is None. Its lines and injury news are still moving, and once
    Saturday's last game kicked off the schedule moved on to next week, so
    freezing on first sight locked the following Thursday to Saturday a
    week early (2026-09-26's picks were set on Sep 19, from 15 games).
    """
    slate, day = _day_games(df, current)
    if slate.empty:
        return None, None, None
    path = PICKS_DIR / f"{day:%Y-%m-%d}.json"
    if path.exists():
        try:
            saved = json.loads(path.read_text())
            return saved["picks"], day, saved.get("locked_at")
        except (ValueError, KeyError):
            pass
    pending = slate[slate["state"] == "pre"]
    if pending.empty:
        return None, day, None
    picks = _compute_picks(pending)
    if day > datetime.now(LEAGUE_TZ).date():
        return picks, day, None
    locked_at = datetime.now(LEAGUE_TZ).strftime("%a %b %-d, %-I:%M %p")
    PICKS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"day": f"{day:%Y-%m-%d}", "locked_at": locked_at,
                                "games": int(len(pending)), "picks": picks}, indent=1))
    return picks, day, locked_at


def _grade(leg: dict, g) -> bool | None:
    """True/False once the game is final, None while it is not."""
    if g is None or g.state != "post" or _v(g.home_score) is None or _v(g.away_score) is None:
        return None
    hs, as_ = float(g.home_score), float(g.away_score)
    if leg["kind"] == "spread":
        margin = (hs - as_) if leg["side"] == "home" else (as_ - hs)
        return None if margin + leg["line"] == 0 else margin + leg["line"] > 0
    if leg["kind"] == "total":
        if hs + as_ == leg["total"]:
            return None
        return (hs + as_ > leg["total"]) == bool(leg["over"])
    if leg["kind"] == "ml":
        return (hs > as_) if leg["side"] == "home" else (as_ > hs)
    return None


def _picks(df: pd.DataFrame, current: int) -> str:
    """GordStats' underdog and parlay of the day: set before the day's first
    kickoff and locked, then graded as the games finish."""
    picks, day, locked_at = _picks_for_day(df, current)
    if not picks or not (picks.get("underdog") or picks.get("legs")):
        return ""
    by_id = {str(g.game_id): g for g in df.itertuples()}

    def mark(ok) -> str:
        if ok is None:
            return ""
        return (' <span class="gp-hit">&#10003;</span>' if ok
                else ' <span class="gp-miss">&#10007;</span>')

    dog_html = ""
    line = []                     # the folded line: each pick, its chance, its grade
    d = picks.get("underdog")
    if d:
        g = by_id.get(d["game_id"])
        where = "at home to" if d["side"] == "home" else "at"
        edge = (f"the book said {d['book_p']:.0%}" if d.get("book_p") is not None
                else f"the book had them at +{d['line']:.1f}")
        # The verdict only; how the chance is read against the book is in the
        # legend with the rest of the picks' small print.
        verdict = ("GordStats' pick to win outright." if d["p"] >= 0.5
                   else "The dog GordStats liked most, short of picking the upset.")
        won = _grade({"kind": "ml", "side": d["side"]}, g)
        ml_html = (f' <span class="gp-book">ML {_ml_text(d["ml"])}</span>'
                   if d.get("ml") is not None else "")
        dog_html = (
            '<div class="gs-pick"><div class="gp-label">Underdog of the day</div>'
            f'<div class="gp-main"><a href="#g-{escape(d["game_id"])}">{escape(d["team"])}'
            f' +{d["line"]:.1f}</a>{ml_html}{mark(won)}</div>'
            f'<div class="gp-sub">{where} {escape(d["opp"])} · {escape(d["kick"])}'
            f' · <span class="gp-p">{d["p"]:.0%}</span> to win, {edge}</div>'
            f"<div class='gp-note'>{verdict}</div></div>")
        line.append(f'{escape(d["team"])} +{d["line"]:.1f} '
                    f'<span class="gp-p">{d["p"]:.0%}</span>{mark(won)}')

    parlay_html = ""
    legs = picks.get("legs") or []
    if len(legs) >= 2:
        ours = float(np.prod([c["p"] for c in legs]))
        book = float(np.prod([c["book"] for c in legs]))
        grades = [_grade(c, by_id.get(c["game_id"])) for c in legs]
        items = "".join(
            f'<li><span><a href="#g-{escape(c["game_id"])}">{escape(c["text"])}</a>'
            f'<span class="gp-game">{escape(c["game"])}</span></span>'
            f'<span class="gp-p">{c["p"]:.0%}{mark(ok)}</span></li>'
            for c, ok in zip(legs, grades))
        state = ("missed" if any(ok is False for ok in grades)
                 else "hit" if all(ok is True for ok in grades) else "")
        parlay_html = (
            '<div class="gs-pick"><div class="gp-label">Parlay of the day'
            + (f' · <span class="gp-{state}">{state}</span>' if state else "") + "</div>"
            f'<div class="gp-main">{len(legs)} legs · <span class="gp-p">{ours:.0%}</span>'
            f' <span class="gp-book">the book implied {book:.0%}</span></div>'
            f'<ul class="gp-legs">{items}</ul></div>')
        line.append(f'Parlay <span class="gp-p">{ours:.0%}</span>'
                    + mark({"hit": True, "missed": False}.get(state)))

    if not (dog_html or parlay_html):
        return ""
    # When, not how: what locking means is in the legend.
    if locked_at:
        note = f"Locked {escape(locked_at)}"
    elif day > datetime.now(LEAGUE_TZ).date():
        note = f"A preview until {day:%A} morning"
    else:
        note = "Set before the first kickoff"
    # Folded to one line (2026-09-30 phone pass): the heading and two cards
    # stood 350-620px tall between the week buttons and the first game on a
    # 390px screen. The line is the picks themselves - who, how likely, and
    # the grade once the games are in; the cards, the book's view and when
    # they were locked open under it.
    return (f'<details class="gs-picks-fold"><summary class="gp-sum">'
            f'<b>{day:%a} picks</b> &middot; {" &middot; ".join(line)}</summary>'
            f'<p class="wk-note">{note}</p>'
            f'<div class="gs-picks">{dog_html}{parlay_html}</div></details>')


def _live_url(week: int) -> str:
    """The scores proxy's URL for one of this site's weeks (bowls included)."""
    q = espn.query(week)
    return f"/api/cfb-scores?week={q['week']}&dates={SEASON}&seasontype={q['seasontype']}"


def _current_week(df: pd.DataFrame) -> int:
    """The first week with a game in progress or still to kick off, else the
    last week. In progress counts: after Saturday's last kickoff the page used
    to move on to next week - default tab and live poll both - while the late
    games were still being played."""
    now = datetime.now(timezone.utc).isoformat()
    live = df["state"] == "in" if "state" in df else False
    pending = df[(df["date_utc"] >= now) | live]
    return int(pending["week"].min()) if len(pending) else int(df["week"].max())


_SORTS = [("kick", "Kickoff"), ("spread", "Closest spread"), ("bigspread", "Biggest spread"),
          ("total", "Highest total"), ("lowtotal", "Lowest total"),
          ("mq", "Matchup quality (ESPN)"), ("upset", "Upset chance"),
          ("homedog", "Biggest home underdog"), ("gap", "Strongest lean vs book"),
          ("wx", "Worst weather")]
_CHIPS = [("ranked", "Ranked"), ("confgame", "Conference games"),
          ("nonconf", "Non-conference"), ("p4", "Power 4"), ("homedog", "Home underdogs"),
          ("tossup", "Toss-ups"), ("lean", "Strong leans"), ("wx", "Bad weather"),
          ("upset", "Upset watch"), ("pending", "Still to play")]
_CONF_LEAD = ["ACC", "Big 12", "Big Ten", "SEC"]

_JS = """<script>
(function(){
"use strict";
var UPSET=%(upset)s,LIVE_URL=%(url)s,CURRENT=%(current)s,COLS=%(cols)s;
var weeks=document.getElementById('cfb-weeks');
var sortSel=document.getElementById('sc-sort');
var confSel=document.getElementById('sc-conf');
var search=document.getElementById('sc-search');
var chips=Array.prototype.slice.call(document.querySelectorAll('.sc-chips button[data-f]'));
var on={};
var current=CURRENT;
var timer=null;
var openGame=null,noScroll=false;     // #g=<espn id> opens that game's More panel

// Sort keys: attribute and direction. Rows lacking the attribute sink to the bottom.
var SORTS={spread:['spread',1],bigspread:['spread',-1],total:['total',-1],
  lowtotal:['total',1],mq:['mq',-1],upset:['upset',-1],homedog:['homedog',-1],
  gap:['gap',-1],wx:['wx',-1]};
var RANK={'in':0,pre:1,post:2};
var SEC={'in':'Live',pre:'Still to play',post:'Final'};

function num(row,key){var v=row.getAttribute('data-'+key);return v===null||v===''?null:+v;}

function passes(row){
  if(on.ranked&&row.getAttribute('data-ranked')!=='1')return false;
  if(on.confgame&&row.getAttribute('data-confgame')!=='1')return false;
  if(on.nonconf&&row.getAttribute('data-confgame')!=='0')return false;
  if(on.p4&&row.getAttribute('data-p4')!=='1')return false;
  if(on.homedog&&num(row,'homedog')===null)return false;
  if(on.tossup&&row.getAttribute('data-tossup')!=='1')return false;
  if(on.lean&&!((num(row,'gap')||0)>=3))return false;
  if(on.wx&&!((num(row,'wx')||0)>=2))return false;
  if(on.upset){var u=num(row,'upset');if(u===null||u<UPSET)return false;}
  if(on.pending&&row.getAttribute('data-final')==='1')return false;
  var c=confSel.value;
  if(c&&(row.getAttribute('data-confs')||'').split('|').indexOf(c)<0)return false;
  var q=(search.value||'').trim().toLowerCase();
  if(q&&(row.getAttribute('data-teams')||'').indexOf(q)<0)return false;
  return true;
}

function hdr(kind,text){
  var tr=document.createElement('tr');tr.className='hdr '+kind;
  var td=document.createElement('td');td.colSpan=COLS;td.textContent=text;
  tr.appendChild(td);return tr;
}

/* Rebuild one week from its rows: order (kickoff within Live / Still to play /
   Final, or the chosen sort), filters, then fresh section and day headers
   over whatever is left. The build-time headers are thrown away first. */
function layout(view){
  var tbody=view.querySelector('tbody');if(!tbody)return;
  Array.prototype.slice.call(tbody.querySelectorAll('tr.hdr')).forEach(function(h){
    h.parentNode.removeChild(h);});
  var all=Array.prototype.slice.call(tbody.rows),dets={};
  all.forEach(function(r){if(r.classList.contains('det'))dets[r.getAttribute('data-for')]=r;});
  var rows=all.filter(function(r){return r.classList.contains('g');});
  var spec=SORTS[sortSel.value];
  rows.sort(function(a,b){
    if(spec){
      var av=num(a,spec[0]),bv=num(b,spec[0]);
      if(av===null&&bv!==null)return 1;
      if(bv===null&&av!==null)return -1;
      if(av!==null&&bv!==null&&av!==bv)return (av-bv)*spec[1];
    }else{
      var ar=RANK[a.getAttribute('data-state')],br=RANK[b.getAttribute('data-state')];
      if(ar===undefined)ar=1;if(br===undefined)br=1;
      if(ar!==br)return ar-br;
      var ak=a.getAttribute('data-kick')||'',bk=b.getAttribute('data-kick')||'';
      if(ak!==bk)return ak<bk?-1:1;
    }
    return (+a.getAttribute('data-i'))-(+b.getAttribute('data-i'));
  });
  var shown=0,total=0,states={};
  rows.forEach(function(r){
    total++;var ok=passes(r);r.classList.toggle('hide',!ok);
    if(ok){shown++;states[r.getAttribute('data-state')||'pre']=1;}
  });
  var split=Object.keys(states).length>1,lastState=null,lastDay=null;
  rows.forEach(function(r){
    if(!spec&&!r.classList.contains('hide')){
      var st=r.getAttribute('data-state')||'pre',day=r.getAttribute('data-day');
      if(split&&st!==lastState){tbody.appendChild(hdr('sec',SEC[st]||st));lastDay=null;}
      if(day!==lastDay)tbody.appendChild(hdr('day',day));
      lastState=st;lastDay=day;
    }
    tbody.appendChild(r);
    var d=dets[r.id];
    if(d){tbody.appendChild(d);
      d.classList.toggle('show',!r.classList.contains('hide')&&r.classList.contains('open'));}
  });
  view.querySelector('table').classList.toggle('sorted',!!spec);
  var count=view.querySelector('.wk-count');
  if(count)count.textContent=(shown===total?total+' games':shown+' of '+total+' games');
}

function applyAll(){
  Array.prototype.forEach.call(weeks.querySelectorAll('.wk-view'),layout);
  markFilt();
  writeHash();
}

/* The phone's Filters button, which folds everything but the week row out of
   the pinned bar. Shut, its label counts what is cutting the list down - the
   chips, a conference, a search - since the controls that would show it are
   out of sight. The sort is not counted: it drops nothing. */
var filt=document.getElementById('sc-filt');
function markFilt(){
  if(!filt)return;
  var n=Object.keys(on).filter(function(k){return on[k];}).length
    +(confSel.value?1:0)+(search.value.trim()?1:0);
  filt.textContent='Filters'+(n?' \\u00b7 '+n:'');
  filt.classList.toggle('sc-some',!!n);
}
if(filt)filt.addEventListener('click',function(){
  var pin=filt.closest('.sc-pin'),open=!pin.classList.contains('sc-open');
  pin.classList.toggle('sc-open',open);
  filt.setAttribute('aria-expanded',open?'true':'false');
});

function writeHash(){
  var parts=['w='+current];
  if(sortSel.value!=='kick')parts.push('sort='+sortSel.value);
  var f=Object.keys(on).filter(function(k){return on[k];});
  if(f.length)parts.push('f='+f.join(','));
  if(confSel.value)parts.push('conf='+encodeURIComponent(confSel.value));
  if(search.value.trim())parts.push('q='+encodeURIComponent(search.value.trim()));
  history.replaceState(null,'','#'+parts.join('&'));
}

function readHash(){
  var h=location.hash.replace(/^#/,'');if(!h)return;
  h.split('&').forEach(function(kv){
    var i=kv.indexOf('='),k=i<0?kv:kv.slice(0,i),v=i<0?'':decodeURIComponent(kv.slice(i+1));
    if(k==='w'&&document.getElementById('wk-view-'+v))current=+v;
    else if(k==='sort'&&SORTS[v])sortSel.value=v;
    else if(k==='f')v.split(',').forEach(function(x){on[x]=true;});
    else if(k==='conf'){for(var j=0;j<confSel.options.length;j++)
      if(confSel.options[j].value===v)confSel.value=v;}
    else if(k==='q')search.value=v;
    else if(k==='g')openGame=v;
    else if(k==='noscroll')noScroll=true;   // screenshot checks; a headless capture goes blank once scrolled
  });
  chips.forEach(function(b){b.classList.toggle('active',!!on[b.getAttribute('data-f')]);});
}

/* Only the current week's rows are in the page; the rest are fetched once,
   on the first click. Returns a promise so a deep link into another week can
   wait for its row to exist. */
function loadWeek(view){
  var src=view.getAttribute('data-src');
  if(!src) return Promise.resolve(view);          // already here
  if(view._loading) return view._loading;         // a second click while in flight
  view.setAttribute('data-was',src);      // so it can be dropped and refetched
  view.removeAttribute('data-src');
  // Bare path first, `.html` if that is not a thing on this host.
  view._loading=fetch(src).then(function(r){
    if(r.ok) return r.text();
    return fetch(src+'.html').then(function(r2){
      if(!r2.ok) throw new Error(r2.status);
      return r2.text();
    });
  }).then(function(html){
    view.innerHTML=html;
    // Rows that arrive after boot have never been through either of these:
    // the sort/filter that the controls are currently set to, and the star
    // painting that turns a reader's favourites on.
    layout(view);
    if(window.GSFavorites&&window.GSFavorites.repaint)window.GSFavorites.repaint();
    return view;
  }).catch(function(){
    view.innerHTML='<p class="sc-intro">That week could not be loaded. '
      +'Check your connection and try again.</p>';
    view.setAttribute('data-src',src);           // let a later click retry
    view._loading=null;
    return view;
  });
  return view._loading;
}

/* How many weeks' rows to keep. Loading one week is ~12,000 nodes, so a
   reader working through the season would arrive back at the 125,000 this
   change exists to avoid. Three is enough to flick between neighbouring
   weeks without refetching, and an evicted week costs one small request to
   come back. The current week is never evicted. */
var KEEP_WEEKS=3, shownOrder=[];

function evict(){
  while(shownOrder.length>KEEP_WEEKS){
    var old=shownOrder.shift();
    if(old===current) continue;                 // never the one being read
    var v=document.getElementById('wk-view-'+old);
    if(!v||!v.getAttribute('data-was')) continue;
    v.innerHTML='';
    v.setAttribute('data-src',v.getAttribute('data-was'));
    v._loading=null;
  }
}

window.show_wk=function(w){
  current=+w;
  var view=document.getElementById('wk-view-'+w);
  Array.prototype.forEach.call(document.querySelectorAll('.wk-btn'),function(b){b.classList.remove('active');});
  var tab=document.getElementById('wk-tab-'+w);if(tab)tab.classList.add('active');
  // On a phone the week row scrolls sideways and shows five or six weeks, so
  // by October the current one opened out of sight. Centre it in the row -
  // the row only, never the page.
  if(tab){var sw=tab.parentNode,a=tab.getBoundingClientRect(),b=sw.getBoundingClientRect();
    if(sw.scrollWidth>sw.clientWidth)sw.scrollLeft+=a.left-b.left-(b.width-a.width)/2;}
  writeHash();
  if(!view) return Promise.resolve(null);
  if(view.getAttribute('data-src'))view.innerHTML='<p class="sc-intro">Loading week '+w+'\u2026</p>';
  return loadWeek(view).then(function(){
    Array.prototype.forEach.call(document.querySelectorAll('.wk-view'),function(e){e.style.display='none';});
    view.style.display='';
    var at=shownOrder.indexOf(+w);
    if(at>=0) shownOrder.splice(at,1);
    shownOrder.push(+w);                  // most recently read, last
    evict();
    return view;
  });
};

/* ---- live scores for the current week ---- */
function apply(ev){
  var row=document.getElementById('g-'+ev.id);if(!row)return null;
  var comp=(ev.competitions||[])[0]||{};
  var st=ev.status||comp.status||{};
  var state=(st.type||{}).state||'pre';
  var sit=comp.situation||{};
  (comp.competitors||[]).forEach(function(c){
    var side=row.querySelector('.sc-row[data-tid="'+c.team.id+'"]');if(!side)return;
    if(state!=='pre'){
      var pts=side.querySelector('.sc-pts');
      if(!pts){pts=document.createElement('span');pts.className='sc-pts';side.appendChild(pts);}
      pts.textContent=c.score;
    }
    var recs=c.records||[];
    for(var i=0;i<recs.length;i++){
      if(recs[i].type==='total'&&recs[i].summary){
        var el=side.querySelector('.sc-rec');
        if(!el){el=document.createElement('span');el.className='sc-rec';
          side.querySelector('.sc-name').appendChild(el);}
        el.textContent=recs[i].summary;break;
      }
    }
    side.classList.toggle('sc-ball',state==='in'&&sit.possession===c.team.id);
  });
  var when=row.querySelector('.t-when');
  if(when&&state!=='pre'){
    when.textContent=(st.type||{}).shortDetail||(state==='post'?'Final':'Live');
    when.classList.toggle('t-live',state==='in');
  }
  if(state==='post'){
    var cs=comp.competitors||[];
    if(cs.length===2&&+cs[0].score!==+cs[1].score){
      var w=+cs[0].score>+cs[1].score?cs[0]:cs[1];
      Array.prototype.forEach.call(row.querySelectorAll('.sc-row'),function(sd){
        sd.classList.toggle('sc-win',sd.getAttribute('data-tid')===String(w.team.id));});
    }
    row.setAttribute('data-final','1');
  }
  if(state==='in'){
    row.querySelector('.sc-sit').textContent=
      [sit.downDistanceText,sit.possessionText].filter(Boolean).join(' \\u00b7 ');
    row.querySelector('.sc-play').textContent=(sit.lastPlay||{}).text||'';
  }
  var changed=row.getAttribute('data-state')!==state;
  row.setAttribute('data-state',state);
  return {state:state,kick:ev.date,changed:changed};
}

function poll(){
  fetch(LIVE_URL).then(function(r){return r.json();}).then(function(data){
    var live=false,next=null,now=Date.now(),changed=false;
    (data.events||[]).forEach(function(ev){
      var r=apply(ev);if(!r)return;
      if(r.changed)changed=true;
      if(r.state==='in')live=true;
      else if(r.state==='pre'){
        var t=new Date(r.kick).getTime();
        if(t>now&&(next===null||t<next))next=t;
      }
    });
    if(changed){var v=document.getElementById('wk-view-'+CURRENT);if(v)layout(v);}
    // 30s while anything is live; 90s in the half hour before a kickoff;
    // otherwise sleep until just before the next one (checking at most
    // every 30 min in case the slate changes). Nothing left: stop.
    var delay;
    if(live)delay=30e3;
    else if(next!==null&&next-now<45*60e3)delay=90e3;
    else if(next!==null)delay=Math.min(next-now-40*60e3,30*60e3);
    else return;
    timer=setTimeout(poll,Math.max(delay,30e3));
  }).catch(function(){timer=setTimeout(poll,120e3);});
}

chips.forEach(function(b){
  b.addEventListener('click',function(){
    var k=b.getAttribute('data-f');on[k]=!on[k];
    // Conference and non-conference cannot both be on; the newer one wins.
    if(on[k]&&k==='confgame')on.nonconf=false;
    if(on[k]&&k==='nonconf')on.confgame=false;
    chips.forEach(function(c){c.classList.toggle('active',!!on[c.getAttribute('data-f')]);});
    applyAll();
  });
});
document.getElementById('sc-clear').addEventListener('click',function(){
  on={};chips.forEach(function(c){c.classList.remove('active');});
  sortSel.value='kick';confSel.value='';search.value='';applyAll();
});
sortSel.addEventListener('change',applyAll);
confSel.addEventListener('change',applyAll);
search.addEventListener('input',applyAll);
function setOpen(row,open){
  row.classList.toggle('open',open);
  var btn=row.querySelector('.det-btn');
  if(btn){btn.setAttribute('aria-expanded',open?'true':'false');
    btn.innerHTML=open?'Less \u25b4':'More \u25be';}
  var d=row.parentNode.querySelector('tr.det[data-for="'+row.id+'"]');
  if(d)d.classList.toggle('show',open);
}
document.addEventListener('click',function(ev){
  var btn=ev.target.closest('.det-btn');if(!btn)return;
  var row=btn.closest('tr.g');if(!row)return;
  setOpen(row,!row.classList.contains('open'));
});
document.addEventListener('visibilitychange',function(){
  if(!document.hidden){clearTimeout(timer);poll();}
});

readHash();
applyAll();
// A deep link can name a game in a week whose rows are not here yet, so the
// scroll waits for the fetch rather than looking for a row that cannot exist.
window.show_wk(current).then(function(){
  if(!openGame)return;
  var row=document.getElementById('g-'+openGame);
  if(!row)return;
  setOpen(row,true);
  if(!noScroll)row.scrollIntoView({block:'start'});
});
poll();
})();
</script>"""


def _controls(confs: dict) -> str:
    names = set(confs.values())
    ordered = [c for c in _CONF_LEAD if c in names] + sorted(names - set(_CONF_LEAD))
    conf_opts = '<option value="">All confs</option>' + "".join(
        f'<option value="{escape(c)}">{escape(c)}</option>' for c in ordered)
    sort_opts = "".join(f'<option value="{k}">{v}</option>' for k, v in _SORTS)
    chips = "".join(f'<button type="button" data-f="{k}">{v}</button>' for k, v in _CHIPS)
    return (
        '<div class="sc-controls">'
        '<span class="lbl">Sort</span>'
        f'<select id="sc-sort" class="sc-select" aria-label="Sort games">{sort_opts}</select>'
        f'<select id="sc-conf" class="sc-select" aria-label="Conference">{conf_opts}</select>'
        '<input id="sc-search" class="sc-search" type="search" placeholder="Team&hellip;" '
        'aria-label="Find a team">'
        "</div>"
        f'<div class="sc-chips"><span class="lbl">Show</span>{chips}'
        '<button type="button" id="sc-clear" class="clear">Reset</button></div>')


def _switcher(week_ids: list[int], current: int, views: dict[int, str],
              controls: str = "") -> str:
    """The week tabs, with only the current week's rows in the page.

    Every week used to be rendered here and all but one hidden with
    `display:none`. That is 15 weeks of a season in the DOM to show one of
    them: 4.2 MB and 125,000 nodes, which a phone must parse and hold whatever
    it ends up painting. The rest are fetched on the first click instead - see
    `show_wk` - so the page arrives at about a fifteenth of the size and the
    switch still feels like a switch.
    """
    buttons = "".join(
        f'<button class="wk-btn{" active" if w == current else ""}" '
        f"onclick=\"show_wk('{w}')\" id=\"wk-tab-{w}\">"
        f"{espn.POSTSEASON_LABEL if w == espn.POSTSEASON_WEEK else w}</button>"
        for w in week_ids)
    divs = "".join(
        f'<div id="wk-view-{w}" class="wk-view"'
        + ("" if w == current
           else f" style='display:none' data-src='{WEEK_URL % w}'")
        + f">{views[w] if w == current else ''}</div>"
        for w in week_ids)
    # The controls sit in a fold a phone keeps shut behind the Filters button;
    # on a desktop the button is hidden and the fold is simply open.
    fold = (f'<div class="sc-fold" id="sc-fold">{controls}</div>'
            '<div class="sc-weekrow"><button type="button" class="sc-filt" id="sc-filt" '
            'aria-expanded="false" aria-controls="sc-fold">Filters</button>'
            if controls else '<div class="sc-weekrow">')
    return ('<div class="pin-bar sc-pin">' + fold
            + f'<div class="view-switch"><span class="switch-label">Week:</span>{buttons}</div>'
            f'</div></div><div id="cfb-weeks">{divs}</div>')


#: Where a week's rows live once they are not all in the page.
#
#: Requested without the extension, because Cloudflare Pages canonicalises
#: `/x.html` to `/x` with a 308 and a redirect is a whole round trip on the
#: connection this page is most often read over. The file on disk keeps its
#: `.html` - that is what Pages serves the bare path from - and `show_wk`
#: falls back to it if the bare path ever 404s, so this does not quietly
#: depend on one host's URL habits.
WEEK_URL = "/cfb/schedule/week-%s"
WEEK_FILE = "week-%s.html"


def build() -> tuple:
    """(page html, {week: its rows}) - the fragments are written beside it."""
    df = _frame()
    week_ids = sorted(int(w) for w in df["week"].unique())
    current = _current_week(df)
    records = _records(current)
    picks = _picks(df, current)
    views = {int(w): _week_view(grp.sort_values("local"), records if int(w) == current else {},
                                picks if int(w) == current else "")
             for w, grp in df.groupby("week")}
    built = datetime.now(LEAGUE_TZ).strftime("%b %-d, %-I:%M %p %Z")
    # One short sentence. This was 110 words - most of the first screen on a
    # phone - and then 30, listing what every card visibly shows; the rest,
    # the build time included, is in the folded legend below it.
    intro = (f'<p class="sc-intro">Every FBS game of {SEASON}: live scores, the '
             "<b>GordStats</b> pick and the <b>DraftKings</b> line.</p>")
    legend = _LEGEND.replace("{built}", built)
    # Scoped through tbody, not just the table: this page's own stripe rule is
    # `table.cfb-sched tbody tr.g:nth-child(even) td`, and a selector one
    # element shorter loses to it on every second row. Emitted after _CSS so a
    # tie in specificity goes to the highlight.
    html = (_CSS + favorites.table_css("table.cfb-sched tbody") + _NOSCRIPT + intro + legend
            + _switcher(week_ids, current, views, controls=_controls(espn.conferences()))
            + _JS % {"upset": json.dumps(UPSET_WATCH), "current": current, "cols": _COLS,
                     "url": json.dumps(_live_url(current))})
    return html, {w: v for w, v in views.items() if w != current}


def body() -> str:
    return build()[0]


def generate():
    html, fragments = build()
    out = WEB_DIR / "schedule"
    write_page(out / "index.html", f"CFB Schedule & Scores {SEASON}", html)
    # Plain fragments, no front matter: Jekyll copies a file it cannot parse as
    # a page straight through, which is what these want to be.
    for week, view in fragments.items():
        (out / (WEEK_FILE % week)).write_text(view, encoding="utf-8")
    print(f"  {len(fragments)} weeks written beside it, fetched on demand")


if __name__ == "__main__":
    generate()
