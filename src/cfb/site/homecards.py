"""
The two CFB graphics on the homepage (docs/_includes/cfb_top25.html and
cfb_bets.html).

The homepage is written by cbb.render.render_home, which has no business
importing the football model, so this follows the pattern cfb.site.countdown
set: the CFB build writes an include, and the homepage includes it. Both are
plain HTML with their own <style> block, so nothing has to be added to the
site theme for one card.

  Top 25    the three rankings side by side - ours, the AP poll and ESPN's
            FPI - ordered by where they agree, so the rows that disagree are
            the point of the table rather than a footnote.
  Best bets one spread bet and a short parlay, taken from the model's widest
            disagreements with the book and frozen for the week the morning
            of its first kickoff. What that is worth is printed on the card:
            see the note below.

    python -m cfb.site.homecards
"""
from datetime import datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

import pandas as pd

from cfb import espn, games as games_mod, predict, results
from cfb import odds as odds_mod
from cfb.config import DATA_DIR, SEASON
from cfb.site import power, teams as teams_page
from gordstats import logos, paths, share_button

ET = ZoneInfo("America/New_York")
TOP25_OUT = paths.DOCS / "_includes" / "cfb_top25.html"
BETS_OUT = paths.DOCS / "_includes" / "cfb_bets.html"
BETS_DIR = DATA_DIR / "best_bets"
# How far apart the sources have to be before a team is marked high/low. One
# place is not an opinion.
MARK_GAP = 3

# The picks are frozen from this hour on the day of the week's first kickoff -
# "Thursday morning" for a normal week, and the right morning for the weeks
# that open on a Tuesday. Before it the card shows what it would take and says
# so; after it the file on disk is the card, whatever the model later thinks.
LOCK_HOUR = 9

# A disagreement worth pricing, in points. Same gate as the predictions page's
# scored record (cfb.results.BET_MIN), so the record printed on this card is
# the record of exactly these picks.
EDGE_MIN = results.BET_MIN
# And the widest worth believing. Every FBS team has its own rating; the whole
# of the FCS shares one bucket, so a game against it is priced by a number that
# was never fitted to that opponent - which is how a first cut of this card
# came back holding four 30-point disagreements, all of them cupcakes. Those
# games are dropped outright, and a disagreement bigger than this on a real
# matchup is treated as a modelling artefact rather than a bet.
EDGE_MAX = 10
PARLAY_LEGS = 3

