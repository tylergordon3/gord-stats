"""
The live college draft board (docs/cfb/live/).

Every other page in this section reports on something that already happened.
This one runs during the draft, and it is the only page here that has to be
right within thirty seconds rather than within six hours.

Two halves.

The data half is baked in at build time: the valued board from cfb.projections
- every rosterable player with a projection, a floor and a ceiling, value over
replacement at this league's own roster settings, a tier, and how far his
Yahoo average pick sits from what he is worth. That is the part that needs a
season of college stats, this site's game model and a few seconds of Python,
and none of it changes while a draft is running.

The live half runs in the reader's browser. It asks /api/cfb-draft (a Pages
Function, because Yahoo's public API serves no CORS header) for whatever Yahoo
will admit about the draft so far, and it takes picks typed in by hand, and it
reconciles the two - so the board still works in the case that has to work,
which is Yahoo not publishing a live feed at all.

What it does with that is the point. A board that says "the next best player
left" is a sorted list; this one answers the question actually being asked,
which is what to do with *this* pick given *this* roster and the picks between
now and your next one:

  * Value over replacement, at this league's settings rather than a generic
    league's. Two starting quarterbacks in a ten-team league puts replacement
    at QB20, and 6-point passing touchdowns put the position's ceiling above
    everything else - which is why the model wants quarterbacks two rounds
    before Yahoo's ADP does. That ADP is one number for the whole college game,
    pooled across every league Yahoo runs whatever their settings; this one's
    settings are not in it.
  * Marginal value, not raw value: what a player adds to the starting lineup
    you already have. A third quarterback is worth what a bench spot is worth.
  * A two-pick lookahead. For every candidate it works out the best it could
    expect to do at its next pick if it took him now, and picks the pair. That
    is what turns "he is the best player left" into "take the quarterback now,
    because the running backs you want will still be there and the quarterbacks
    will not".
  * Survival odds for every player, from Yahoo's average pick and how often he
    goes undrafted, conditioned on his still being here.
  * Tier cliffs and positional runs, because both change what waiting costs.

    python -m cfb.site.draft_live       # writes docs/cfb/live/index.html
"""
import json

import numpy as np
import pandas as pd

from cfb import projections, schools as schools_mod, yahoo
from cfb.config import (
    DATA_DIR, LEAGUE_TEAMS, LEAGUE_TZ, LEAGUE_URL, SEASON, WEB_DIR,
)
from cfb.site import write_page

OUTPUT = WEB_DIR / "live" / "index.html"

# Row layout of the embedded board, as arrays rather than objects: ~480 players
# ship on every page load and the keys would be most of the bytes. The order
# here is the order the page script reads them in, and the two must agree.
_FIELDS = ["player", "pos", "team", "school", "bye", "adp", "pct_drafted",
           "adp_sd", "rank", "pos_rank", "proj", "floor", "ceiling", "vorp",
           "tier", "playoff_ratio", "team_scored", "opp_allowed", "yahoo_id",
           "espn"]

# Positions the filter chips offer, in the order a roster fills.
POSITIONS = ["QB", "RB", "WR", "TE", "DEF"]

# Whose board this is, by team name. The page opens on this roster rather than
# asking, since it is read on draft night with a clock running; the team menu
# still changes it, and the choice is remembered per browser.
MY_TEAM = "Puntaholics"


def _cell(value):
    """JSON-safe: NaN becomes null, whole floats become ints."""
    if isinstance(value, str):
        return value
    if value is None or pd.isna(value):
        return None
    value = float(value)
    return int(value) if value.is_integer() else round(value, 2)


def rows(board: pd.DataFrame) -> list:
    frame = board.copy()
    for field in _FIELDS:
        if field not in frame:
            frame[field] = np.nan
    return [[_cell(v) for v in row]
            for row in frame[_FIELDS].itertuples(index=False, name=None)]


def draft_order(league: dict) -> dict:
    """{team key: draft slot}, from data/cfb/draft_order.json.

    Yahoo's public API does not publish the order before the draft - teams,
    settings and draftresults all omit it - but the order is set in the draft
    client days beforehand, and knowing it is what lets the board name the ten
    columns, work out whose pick is on the clock, and fill in a slot the moment
    a team is chosen. So it is recorded by hand and read here.

    Matched on the team's name rather than its key, because a name is what can
    be read off the draft client; an unmatched name raises rather than silently
    dropping a slot, since a wrong slot map assigns picks to the wrong roster
    and every recommendation after it is answering the wrong question.
    """
    path = DATA_DIR / "draft_order.json"
    if not path.exists():
        return {}
    order = json.loads(path.read_text()).get("order") or []
    keys = {t["name"]: t["team_key"] for t in league["teams"]}
    unknown = [n for n in order if n not in keys]
    if unknown:
        raise ValueError(f"draft_order.json names no team in this league: {unknown}")
    return {keys[name]: slot for slot, name in enumerate(order, start=1)}


def _slots(league: dict) -> list:
    """Starting slots as [position, count], bench and IL dropped."""
    return [[s["position"], int(s["count"])] for s in league["roster"]
            if s["position"] not in ("BN", "IL")]


def _bench(league: dict) -> int:
    return sum(int(s["count"]) for s in league["roster"] if s["position"] == "BN")


def config(board: pd.DataFrame, league: dict) -> dict:
    levels = projections.replacement_levels(board, league)
    teams = [{"key": t["team_key"], "name": t["name"], "logo": t.get("logo") or ""}
             for t in league["teams"]]
    mine = next((t["team_key"] for t in league["teams"] if t["name"] == MY_TEAM), None)
    if MY_TEAM and mine is None:
        raise ValueError(f"MY_TEAM {MY_TEAM!r} is not a team in this league")
    rounds = sum(int(s["count"]) for s in league["roster"] if s["position"] != "IL")
    return {
        "rows": rows(board),
        "teams": teams,
        "slotOf": draft_order(league),
        "defaultTeam": mine,
        "numTeams": int(league.get("num_teams") or LEAGUE_TEAMS),
        "rounds": rounds,
        "slots": _slots(league),
        "bench": _bench(league),
        "flexSlot": projections.FLEX_SLOT,
        "flexPositions": projections.FLEX_POSITIONS,
        "positions": POSITIONS,
        "replacement": {k: round(v, 1) for k, v in levels.items()},
        "draftTime": league.get("draft_time"),
        "pickSeconds": int(league.get("draft_pick_seconds") or 0),
        "leagueUrl": league.get("url") or LEAGUE_URL,
        "leagueName": league.get("name"),
        "playoffWeek": int(league.get("playoff_start_week") or 0),
        "endWeek": int(league.get("end_week") or 13),
        "season": SEASON,
    }


# --------------------------------------------------------------------------- #
# Styles
# --------------------------------------------------------------------------- #
# Reuses the board classes the ADP page already ships (.adp-controls, .adp-label,
# .pos-tag) so the chips and pills match the rest of the section; everything
# below is what this page adds.

