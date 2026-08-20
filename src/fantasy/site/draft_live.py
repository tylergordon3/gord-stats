"""
Live draft board for the upcoming draft (docs/fantasy/live/).

Every other page in this section is a report on a draft that already happened.
This one is the draft happening: it watches Sleeper's public draft API from the
reader's own browser and redraws the board as picks land.

Nothing here polls on the Pi. Sleeper serves `access-control-allow-origin: *`,
so the page can call the API directly, which is the only arrangement that keeps
up with a draft — a pick every thirty seconds against a rebuild that runs every
six hours and takes minutes to publish would have shown a board rounds stale. The build's
only job is to bake in the ADP board (fantasy.league.adp_board) so each pick can
be graded as a value or a reach the moment it is made, and so the sidebar knows
who is still on the table. Everything else arrives at read time:

    /draft/{id}            status, start_time, draft_order, pick_timer, rounds
    /draft/{id}/picks      every pick, each carrying its player's name and team
    /league/{id}/users     display names, joined to our owner names by roster_id

Two details worth knowing before editing:

  * Sleeper's CDN sends `s-maxage=86400` on the picks feed, so a plain poll can
    serve a board that is hours old. Every request adds a `t=` cache-buster,
    which is what makes the poll actually live (see `fresh` in the page script).
  * The clock comes from Sleeper's `start_time`, not from _data/countdowns.yml.
    The draft's date is still being moved around, and the point of reading it
    from the API is that the page follows it without a rebuild.

    python -m fantasy.site.draft_live      # writes docs/fantasy/live/index.html
"""
import json

import pandas as pd
import requests

from fantasy import paths
from fantasy.config import (
    LEAGUE_TEAMS, LEAGUE_TZ, ROSTER_NAMES, UPCOMING_DRAFT_ID, UPCOMING_SEASON,
    UPCOMING_YEAR,
)
from fantasy.league.adp_board import board, last_updated
from fantasy.site import layout
from gordstats.frontmatter import add_front_matter

OUTPUT = paths.WEB_DRAFT_LIVE
SLEEPER_API = "https://api.sleeper.app/v1"
_TIMEOUT = 20

# Board columns baked into the page, in the order the page script reads them.
# Arrays rather than objects: 300-odd players ship on every page load, and the
# keys would be most of the bytes.
_FIELDS = ["player", "pos", "team", "bye", "Ovr", "Avg", "Pick", "PosRk"]

# Positions the Best Available filter offers. The ADP board drops kickers and
# defenses (adp_board.STREAMER_POS), so they are not chips here either — they
# still appear on the grid when somebody spends a pick on one.
POSITIONS = ["QB", "RB", "WR", "TE"]

# How far a pick has to sit from its board rank before the cell is tinted. A
# round is 10 picks in this league, so half a round is noise and a round and a
# half is somebody making a decision.
NUDGE = 5
SWING = 15


def _num(v):
    """JSON-safe number: NaN and NaT become null."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, str):
        return v
    return None if pd.isna(v) else (int(v) if float(v).is_integer() else round(float(v), 1))


def adp_data(year=UPCOMING_YEAR) -> tuple[dict, list]:
    """(rows keyed by the board's merge_name, draft order by board rank).

    The key is adp_board's own join key — a normalized name, or "dst" + team for
    a defense — which the page script rebuilds from each pick's metadata. Sleeper
    and FantasyPros disagree about punctuation and suffixes often enough
    (A.J. Brown, Marvin Harrison Jr.) that matching on the raw name would have
    quietly failed on exactly the players the board is consulted about.
    """
    df = board(year)
    df = df.sort_values("Ovr")
    rows, order = {}, []
    for row in df.itertuples(index=False):
        key = getattr(row, "merge_name")
        if not key:
            continue
        rows[key] = [_num(getattr(row, f, None)) for f in _FIELDS]
        order.append(key)
    return rows, order


def _draft_meta(draft_id: str = UPCOMING_DRAFT_ID) -> dict:
    """The draft object, or {} if Sleeper is unreachable at build time.

    Only used to seed the page: the script refetches it on load and every poll
    after that. A failed build-time fetch costs a countdown that starts blank
    for one second, not a broken page.
    """
    try:
        r = requests.get(f"{SLEEPER_API}/draft/{draft_id}", timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json() or {}
    except Exception as exc:                      # network, JSON, HTTP - same answer
        print(f"  ! could not read draft {draft_id} at build time ({exc})")
        return {}


def _countdown(meta: dict) -> str:
    """The pre-draft clock, seeded from Sleeper and re-pointed by the script.

    Same markup and classes as _includes/countdown.html so it inherits the
    site's card styling and is driven by the shared assets/js/countdown.js.
    It cannot use the include itself: that reads _data/countdowns.yml, and the
    whole point here is to follow whatever time the draft is set to on Sleeper.

    The target is written as an absolute instant (UTC), where the yml-driven
    cards are deliberately zoneless so they read "8:00 PM" everywhere. A
    countdown shows time remaining either way; anchoring it to the instant is
    what lets the script move it when Sleeper's start_time changes.
    """
    start = meta.get("start_time")
    target = title = ""
    if start:
        when = pd.Timestamp(start, unit="ms", tz="UTC")
        target = when.strftime("%Y-%m-%dT%H:%M:%SZ")
        title = when.tz_convert(LEAGUE_TZ).strftime("%A, %B %-d - %-I:%M %p %Z")
    units = "".join(
        f'<div class="countdown-unit"><div class="countdown-num" data-unit="{u}">--</div>'
        f'<div class="countdown-lbl">{label}</div></div>'
        for u, label in (("d", "Days"), ("h", "Hours"), ("m", "Minutes"), ("s", "Seconds")))
    return f"""<div class="countdown-card" id="ld-countdown" data-countdown
     data-target="{target}" data-expired="The draft is here. Good luck.">
  <p class="countdown-eyebrow">{UPCOMING_SEASON} DRAFT</p>
  <p class="countdown-title" id="ld-when">{title}</p>
  <div class="countdown-units">{units}</div>
  <p class="countdown-note">Draft time comes from Sleeper. If it moves there, this moves with it.</p>
</div>"""


# --------------------------------------------------------------------------- #
# Styling. Deliberately shares the ADP board's palette (.pos-tag, the slate
# greys, the same dark-mode pairs) so the two draft pages read as one section.
# --------------------------------------------------------------------------- #

_CSS = """<style>
.ld-bar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:12px 0;
  padding:10px 14px;border:1px solid #e5e7eb;border-radius:12px;background:#fff;
  box-shadow:0 2px 8px rgba(15,23,42,.05)}