_CSS = """<style>
.hc{--hc-line:#e5e7eb;--hc-ink:#0f172a;--hc-mute:#64748b;--hc-soft:#f8fafc;
  --hc-up:#15803d;--hc-down:#b91c1c;--hc-accent:#2a78d6;--hc-flag:#d08700;
  --hc-rank:#475569;--hc-disc:transparent;
  --hc-hi-bg:rgba(21,128,61,.10);--hc-lo-bg:rgba(185,28,28,.09);
  --hc-focus:rgba(42,120,214,.14)}
@media (prefers-color-scheme:dark){
  .hc{--hc-line:#2b3852;--hc-ink:#e3eaf4;--hc-mute:#aab7c9;--hc-soft:#1b2540;
    --hc-up:#6ee7b7;--hc-down:#ff9b91;--hc-accent:#6aa9f0;--hc-flag:#e0a92a;
    --hc-rank:#cbd5e1;--hc-disc:#e8edf4;
    --hc-hi-bg:rgba(110,231,183,.13);--hc-lo-bg:rgba(255,155,145,.13);
    --hc-focus:rgba(106,169,240,.20)}
}
.hc .hc-note{font-size:12px;color:var(--hc-mute);margin:8px 0 0;line-height:1.5}
/* One table: the rank written once down the left, the three sources across.
   Three separate lists repeated the numbers 1-25 three times and, on the dark
   theme, needed striping to keep the eye on a line - which came out muddy
   against the highlight. Here the rank column does that job. */
.hc-head{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;
  gap:8px;margin:0 0 10px;font-size:15px;color:var(--hc-ink)}
.hc-head .hc-when{font-size:11px;color:var(--hc-mute);text-transform:uppercase;
  letter-spacing:.04em}
table.hc-t25{width:100%;border-collapse:collapse;table-layout:fixed}
/* The site theme boxes every cell, centres it and stripes the rows; this is a
   card, so all three are reset here rather than fought row by row. */
table.hc-t25 th{font-size:13px;font-weight:800;text-transform:uppercase;
  letter-spacing:.07em;color:var(--hc-ink);text-align:left;padding:8px;
  border:0;border-bottom:2px solid var(--hc-accent);background:var(--hc-soft)}
table.hc-t25 th:not(:first-child){border-left:3px solid transparent}
table.hc-t25 th:first-child{width:46px;padding:0}
table.hc-t25 td{padding:5px 8px;border:0;border-bottom:1px solid var(--hc-line);
  color:var(--hc-ink);font-size:14px;line-height:1.25;background:transparent;
  text-align:left;vertical-align:middle;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis}
table.hc-t25 tbody tr td.hc-rk,
table.hc-t25 tbody tr:nth-child(even) td.hc-rk{background:transparent}
table.hc-t25 tr:last-child td{border-bottom:0}
/* The rank is the spine of the table, so it is read at the same weight as the
   names rather than as a grey subscript - and it gets enough room that the
   next cell's accent bar cannot crowd the digits. */
td.hc-rk{width:46px;text-align:right;padding:6px 14px 6px 0;color:var(--hc-rank);
  font-size:14px;font-weight:700;font-variant-numeric:tabular-nums;
  border-bottom-color:transparent;overflow:visible}
/* Specific enough to beat the border reset above, which is two elements and a
   class and would otherwise flatten the accent bar. */
table.hc-t25 td.hc-tc{border-left:3px solid transparent}
/* Logos are normalised into a fixed box: the marks arrive at wildly different
   aspect ratios and paddings, and left alone they jitter the column. */
td.hc-tc img{width:22px;height:22px;object-fit:contain;border:none;padding:0;
  margin:0 8px 0 0;box-shadow:none;background:none;border-radius:0;
  vertical-align:middle}
/* Ohio State, Penn State and a dozen others ship a near-black mark, which on
   the dark theme is an 18px hole. A white disc behind every logo is the only
   treatment that works for all of them - a halo leaves dark-on-dark dark. */
/* Every logo gets the same soft disc on the dark theme - a halo leaves
   dark-on-dark dark, and a pure white disc glares against the navy. The
   padding is what stops a square mark filling the circle. */
@media (prefers-color-scheme:dark){
  td.hc-tc img{background:var(--hc-disc);border-radius:50%;padding:2px;
    box-sizing:border-box;box-shadow:0 0 0 1px rgba(255,255,255,.08)}
}
td.hc-tc .hc-tm{font-weight:500}
/* Where the lists part company: the column that rates a team highest carries
   a green bar, the one that rates it lowest a red one. A bar rather than a
   wash behind the text - a tinted fill on the dark theme reads as muddy and
   costs the name its contrast. */
table.hc-t25 td.hc-tc.hc-hi{border-left-color:var(--hc-up);background:var(--hc-hi-bg)}
table.hc-t25 td.hc-tc.hc-lo{border-left-color:var(--hc-down);background:var(--hc-lo-bg)}
td.hc-tc.hc-hi .hc-tm,td.hc-tc.hc-lo .hc-tm{font-weight:700}
/* Hover (or tap) a team and the rest of the table steps back, so its three
   placements line up on their own. The rank column stays lit - the whole
   point is which rows the team sits on. */
table.hc-t25.hc-following td.hc-tc{opacity:.22;transition:opacity .12s ease}
table.hc-t25.hc-following td.hc-tc.hc-on{opacity:1;background:var(--hc-focus);
  border-left-color:var(--hc-accent)}
table.hc-t25.hc-following td.hc-tc.hc-on .hc-tm{font-weight:700}
.hc-key{display:inline-flex;align-items:center;gap:6px;font-size:12px;
  color:var(--hc-mute);margin-right:14px}
.hc-key i{width:3px;height:14px;border-radius:2px;display:inline-block}
.hc-key i.hi{background:var(--hc-up)}
.hc-key i.lo{background:var(--hc-down)}
/* --- The week's bets ------------------------------------------------------
   These classes went out unstyled, so the card rendered as the site theme's
   default list - which is what "it is just a list" meant. The pick is the
   headline, so it is set big; everything explaining it is small and muted. */
.hc-bet{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(240px,1fr))}
.hc-pick{border:1px solid var(--hc-line);border-radius:10px;padding:11px 13px;
  background:var(--hc-soft);min-width:0}
.hc-kind{font-size:11px;font-weight:800;text-transform:uppercase;
  letter-spacing:.07em;color:var(--hc-accent);margin:0 0 6px}
.hc-call{font-size:19px;font-weight:800;color:var(--hc-ink);line-height:1.2;
  font-variant-numeric:tabular-nums;display:flex;align-items:center;gap:7px;
  flex-wrap:wrap}
.hc .hc-sub{font-size:12px;color:var(--hc-mute);line-height:1.45;margin-top:3px}
/* Legs are rows, not bullets: three picks stacked with a rule between them
   read as three picks. A disc in front of each read as prose. */
.hc .hc-legs{list-style:none;margin:0;padding:0}
.hc .hc-legs li{margin:0;padding:7px 0;border-top:1px solid var(--hc-line);
  font-size:15px;font-weight:700;color:var(--hc-ink);
  font-variant-numeric:tabular-nums}
.hc .hc-legs li:first-child{border-top:0;padding-top:0}
.hc .hc-legs li:last-child{padding-bottom:0}
.hc-res{font-size:11px;font-weight:800;padding:1px 6px;border-radius:999px;
  text-transform:uppercase;letter-spacing:.04em;vertical-align:middle}
.hc-res.win{color:var(--hc-up);background:var(--hc-hi-bg)}
.hc-res.loss{color:var(--hc-down);background:var(--hc-lo-bg)}
.hc-res.push{color:var(--hc-mute);background:var(--hc-focus)}
/* When it was worked out, and how long it stands. Its own line above the
   record so neither has to be hunted for in a paragraph. */
.hc-when-row{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 12px;
  margin:11px 0 0;font-size:11px;text-transform:uppercase;letter-spacing:.04em;
  color:var(--hc-mute)}
.hc-lock{font-weight:800;color:var(--hc-flag)}
.hc-lock.hc-locked{color:var(--hc-mute)}
.hc-rec{font-size:13px;color:var(--hc-ink);margin:7px 0 0;line-height:1.45}
.hc-rec .hc-dis{color:var(--hc-mute)}
@media (max-width:560px){
  .hc-bet{grid-template-columns:1fr;gap:8px}
  .hc-call{font-size:17px}
  .hc .hc-legs li{font-size:14px}
}
@media (max-width:560px){
  table.hc-t25 td{font-size:12px;padding:4px 4px}
  table.hc-t25 th{font-size:11px;letter-spacing:.03em;padding:0 4px 5px}
  td.hc-rk{width:30px;font-size:12px;padding-right:9px}
  table.hc-t25 th:first-child{width:30px}
  /* A third of 390px is about 115px, and a logo eats a fifth of it:
     "Notre Dame" became "Notre D...". The name is the information. */
  td.hc-tc img{display:none}
}
</style>"""