_CSS = """<style>
.ld-bar{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin:10px 0;
  padding:10px 12px;border:1px solid #e5e7eb;border-radius:12px;background:#f8fafc}
.ld-bar select,.ld-bar button{font:inherit;font-size:13px;padding:5px 9px;
  border:1px solid #cbd5e1;border-radius:8px;background:#fff;color:#0f172a}
.ld-bar button{cursor:pointer}
.ld-bar button.on{background:#334155;border-color:#334155;color:#fff}
.ld-pill{font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.03em;
  padding:3px 9px;border-radius:999px;background:#e2e8f0;color:#334155}
.ld-pill.live{background:#1a7f4b;color:#fff}
.ld-pill.mine{background:#b45309;color:#fff}
.ld-note{font-size:12px;color:#4a5a68}
img.ld-tlogo{width:16px;height:16px;border-radius:50%;vertical-align:-3px;
  margin-right:5px;background:#fff;object-fit:cover}
table.ld-grid th img.ld-tlogo{display:block;width:18px;height:18px;margin:0 auto 2px}
.ld-panel h3 img.ld-tlogo{vertical-align:-4px}
img.ld-slogo{width:15px;height:15px;vertical-align:-3px;margin-right:3px}
table.ld-avail td.tm{text-align:left}
#ld-status,#ld-feed{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.ld-clock{font-family:monospace;font-size:15px;font-weight:700;color:#0f172a}

.ld-recs{display:grid;gap:10px;margin:10px 0;
  grid-template-columns:repeat(auto-fit,minmax(280px,1fr))}
.ld-rec{border:1px solid #e5e7eb;border-radius:12px;background:#fff;padding:10px 12px;
  box-shadow:0 2px 8px rgba(15,23,42,.05);display:flex;flex-direction:column;gap:6px}
.ld-rec.top{border-color:#b45309;box-shadow:0 2px 10px rgba(180,83,9,.18)}
.ld-rec .hd{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
.ld-rec .nm{font-weight:700;font-size:15px;color:#0f172a}
.ld-rec .sub{font-size:12px;color:#4a5a68}
.ld-rec .edge{margin-left:auto;font-family:monospace;font-weight:700;color:#1a7f4b}
.ld-rec .why{font-size:12.5px;color:#334155;line-height:1.5;margin:0}
.ld-rec .chips{display:flex;flex-wrap:wrap;gap:5px}
.ld-chip{font-size:11px;padding:2px 7px;border-radius:999px;background:#eef2f7;color:#334155}
.ld-chip.warn{background:#fde9c8;color:#8a4b00}
.ld-chip.good{background:#d5efdd;color:#14603a}
.ld-rec button{align-self:flex-start;font:inherit;font-size:12px;padding:4px 10px;
  border:1px solid #cbd5e1;border-radius:8px;background:#fff;color:#0f172a;cursor:pointer}

.ld-cols{display:grid;gap:14px;grid-template-columns:1fr;margin:10px 0}
@media (min-width:900px){.ld-cols{grid-template-columns:minmax(0,2fr) minmax(0,1fr)}}
.ld-panel{border:1px solid #e5e7eb;border-radius:12px;background:#fff;overflow:hidden}
.ld-panel h3{margin:0;padding:7px 11px;font-size:12px;text-transform:uppercase;
  letter-spacing:.04em;background:#eef2f7;color:#334155}
.ld-panel .body{padding:8px 11px}

table.ld-avail{width:100%;border-collapse:separate;border-spacing:0;font-size:13px;
  font-family:monospace}
table.ld-avail th{position:sticky;top:0;z-index:2;background:#eef2f7;color:#334155;
  padding:6px 8px;font-size:11px;text-transform:uppercase;letter-spacing:.03em;
  cursor:pointer;white-space:nowrap;border-bottom:1px solid #e2e8f0}
table.ld-avail th.sort-desc::after{content:" ▼";font-size:9px}
table.ld-avail th.sort-asc::after{content:" ▲";font-size:9px}
table.ld-avail td{padding:4px 8px;text-align:center;white-space:nowrap;
  border-bottom:1px solid #eef2f7;color:#0f172a}
table.ld-avail td.nm{text-align:left;font-family:inherit}
table.ld-avail tbody tr:nth-child(even) td{background:#f8fafc}
table.ld-avail tbody tr:hover td{background:#eef2f6}
table.ld-avail td.v{font-weight:700}
.ld-scroll{max-height:460px;overflow:auto;overscroll-behavior:contain}
.ld-take{font:inherit;font-size:11px;padding:2px 7px;border:1px solid #cbd5e1;
  border-radius:6px;background:#fff;cursor:pointer;color:#0f172a}
.ld-take:hover{background:#334155;border-color:#334155;color:#fff}

table.ld-grid{width:100%;border-collapse:collapse;font-size:11px;table-layout:fixed}
table.ld-grid th{background:#eef2f7;color:#334155;padding:4px 3px;font-size:10px;
  text-transform:uppercase;letter-spacing:.02em;border:1px solid #e2e8f0;
  overflow:hidden;text-overflow:ellipsis}
table.ld-grid th[data-slot]{cursor:pointer}
table.ld-grid th[data-slot]:hover{background:#e2e8f0}
table.ld-grid th.mine-col{color:#b45309;box-shadow:inset 0 -3px 0 #b45309}
table.ld-grid td{border:1px solid #eef2f7;padding:3px;height:34px;vertical-align:top;
  overflow:hidden;color:#0f172a}
table.ld-grid td.on{outline:2px solid #b45309;outline-offset:-2px}
table.ld-grid td.mine{box-shadow:inset 3px 0 0 #b45309}
table.ld-grid .pk{font-size:9px;color:#5d6b7e;font-family:monospace}
table.ld-grid .pl{display:block;line-height:1.2;overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap}
td.p-QB{background:#d3ddf5}td.p-RB{background:#d5efdd}td.p-WR{background:#fbeec2}
td.p-TE{background:#fadfc8}td.p-DEF{background:#d4f0f7}

.ld-lineup{width:100%;border-collapse:collapse;font-size:13px}
.ld-lineup td{padding:3px 4px;border-bottom:1px solid #eef2f7}
.ld-lineup td.slot{font-size:11px;text-transform:uppercase;letter-spacing:.03em;
  color:#4a5a68;width:52px}
.ld-lineup td.pts{text-align:right;font-family:monospace;color:#4a5a68}
.ld-lineup tr.empty td{color:#93a1ad}
.ld-need{font-size:12.5px;color:#334155;margin:6px 0 0;line-height:1.5}

@media (prefers-color-scheme: dark){
  .ld-bar{background:#1b2540;border-color:#2b3852}
  .ld-bar select,.ld-bar button,.ld-take{background:#16203a;border-color:#2b3852;color:#dde5ef}
  .ld-bar button.on{background:#dde5ef;color:#16203a;border-color:#dde5ef}
  .ld-pill{background:#223052;color:#dde5ef}
  .ld-note,.ld-rec .sub{color:#aab7c9}
  .ld-clock{color:#fff}
  .ld-rec,.ld-panel{background:#1b2540;border-color:#2b3852}
  .ld-rec .nm{color:#fff}
  .ld-rec .why{color:#dde5ef}
  .ld-rec .edge{color:#6ee7b7}
  .ld-chip{background:#223052;color:#dde5ef}
  .ld-chip.warn{background:#4a3410;color:#ffd79a}
  .ld-chip.good{background:#123c2e;color:#8ff0bd}
  .ld-panel h3{background:#223052;color:#dde5ef}
  table.ld-avail th{background:#223052;color:#dde5ef;border-color:#2b3852}
  table.ld-avail td{color:#dde5ef;border-color:#2b3852}
  table.ld-avail tbody tr:nth-child(even) td{background:#16203a}
  table.ld-avail tbody tr:hover td{background:#26365c}
  table.ld-grid th{background:#223052;color:#dde5ef;border-color:#2b3852}
  table.ld-grid th[data-slot]:hover{background:#26365c}
  table.ld-grid th.mine-col{color:#ffb457;box-shadow:inset 0 -3px 0 #ffb457}
  table.ld-grid td{border-color:#2b3852;color:#dde5ef}
  td.p-QB{background:#1e2c52}td.p-RB{background:#123c2e}td.p-WR{background:#3d3413}
  td.p-TE{background:#40280f}td.p-DEF{background:#143a45}
  table.ld-grid .pk{color:#aab7c9}
  .ld-lineup td{border-color:#2b3852}
  .ld-lineup td.slot,.ld-lineup td.pts{color:#aab7c9}
  .ld-need{color:#dde5ef}
}
@media (max-width:700px){
  .ld-scroll{max-height:60vh}
  table.ld-grid{font-size:10px}
  table.ld-grid td{height:30px}
}
</style>"""


# --------------------------------------------------------------------------- #
# The engine
# --------------------------------------------------------------------------- #