.ld-pill{display:inline-block;padding:3px 12px;border-radius:999px;font-size:13px;
  font-weight:700;text-transform:uppercase;letter-spacing:.04em;background:#eef2f7;color:#334155}
.ld-pill.live{background:#1a7f4b;color:#fff}
.ld-pill.soon{background:#A34F0A;color:#fff}
.ld-pill.done{background:#334155;color:#fff}
.ld-pill.err{background:#b3382c;color:#fff}
.ld-onclock{font-size:15px;color:#0f172a}
.ld-onclock strong{font-size:17px}
.ld-timer{font-family:monospace;font-weight:700;font-size:16px;color:#334155}
.ld-timer.low{color:#b3382c}
.ld-meta{margin-left:auto;font-size:12px;color:#4a5a68;text-align:right}

/* The grid scrolls sideways on anything narrower than a laptop: ten columns of
   names do not fit a phone, and squeezing them to fit made the board unreadable
   at exactly the moment it is being read one-handed. The round column and the
   header row stay pinned so a cell never loses its address. */
.ld-wrap{overflow:auto;overscroll-behavior:contain;max-height:calc(100vh - 170px);
  border:1px solid #e5e7eb;border-radius:12px;background:#fff;
  box-shadow:0 2px 8px rgba(15,23,42,.05)}
table.ld-grid{border-collapse:separate;border-spacing:0;width:100%;font-size:13px}
table.ld-grid th{position:sticky;top:0;z-index:3;background:#eef2f7;color:#334155;
  padding:6px 8px;font-size:12px;text-transform:uppercase;letter-spacing:.03em;
  border-right:1px solid #e2e8f0;border-bottom:1px solid #e2e8f0;white-space:nowrap}
table.ld-grid th .ld-team{display:block;font-size:11px;font-weight:400;
  text-transform:none;letter-spacing:0;color:#5d6b7e;overflow:hidden;
  text-overflow:ellipsis;max-width:120px}
table.ld-grid th.ld-rd,table.ld-grid td.ld-rd{position:sticky;left:0;z-index:4;
  background:#eef2f7;color:#334155;text-align:center;font-weight:700;
  min-width:38px;box-shadow:2px 0 4px -2px rgba(0,0,0,.25)}
table.ld-grid td.ld-rd{z-index:2;font-size:12px}
table.ld-grid td{vertical-align:top;padding:5px 7px;min-width:118px;
  border-right:1px solid #eef2f7;border-bottom:1px solid #eef2f7;background:#fff;color:#0f172a}
.ld-pk{display:block;font-family:monospace;font-size:11px;color:#5d6b7e}
.ld-name{display:block;font-weight:600;line-height:1.25;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis;max-width:150px}
.ld-sub{display:block;margin-top:2px;font-size:11px;color:#4a5a68;white-space:nowrap}
.ld-sub .pos-tag{min-width:0;padding:0 5px;font-size:10px;vertical-align:1px}
/* Value / reach against the ADP board, in the ADP page's sense: the pick number
   minus the player's board rank, so + means he lasted longer than the market
   said he would. */
.ld-val{font-family:monospace;font-weight:700}
.ld-val.up{color:#1a7f4b}
.ld-val.down{color:#b3382c}
/* Qualified with the table, not written as a bare `td.ld-value`: the cell's
   own background above is `table.ld-grid td`, which outweighs a lone class and
   painted every tint back to white. */
table.ld-grid td.ld-value{background:#d8f0dd}
table.ld-grid td.ld-reach{background:#fadddd}
table.ld-grid td.ld-empty{background:#f8fafc}
table.ld-grid td.ld-onclock-cell{background:#fff7e8;box-shadow:inset 0 0 0 2px #A34F0A}
/* A pick that landed while you were looking at the board. Fades out on its own
   so the highlight always means "this is new", not "this was new at some point". */
@keyframes ld-flash{from{background:#ffe9b8}to{background:transparent}}
table.ld-grid td.ld-new{animation:ld-flash 6s ease-out}
@media (prefers-reduced-motion: reduce){
  table.ld-grid td.ld-new{animation:none;background:#ffe9b8}
}

.ld-avail{width:100%;border-collapse:separate;border-spacing:0;font-size:13px}
.ld-avail th{position:sticky;top:0;z-index:2;background:#eef2f7;color:#334155;
  padding:7px 9px;font-size:11px;text-transform:uppercase;letter-spacing:.03em;
  border-right:1px solid #e2e8f0;border-bottom:1px solid #e2e8f0;white-space:nowrap}
.ld-avail td{padding:5px 9px;border-right:1px solid #eef2f7;border-bottom:1px solid #eef2f7;
  background:#fff;color:#0f172a;white-space:nowrap;text-align:center}
.ld-avail td.name{text-align:left;font-weight:600}
.ld-avail tbody tr:nth-child(even) td{background:#f8fafc}
.ld-avail .ld-gone td{opacity:.45;text-decoration:line-through}

.ld-rosters{display:flex;flex-wrap:wrap;gap:12px;margin-top:10px}
.ld-team-card{flex:1 1 260px;min-width:0;border:1px solid #e5e7eb;border-radius:12px;
  overflow:hidden;background:#fff;box-shadow:0 2px 8px rgba(15,23,42,.05)}
.ld-team-head{padding:6px 10px;background:#eef2f7;color:#334155;font-size:13px;font-weight:700}
.ld-team-head .ld-need{float:right;font-weight:400;font-size:12px;color:#4a5a68}
.ld-team-card ol{margin:0;padding:6px 10px 8px 26px;font-size:13px;color:#0f172a}
.ld-team-card li{padding:1px 0;line-height:1.4}
.ld-team-card .ld-none{padding:10px;font-size:13px;color:#4a5a68}
.ld-note{font-size:13px;color:#4a5a68;margin:6px 0 0}
.ld-legend{font-size:13px;color:#4a5a68;margin:0 0 8px}
.ld-sw{display:inline-block;width:11px;height:11px;border-radius:3px;
  vertical-align:-1px;margin:0 2px}
.ld-sw.v{background:#d8f0dd;border:1px solid #9ed5b0}
.ld-sw.r{background:#fadddd;border:1px solid #e6a9a9}

@media (max-width:600px){
  .ld-bar{gap:6px;padding:8px 10px}
  .ld-meta{margin-left:0;text-align:left;flex:1 1 100%}
  .ld-wrap{max-height:72vh}
  table.ld-grid td{min-width:104px}
  .ld-name{max-width:104px}
  .ld-team-card{flex:1 1 100%}
  /* Same treatment the ADP board gives its name column: scrolled sideways on a
     phone, a row of numbers with no player attached to it is unreadable. */
  .ld-avail td.name,.ld-avail th:first-child{position:sticky;left:0;z-index:1;
    max-width:132px;overflow:hidden;text-overflow:ellipsis;background:#fff;
    box-shadow:2px 0 4px -2px rgba(0,0,0,.3)}
  .ld-avail th:first-child{z-index:3;background:#eef2f7}
  .ld-avail tbody tr:nth-child(even) td.name{background:#f8fafc}
}

@media (prefers-color-scheme: dark){
  .ld-bar{background:#1b2540;border-color:#2b3852}
  .ld-pill{background:#223052;color:#dde5ef}
  .ld-onclock{color:#dde5ef}
  .ld-timer{color:#dde5ef}
  .ld-meta,.ld-note,.ld-legend{color:#aab7c9}
  .ld-wrap{background:#16203a;border-color:#2b3852}
  table.ld-grid th,table.ld-grid th.ld-rd,table.ld-grid td.ld-rd{background:#223052;color:#dde5ef;
    border-color:#2b3852}
  table.ld-grid th .ld-team{color:#aab7c9}
  table.ld-grid td{background:#16203a;border-color:#2b3852;color:#dde5ef}
  table.ld-grid td.ld-empty{background:#1b2540}
  .ld-pk,.ld-sub{color:#aab7c9}
  /* The tints have to be re-mixed for dark rather than dimmed: the light greens
     and pinks above carry dark text, which vanishes on them here. */
  table.ld-grid td.ld-value{background:#123c2e}
  table.ld-grid td.ld-reach{background:#4a1d1d}
  table.ld-grid td.ld-onclock-cell{background:#3a2e12;box-shadow:inset 0 0 0 2px #d98324}
  .ld-val.up{color:#6ee7b7}
  .ld-val.down{color:#ff9b91}
  @keyframes ld-flash{from{background:#5a4a18}to{background:transparent}}
  .ld-avail th{background:#223052;color:#dde5ef;border-color:#2b3852}
  .ld-avail td{background:#16203a;border-color:#2b3852;color:#dde5ef}
  .ld-avail tbody tr:nth-child(even) td{background:#1b2540}
  /* The pinned column above paints itself opaque so rows cannot show through
     it, which means it needs the dark surface named here too. */
  @media (max-width:600px){
    .ld-avail td.name{background:#16203a}
    .ld-avail th:first-child{background:#223052}
    .ld-avail tbody tr:nth-child(even) td.name{background:#1b2540}
  }
  .ld-team-card{background:#1b2540;border-color:#2b3852}
  .ld-team-head{background:#223052;color:#dde5ef}
  .ld-team-head .ld-need{color:#aab7c9}
  .ld-team-card ol,.ld-team-card li{color:#dde5ef}
  .ld-team-card .ld-none{color:#aab7c9}
  .ld-sw.v{background:#123c2e;border-color:#1f6b4d}
  .ld-sw.r{background:#4a1d1d;border-color:#7d3232}
}
</style>"""


# --------------------------------------------------------------------------- #
# The page script. Plain ES5-ish vanilla JS, like the rest of the site: this is
# a static Jekyll build with no bundler and no JS dependencies.
# --------------------------------------------------------------------------- #

_SCRIPT = """<script>
(function () {
  "use strict";

  var CFG = window.LD_CONFIG;
  var API = "https://api.sleeper.app/v1";
  var params = new URLSearchParams(location.search);
  // ?draft=<id> points the board at any Sleeper draft. It is here so the page
  // can be rehearsed against a finished draft — last year's has 150 real picks
  // in the same shape — instead of being seen working for the first time live.
  var DRAFT_ID = params.get("draft") || CFG.draft_id;

  var POLL_LIVE = 5000;        // a pick can land every few seconds
  var POLL_SOON = 15000;       // draft is close but has not started
  var POLL_IDLE = 60000;       // days out, or already over
  var FLASH_MS = 6000;         // how long a new pick stays highlighted
  var AVAIL_ROWS = 75;         // rows rendered in Best Available

  var USERS_MAX_AGE = 300000;   // team names get changed mid-draft

  var state = {
    meta: null, picks: [], users: {}, usersFor: null, usersAt: 0,
    firstSeen: {},             // pick_no -> when we first saw it (drives the flash)
    seeded: false,             // has the first paint happened?
    at: 0, failures: 0, sig: "", filter: "ALL", query: ""
  };

  // ----------------------------------------------------------------- helpers
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c];
    });
  }

  function fresh(url) {
    // Sleeper's CDN holds these responses for a day (s-maxage=86400), so a
    // plain poll can serve a board that is hours stale. A unique query string
    // is a different cache key, which is what makes this actually live.
    var bust = url + (url.indexOf("?") < 0 ? "?" : "&") + "t=" + Date.now();
    return fetch(bust, {cache: "no-store"}).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }

  /** adp_board's join key: normalized name, or "dst" + team for a defense. */
  function normKey(name) {
    if (!name) return "";
    var t = name.normalize ? name.normalize("NFKD") : name;
    t = t.replace(/[\\u0300-\\u036f]/g, "").toLowerCase().trim();
    t = t.replace(/[.'`]/g, "");
    t = t.replace(/\\s+(jr|sr|ii|iii|iv|v)$/, "");
    return t.replace(/[^a-z0-9]/g, "");
  }

  function keyFor(md) {
    var pos = String(md.position || "").toUpperCase();
    if (pos === "DEF" || pos === "DST") return "dst" + String(md.team || "").toUpperCase();
    return normKey(((md.first_name || "") + " " + (md.last_name || "")).trim());
  }

  function nameOf(pick) {
    var md = pick.metadata || {};
    var name = ((md.first_name || "") + " " + (md.last_name || "")).trim();
    return name || ("Player " + pick.player_id);
  }

  function teamCount() {
    var s = (state.meta && state.meta.settings) || {};
    return s.teams || CFG.teams;
  }

  function roundCount() {
    var s = (state.meta && state.meta.settings) || {};
    return s.rounds || CFG.rounds;
  }

  function status() {
    return (state.meta && state.meta.status) || "pre_draft";
  }

  function isLive() {
    var s = status();
    return s === "drafting" || s === "paused";
  }

  /** Overall pick number of (round, slot) in a snake draft. */
  function pickNumber(round, slot, teams) {
    var base = (round - 1) * teams;
    return round % 2 ? base + slot : base + (teams - slot + 1);
  }

  function slotOf(pickNo, teams) {
    var round = Math.ceil(pickNo / teams), i = (pickNo - 1) % teams;
    return round % 2 ? i + 1 : teams - i;
  }

  /** One entry per draft slot: who picks there, under both names we have. */
  function slots() {
    var meta = state.meta || {};
    var s2r = meta.slot_to_roster_id || {};
    var order = meta.draft_order || {};
    var userAt = {};
    for (var uid in order) { if (order.hasOwnProperty(uid)) userAt[order[uid]] = uid; }

    var out = [], n = teamCount();
    for (var slot = 1; slot <= n; slot++) {
      var roster = s2r[slot] || s2r[String(slot)] || null;
      var user = state.users[userAt[slot]] || {};
      var team = (user.metadata && user.metadata.team_name) || "";
      out.push({
        slot: slot,
        roster: roster,
        // Our own name for the manager wins: the rest of the site calls him
        // Colin, not colincampbell2. Sleeper's handle is the fallback for a
        // roster the league config has not been told about yet.
        owner: (roster && CFG.roster_names[roster]) || user.display_name || ("Slot " + slot),
        team: team
      });
    }
    return out;
  }

  function slotFor(pickNo) {
    // Trust the pick's own slot when Sleeper gives us one: a draft with a
    // traded pick or a reversal round would not match the plain snake maths.
    var picked = state.picks[pickNo - 1];
    if (picked && picked.draft_slot) return picked.draft_slot;
    return slotOf(pickNo, teamCount());
  }

  // ------------------------------------------------------------------ render
  function pickLabel(no, round, teams) {
    var inRound = no - (round - 1) * teams;
    return round + "." + (inRound < 10 ? "0" : "") + inRound;
  }

  function valueTag(diff) {
    if (diff === null || Math.abs(diff) < CFG.nudge) return "";
    var cls = diff > 0 ? "up" : "down";
    return " <span class='ld-val " + cls + "'>" + (diff > 0 ? "+" : "") + diff + "</span>";
  }

  function cellHTML(pick, no, round, teams, next) {
    var label = pickLabel(no, round, teams);
    if (!pick) {
      var onClock = (no === next && isLive());
      return "<td class='" + (onClock ? "ld-onclock-cell" : "ld-empty") + "'>" +
        "<span class='ld-pk'>" + label + "</span>" +
        (onClock ? "<span class='ld-name'>On the clock</span>" : "") + "</td>";
    }
    var md = pick.metadata || {};
    var pos = String(md.position || "").toUpperCase();
    var adp = CFG.adp[keyFor(md)];
    // The ADP page's convention: pick number minus board rank, so + means the
    // player lasted longer than the market said he would.
    var diff = (adp && adp[4]) ? no - adp[4] : null;
    var tint = "";
    if (diff !== null) tint = diff >= CFG.swing ? " ld-value" : (diff <= -CFG.swing ? " ld-reach" : "");
    var isNew = state.seeded && (Date.now() - (state.firstSeen[no] || 0)) < FLASH_MS;
    return "<td class='" + tint + (isNew ? " ld-new" : "") + "'>" +
      "<span class='ld-pk'>" + label + "</span>" +
      "<span class='ld-name'>" + esc(nameOf(pick)) + "</span>" +
      "<span class='ld-sub'><span class='pos-tag pos-" + esc(pos) + "'>" + esc(pos) + "</span> " +
      esc(md.team || "FA") + valueTag(diff) + "</span></td>";
  }

  function renderGrid() {
    var teams = slots(), n = teams.length, rounds = roundCount();
    var byPick = {};
    state.picks.forEach(function (p) { byPick[p.pick_no] = p; });
    var next = state.picks.length + 1;

    var html = "<thead><tr><th class='ld-rd'>Rd</th>";
    teams.forEach(function (t) {
      html += "<th>" + esc(t.owner) +
        (t.team ? "<span class='ld-team'>" + esc(t.team) + "</span>" : "") + "</th>";
    });
    html += "</tr></thead><tbody>";
    for (var r = 1; r <= rounds; r++) {
      html += "<tr><td class='ld-rd'>" + r + "</td>";
      for (var slot = 1; slot <= n; slot++) {
        var no = pickNumber(r, slot, n);
        html += cellHTML(byPick[no], no, r, n, next);
      }
      html += "</tr>";
    }
    document.getElementById("ld-grid").innerHTML = html + "</tbody>";
  }

  function renderAvailable() {
    var taken = {};
    state.picks.forEach(function (p) { taken[keyFor(p.metadata || {})] = true; });

    var rows = "", shown = 0, left = 0;
    for (var i = 0; i < CFG.order.length; i++) {
      var key = CFG.order[i];
      if (taken[key]) continue;
      var a = CFG.adp[key];
      if (state.filter !== "ALL" && a[1] !== state.filter) continue;
      if (state.query && a[0].toLowerCase().indexOf(state.query) < 0) continue;
      left++;
      if (shown >= AVAIL_ROWS) continue;
      shown++;
      rows += "<tr><td class='name'>" + esc(a[0]) + "</td>" +
        "<td><span class='pos-tag pos-" + esc(a[1]) + "'>" + esc(a[1]) + "</span></td>" +
        "<td>" + esc(a[2] || "") + "</td>" +
        "<td>" + (a[3] == null ? "-" : a[3]) + "</td>" +
        "<td>" + (a[5] == null ? "-" : a[5]) + "</td>" +
        "<td>" + (a[4] == null ? "-" : a[4]) + "</td>" +
        "<td>" + esc(a[6] || "") + "</td>" +
        "<td>" + esc(a[7] || "") + "</td></tr>";
    }
    document.getElementById("ld-avail-body").innerHTML = rows ||
      "<tr><td colspan='8' style='padding:14px'>Nobody left matching that.</td></tr>";
    document.getElementById("ld-avail-count").textContent =
      left + " available" + (shown < left ? " (top " + shown + " shown)" : "");
  }

  function renderRosters() {
    var byRoster = {};
    state.picks.forEach(function (p) {
      (byRoster[p.roster_id] = byRoster[p.roster_id] || []).push(p);
    });
    var html = "";
    slots().forEach(function (t) {
      var picks = byRoster[t.roster] || [];
      var counts = {};
      picks.forEach(function (p) {
        var pos = String((p.metadata || {}).position || "?").toUpperCase();
        counts[pos] = (counts[pos] || 0) + 1;
      });
      var need = ["QB", "RB", "WR", "TE", "K", "DEF"].filter(function (p) { return counts[p]; })
        .map(function (p) { return p + counts[p]; }).join(" ");
      var body = picks.length
        ? "<ol>" + picks.map(function (p) {
            var md = p.metadata || {};
            var pos = String(md.position || "").toUpperCase();
            return "<li>" + esc(nameOf(p)) +
              " <span class='ld-sub' style='display:inline'>" +
              "<span class='pos-tag pos-" + esc(pos) + "'>" + esc(pos) + "</span> " +
              esc(md.team || "FA") + "</span></li>";
          }).join("") + "</ol>"
        : "<p class='ld-none'>No picks yet.</p>";
      html += "<div class='ld-team-card'><div class='ld-team-head'>" + esc(t.owner) +
        "<span class='ld-need'>" + esc(need) + "</span></div>" + body + "</div>";
    });
    document.getElementById("ld-rosters").innerHTML = html;
  }

  function whenText(ms) {
    // League time, like every other date on the site. The units below the label
    // count down in absolute terms, so they are right in any timezone.
    try {
      return new Date(ms).toLocaleString("en-US", {
        timeZone: CFG.tz, weekday: "long", month: "long", day: "numeric",
        hour: "numeric", minute: "2-digit", timeZoneName: "short"
      });
    } catch (e) {
      return new Date(ms).toLocaleString();
    }
  }

  function syncCountdown() {
    var card = document.getElementById("ld-countdown");
    if (!card) return;
    var meta = state.meta || {};
    if (status() !== "pre_draft") { card.style.display = "none"; return; }
    card.style.display = "";
    if (!meta.start_time || !window.Countdown) return;
    var iso = new Date(meta.start_time).toISOString().replace(/\\.\\d+Z$/, "Z");
    window.Countdown.retarget(card, iso, whenText(meta.start_time));
  }

  /** Seconds left on the current pick, or null when that is unknowable. */
  function clockLeft() {
    var meta = state.meta || {}, s = meta.settings || {};
    if (!isLive() || !s.pick_timer) return null;
    var base = meta.last_picked || meta.start_time;
    if (!base) return null;
    var left = Math.round(s.pick_timer - (Date.now() - base) / 1000);
    // Clamped both ways: the reader's clock and Sleeper's are not the same
    // clock, and a paused draft keeps running this number down.
    return Math.max(0, Math.min(left, s.pick_timer));
  }

  function fmtClock(sec) {
    return Math.floor(sec / 60) + ":" + (sec % 60 < 10 ? "0" : "") + (sec % 60);
  }

  function renderStatus() {
    var pill = document.getElementById("ld-pill");
    var line = document.getElementById("ld-onclock");
    var meta = state.meta || {};
    var st = status();

    if (state.failures >= 3) {
      pill.className = "ld-pill err";
      pill.textContent = "Sleeper unreachable";
    } else if (st === "drafting") {
      pill.className = "ld-pill live";
      pill.textContent = "Live";
    } else if (st === "paused") {
      pill.className = "ld-pill soon";
      pill.textContent = "Paused";
    } else if (st === "complete") {
      pill.className = "ld-pill done";
      pill.textContent = "Draft complete";
    } else {
      var soon = meta.start_time && (meta.start_time - Date.now()) < 30 * 60 * 1000;
      pill.className = "ld-pill" + (soon ? " soon" : "");
      pill.textContent = soon ? "Starting soon" : "Pre-draft";
    }

    var total = teamCount() * roundCount();
    if (isLive() && state.picks.length < total) {
      var next = state.picks.length + 1;
      var slot = slotFor(next);
      var team = slots()[slot - 1] || {};
      var left = clockLeft();
      line.innerHTML = "<strong>" + esc(team.owner || ("Slot " + slot)) + "</strong> on the clock" +
        " &middot; pick " + pickLabel(next, Math.ceil(next / teamCount()), teamCount()) +
        (left === null ? "" : " <span class='ld-timer" + (left <= 15 ? " low" : "") + "'>" +
          fmtClock(left) + "</span>");
    } else if (st === "complete" || state.picks.length >= total) {
      var last = state.picks[state.picks.length - 1];
      line.innerHTML = last ? "Last pick: <strong>" + esc(nameOf(last)) + "</strong>" : "";
    } else {
      line.innerHTML = "";
    }

    var ago = state.at ? Math.round((Date.now() - state.at) / 1000) : null;
    document.getElementById("ld-meta").innerHTML =
      state.picks.length + " of " + total + " picks" +
      (ago === null ? "" : " &middot; updated " + (ago < 60 ? ago + "s" : Math.round(ago / 60) + "m") + " ago");
  }

  /** Everything that changes what the board looks like, in one string.
   *
   * The draft order belongs in here even though it is not obviously "what the
   * board looks like": randomizing the order is the last thing that happens
   * before a draft starts, and without it the column headings would keep the
   * old order until the first pick landed and changed the pick count.
   */
  function signature() {
    var meta = state.meta || {};
    return [state.picks.length, meta.status, meta.start_time, meta.last_picked,
            roundCount(), teamCount(), state.usersAt,
            JSON.stringify(meta.draft_order), JSON.stringify(meta.slot_to_roster_id),
            state.filter, state.query].join("|");
  }

  function render(force) {
    var sig = signature();
    if (!force && sig === state.sig) { renderStatus(); return; }
    state.sig = sig;
    renderGrid();
    renderAvailable();
    renderRosters();
    renderStatus();
    syncCountdown();
    state.seeded = true;
  }

  // -------------------------------------------------------------------- poll
  function pull() {
    return Promise.all([
      fresh(API + "/draft/" + DRAFT_ID),
      fresh(API + "/draft/" + DRAFT_ID + "/picks")
    ]).then(function (res) {
      state.meta = res[0] || {};
      var picks = (res[1] || []).slice().sort(function (a, b) { return a.pick_no - b.pick_no; });
      var now = Date.now();
      picks.forEach(function (p) {
        if (!state.firstSeen[p.pick_no]) state.firstSeen[p.pick_no] = now;
      });
      state.picks = picks;
      state.at = now;
      state.failures = 0;
      var league = state.meta.league_id;
      if (league && (state.usersFor !== league || now - state.usersAt > USERS_MAX_AGE)) {
        return users(league);
      }
    }).catch(function (err) {
      state.failures++;
      if (window.console) console.warn("draft poll failed", err);
    }).then(function () {
      render();
    });
  }

  function users(leagueId) {
    return fresh(API + "/league/" + leagueId + "/users").then(function (list) {
      var out = {};
      (list || []).forEach(function (u) { out[u.user_id] = u; });
      state.users = out;
      state.usersFor = leagueId;
      state.usersAt = Date.now();
    }).catch(function () { /* names fall back to the league config */ });
  }

  function interval() {
    var st = status();
    if (isLive()) return POLL_LIVE;
    if (st === "complete") return POLL_IDLE;
    var start = state.meta && state.meta.start_time;
    if (start && start - Date.now() < 30 * 60 * 1000) return POLL_SOON;
    return POLL_IDLE;
  }

  function loop() {
    // A backgrounded tab is not being read, and a phone left open on the couch
    // through a three-hour draft should not spend the battery polling for it.
    var wait = document.hidden ? POLL_IDLE : interval();
    setTimeout(function () {
      (document.hidden ? Promise.resolve() : pull()).then(loop);
    }, wait);
  }

  function bindControls() {
    document.querySelectorAll("[data-pos]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        state.filter = btn.getAttribute("data-pos");
        document.querySelectorAll("[data-pos]").forEach(function (b) {
          b.classList.toggle("active", b === btn);
        });
        render(true);
      });
    });
    var search = document.getElementById("ld-search");
    search.addEventListener("input", function () {
      state.query = search.value.trim().toLowerCase();
      render(true);
    });
    document.addEventListener("visibilitychange", function () {
      if (!document.hidden) pull();
    });
  }

  bindControls();
  pull().then(loop);
  // The pick clock and the "updated Ns ago" stamp move between polls.
  setInterval(renderStatus, 1000);
})();
</script>"""


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #

def _intro() -> str:
    stamp = last_updated(UPCOMING_YEAR)
    when = stamp.astimezone(LEAGUE_TZ).strftime("%b %-d, %-I:%M %p %Z") if stamp else "an earlier build"
    return (f"<p>The {UPCOMING_SEASON} draft as it happens, read straight from Sleeper. "
            f"The page polls for picks every few seconds while the draft is live — leave it open, "
            f"there is nothing to refresh.</p>"
            f"<p class='ld-note'>Each pick is graded against the multi-site ADP board on the "
            f"{layout.internal_link('/fantasy/', 'fantasy homepage')}, pulled {when}. "
            f"A green cell (<span class='ld-sw v'></span>) means the player lasted {SWING}+ picks "
            f"past his board rank; a red one (<span class='ld-sw r'></span>) means he went {SWING}+ "
            f"picks early. Kickers and defenses are not on the board, so they are never tinted.</p>")


def _status_bar() -> str:
    return """<div class="ld-bar">
  <span class="ld-pill" id="ld-pill">Loading</span>
  <span class="ld-onclock" id="ld-onclock"></span>
  <span class="ld-meta" id="ld-meta"></span>
</div>"""


def _board_section() -> str:
    return ('<p class="ld-legend">Snake order, so even rounds run right to left. '
            'The number in each cell is the pick it was made with.</p>'
            '<div class="ld-wrap"><table class="ld-grid" id="ld-grid"></table></div>')


def _available_section() -> str:
    chips = "".join(
        f'<button data-pos="{p}"{" class=\'active\'" if p == "ALL" else ""}>{p}</button>'
        for p in ["ALL"] + POSITIONS)
    head = "".join(f"<th>{h}</th>" for h in
                   ["Player", "Pos", "Team", "Bye", "ADP", "Board", "Pick", "PosRk"])
    return f"""<div class="adp-controls">
  <span class="adp-label">Position:</span>{chips}
  <input id="ld-search" type="search" placeholder="Search players" aria-label="Search players">
  <span class="adp-label" id="ld-avail-count"></span>
</div>
<div class="ld-wrap"><table class="ld-avail"><thead><tr>{head}</tr></thead>
<tbody id="ld-avail-body"></tbody></table></div>
<p class="ld-note"><strong>ADP</strong> is the average pick across the five sites on the board;
<strong>Board</strong> is that average turned into an overall rank, and <strong>Pick</strong> is
where that rank falls in a {LEAGUE_TEAMS}-team draft.</p>"""


def _config_json(rows: dict, order: list, meta: dict) -> str:
    settings = meta.get("settings") or {}
    cfg = {
        "draft_id": UPCOMING_DRAFT_ID,
        "roster_names": {str(k): v for k, v in ROSTER_NAMES.items()},
        "teams": settings.get("teams") or LEAGUE_TEAMS,
        "rounds": settings.get("rounds") or 15,
        "tz": str(LEAGUE_TZ),
        "nudge": NUDGE,
        "swing": SWING,
        "adp": rows,
        "order": order,
    }
    # </script> inside the JSON would close the block early; nothing in a player
    # name can produce one, but the board is fed by five scraped sites.
    return ('<script id="ld-config">window.LD_CONFIG='
            + json.dumps(cfg, separators=(",", ":")).replace("</", "<\\/")
            + ";</script>")


def generate(output=OUTPUT):
    """Write the live draft board to `output`."""
    rows, order = adp_data()
    meta = _draft_meta()

    sections = [
        ("board", "Draft Board", _board_section(), True),
        ("available", "Best Available", _available_section(), True),
        ("rosters", "Rosters", '<div class="ld-rosters" id="ld-rosters"></div>', False),
    ]
    nav = layout.section_nav([(anchor, title) for anchor, title, _, _ in sections])
    body = (layout.HEAD + _CSS + _intro() + _countdown(meta) + _status_bar() + nav
            + "".join(layout.details(title, html, open=is_open, anchor=anchor)
                      for anchor, title, html, is_open in sections)
            + _config_json(rows, order, meta) + _SCRIPT)

    page = add_front_matter(body, "Live Draft Board")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding="utf-8")
    print(f"Wrote live draft board -> {output} ({len(order)} players on the board)")


if __name__ == "__main__":
    generate()