# --------------------------------------------------------------------------- #
# Top 25: ours, the AP poll, ESPN's FPI
# --------------------------------------------------------------------------- #

def _rankings() -> tuple:
    """({espn id: {name, logo, gs, ap, fpi}}, whether the AP poll is live)."""
    rows = power._rows(power.fpi())
    ap_ranks, ap_season, _label = power.ap_poll(others=True)
    show_ap = bool(ap_ranks) and ap_season == SEASON

    teams = {}
    for i, t in enumerate(rows, 1):
        teams[t["id"]] = {"name": t["school"] or t["name"], "logo": t["logo"],
                          "fpi": i, "ap": None, "gs": None}
    frame, model, names = predict.season()
    for _, r in teams_page._standings(frame, model, names).iterrows():
        team = teams.setdefault(str(r["team"]), {"name": str(r["name"]), "logo": None,
                                                 "fpi": None, "ap": None, "gs": None})
        team["gs"] = int(r["rank"])
    if show_ap:
        for team_id, rank in ap_ranks.items():
            teams.setdefault(team_id, {"name": team_id, "logo": None, "fpi": None,
                                       "ap": None, "gs": None})["ap"] = int(rank)
    return teams, show_ap


def _cell(rank) -> str:
    return f"<span class='hc-none'>&mdash;</span>" if rank is None else f"{rank}"