_ENGINE = r"""
(function () {
  var CFG = window.LD_CFG, P = CFG.rows;

  // Column indices into a board row - the order _FIELDS ships them in.
  var NAME = 0, POS = 1, TEAM = 2, SCHOOL = 3, BYE = 4, ADP = 5, PCTD = 6,
      ADPSD = 7, RANK = 8, POSRK = 9, PROJ = 10, FLOOR = 11, CEIL = 12,
      VORP = 13, TIER = 14, PLAYOFF = 15, TSCORED = 16, OPPALL = 17, YID = 18,
      ESPN = 19;

  // What a player who never cracks the lineup is worth, as a share of his value
  // over replacement. Six bench spots on a seventeen-round roster is a lot of
  // depth to fill, and a backup at a two-starter position is an injury away
  // from being a starter - but he is not one now, and the number says so.
  var BENCH_SHARE = 0.28;

  // How many players a lookahead considers at a position, and how many
  // candidates get the full two-pick treatment. Both are far past where the
  // answer stops changing; they exist so a phone does not have to score 480
  // players against every position on every redraw.
  var LOOKAHEAD_DEPTH = 30, CANDIDATES = 40;

  // A run is this many picks back. Two rounds is what a manager can feel.
  var RUN_WINDOW = 12;

  var STORE = "cfb-live-" + CFG.season;
  var byId = {};
  for (var i = 0; i < P.length; i++) byId[P[i][YID]] = i;

  // Picks are owned by draft *slot*, not by team key: the snake decides whose
  // pick number 34 is, and that is knowable from the pick alone. Team keys are
  // metadata - what Yahoo calls the manager sitting in that slot - and arrive
  // only if Yahoo publishes the draft live. The board never needs them to work.
  /** The slot map, layered: the order recorded at build time is the base, a
   *  correction saved in this browser wins over it, and the live feed - which
   *  is the draft actually happening - wins over both. */
  function seedSlots(saved) {
    var out = {};
    for (var k in (CFG.slotOf || {})) out[k] = CFG.slotOf[k];
    for (var j in (saved || {})) out[j] = saved[j];
    return out;
  }

  var state = {
    picks: [],            // {pick, id, team, manual}
    mySlot: null,         // 1..teams, chosen or learnt
    myTeam: null,         // Yahoo team key, for names and for the live feed
    slotOf: {},           // team key -> draft slot; seeded below
    auto: true,
    source: "none",
    fetched: 0,
    error: null,
    pos: "ALL",
    query: "",
    sort: "score",
    sortFlip: false,      // clicking the sorted column again reverses it
  };

  // ----------------------------------------------------------------- storage
  function save() {
    try {
      localStorage.setItem(STORE, JSON.stringify({
        picks: state.picks, mySlot: state.mySlot, myTeam: state.myTeam,
        slotOf: state.slotOf, auto: state.auto,
      }));
    } catch (e) { /* private mode; the board still works, it just forgets */ }
  }
  function restore() {
    state.slotOf = seedSlots(null);
    state.myTeam = CFG.defaultTeam || null;
    try {
      var raw = localStorage.getItem(STORE);
      if (!raw) return;
      var s = JSON.parse(raw);
      state.picks = s.picks || [];
      state.mySlot = s.mySlot || null;
      if (s.myTeam) state.myTeam = s.myTeam;
      state.slotOf = seedSlots(s.slotOf);
      if (s.auto === false) state.auto = false;
    } catch (e) { /* corrupt or unreadable; start clean */ }
  }

  // -------------------------------------------------------------- draft shape
  function teams() { return CFG.teams; }
  function nTeams() { return CFG.numTeams; }
  function totalPicks() { return nTeams() * CFG.rounds; }

  function roundOf(pick) { return Math.floor((pick - 1) / nTeams()) + 1; }
  function slotOfPick(pick) {
    var r = roundOf(pick), i = pick - (r - 1) * nTeams();
    return r % 2 === 1 ? i : nTeams() + 1 - i;      // snake
  }
  function pickAt(round, slot) {
    var i = round % 2 === 1 ? slot : nTeams() + 1 - slot;
    return (round - 1) * nTeams() + i;
  }
  function label(pick) {
    var r = roundOf(pick), i = pick - (r - 1) * nTeams();
    return r + "." + (i < 10 ? "0" : "") + i;
  }

  function onClock() {
    var last = 0;
    for (var i = 0; i < state.picks.length; i++) {
      if (state.picks[i].pick > last) last = state.picks[i].pick;
    }
    return last + 1;
  }

  /** My draft slot: what I picked in the bar, or what the feed revealed. */
  function mySlot() {
    if (state.mySlot) return state.mySlot;
    if (state.myTeam && state.slotOf[state.myTeam]) return state.slotOf[state.myTeam];
    return null;
  }

  /** The next pick that is mine, and the one after it. */
  function myPicks() {
    var slot = mySlot(), now = onClock();
    if (!slot) return [now, now + nTeams()];        // no slot set: assume it is mine
    var out = [];
    for (var r = 1; r <= CFG.rounds; r++) {
      var p = pickAt(r, slot);
      if (p >= now) out.push(p);
      if (out.length === 3) break;
    }
    while (out.length < 2) out.push(totalPicks() + nTeams() * (out.length + 1));
    return out;
  }

  function teamOfSlot(slot) {
    for (var key in state.slotOf) {
      if (state.slotOf[key] === slot) {
        for (var t = 0; t < CFG.teams.length; t++) {
          if (CFG.teams[t].key === key) return CFG.teams[t];
        }
      }
    }
    return null;
  }
  function nameOfSlot(slot) {
    var t = teamOfSlot(slot);
    return t ? t.name : "Slot " + slot;
  }
  function logoOfSlot(slot) {
    var t = teamOfSlot(slot);
    return t && t.logo
      ? '<img class="ld-tlogo" src="' + esc(t.logo) + '" alt="" loading="lazy">'
      : "";
  }

  // -------------------------------------------------------------- availability
  function takenSet() {
    var t = {};
    for (var i = 0; i < state.picks.length; i++) t[state.picks[i].id] = true;
    return t;
  }

  function availableIdx() {
    var taken = takenSet(), out = [];
    for (var i = 0; i < P.length; i++) if (!taken[P[i][YID]]) out.push(i);
    return out;
  }

  function ncdf(x) {
    var t = 1 / (1 + 0.2316419 * Math.abs(x));
    var d = 0.3989422804014327 * Math.exp(-x * x / 2);
    var p = d * t * (0.31938153 + t * (-0.356563782 + t * (1.781477937
            + t * (-1.821255978 + t * 1.330274429))));
    return x > 0 ? 1 - p : p;
  }

  /** How this room is actually drafting, position by position: the mean of
   *  (actual pick - Yahoo ADP) over the picks made so far, shrunk toward zero
   *  while the sample is small and clamped per pick so one manager's reach
   *  does not reprice a whole position. Yahoo's ADP is pooled over every
   *  league in the game whatever its settings; this league starts two
   *  quarterbacks, and the nine other managers can read the settings too. The
   *  first few quarterbacks going eight picks early is the room saying so,
   *  and the survival odds should listen rather than keep promising that the
   *  position this board most wants to exploit will still be there. */
  var DRIFT = {};
  function adpDrift() {
    var sum = {}, n = {};
    state.picks.forEach(function (p) {
      var idx = byId[p.id];
      if (idx === undefined || P[idx][ADP] === null) return;
      var pos = P[idx][POS];
      var d = Math.max(-30, Math.min(30, p.pick - P[idx][ADP]));
      sum[pos] = (sum[pos] || 0) + d;
      n[pos] = (n[pos] || 0) + 1;
    });
    var out = {};
    for (var pos in sum) out[pos] = (sum[pos] / n[pos]) * (n[pos] / (n[pos] + 4));
    return out;
  }

  /** P(this player is off the board by the time pick `k` comes round).
   *
   * Yahoo's average pick with a spread that widens down the board, scaled by
   * how often he is drafted at all - a player taken in 40% of leagues cannot be
   * more than 40% likely to be gone, however early his average pick is. The
   * average pick is first shifted by how early this room has been taking the
   * position tonight. */
  function goneBy(i, k) {
    var adp = P[i][ADP];
    if (adp === null) return 0.04;                  // ranked, but nobody drafts him
    adp += DRIFT[P[i][POS]] || 0;
    var sd = P[i][ADPSD] || 4;
    var pct = P[i][PCTD] === null ? 1 : P[i][PCTD];
    return Math.max(0, Math.min(1, pct * ncdf((k - adp) / sd)));
  }

  /** P(still there at pick `k`), given he is still here at pick `now`. */
  function survives(i, k, now) {
    var a = goneBy(i, now), b = goneBy(i, k);
    if (a >= 0.995) return 0.02;
    return Math.max(0, Math.min(1, (1 - b) / (1 - a)));
  }

  // ------------------------------------------------------------- roster value
  function repl(pos) { return CFG.replacement[pos] || 0; }
  var FLEX_REPL = (function () {
    var m = 0;
    CFG.flexPositions.forEach(function (p) { m = Math.max(m, repl(p)); });
    return m;
  })();

  var EMPTY_LINEUP = 0;      // set once lineupValue exists; see below

  function rosterAt(slot) {
    var out = [];
    if (!slot) return out;
    for (var i = 0; i < state.picks.length; i++) {
      if (slotOfPick(state.picks[i].pick) === slot) {
        var idx = byId[state.picks[i].id];
        if (idx !== undefined) out.push(idx);
      }
    }
    return out;
  }
  function myRoster() { return rosterAt(mySlot()); }

  /** The starting lineup this set of players supports, in projected points,
   *  with every slot nobody fills counted at replacement level. Dedicated slots
   *  take the best player at their position; the flex slots then take the best
   *  of whoever is left, which is both what a manager does and what makes a
   *  fourth receiver worth less than a third. */
  function lineupValue(ids) {
    var pools = {};
    for (var k = 0; k < ids.length; k++) {
      var r = P[ids[k]];
      (pools[r[POS]] = pools[r[POS]] || []).push(r[PROJ]);
    }
    for (var p in pools) pools[p].sort(function (a, b) { return b - a; });

    var used = {}, total = 0, flexN = 0;
    CFG.slots.forEach(function (s) {
      var pos = s[0], n = s[1];
      if (pos === CFG.flexSlot) { flexN += n; return; }
      for (var c = 0; c < n; c++) {
        var pool = pools[pos] || [], at = used[pos] || 0;
        total += at < pool.length ? pool[at] : repl(pos);
        used[pos] = at + 1;
      }
    });
    for (var f = 0; f < flexN; f++) {
      var best = null, bestPos = null;
      CFG.flexPositions.forEach(function (pos) {
        var pool = pools[pos] || [], at = used[pos] || 0;
        if (at < pool.length && (best === null || pool[at] > best)) {
          best = pool[at]; bestPos = pos;
        }
      });
      if (best !== null && best > FLEX_REPL) { total += best; used[bestPos]++; }
      else total += FLEX_REPL;
    }
    return total;
  }

  /** What adding this player does for that roster's starting lineup - and if
   *  he does not crack it, what a bench spot he fills is worth. */
  EMPTY_LINEUP = lineupValue([]);

  function marginal(i, ids, base) {
    var full = ids.length >= CFG.rounds;
    if (full) return 0;
    var gain = lineupValue(ids.concat([i])) - (base === undefined ? lineupValue(ids) : base);
    var bench = BENCH_SHARE * Math.max(0, P[i][VORP]);
    return Math.max(gain, bench);
  }

  /** Expected value of the best player at this position still there at pick k.
   *
   *  Walk the position in value order: the first one who survives is the one
   *  taken, so his value counts for the chance he is there times the chance
   *  everyone better is not. That is the expectation exactly, not a sample. */
  function expectedBest(pos, k, ids, pool, now) {
    var base = lineupValue(ids), scored = [];
    for (var n = 0; n < pool.length; n++) {
      var i = pool[n];
      if (P[i][POS] !== pos) continue;
      scored.push([i, marginal(i, ids, base)]);
      if (scored.length >= LOOKAHEAD_DEPTH * 2) break;   // pool is value-ordered
    }
    scored.sort(function (a, b) { return b[1] - a[1]; });
    var total = 0, none = 1;
    for (var s = 0; s < Math.min(scored.length, LOOKAHEAD_DEPTH); s++) {
      var live = survives(scored[s][0], k, now);
      total += scored[s][1] * live * none;
      none *= (1 - live);
    }
    return total;
  }

  // ------------------------------------------------------------ the two picks
  /** Rank every candidate by what the *pair* of picks is worth: him now, plus
   *  the best this roster could expect at its next pick with him already on it.
   *  Taking the best player left is the special case of this where the board
   *  never changes between your picks, which is never. */
  function recommend() {
    var ids = myRoster(), base = lineupValue(ids);
    var picks = myPicks(), now = picks[0], next = picks[1];
    var pool = availableIdx();
    pool.sort(function (a, b) { return P[b][VORP] - P[a][VORP]; });

    var cands = [];
    for (var n = 0; n < pool.length && cands.length < CANDIDATES; n++) {
      cands.push({ i: pool[n], now: marginal(pool[n], ids, base) });
    }
    cands.sort(function (a, b) { return b.now - a.now; });

    // What each position is worth at the next pick if I do nothing now - the
    // baseline every candidate is measured against.
    var waitAt = {};
    CFG.positions.forEach(function (pos) {
      waitAt[pos] = expectedBest(pos, next, ids, pool, now);
    });

    cands.forEach(function (c) {
      var after = ids.concat([c.i]);
      var best = 0, bestPos = null;
      CFG.positions.forEach(function (pos) {
        var e = expectedBest(pos, next, after, pool.filter(function (x) { return x !== c.i; }), now);
        if (e > best) { best = e; bestPos = pos; }
      });
      c.next = best;
      c.nextPos = bestPos;
      c.score = c.now + best;
      c.wait = c.now - waitAt[P[c.i][POS]];      // cost of not taking him now
      c.surv = survives(c.i, next, now);
    });
    cands.sort(function (a, b) { return b.score - a.score; });

    // The best available at each position now, against what that position
    // should still be worth at the next pick. The difference is the whole
    // strategic question - which board is about to thin out, and which will
    // keep. It is what the pair-scoring above is deciding with, shown plainly.
    var byPos = {};
    CFG.positions.forEach(function (pos) {
      var best = null;
      for (var n = 0; n < cands.length; n++) {
        if (P[cands[n].i][POS] === pos) { best = cands[n]; break; }
      }
      if (!best) {
        for (var m = 0; m < pool.length; m++) {
          if (P[pool[m]][POS] === pos) {
            best = { i: pool[m], now: marginal(pool[m], ids, base) };
            break;
          }
        }
      }
      if (best) byPos[pos] = { best: best, later: waitAt[pos] };
    });
    return { list: cands, now: now, next: next, byPos: byPos };
  }

  // ------------------------------------------------------------------ context
  /** How many players are left in this player's tier at his position. */
  function tierLeft(i) {
    var taken = takenSet(), n = 0;
    for (var k = 0; k < P.length; k++) {
      if (P[k][POS] === P[i][POS] && P[k][TIER] === P[i][TIER] && !taken[P[k][YID]]) n++;
    }
    return n;
  }

  /** Positions taken more often than their share over the last two rounds. */
  function runs() {
    var recent = state.picks.slice(-RUN_WINDOW), counts = {};
    recent.forEach(function (p) {
      var idx = byId[p.id];
      if (idx === undefined) return;
      counts[P[idx][POS]] = (counts[P[idx][POS]] || 0) + 1;
    });
    return { counts: counts, n: recent.length };
  }

  /** Bye weeks my starters already stack on, by position. */
  function byeClash(i) {
    var ids = myRoster(), pos = P[i][POS], bye = P[i][BYE], same = 0;
    if (!bye) return 0;
    ids.forEach(function (k) { if (P[k][POS] === pos && P[k][BYE] === bye) same++; });
    return same;
  }
"""

