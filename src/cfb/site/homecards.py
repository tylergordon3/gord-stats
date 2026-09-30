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
            of its first kickoff. What that is worth is printed on the card.
            The card itself is gordstats.bets_card, shared with the NFL's
            (nfl.site.homecards); what is the college game's is here - which
            games may be bet, the gates, the finals and the closing line.

    python -m cfb.site.homecards
"""
from datetime import datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

import pandas as pd

from cfb import espn, gameinfo, games as games_mod, predict, results
from cfb import odds as odds_mod
from cfb.config import DATA_DIR, SEASON
from cfb.site import power, teams as teams_page
from gordstats import bets_card, logos, paths

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
LOCK_HOUR = bets_card.LOCK_HOUR

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
PARLAY_LEGS = bets_card.PARLAY_LEGS

# The table's own rules. The card colours and the bets rules are
# gordstats.bets_card's, shared with the NFL's bets card; the Top 25 carries
# them all, as it always has, so the two college includes stand alone.
_T25_CSS = """/* One table: the rank written once down the left, the three sources across.
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
"""
_T25_PHONE_CSS = """@media (max-width:560px){
  table.hc-t25 td{font-size:12px;padding:4px 4px}
  table.hc-t25 th{font-size:11px;letter-spacing:.03em;padding:0 4px 5px}
  td.hc-rk{width:30px;font-size:12px;padding-right:9px}
  table.hc-t25 th:first-child{width:30px}
  /* A third of 390px is about 115px, and a logo eats a fifth of it:
     "Notre Dame" became "Notre D...". The name is the information. */
  td.hc-tc img{display:none}
}
"""
_CSS = ("<style>\n" + bets_card.VARS_CSS + _T25_CSS + bets_card.BETS_CSS
        + _T25_PHONE_CSS + "</style>")


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
    return bets_card.with_edges(games)


def _pick_week(week: int) -> dict:
    """The card's picks for a week, as they would be taken right now."""
    return bets_card.pick_week(_candidates(week), week, EDGE_MIN, EDGE_MAX, PARLAY_LEGS)


def _lock_path(week: int):
    return bets_card.lock_path(BETS_DIR, SEASON, week)


def locked_picks(week: int, first_kick: datetime, now: datetime) -> tuple:
    """(picks, locked at, whether they are frozen) - bets_card.locked_picks
    on this week's file. Frozen from LOCK_HOUR on the day of the week's first
    kickoff: the file is written once and then read, so a card published on
    Saturday says what it said on Thursday even if the ratings have moved
    since."""
    return bets_card.locked_picks(_lock_path(week), lambda: _pick_week(week),
                                  first_kick, now, LOCK_HOUR)


def _finals() -> dict:
    """{game_id: (home margin, total)} for games with a result."""
    frame, _model, _names = predict.season()
    done = frame[frame["played"]]
    return {str(g["game_id"]): (float(g["home_score"] - g["away_score"]),
                                float(g["home_score"] + g["away_score"]))
            for _, g in done.iterrows()}


def _closes(game_ids) -> dict:
    """{game id: (home spread, total)}, DraftKings' last line before kickoff,
    for the games that have kicked off: the later of two looks at it - the
    game summary's (cfb.gameinfo, refetched every few hours and frozen at
    kickoff, so usually inside the last hour or two) and the daily odds
    archive's."""
    now = pd.Timestamp.now(tz="UTC")
    info = gameinfo.load(SEASON)
    sched = espn.schedule()
    hist = odds_mod.history(SEASON)
    out = {}
    for gid in {str(g) for g in game_ids}:
        seen = []                                   # (captured, spread, total)
        e = info.get(gid) or {}
        if e.get("captured") and e.get("kickoff") and e.get("spread") is not None:
            seen.append((pd.Timestamp(e["captured"]), pd.Timestamp(e["kickoff"]),
                         e["spread"], e.get("total")))
        row = sched[sched["game_id"].astype(str) == gid] if "game_id" in sched else sched.iloc[0:0]
        if not row.empty and not hist.empty:
            g = row.iloc[0]
            h = hist[(hist["week"].astype(int) == int(g["week"]))
                     & (hist["home_id"].astype(str) == str(g["home_id"]))
                     & (hist["away_id"].astype(str) == str(g["away_id"]))]
            for r in h.itertuples(index=False):
                seen.append((pd.Timestamp(r.captured), pd.Timestamp(r.date_utc),
                             r.spread, r.total))
        before = [x for x in seen if x[0] < x[1] <= now]
        if before:
            _cap, _kick, spread, total = max(before, key=lambda x: x[0])
            out[gid] = (float(spread), None if total is None or pd.isna(total) else float(total))
    return out


# The card's parts, under the names they had here before they moved to
# gordstats.bets_card (the tests still call them by these).
_spread_pick = bets_card.spread_pick
_total_pick = bets_card.total_pick
_grade = bets_card.grade
_close_of = bets_card.close_of
_close_html = bets_card.close_html
_mark = bets_card.mark
_as_line = bets_card.as_line
_leg_html = bets_card.leg_html


def _season_record(finals: dict = None, closes: dict = None) -> str:
    """How every locked pick of the season has done (bets_card.season_record):
    graded on the results, in units, and against the closing line."""
    weeks = bets_card.saved_weeks(BETS_DIR, SEASON)
    finals = _finals() if finals is None else finals
    closes = _closes(p["game_id"] for p in bets_card.legs(weeks)) if closes is None else closes
    return bets_card.season_record(weeks, finals, closes)


def bets_html(now: datetime = None) -> str:
    now = now or datetime.now()
    week, first_kick = _current_week(now)
    if week is None:
        return bets_card.note("No games scheduled.")
    picks, when, frozen = locked_picks(week, first_kick, now)
    finals = _finals()
    if not picks.get("single"):
        return bets_card.no_bet(EDGE_MIN)
    closes = _closes(p["game_id"] for p in [picks["single"]] + picks["parlay"])
    return bets_card.card_html(picks, espn.week_label(week), now, when, frozen, finals,
                               closes, _season_record(finals), "/cfb/predictions/")


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