def _ordered(teams: dict, source: str, limit: int) -> list:
    """The top `limit` of one source, best first."""
    rows = [(t[source], tid, t) for tid, t in teams.items() if t.get(source)]
    rows.sort(key=lambda r: r[0])
    return rows[:limit]


def top25_html(limit: int = 25) -> str:
    """The three polls as one table: the rank down the left, and what each
    source puts there across the row.

    Built to be screenshotted into a group chat. One rank column rather than
    three means the numbers are written once and every row is a like-for-like
    comparison - rank 8 is Ole Miss to the AP, Texas to us, Texas A&M to FPI.

    Every team the sources actually disagree about is marked: green in the
    column that rates it highest, red in the one that rates it lowest. A place
    or two apart is not a disagreement - mark those and nearly every row ends
    up striped - so MARK_GAP is where it starts.
    """
    teams, show_ap = _rankings()
    sources = [("ap", "AP Poll")] if show_ap else []
    sources += [("gs", "GordStats"), ("fpi", "ESPN FPI")]
    # Where the AP puts a team without a vote: below every team with one. Ours
    # and FPI rank all of FBS, so only the poll runs out - and leaving it out
    # of the comparison is how Penn State (15th to FPI, 17th to us, 28th by AP
    # votes) went unmarked while a team we both rank sat beside it marked.
    ap_floor = 1 + max((t["ap"] or 0) for t in teams.values())

    def seen(team) -> dict:
        """{source: rank} over the sources, an AP vote-less team at ap_floor."""
        got = {key: team[key] for key, _label in sources if team[key] is not None}
        if show_ap and got and "ap" not in got:
            got["ap"] = ap_floor
        return got

    def where(team) -> str:
        def say(key, rank):
            if rank is None:
                return "unranked"
            if key == "ap" and rank > 25:
                return f"unranked ({rank}{teams_page._ordinal(rank)} by votes)"
            return str(rank)
        return " \u00b7 ".join(
            f"{label.replace(' Poll', '').replace('ESPN ', '')} " + say(key, team[key])
            for key, label in sources)

    ranked = {key: {rank: (team_id, team)
                    for rank, team_id, team in _ordered(teams, key, limit)}
              for key, _label in sources}

    rows = []
    for rank in range(1, limit + 1):
        cells = []
        for key, _label in sources:
            got = ranked[key].get(rank)
            if not got:
                cells.append("<td class='hc-tc'></td>")
                continue
            team_id, team = got
            marks = seen(team)
            # Highest is the smallest rank number.
            best, worst = min(marks.values()), max(marks.values())
            mark = ""
            if worst - best >= MARK_GAP:
                if marks.get(key) == best:
                    mark = " hc-hi"
                elif marks.get(key) == worst:
                    mark = " hc-lo"
            logo = logos.img("ncaa", team_id, 22)
            cells.append(
                f"<td class='hc-tc{mark}' data-team='{escape(str(team_id), quote=True)}' "
                f"title=\"{escape(where(team), quote=True)}\">"
                f"{logo}<span class='hc-tm'>{escape(str(team['name']))}</span></td>")
        rows.append(f"<tr><td class='hc-rk'>{rank}</td>{''.join(cells)}</tr>")

    head = ("<tr><th></th>"
            + "".join(f"<th>{label}</th>" for _key, label in sources) + "</tr>")
    stamp = datetime.now(ET).strftime("%b %-d, %-I:%M %p ET")
    many = "three" if show_ap else "two"
    key_line = ("<span class='hc-key'><i class='hi'></i>rates them highest</span>"
                "<span class='hc-key'><i class='lo'></i>lowest</span>")
    return (_CSS + _FOLLOW_JS + "<div class='hc'>"
            f"<div class='hc-head'><span class='hc-when'>Updated {stamp}</span></div>"
            f"<div class='hc-scroll'><table class='hc-t25'><thead>{head}</thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>"
            f"<p class='hc-note'>{key_line} &mdash; "
            f"marked where the {many} lists are {MARK_GAP}+ places apart on a team. "
            f"Hover a team (or tap, on a phone) to follow it across all "
            f"{many}.</p></div>")