_RENDER = r"""
  // ------------------------------------------------------------------ helpers
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function n0(v) { return v === null || v === undefined ? "-" : Math.round(v); }
  function n1(v) { return v === null || v === undefined ? "-" : v.toFixed(1); }
  function pct(v) { return Math.round(v * 100) + "%"; }
  function el(id) { return document.getElementById(id); }

  function posTag(pos, rank) {
    return '<span class="pos-tag pos-' + pos + '">' + pos + (rank || "") + "</span>";
  }

  /** The school's mark, off the ESPN id the schedule pages already key on. */
  function schoolLogo(i) {
    var id = P[i][ESPN];
    if (!id) return "";
    return '<img class="ld-slogo" loading="lazy" alt="" '
      + 'src="https://a.espncdn.com/i/teamlogos/ncaa/500/' + esc(id) + '.png">';
  }

  // --------------------------------------------------------------- pick entry
  function draft(i, atPick) {
    var pick = atPick || onClock();
    if (pick > totalPicks()) return;
    state.picks = state.picks.filter(function (p) { return p.id !== P[i][YID]; });
    state.picks.push({ pick: pick, id: P[i][YID], manual: true });
    state.picks.sort(function (a, b) { return a.pick - b.pick; });
    renumber();
    save();
    render();
  }
  function undo() {
    if (!state.picks.length) return;
    state.picks.pop();
    save();
    render();
  }
  /** Someone drafted a player this board does not list (it carries Yahoo's
   *  top 500; the pool runs deeper). The pick still has to be counted, or
   *  every pick after it lands on the wrong roster. */
  function skipPick() {
    var pick = onClock();
    if (pick > totalPicks()) return;
    state.picks.push({ pick: pick, id: "off-" + pick, manual: true });
    save();
    render();
  }
  function reset() {
    if (!confirm("Clear every pick on this board?")) return;
    state.picks = [];
    save();
    render();
  }
  /** Picks are a dense sequence; a hand-entered one out of order closes up. */
  function renumber() {
    state.picks.forEach(function (p, k) { p.pick = k + 1; });
  }

  // --------------------------------------------------------------- live feed
  /** What the board is showing, in one string. The poll runs every few seconds
   *  and Yahoo answers it whether or not a pick has landed; re-rendering on
   *  every answer would rebuild the recommendations, the table and the grid
   *  once a heartbeat - which on a phone is a visible stall, and which throws
   *  away the reader's scroll position and whatever they were typing. */
  function signature() {
    return state.picks.length + "|"
      + state.picks.map(function (p) { return p.id; }).join(",");
  }

  function applyFeed(data) {
    var before = signature();
    state.source = data.source || "none";
    state.fetched = data.fetched || Date.now();

    if (data.picks && data.picks.length) {
      // Yahoo is publishing the draft itself: it wins outright, its pick
      // numbers are the truth, and it also says who is sitting in which slot.
      // A pick of a player this board does not carry keeps its pick with the
      // id Yahoo gave it - dropping it and closing up would hand every later
      // pick to the wrong roster, and the snake would be lying from there on.
      var mapped = [], seen = {}, last = 0;
      data.picks.forEach(function (p) {
        if (!p.pick) return;
        mapped.push({ pick: p.pick, id: p.player_id, team: p.team_key });
        seen[p.player_id] = true;
        if (p.pick > last) last = p.pick;
        if (p.team_key && p.round === 1) state.slotOf[p.team_key] = slotOfPick(p.pick);
      });
      // Anything typed in that Yahoo has not caught up to yet stays, after.
      state.picks.filter(function (p) { return p.manual && !seen[p.id]; })
        .forEach(function (p) { mapped.push({ pick: ++last, id: p.id, manual: true }); });
      state.picks = mapped;
      save();
      return signature() !== before;
    }

    // No pick list. Rosters or the taken-players feed still tell us who is off
    // the board, which is most of what the recommendations need; the order is
    // then a guess, so hand-entered picks keep their place ahead of it.
    var ids = [];
    if (data.rosters) {
      for (var key in data.rosters) {
        data.rosters[key].forEach(function (id) { ids.push({ id: id, team: key }); });
      }
    }
    if (!ids.length && data.taken) {
      data.taken.forEach(function (id) { ids.push({ id: id, team: null }); });
    }
    if (!ids.length) return false;

    var have = {};
    state.picks.forEach(function (p) { have[p.id] = true; });
    var added = 0;
    ids.forEach(function (x) {
      // A player this board does not carry still occupies a pick; skipping
      // him would put the count of picks made - and whose turn it is - wrong.
      if (have[x.id]) return;
      state.picks.push({ pick: state.picks.length + 1, id: x.id, team: x.team });
      have[x.id] = true;
      added++;
    });
    if (added) { renumber(); save(); }
    return signature() !== before;
  }

  function pull() {
    if (!state.auto) return Promise.resolve();
    return fetch("/api/cfb-draft?t=" + Date.now(), { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        state.error = null;
        if (applyFeed(data)) render(); else renderStatus();
      })
      .catch(function (err) {
        state.error = String(err && err.message || err);
        renderStatus();
      });
  }

  // ------------------------------------------------------------------ status
  function ago(ms) {
    if (!ms) return "never";
    var s = Math.round((Date.now() - ms) / 1000);
    return s < 60 ? s + "s ago" : Math.round(s / 60) + "m ago";
  }

  function renderStatus() {
    var pick = onClock(), done = pick > totalPicks();
    var slot = slotOfPick(pick), mine = mySlot() && slot === mySlot();
    var sourceText = {
      draftresults: "following Yahoo's draft feed",
      rosters: "following Yahoo rosters",
      taken: "following Yahoo's taken list",
      none: "no live feed yet - picks are the ones entered here",
    }[state.source] || "";

    el("ld-status").innerHTML = done
      ? '<span class="ld-pill">Draft complete</span>'
      : '<span class="ld-pill' + (mine ? " mine" : " live") + '">'
        + (mine ? "Your pick" : "On the clock") + "</span>"
        + '<span class="ld-clock">' + label(pick) + " &middot; overall " + pick + "</span>"
        + '<span class="ld-note">' + logoOfSlot(slot) + esc(nameOfSlot(slot)) + "</span>";

    el("ld-feed").innerHTML =
      '<span class="ld-note">' + esc(sourceText)
      + (state.auto ? " &middot; checked " + ago(state.fetched) : " &middot; auto-sync off")
      + (state.error ? " &middot; last check failed" : "") + "</span>";
  }

  // --------------------------------------------------------- recommendations
  function chips(c) {
    var out = [], i = c.i, r = P[i];
    var left = tierLeft(i);
    if (left <= 3) {
      out.push('<span class="ld-chip warn">' + r[POS] + " tier " + r[TIER] + ": "
        + left + " left</span>");
    }
    if (c.surv < 0.35) {
      out.push('<span class="ld-chip warn">' + pct(c.surv) + " to last</span>");
    } else if (c.surv > 0.75) {
      out.push('<span class="ld-chip good">' + pct(c.surv) + " to last</span>");
    }
    if (r[ADP] !== null) {
      var gap = c.pickNow - r[ADP];        // picks he has lasted past his ADP
      if (gap >= 10) out.push('<span class="ld-chip good">' + Math.round(gap)
        + " past ADP " + n1(r[ADP]) + "</span>");
      else if (gap <= -10) out.push('<span class="ld-chip warn">' + Math.round(-gap)
        + " ahead of ADP " + n1(r[ADP]) + "</span>");
    }
    if (r[PLAYOFF] !== null && r[PLAYOFF] >= 1.06) {
      out.push('<span class="ld-chip good">playoff schedule</span>');
    } else if (r[PLAYOFF] !== null && r[PLAYOFF] <= 0.92) {
      out.push('<span class="ld-chip warn">hard weeks ' + CFG.playoffWeek + "-"
        + CFG.endWeek + "</span>");
    }
    var clash = byeClash(i);
    if (clash) {
      out.push('<span class="ld-chip warn">' + (clash + 1) + " " + r[POS]
        + "s on bye week " + r[BYE] + "</span>");
    }
    var run = runs();
    if (run.n >= 6 && (run.counts[r[POS]] || 0) / run.n >= 0.42) {
      out.push('<span class="ld-chip warn">' + (run.counts[r[POS]] || 0) + " of last "
        + run.n + " were " + r[POS] + "</span>");
    }
    return out.join("");
  }

  function why(c, best) {
    var r = P[c.i], parts = [];
    var lead = "Worth <b>" + n0(c.now) + "</b> to your lineup now";
    if (c.wait > 4) {
      lead += ", <b>" + n0(c.wait) + "</b> more than the best " + r[POS]
        + " you should expect at " + label(c.pickNext);
    } else if (c.wait < -4) {
      lead += ", but the " + r[POS] + " pool holds up &mdash; waiting costs about "
        + n0(-c.wait);
    }
    parts.push(lead);
    if (c.nextPos) {
      parts.push("Take him and " + label(c.pickNext) + " still lands a "
        + c.nextPos + " worth about <b>" + n0(c.next) + "</b>");
    }
    if (best && c !== best) {
      parts.push("<i>" + n0(best.score - c.score) + " behind the top pair</i>");
    }
    return parts.join(". ") + ".";
  }

  function renderRecs() {
    var out = recommend();
    var wrap = el("ld-recs");
    if (!out.list.length) {
      wrap.innerHTML = '<p class="ld-note">Every player on the board is gone.</p>';
      return;
    }
    out.list.forEach(function (c) { c.pickNow = out.now; c.pickNext = out.next; });
    var top = out.list[0], seen = {}, cards = [];
    out.list.forEach(function (c) {
      var pos = P[c.i][POS];
      if (cards.length >= 5 || (seen[pos] || 0) >= 2) return;
      seen[pos] = (seen[pos] || 0) + 1;
      cards.push(c);
    });
    wrap.innerHTML = cards.map(function (c, k) {
      var r = P[c.i];
      return '<div class="ld-rec' + (k === 0 ? " top" : "") + '">'
        + '<div class="hd"><span class="nm">' + esc(r[NAME]) + "</span>"
        + posTag(r[POS], r[POSRK]) + '<span class="sub">' + schoolLogo(c.i)
        + esc(r[TEAM]) + " &middot; bye " + (r[BYE] || "-") + "</span>"
        + '<span class="edge">' + n0(c.score) + "</span></div>"
        + '<div class="chips">' + chips(c) + "</div>"
        + '<p class="why">' + why(c, top) + "</p>"
        + '<button data-take="' + c.i + '">'
        + (out.now === onClock() ? "Draft at " : "Mark taken at ")
        + label(onClock()) + "</button>"
        + "</div>";
    }).join("");

    renderPositions(out);

    el("ld-recs-note").innerHTML =
      "Scored as a pair: what he adds to your starting lineup at <b>" + label(out.now)
      + "</b>, plus the best your roster should expect at <b>" + label(out.next)
      + "</b> once he is on it. Replacement level is this league's own &mdash; "
      + Object.keys(CFG.replacement).map(function (p) {
        return p + " " + Math.round(CFG.replacement[p]);
      }).join(", ") + " points.";
  }
"""