_FOLLOW_JS = """{% raw %}<script>
(function(){
  function wire(table){
    var body=table.tBodies[0]; if(!body) return;
    var pinned=null;
    function show(team){
      var cells=body.querySelectorAll('td.hc-tc');
      for(var i=0;i<cells.length;i++){
        cells[i].classList.toggle('hc-on', !!team && cells[i].dataset.team===team);
      }
      table.classList.toggle('hc-following', !!team);
    }
    body.addEventListener('mouseover', function(e){
      if(pinned) return;
      var cell=e.target.closest('td.hc-tc');
      show(cell&&cell.dataset.team);
    });
    body.addEventListener('mouseleave', function(){ if(!pinned) show(null); });
    // A phone has no hover: a tap pins a team, a second tap lets it go.
    body.addEventListener('click', function(e){
      var cell=e.target.closest('td.hc-tc');
      var team=cell&&cell.dataset.team;
      pinned=(pinned===team)?null:team;
      show(pinned);
    });
  }
  function init(){
    var tables=document.querySelectorAll('table.hc-t25');
    for(var i=0;i<tables.length;i++) wire(tables[i]);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);
  else init();
})();
</script>{% endraw %}"""


_LOCK_JS = """{% raw %}<script>
(function(){
  // Counts the provisional card down to its lock. Server-rendered text is
  // already correct ("Locks Thu 9 AM ET"), so this only sharpens it while the
  // page is open and never leaves it blank if the date will not parse.
  function tick(){
    var els=document.querySelectorAll('.hc-lock[data-lock]');
    for(var i=0;i<els.length;i++){
      var at=Date.parse(els[i].dataset.lock);
      if(isNaN(at)) continue;
      var left=at-Date.now();
      if(left<=0){
        els[i].textContent='Locking now';
        els[i].removeAttribute('data-lock');
        continue;
      }
      var m=Math.floor(left/60000), h=Math.floor(m/60), d=Math.floor(h/24);
      els[i].textContent='Locks in '+(d?d+'d '+(h%24)+'h':h?h+'h '+(m%60)+'m':m+'m');
    }
  }
  tick();
  setInterval(tick, 60000);
})();
</script>{% endraw %}"""


# --------------------------------------------------------------------------- #
# Best bets, frozen for the week
# --------------------------------------------------------------------------- #

def _current_week(now: datetime) -> tuple:
    """(week number, first kickoff) for the week the card is about: the one
    being played, or the next one to start."""
    spans = espn.week_spans()
    for number, start, end in spans:
        if now < end:
            return number, start
    return (spans[-1][0], spans[-1][1]) if spans else (None, None)


def _candidates(week: int) -> pd.DataFrame:
    """This week's games with both our number and the book's, widest first."""
    frame, _model, _names = predict.season()
    games = frame[(frame["week"] == week) & (~frame["played"])].copy()
    # FBS on both sides. The FCS pool is one shared rating, and the schools the
    # model does rate individually but ESPN does not cover (Sacramento St, N
    # Dakota St) are fitted on a handful of games against each other - either
    # way the number is not one to bet. espn.conferences() is exactly the FBS.
    fbs = set(espn.conferences())
    both = (games["home_id"].astype(str).isin(fbs) & games["away_id"].astype(str).isin(fbs)
            & (games["home_team"] != games_mod.FCS) & (games["away_team"] != games_mod.FCS))
    games = games[both].copy()
    board = odds_mod.latest(SEASON)
    if games.empty or board.empty:
        return pd.DataFrame()
    games = games.merge(board[odds_mod.KEY + ["spread", "total"]],
                        on=odds_mod.KEY, how="left")
    # The book prices the home side; the model talks in home margin.
    games["market_margin"] = -games["spread"]
    games["edge"] = games["pred_margin"] - games["market_margin"]
    games["ou_edge"] = games["pred_total"] - games["total"]
    return games