_RENDER2 = r"""
  /** One row per position: the best there is now, what the position should
   *  still be worth at the next pick, and the gap between them. */
  function renderPositions(out) {
    var rows = CFG.positions.map(function (pos) {
      var x = out.byPos[pos];
      if (!x) return "";
      var cost = x.best.now - x.later;
      // "Holds" is the useful answer, not a rounded zero: it means this is the
      // position to leave alone, which is a decision.
      var cls = cost >= 15 ? "warn" : cost < 4 ? "good" : "";
      var text = cost < 4 ? "holds" : "&minus;" + n0(cost);
      return "<tr><td>" + posTag(pos, "") + "</td>"
        + '<td class="nm">' + esc(P[x.best.i][NAME]) + " "
        + '<span class="ld-note">' + schoolLogo(x.best.i)
        + esc(P[x.best.i][TEAM]) + "</span></td>"
        + '<td class="v">' + n0(x.best.now) + "</td>"
        + "<td>" + n0(x.later) + "</td>"
        + '<td><span class="ld-chip ' + cls + '">' + text + "</span></td>"
        + '<td><button class="ld-take" data-take="' + x.best.i + '">+</button></td></tr>';
    }).join("");
    el("ld-positions").innerHTML =
      '<table class="ld-avail"><thead><tr><th>Pos</th><th>Best available</th>'
      + '<th title="What he adds to your lineup right now">Now</th>'
      + '<th title="What this position should still be worth at your next pick">'
      + "At " + label(out.next) + "</th>"
      + '<th title="What waiting on this position costs">Wait</th><th></th>'
      + "</tr></thead><tbody>" + rows + "</tbody></table>";
  }

  // ------------------------------------------------------- best available
  // One value per sortable column; the comparator applies the direction and
  // keeps blanks (an ADP nobody has) at the bottom whichever way it points.
  // Ties keep the underlying board order, which is VORP - so sorting by tier
  // lists each tier best-first rather than shuffled.
  var SORT_VALS = {
    score: function (c) { return c.m; },
    vorp: function (c) { return P[c.i][VORP]; },
    proj: function (c) { return P[c.i][PROJ]; },
    ceiling: function (c) { return P[c.i][CEIL]; },
    floor: function (c) { return P[c.i][FLOOR]; },
    tier: function (c) { return P[c.i][TIER]; },
    adp: function (c) { return P[c.i][ADP]; },
    surv: function (c) { return c.s; },
  };
  // Columns whose best reading is smallest-first; the rest lead with biggest.
  var SORT_ASC = { adp: true, tier: true, surv: true };

  function compare() {
    var val = SORT_VALS[state.sort] || SORT_VALS.score;
    var asc = !!SORT_ASC[state.sort];
    if (state.sortFlip) asc = !asc;
    return function (a, b) {
      var x = val(a), y = val(b);
      if (x === null || x === undefined) return 1;
      if (y === null || y === undefined) return -1;
      if (x === y) return 0;
      return (x < y) === asc ? -1 : 1;
    };
  }

  function sortBy(key) {
    state.sortFlip = state.sort === key && !state.sortFlip;
    state.sort = key;
    el("ld-sort").value = key;
    renderAvail();
  }

  function markSortHeads() {
    var asc = !!SORT_ASC[state.sort];
    if (state.sortFlip) asc = !asc;
    document.querySelectorAll("th[data-sortkey]").forEach(function (th) {
      th.classList.remove("sort-asc", "sort-desc");
      if (th.dataset.sortkey === state.sort) {
        th.classList.add(asc ? "sort-asc" : "sort-desc");
      }
    });
  }

  function renderAvail() {
    var ids = myRoster(), base = lineupValue(ids);
    var picks = myPicks(), now = picks[0], next = picks[1];
    var q = state.query.toLowerCase();

    var list = availableIdx().filter(function (i) {
      if (state.pos !== "ALL" && P[i][POS] !== state.pos) return false;
      if (q && (P[i][NAME] + " " + P[i][TEAM] + " " + P[i][SCHOOL]).toLowerCase()
        .indexOf(q) < 0) return false;
      return true;
    }).map(function (i) {
      return { i: i, m: marginal(i, ids, base), s: survives(i, next, now) };
    });
    list.sort(compare());
    markSortHeads();

    // Replacing the rows resets the scroller, and during a draft this list is
    // being scrolled and tapped continuously - losing the reader's place on
    // every pick is the difference between usable and not.
    var scroller = document.querySelector(".ld-scroll");
    var top = scroller ? scroller.scrollTop : 0;

    var shown = list.slice(0, 120);
    el("ld-avail-body").innerHTML = shown.length ? shown.map(function (c) {
      var r = P[c.i];
      return "<tr>"
        + '<td class="nm">' + esc(r[NAME]) + "</td>"
        + "<td>" + posTag(r[POS], r[POSRK]) + "</td>"
        + '<td class="tm" title="' + esc(r[SCHOOL] || "") + '">' + schoolLogo(c.i)
        + esc(r[TEAM] || "-") + "</td>"
        + "<td>" + (r[BYE] || "-") + "</td>"
        + '<td class="v">' + n0(r[PROJ]) + "</td>"
        + "<td>" + n0(r[FLOOR]) + "&ndash;" + n0(r[CEIL]) + "</td>"
        + '<td class="v">' + n0(r[VORP]) + "</td>"
        + "<td>" + n0(c.m) + "</td>"
        + "<td>" + r[TIER] + "</td>"
        + "<td>" + (r[ADP] === null ? "-" : n1(r[ADP])) + "</td>"
        + "<td>" + pct(c.s) + "</td>"
        + '<td><button class="ld-take" data-take="' + c.i + '">+</button></td>'
        + "</tr>";
    }).join("") : '<tr><td colspan="12" class="ld-note">No players match.</td></tr>';

    if (scroller) scroller.scrollTop = top;

    el("ld-avail-count").textContent = "Showing " + shown.length + " of " + list.length
      + " available" + (state.pos === "ALL" ? "" : " at " + state.pos)
      + " · survival is to " + label(next) + ".";
  }

  // ------------------------------------------------------------- my lineup
  function lineupRows() {
    var ids = myRoster(), pools = {};
    ids.forEach(function (i) { (pools[P[i][POS]] = pools[P[i][POS]] || []).push(i); });
    for (var p in pools) {
      pools[p].sort(function (a, b) { return P[b][PROJ] - P[a][PROJ]; });
    }
    var used = {}, rows = [], flexN = 0, starters = [];
    CFG.slots.forEach(function (s) {
      if (s[0] === CFG.flexSlot) { flexN += s[1]; return; }
      for (var c = 0; c < s[1]; c++) {
        var pool = pools[s[0]] || [], at = used[s[0]] || 0;
        var who = at < pool.length ? pool[at] : null;
        used[s[0]] = at + 1;
        rows.push([s[0], who]);
        if (who !== null) starters.push(who);
      }
    });
    for (var f = 0; f < flexN; f++) {
      var best = null, bestPos = null;
      CFG.flexPositions.forEach(function (pos) {
        var pool = pools[pos] || [], at = used[pos] || 0;
        if (at < pool.length && (best === null || P[pool[at]][PROJ] > P[best][PROJ])) {
          best = pool[at]; bestPos = pos;
        }
      });
      if (best !== null) { used[bestPos]++; starters.push(best); }
      rows.push([CFG.flexSlot, best]);
    }
    var bench = ids.filter(function (i) { return starters.indexOf(i) < 0; })
      .sort(function (a, b) { return P[b][PROJ] - P[a][PROJ]; });
    return { rows: rows, bench: bench, ids: ids };
  }

  function renderLineup() {
    var mine = null;
    for (var t = 0; t < CFG.teams.length; t++) {
      if (CFG.teams[t].key === state.myTeam) mine = CFG.teams[t];
    }
    el("ld-my-logo").innerHTML = mine && mine.logo
      ? '<img class="ld-tlogo" src="' + esc(mine.logo) + '" alt="">' : "";
    var lu = lineupRows();
    var body = lu.rows.map(function (row) {
      var slot = row[0], i = row[1];
      if (i === null) {
        return '<tr class="empty"><td class="slot">' + slot
          + '</td><td>&mdash;</td><td class="pts"></td></tr>';
      }
      return '<tr><td class="slot">' + slot + "</td><td>" + esc(P[i][NAME])
        + ' <span class="ld-note">' + P[i][POS] + " · " + schoolLogo(i)
        + esc(P[i][TEAM]) + " · bye " + (P[i][BYE] || "-")
        + '</span></td><td class="pts">' + n0(P[i][PROJ]) + "</td></tr>";
    }).join("");
    var bench = lu.bench.map(function (i) {
      return '<tr><td class="slot">BN</td><td>' + esc(P[i][NAME])
        + ' <span class="ld-note">' + P[i][POS] + " · " + schoolLogo(i)
        + esc(P[i][TEAM]) + '</span></td><td class="pts">' + n0(P[i][PROJ])
        + "</td></tr>";
    }).join("");
    el("ld-lineup").innerHTML = '<table class="ld-lineup">' + body + bench + "</table>";

    // What the roster is short of: the slots still empty, and the byes stacking.
    var empty = {}, byes = {};
    lu.rows.forEach(function (row) { if (row[1] === null) empty[row[0]] = (empty[row[0]] || 0) + 1; });
    lu.ids.forEach(function (i) {
      if (P[i][BYE]) byes[P[i][BYE]] = (byes[P[i][BYE]] || 0) + 1;
    });
    var needs = Object.keys(empty).map(function (k) { return empty[k] + " " + k; });
    var stack = Object.keys(byes).filter(function (w) { return byes[w] >= 3; })
      .map(function (w) { return byes[w] + " on bye week " + w; });
    var over = lineupValue(lu.ids) - EMPTY_LINEUP;
    el("ld-need").innerHTML =
      "<b>" + (over > 0 ? "+" : "") + n0(over) + "</b> over a replacement lineup"
      + (needs.length ? " &middot; still to fill: <b>" + needs.join(", ") + "</b>"
        : " &middot; <b>lineup full</b>")
      + " &middot; " + lu.ids.length + " of " + CFG.rounds + " roster spots"
      + (stack.length ? " &middot; <b>" + stack.join("; ") + "</b>" : "");
  }

  // ---------------------------------------------------------------- the board
  function renderGrid() {
    var byPick = {};
    state.picks.forEach(function (p) { byPick[p.pick] = p; });
    var mine = mySlot(), current = onClock();
    var head = "<tr><th></th>";
    for (var s = 1; s <= nTeams(); s++) {
      head += '<th data-slot="' + s + '" title="Click if this column is yours"'
        + (s === mine ? ' class="mine-col"' : "") + ">"
        + logoOfSlot(s) + esc(nameOfSlot(s)) + "</th>";
    }
    head += "</tr>";

    var body = "";
    for (var r = 1; r <= CFG.rounds; r++) {
      body += "<tr><th>" + r + "</th>";
      for (var slot = 1; slot <= nTeams(); slot++) {
        var no = pickAt(r, slot), p = byPick[no];
        var idx = p ? byId[p.id] : undefined;
        var cls = [];
        if (idx !== undefined) cls.push("p-" + P[idx][POS]);
        if (no === current) cls.push("on");
        if (slot === mine) cls.push("mine");
        body += '<td class="' + cls.join(" ") + '"><span class="pk">' + label(no) + "</span>"
          + (idx !== undefined
            ? '<span class="pl">' + esc(P[idx][NAME]) + "</span>"
            : p ? '<span class="pl">(off board)</span>' : "") + "</td>";
      }
      body += "</tr>";
    }
    el("ld-grid").innerHTML = head + body;
  }

  // ------------------------------------------------------------------- wiring
  function render() {
    DRIFT = adpDrift();
    renderStatus();
    renderRecs();
    renderAvail();
    renderLineup();
    renderGrid();
  }
"""