def _spread_pick(game) -> dict:
    """The side the model wants, and the number it is laying or taking.

    Both numbers are quoted from that side's own point of view - a pick on the
    underdog reading "we make it +29, the book +56" is two different sign
    conventions in one sentence. `model` and `market_margin` are margins (the
    side wins by); the card writes them as lines (_as_line).
    """
    home = game["edge"] > 0
    side, other = (game["home"], game["away"]) if home else (game["away"], game["home"])
    flip = 1 if home else -1
    return {"kind": "spread", "game_id": str(game["game_id"]),
            "team": str(side), "opponent": str(other), "home": bool(home),
            "line": round(float(game["spread"] * flip), 1),
            "market_margin": round(float(game["market_margin"] * flip), 1),
            "model": round(float(game["pred_margin"] * flip), 1),
            "edge": round(float(abs(game["edge"])), 1),
            "kickoff": pd.Timestamp(game["date"]).isoformat()}


def _total_pick(game) -> dict:
    over = game["ou_edge"] > 0
    return {"kind": "total", "game_id": str(game["game_id"]),
            "team": f"{game['away']} at {game['home']}", "opponent": "",
            "side": "Over" if over else "Under", "line": round(float(game["total"]), 1),
            "model": round(float(game["pred_total"]), 1),
            "edge": round(float(abs(game["ou_edge"])), 1),
            "kickoff": pd.Timestamp(game["date"]).isoformat()}


def _pick_week(week: int) -> dict:
    """The card's picks for a week, as they would be taken right now."""
    games = _candidates(week)
    out = {"week": week, "single": None, "parlay": []}
    if games.empty:
        return out
    spreads = games.dropna(subset=["spread", "edge"])
    spreads = spreads[spreads["edge"].abs().between(EDGE_MIN, EDGE_MAX)].sort_values(
        "edge", key=lambda s: s.abs(), ascending=False)
    totals = games.dropna(subset=["total", "ou_edge"])
    totals = totals[totals["ou_edge"].abs().between(EDGE_MIN, EDGE_MAX)].sort_values(
        "ou_edge", key=lambda s: s.abs(), ascending=False)

    picks = [_spread_pick(g) for _, g in spreads.iterrows()]
    if picks:
        out["single"] = picks[0]
    # The parlay is the next-best calls, and deliberately not the single again:
    # one bet repeated inside a parlay is one opinion priced twice.
    rest = picks[1:] + [_total_pick(g) for _, g in totals.iterrows()]
    rest.sort(key=lambda p: -p["edge"])
    out["parlay"] = rest[:PARLAY_LEGS]
    return out


def _lock_path(week: int):
    return BETS_DIR / f"{SEASON}_wk{int(week):02d}.json"


def locked_picks(week: int, first_kick: datetime, now: datetime) -> tuple:
    """(picks, locked at, whether they are frozen).

    Frozen from LOCK_HOUR on the day of the week's first kickoff: the file is
    written once and then read, so a card published on Saturday says what it
    said on Thursday even if the ratings have moved since.
    """
    import json
    path = _lock_path(week)
    if path.exists():
        saved = json.loads(path.read_text(encoding="utf-8"))
        return saved, datetime.fromisoformat(saved["locked"]), True
    picks = _pick_week(week)
    lock_at = first_kick.replace(hour=LOCK_HOUR, minute=0, second=0, microsecond=0)
    if now < lock_at or not picks["single"]:
        return picks, lock_at, False
    picks["locked"] = now.isoformat(timespec="seconds")
    BETS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(picks, indent=1), encoding="utf-8")
    return picks, now, True


def _finals() -> dict:
    """{game_id: (home margin, total)} for games with a result."""
    frame, _model, _names = predict.season()
    done = frame[frame["played"]]
    return {str(g["game_id"]): (float(g["home_score"] - g["away_score"]),
                                float(g["home_score"] + g["away_score"]))
            for _, g in done.iterrows()}


def _grade(pick: dict, finals: dict):
    """True, False, None (push) or "" for a game that has not finished."""
    got = finals.get(pick["game_id"])
    if got is None:
        return ""
    margin, total = got
    if pick["kind"] == "spread":
        # The pick's own margin: the side it took, against the line it took.
        mine = margin if pick["home"] else -margin
        cover = mine + pick["line"]
        return None if abs(cover) < 1e-9 else cover > 0
    diff = total - pick["line"]
    return None if abs(diff) < 1e-9 else (diff > 0) == (pick["side"] == "Over")


def _mark(state) -> str:
    if state == "":
        return ""
    if state is None:
        return "<span class='hc-res push'>push</span>"
    return ("<span class='hc-res win'>&check;</span>" if state
            else "<span class='hc-res loss'>&times;</span>")


def _season_record() -> str:
    """How every locked pick of the season has done, graded on the results."""
    import json
    finals = _finals()
    wins = losses = pushes = 0
    for path in sorted(BETS_DIR.glob(f"{SEASON}_wk*.json")):
        saved = json.loads(path.read_text(encoding="utf-8"))
        for pick in ([saved["single"]] if saved.get("single") else []) + saved.get("parlay", []):
            state = _grade(pick, finals)
            if state == "":
                continue
            if state is None:
                pushes += 1
            else:
                wins, losses = wins + int(state), losses + int(not state)
    if not (wins + losses + pushes):
        return ""
    return (f"Locked picks this season: <strong>{wins}-{losses}"
            + (f"-{pushes}" if pushes else "") + "</strong>.")


def _as_line(margin: float) -> str:
    """A side's winning margin written as a sportsbook line, the favourite
    negative: we have them winning by 14.9 -> -14.9 (the card read "+14.9"
    beside a call of "-6.0", two conventions in one sentence)."""
    line = -float(margin)
    return "pk" if abs(line) < 0.05 else f"{line:+.1f}"


def _leg_html(pick: dict, finals: dict) -> str:
    if pick["kind"] == "spread":
        call = f"{escape(pick['team'])} {pick['line']:+.1f}"
        sub = (f"vs {escape(pick['opponent'])} &middot; we have them "
               f"{_as_line(pick['model'])}, the book {_as_line(pick['market_margin'])}")
    else:
        call = f"{pick['side']} {pick['line']:.1f}"
        sub = f"{escape(pick['team'])} &middot; we make it {pick['model']:.1f}"
    return (f"<li>{call}{_mark(_grade(pick, finals))}"
            f"<div class='hc-sub'>{sub}</div></li>")


def bets_html(now: datetime = None) -> str:
    now = now or datetime.now()
    week, first_kick = _current_week(now)
    if week is None:
        return _CSS + "<div class='hc'><p class='hc-note'>No games scheduled.</p></div>"
    picks, when, frozen = locked_picks(week, first_kick, now)
    finals = _finals()

    if not picks.get("single"):
        return (_CSS + "<div class='hc'><p class='hc-note'>The model and the book agree "
                f"to within {EDGE_MIN:.0f} points on every game this week, so there is "
                "no bet to name.</p></div>")

    single = picks["single"]
    body = [f"<div class='hc-bet'><div class='hc-pick'>"
            f"<div class='hc-kind'>Single bet</div>"
            f"<div class='hc-call'>{escape(single['team'])} {single['line']:+.1f}"
            f"{_mark(_grade(single, finals))}</div>"
            f"<div class='hc-sub'>vs {escape(single['opponent'])} &middot; we have them "
            f"{_as_line(single['model'])}, the book {_as_line(single['market_margin'])}</div></div>"]
    if picks["parlay"]:
        legs = "".join(_leg_html(p, finals) for p in picks["parlay"])
        body.append(f"<div class='hc-pick'><div class='hc-kind'>"
                    f"{len(picks['parlay'])}-leg parlay</div>"
                    f"<ul class='hc-legs'>{legs}</ul></div>")
    body.append("</div>")

    # Two short lines instead of a paragraph: when the call was made and how
    # long it stands, then the record. The backtest caveat that used to live
    # here (these picks hit 48% ATS, under the 52.4% juice needs) was four
    # lines of small print nobody read on a phone; it belongs with the rest of
    # the record, one tap away on the predictions page.
    if frozen:
        timing = (f"<span>Generated {when:%a %-d %b, %-I:%M %p ET}</span>"
                  f"<span class='hc-lock hc-locked'>Locked</span>")
    else:
        # Emitted as an instant, not a wall clock: week_spans is naive ET and
        # the reader may not be.
        lock_iso = when.replace(tzinfo=ET).isoformat()
        timing = (f"<span>Generated {now:%a %-d %b, %-I:%M %p ET}</span>"
                  f"<span class='hc-lock' data-lock='{lock_iso}'>"
                  f"Locks {when:%a %-I %p ET}</span>")
    record = _season_record()
    note = (f"<div class='hc-when-row'><span>{espn.week_label(week)}</span>{timing}</div>"
            f"<p class='hc-rec'>{record} <span class='hc-dis'>Not gambling "
            f"advice.</span> <a href='/cfb/predictions/'>Full record</a>.</p>")
    # The bet, as the sender would have typed it; the home page it links to
    # carries this card.
    line = (f"GordStats' {espn.week_label(week)} bet: {single['team']} {single['line']:+.1f} "
            f"vs {single['opponent']}")
    if picks["parlay"]:
        line += f", plus a {len(picks['parlay'])}-leg parlay"
    return (_CSS + _LOCK_JS + "<div class='hc'>" + "".join(body)
            + note + share_button.row("/", line) + "</div>")