_WIRE = r"""
  function bind() {
    document.addEventListener("click", function (ev) {
      var take = ev.target.closest && ev.target.closest("[data-take]");
      if (take) { draft(+take.dataset.take); return; }
      var sk = ev.target.closest && ev.target.closest("th[data-sortkey]");
      if (sk) { sortBy(sk.dataset.sortkey); return; }
      var pos = ev.target.closest && ev.target.closest("[data-pos]");
      if (pos) {
        state.pos = pos.dataset.pos;
        document.querySelectorAll("[data-pos]").forEach(function (b) {
          b.classList.toggle("active", b === pos);
        });
        renderAvail();
      }
    });

    el("ld-search").addEventListener("input", function (e) {
      state.query = e.target.value; renderAvail();
    });
    el("ld-sort").addEventListener("change", function (e) {
      state.sort = e.target.value; state.sortFlip = false; renderAvail();
    });
    el("ld-team").addEventListener("change", function (e) {
      state.myTeam = e.target.value || null;
      state.mySlot = null;              // the order decides the slot again
      save(); render();
    });

    // The one way left to say "the recorded order is wrong, this column is
    // me". The slot menu that used to do it was a second control asking the
    // same question the team menu already answers, and on a phone it was two
    // taps of clutter on the row that matters most.
    el("ld-grid").addEventListener("click", function (ev) {
      var th = ev.target.closest && ev.target.closest("th[data-slot]");
      if (!th) return;
      var slot = +th.dataset.slot;
      state.mySlot = mySlot() === slot ? null : slot;
      save(); render();
    });
    el("ld-auto").addEventListener("click", function () {
      state.auto = !state.auto;
      el("ld-auto").classList.toggle("on", state.auto);
      el("ld-auto").textContent = state.auto ? "Auto-sync on" : "Auto-sync off";
      save();
      if (state.auto) pull();
      else renderStatus();
    });
    el("ld-undo").addEventListener("click", undo);
    el("ld-skip").addEventListener("click", skipPick);
    el("ld-reset").addEventListener("click", reset);

    // On draft night this tab shares a phone with Yahoo's draft client, and a
    // hidden tab polls slowly. Coming back should not mean thirty seconds of
    // stale board with a pick clock running.
    document.addEventListener("visibilitychange", function () {
      if (!document.hidden) pull();
    });

    document.addEventListener("keydown", function (e) {
      if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
      if (e.key === "u") undo();
      if (e.key === "/") { e.preventDefault(); el("ld-search").focus(); }
    });
  }

  function fillControls() {
    var opts = ['<option value="">Your team…</option>'].concat(
      CFG.teams.map(function (t) {
        return '<option value="' + esc(t.key) + '"'
          + (state.myTeam === t.key ? " selected" : "") + ">" + esc(t.name) + "</option>";
      }));
    el("ld-team").innerHTML = opts.join("");
    el("ld-auto").classList.toggle("on", state.auto);
    el("ld-auto").textContent = state.auto ? "Auto-sync on" : "Auto-sync off";
  }

  // The poll is fast while a draft is running and slow when one is not; a page
  // left open overnight should not hammer the proxy for eight hours.
  function interval() {
    if (!state.auto) return 30000;
    if (onClock() > totalPicks()) return 120000;
    if (document.hidden) return 30000;
    return state.picks.length ? 6000 : 15000;
  }
  function loop() {
    pull().then(function () { setTimeout(loop, interval()); });
  }

  restore();
  fillControls();
  bind();
  render();
  loop();
  setInterval(renderStatus, 5000);
})();
"""


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #

_SORTS = [("score", "Fit with my roster"), ("vorp", "Value over replacement"),
          ("proj", "Projected points"), ("ceiling", "Ceiling"),
          ("floor", "Floor"), ("tier", "Tier"), ("adp", "Yahoo ADP"),
          ("surv", "Least likely to last")]

# (label, tooltip, sort key or None). A keyed column sorts on click, its
# natural direction first, reversed on a second click; the Range column sorts
# by ceiling since that is the number the eye reads it for.
_AVAIL_HEADERS = [
    ("Player", "Player", None),
    ("Pos", "Position, and his rank in it on this board", None),
    ("Team", "School", None), ("Bye", "Bye week", None),
    ("Proj", "Projected season points in this league's scoring", "proj"),
    ("Range", "20th to 80th percentile of where he finishes; sorts by ceiling",
     "ceiling"),
    ("VORP", "Points above the last player nobody has to start", "vorp"),
    ("Fit", "What he adds to your starting lineup as it stands", "score"),
    ("Tier", "Tier at his position; a new tier is a cliff in the curve", "tier"),
    ("ADP", "Yahoo's average draft pick, across every college league it runs",
     "adp"),
    ("Last?", "Chance he is still there at your next pick", "surv"),
    ("", "Mark him drafted at the pick on the clock", None),
]