WEEK_GAMES_OUT = paths.DOCS / "cfb" / "week-games.json"
WEEK_GAMES_DAYS = 7


def week_games(now: datetime = None) -> dict:
    """Every FBS game from the start of today (ET) to a week out, with our
    prediction and the book's line, for the home page's "My teams" card
    (gordstats.my_teams_today) - which picks out the reader's starred teams in
    the browser and polls the live score itself. `teams` names every team on
    the schedule, so a starred team with no game can be named on its bye."""
    import json
    now = now or datetime.now(ET)
    start = now.astimezone(ET).replace(hour=0, minute=0, second=0, microsecond=0)
    frame, _model, _names = predict.season()
    frame = frame[(frame["date"] >= start) & (frame["date"] < now + timedelta(days=WEEK_GAMES_DAYS))]
    board = odds_mod.latest(SEASON)
    if not board.empty and not frame.empty:
        frame = frame.merge(board[odds_mod.KEY + ["spread", "total"]].rename(
            columns={"spread": "book_spread", "total": "book_total"}), on=odds_mod.KEY, how="left")

    def num(v, places=1):
        return None if v is None or pd.isna(v) else round(float(v), places)

    games = []
    for _, g in frame.sort_values("date").iterrows():
        q = espn.query(int(g["week"]))
        games.append({
            "id": str(g["game_id"]), "week": q["week"], "seasontype": q["seasontype"],
            "kickoff": g["date"].strftime("%Y-%m-%dT%H:%M:%SZ"),
            "time_known": bool(g.get("time_valid", True)) if not pd.isna(g.get("time_valid", True)) else True,
            "home": {"id": str(g["home_id"]), "name": g["home"], "rank": num(g.get("home_rank"), 0),
                     "pred": num(g.get("pred_home")), "score": num(g.get("home_score"), 0)},
            "away": {"id": str(g["away_id"]), "name": g["away"], "rank": num(g.get("away_rank"), 0),
                     "pred": num(g.get("pred_away")), "score": num(g.get("away_score"), 0)},
            "neutral": bool(g.get("neutral")), "tv": g.get("tv") or "",
            "note": g.get("note") or "", "state": g.get("state") or "pre",
            "home_win": num(g.get("home_win_prob"), 3),
            "book_spread": num(g.get("book_spread")), "book_total": num(g.get("book_total")),
        })
    teams = {}
    full = espn.schedule()
    for side in ("home", "away"):
        for tid, name in zip(full[f"{side}_id"].astype(str), full[side]):
            if not tid.startswith("-"):
                teams.setdefault(tid, name)
    return {"season": SEASON, "generated": now.astimezone(ET).isoformat(timespec="minutes"),
            "games": games, "teams": teams}


def generate() -> None:
    import json
    WEEK_GAMES_OUT.parent.mkdir(parents=True, exist_ok=True)
    WEEK_GAMES_OUT.write_text(json.dumps(week_games(), separators=(",", ":")), encoding="utf-8")
    print(f"Wrote CFB week games -> {WEEK_GAMES_OUT}")
    TOP25_OUT.parent.mkdir(parents=True, exist_ok=True)
    TOP25_OUT.write_text(top25_html(), encoding="utf-8")
    print(f"Wrote CFB top 25 card -> {TOP25_OUT}")
    BETS_OUT.write_text(bets_html(), encoding="utf-8")
    print(f"Wrote CFB best bets card -> {BETS_OUT}")


if __name__ == "__main__":
    generate()