def _setup_bar() -> str:
    return (
        '<div class="ld-bar">'
        '<select id="ld-team" aria-label="Your team"></select>'
        '<button id="ld-auto" type="button">Auto-sync</button>'
        '<button id="ld-undo" type="button" title="Undo the last pick (u)">Undo</button>'
        '<button id="ld-skip" type="button" title="Record a pick of a player this '
        'board does not list, so later picks stay on the right rosters">'
        'Off-board pick</button>'
        '<button id="ld-reset" type="button">Clear</button>'
        '<span class="ld-note">Picks and settings stay in this browser.</span>'
        "</div>"
        '<div class="ld-bar" id="ld-statusbar">'
        '<span id="ld-status"></span><span id="ld-feed"></span></div>')


def _recs_section() -> str:
    return (
        "<h2>What To Do With This Pick</h2>"
        '<p id="ld-recs-note" class="ld-note"></p>'
        '<div class="ld-recs" id="ld-recs"></div>'
        '<div class="ld-panel" id="ld-positions-panel">'
        "<h3>Where The Board Is About To Thin Out</h3>"
        '<div class="body"><div id="ld-positions"></div>'
        '<p class="ld-note">The best player available at each position, what he '
        "adds to your lineup now, and what that position should still be worth "
        "when your next pick comes round. A big <b>Wait</b> number is a position "
        "that is about to get worse; a small one is a position you can leave "
        "alone.</p></div></div>")


def _available_section() -> str:
    chips = "".join(
        f'<button class="adp-pos{" active" if p == "ALL" else ""}" data-pos="{p}">{p}</button>'
        for p in ["ALL"] + POSITIONS)
    sorts = "".join(f'<option value="{key}">{label}</option>' for key, label in _SORTS)
    head = "".join(
        f'<th title="{tip}"' + (f' data-sortkey="{key}"' if key else "") + f'>{label}</th>'
        for label, tip, key in _AVAIL_HEADERS)
    return (
        '<div class="ld-panel"><h3>Best Available</h3><div class="body">'
        f'<div class="adp-controls">{chips}</div>'
        '<div class="adp-controls">'
        '<input id="ld-search" type="search" placeholder="Search player or school (/)">'
        f'<select id="ld-sort" aria-label="Sort by">{sorts}</select></div>'
        '<p class="ld-note" id="ld-avail-count"></p>'
        '<div class="ld-scroll"><table class="ld-avail"><thead><tr>'
        f'{head}</tr></thead><tbody id="ld-avail-body"></tbody></table></div>'
        "</div></div>")


def _roster_section() -> str:
    return ('<div class="ld-panel"><h3><span id="ld-my-logo"></span>Your Roster</h3>'
            '<div class="body">'
            '<div id="ld-lineup"></div><p class="ld-need" id="ld-need"></p>'
            "</div></div>")


def _grid_section() -> str:
    return ('<h2>The Board</h2>'
            '<p class="ld-note">Every pick of the draft, coloured by position. '
            'Your column is marked; the outlined cell is on the clock.</p>'
            '<div class="table-scroll"><table class="ld-grid" id="ld-grid"></table></div>')


def _how_it_works(board: pd.DataFrame, league: dict) -> str:
    levels = projections.replacement_levels(board, league)
    starters = projections.starter_demand(league)
    qb = starters["dedicated"]["QB"]
    counts = board["pos"].value_counts()
    return (
        "<h3>How the numbers are made</h3>"
        "<p><b>Projections.</b> Yahoo ranks the college pool but publishes no "
        "projections for it, so the points come from real seasons: every FBS "
        "player at a school this game covers, scored under this league's own "
        "modifiers, sorted by position. That curve says what a WR12 or a QB8 is "
        "worth. A player is then valued not at the curve's reading for his rank "
        "but at its <i>average over where he might actually finish</i> &mdash; "
        "which is what stops the first round from being priced as a certainty, "
        "and is where the floor and ceiling columns come from.</p>"
        "<p><b>Replacement level.</b> From this league's roster, not a generic "
        f"one. {qb} starting quarterback slots across {LEAGUE_TEAMS} teams puts "
        f"quarterback replacement at <b>{levels['QB']:.0f}</b> points, against "
        f"<b>{levels['RB']:.0f}</b> at running back, <b>{levels['WR']:.0f}</b> at "
        f"receiver, <b>{levels['TE']:.0f}</b> at tight end and "
        f"<b>{levels['DEF']:.0f}</b> at defense. Two starting quarterbacks and "
        "6-point passing touchdowns are why this board wants them earlier than "
        "Yahoo's average draft pick does. That ADP is one number for the whole "
        "college game, pooled across every league Yahoo runs whatever their "
        "settings &mdash; so it prices a quarterback for the average league, "
        "not for this one, and the gap is the edge.</p>"
        "<p><b>This site's game model.</b> The predictions page already forecasts "
        "every score of the season, so the board knows which offences are about "
        "to be good and whose schedule is soft in weeks "
        f"{league.get('playoff_start_week')}&ndash;{league.get('end_week')}. It is "
        "applied as a tilt of at most a tenth either way, because Yahoo's rank is "
        "not ignorant of it either. Team defenses are the exception: most of what "
        "one scores is decided by what its opponents score, which the model "
        "predicts outright, so their projections are built from it rather than "
        "from a rank.</p>"
        "<p><b>The recommendation.</b> Not the best player left. For every "
        "candidate it works out what he adds to the starting lineup you already "
        "have, then what your <i>next</i> pick should expect to land with him "
        "already on the roster &mdash; using each remaining player's odds of "
        "surviving that long, from his average pick and how often he goes "
        "undrafted at all. The pair with the best total wins. That is what turns "
        "\"he is the highest ranked\" into \"take the quarterback, the running "
        "backs will still be here\".</p>"
        f"<p><b>What is not on this board.</b> Yahoo ranks team offence units, "
        "and this league has no slot to start one, so they are dropped and every "
        "rank below them closed up &mdash; a player Yahoo shows at 150 is really "
        f"going a few picks sooner than that here. {len(board)} players remain: "
        + ", ".join(f"{int(counts.get(p, 0))} {p}" for p in POSITIONS) + ".</p>")


def body() -> str:
    league = yahoo.league()
    board = projections.value_board()
    # ESPN team id per school, for the logo CDN the rest of the section uses.
    board["espn"] = board["school"].map(schools_mod.espn_ids())
    payload = json.dumps(config(board, league), separators=(",", ":"))
    script = ("{% raw %}<script>window.LD_CFG=" + payload + ";</script>"
              "<script>" + _ENGINE + _RENDER + _RENDER2 + _WIRE + "</script>{% endraw %}")

    when = pd.Timestamp(league["draft_time"], unit="s", tz="UTC").tz_convert(LEAGUE_TZ)
    return (
        _CSS
        + '{% include countdown.html key="cfb" %}'
        + f'<p>The <a href="{league["url"]}">{league["name"]}</a> draft, live: '
        f'{league["num_teams"]} teams, {config(board, league)["rounds"]} rounds, '
        f'{when.strftime("%A %B %-d at %-I:%M %p %Z")}. The order is already set, so '
        "the board knows whose pick is on the clock and which column is yours. "
        "It follows the draft from Yahoo if Yahoo will say, and from what you "
        "tap here either way.</p>"
        + _setup_bar()
        + _recs_section()
        + '<div class="ld-cols">' + _available_section() + _roster_section() + "</div>"
        + _grid_section()
        + '<details class="section"><summary>How this board decides</summary>'
        + _how_it_works(board, league) + "</details>"
        + script)


def generate():
    write_page(OUTPUT, f"CFB Live Draft {SEASON}", body())


if __name__ == "__main__":
    generate()
