"""
Matchup strength (docs/fantasy/strength/): whose schedule helps from here, and
which defences give points up - the NFL league's twin of /cfb/strength/, drawn
by the same gordstats.strength_page.

  * Schedule ahead   every roster's next weeks of the regular season, each
                     player's opponent rated at his own position and weighted
                     by what he is projected to be worth (the power model's
                     points per game, as the dashboards use it). A player on a
                     bye has no matchup to price and is left out of that week;
                     the cell counts the starters it costs.
  * Defence vs pos   fantasy.league.defense: what each defence has allowed per
                     position against the league average, from Sleeper's
                     weekly stats. Not schedule-adjusted, unlike the college
                     model's - the NFL's schedules are close enough to even.

A reader's own league (gordstats.my_league's bar) gets its schedule redrawn in
the browser from docs/fantasy/strength.json - every NFL team's opponents for
the weeks ahead, the ratings, and each player's team, position and projection
- by strength_page.SCHEDULE_JS, the same arithmetic as the table built here.
The defence table is the NFL's, not a league's, so it stays as built.

    python -m fantasy.site.strength
"""
import json
from html import escape

import pandas as pd

from fantasy import paths
from fantasy.config import FANTASY_REG_WEEKS, MY_MANAGER, UPCOMING_YEAR
from fantasy.league import defense
from fantasy.league import matchups as data_mod
from fantasy.site import layout
from fantasy.site import matchups as mu
from gordstats import logos, my_league, my_league_data
from gordstats import strength_page as page
from gordstats.frontmatter import add_front_matter

OUT = paths.WEB_FANTASY_DIR / "strength" / "index.html"
DATA_OUT = paths.WEB_FANTASY_DIR / "strength.json"
POSITIONS = defense.POSITIONS
# What a defence gives up. The DEF column is the other way round - what a
# team's offence hands the defence across from it - so it stays out of All.
DEFENDED = ("QB", "RB", "WR", "TE", "K")
NFL_WEEKS = 18
# Who plays whom does not move; the NFL section refreshes the scores in that
# file every day, so a week-old copy answers this page's question exactly.
SCHEDULE_AGE_HOURS = 24 * 7
STORAGE_KEY = "nflMyTeam"            # the team dashboard's "my team"

# Sleeper's flexible slots and who may fill them. IDP slots are not priced.
FLEX = {"WRRB_FLEX": ("RB", "WR"), "REC_FLEX": ("WR", "TE"),
        "FLEX": ("RB", "WR", "TE"), "SUPER_FLEX": ("QB", "RB", "WR", "TE")}


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #

def opponents(weeks: list, year: int = UPCOMING_YEAR) -> dict:
    """{team: {week: opponent}} for the regular-season `weeks`, in Sleeper's
    team codes. A team missing from a week is on its bye."""
    from nfl import games
    try:
        if games.SEASON == year:
            frame = games.schedule(max_age_hours=SCHEDULE_AGE_HOURS)
        else:
            frame = pd.read_parquet(games.season_path(year))
    except Exception as exc:                                # noqa: BLE001
        print(f"[strength] no NFL schedule ({exc})")
        return {}
    if frame.empty:
        return {}
    frame = frame[(frame["seasontype"] == 2) & frame["week"].isin(weeks)]
    fix = data_mod.ESPN_TO_SLEEPER
    out = {}
    for g in frame.itertuples(index=False):
        home, away = fix.get(g.home_abbr, g.home_abbr), fix.get(g.away_abbr, g.away_abbr)
        out.setdefault(home, {})[int(g.week)] = away
        out.setdefault(away, {})[int(g.week)] = home
    return out


def ratings_table(year: int = UPCOMING_YEAR) -> tuple:
    """(ratings frame with an `all` column, finished weeks behind it)."""
    try:
        data = defense.capture(year)
    except Exception as exc:                                # noqa: BLE001
        print(f"[strength] archived defence ratings only ({exc})")
        data = defense.load(year)
    table = defense.ratings(year, data=data)
    if table.empty:
        return table, 0
    table = table.copy()
    table["all"] = table[[p for p in DEFENDED if p in table]].mean(axis=1)
    return table, len(data)


def starters(players: list, slots: list) -> set:
    """Who a roster starts in a normal week: each slot filled in turn with the
    best player left who may play it - the named positions first, then the
    flex slots narrowest first. `players` are (id, position, projection);
    ties go to the lower id, so the browser's copy (STARTERS_JS) agrees."""
    pool = sorted(players, key=lambda p: (-p[2], str(p[0])))
    order = [s for s in slots if s in POSITIONS] + sorted(
        (s for s in slots if s in FLEX), key=lambda s: len(FLEX[s]))
    taken = set()
    for slot in order:
        ok = FLEX.get(slot, (slot,))
        pick = next((p for p in pool if p[0] not in taken and p[1] in ok), None)
        if pick:
            taken.add(pick[0])
    return taken


def roster_players(sides: list, teams: dict, board: dict, slots: list) -> list:
    """strength_page.price()'s players for this league: every rostered player
    the board prices, less the reserve list, with the season's starters marked."""
    out = []
    for side in sides:
        key = str(side["roster_id"])
        team = teams.get(key) or {}
        reserve = {str(p) for p in team.get("reserve") or []}
        ids = [str(p) for p in side.get("players") or []
               if str(p) not in reserve and str(p) in board]
        start = starters([(pid, board[pid][1], board[pid][2]) for pid in ids], slots)
        label = team.get("name") or f"Team {key}"
        for pid in ids:
            nfl_team, pos, weight = board[pid]
            out.append({"key": key, "label": label, "team": nfl_team, "pos": pos,
                        "weight": weight, "starter": pid in start})
    return out


class League:
    """Everything the page and the browser read, worked out once."""

    def __init__(self, year: int = UPCOMING_YEAR):
        self.year = year
        try:
            weeks = data_mod.capture(year=year)
        except Exception as exc:                            # noqa: BLE001
            print(f"[strength] using the archive only ({exc})")
            weeks = data_mod.archived_weeks(year)
        self.archived = weeks
        datas = {w: data_mod.week_matchups(w, year) for w in weeks}
        open_weeks = [w for w in weeks if not data_mod.week_final(datas[w])]
        self.first = open_weeks[0] if open_weeks else (weeks[-1] + 1 if weeks else 1)
        self.data = datas[open_weeks[0] if open_weeks else weeks[-1]] if weeks else {}
        try:
            lg = data_mod.league()
        except Exception as exc:                            # noqa: BLE001
            print(f"[strength] league settings unavailable ({exc})")
            lg = {}
        self.slots = lg.get("roster_positions") or mu.ctx_slots({})
        start = int(lg.get("playoff_week_start") or 0)
        self.last_regular = start - 1 if start > 1 else FANTASY_REG_WEEKS

        # Shipped: as far ahead as any league's regular season could want; the
        # site's own table stops at its own playoffs, a reader's at theirs.
        self.ship = list(range(self.first, min(self.first + page.WEEKS_AHEAD, NFL_WEEKS + 1)))
        self.weeks = [w for w in self.ship if w <= self.last_regular]
        self.opp = opponents(self.ship, year) if self.ship else {}

        table, self.played = ratings_table(year)
        self.table = table
        # Rounded once, here: the page and the browser price off the same numbers.
        self.ratings = {str(t): {p: round(float(row[p]), 4) for p in POSITIONS
                                 if p in row and not pd.isna(row[p])}
                        for t, row in table.iterrows()} if not table.empty else {}

        board = mu._board(weeks, datas) if weeks else pd.DataFrame()
        self.board = {}
        if not board.empty:
            for r in board.drop_duplicates("sleeper_id").itertuples(index=False):
                w = getattr(r, "mu", None)
                if r.pos in POSITIONS and r.team and w is not None and not pd.isna(w) \
                        and round(float(w), 2) > 0:
                    self.board[str(r.sleeper_id)] = [str(r.team), r.pos, round(float(w), 2)]

    def payload(self) -> dict:
        """docs/fantasy/strength.json."""
        return {"year": self.year, "weeks": self.ship, "ahead": page.WEEKS_AHEAD,
                "opp": {t: [by.get(w, "") for w in self.ship]
                        for t, by in sorted(self.opp.items())},
                "dvp": self.ratings, "p": self.board}

    def opponent_map(self) -> dict:
        return {(t, w): o for t, by in self.opp.items() for w, o in by.items()}

    def rows(self) -> list:
        sides = [s for m in self.data.get("matchups") or [] for s in m["sides"]]
        players = roster_players(sides, self.data.get("teams") or {}, self.board, self.slots)
        return page.price(players, self.weeks, self.opponent_map(), self.ratings)

    def mine(self) -> str:
        return next((k for k, t in (self.data.get("teams") or {}).items()
                     if (t or {}).get("manager") == MY_MANAGER), "")


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #

def defense_section(table: pd.DataFrame) -> str:
    ranked = table.assign(_t=table.index.astype(str)).sort_values(["all", "_t"], kind="mergesort")
    rows = [(logos.img("nfl", team, 16, cls="st-logo") + escape(str(team)),
             {p: row[p] for p in POSITIONS if p in row}, row["all"])
            for team, row in ranked.iterrows()]
    titles = {"DEF": "What this team's offence hands the defence across from it - "
                     "the number a defence facing it is priced on"}
    return page.defense_table(rows, POSITIONS, titles=titles, fit=True)


# The reader's league: the bar's saved league, priced off strength.json by
# strength_page.SCHEDULE_JS. Its starters() is the Python one above, line for
# line (tests/test_strength_page.py compares the two tables in Chromium).
READER_JS = """{% raw %}<script>
(function(){
  'use strict';
  var FLEX={WRRB_FLEX:['RB','WR'],REC_FLEX:['WR','TE'],FLEX:['RB','WR','TE'],
            SUPER_FLEX:['QB','RB','WR','TE']};
  var POS=['QB','RB','WR','TE','K','DEF'];
  function starters(players, slots){
    var pool=players.slice().sort(function(a,b){
      return (b[2]-a[2])||(String(a[0])<String(b[0])?-1:(String(a[0])>String(b[0])?1:0));});
    var named=slots.filter(function(s){ return POS.indexOf(s)>=0; });
    var flex=slots.filter(function(s){ return FLEX[s]; })
      .map(function(s,i){ return [s,i]; })
      .sort(function(a,b){ return (FLEX[a[0]].length-FLEX[b[0]].length)||(a[1]-b[1]); })
      .map(function(x){ return x[0]; });
    var taken={};
    named.concat(flex).forEach(function(slot){
      var ok=FLEX[slot]||[slot];
      for(var i=0;i<pool.length;i++){
        var p=pool[i];
        if(!taken[p[0]]&&ok.indexOf(p[1])>=0){ taken[p[0]]=true; return; }
      }
    });
    return taken;
  }
  /** strength_page.price()'s players for a league as GSL.league returns it. */
  function players(lg, d){
    var out=[];
    (lg.rosters||[]).forEach(function(r){
      var key=String(r.roster_id), off={};
      (r.reserve||[]).concat(r.taxi||[]).forEach(function(p){ off[String(p)]=1; });
      var ids=(r.players||[]).map(String).filter(function(p){ return !off[p]&&d.p[p]; });
      var start=starters(ids.map(function(p){ return [p,d.p[p][1],d.p[p][2]]; }), lg.slots||[]);
      var label=(lg.names||{})[key]||('Team '+key);
      ids.forEach(function(p){
        var x=d.p[p];
        out.push({key:key, label:label, team:x[0], pos:x[1], weight:x[2], starter:!!start[p]});
      });
    });
    return out;
  }
  /** The weeks of `d` this league's regular season still has. */
  function weeks(lg, d){
    var start=Number(((lg.info||{}).settings||{}).playoff_week_start)||0;
    return d.weeks.filter(function(w){ return !(start>1)||w<start; }).slice(0, d.ahead);
  }
  function render(lg, d){
    var ws=weeks(lg, d), at={};
    d.weeks.forEach(function(w,i){ at[w]=i; });
    if(!ws.length) return "<p class='st-wait'>This league's regular season is over.</p>";
    var rows=GSStrength.price(players(lg, d), ws, function(team, w){
      return (d.opp[team]||[])[at[w]]||''; }, d.dvp);
    return rows.length?GSStrength.table(rows, ws)
      :"<p class='st-wait'>Nothing on these rosters to price yet.</p>";
  }
  window.GSStrengthLeague={starters:starters, players:players, weeks:weeks, render:render};

  var host=document.getElementById('st-mine');
  var have=window.GSL&&GSL.saved();
  if(!host||!have||!have.id||have.site) return;
  host.innerHTML="<p class='st-wait'>Reading your league\\u2026</p>";
  Promise.all([GSL.league(have.id),
               fetch('/fantasy/strength.json').then(function(r){ return r.ok?r.json():null; })])
    .then(function(o){
      var lg=o[0], d=o[1];
      if(!lg||!d||!d.weeks) throw new Error('no data');
      host.innerHTML=render(lg, d);
      GSStrength.mark(host, GSL.myRoster(lg, have.id));
    }).catch(function(e){
      if(e instanceof TypeError) console.error(e);
      host.innerHTML="<p class='st-wait'>Could not read that league. The table below is "
        +"the NFL's, so it still applies.</p>";
    });
})();
</script>{% endraw %}"""


def _mark_built(default_key: str) -> str:
    """Bold the reader's team in the built table: the one the team dashboard
    remembers (nflMyTeam), else the site's own manager's."""
    return ("{% raw %}<script>(function(){var k=null;"
            f"try{{k=localStorage.getItem('{STORAGE_KEY}');}}catch(e){{}}"
            "GSStrength.mark(document.getElementById('st-built'),"
            f"k||{json.dumps(default_key)});}})();</script>{{% endraw %}}")


def body(league: League = None) -> str:
    lg = league or League()
    if lg.table.empty and not lg.data:
        return (page.CSS + "<p>Nothing to rate yet — this page fills in once the "
                "first week of the season is final.</p>")
    rows = lg.rows() if lg.weeks and lg.ratings else []
    if not lg.weeks:
        schedule = "<p class='st-wait'>The regular season is over.</p>"
    elif not rows:
        schedule = "<p class='st-wait'>Nothing to price yet.</p>"
    else:
        schedule = page.schedule_table(rows, lg.weeks, byes=True, keyed=True, fit=True)
    weeks_word = f"{lg.played} week{'' if lg.played == 1 else 's'}"
    defence = (defense_section(lg.table) if not lg.table.empty
               else "<p class='st-wait'>No finished week to rate a defence on yet.</p>")
    return (
        page.CSS
        + "<p><strong>1.00 is par</strong>: above 1, a defence to attack; below 1, one "
        f"to avoid. From {weeks_word} so far.</p>"
        "<details class='section'><summary>How this is worked out</summary>"
        "<p class='st-note'>Fantasy points each defence has allowed to a position, from "
        "Sleeper's weekly stats in this league's PPR scoring, against the league average "
        "at that position - 1.00 is a defence giving up exactly the average. Ratings on "
        f"fewer than {defense.FULL_WEIGHT_GAMES} games are pulled toward par, so one "
        "shootout does not brand a defence for the season.</p>"
        "<p class='st-note'>The schedule weights each player by his projected points per "
        "game, so a schedule is only easy where a roster starts somebody. A player on a "
        "bye is left out of that week; the count under a rating is how many of the "
        "roster's usual starters are off.</p></details>"
        + my_league.bar()
        + "<h2 id='schedule'>Schedule ahead</h2>"
        "<p class='st-note'>Each roster's next weeks, priced by who its players face. "
        "Higher is easier.</p>"
        "<div id='st-mine-wrap' hidden><div id='st-mine'></div></div>"
        f"<div id='st-built'>{schedule}</div>"
        + my_league.takeover("st-mine-wrap", "st-built")
        + "<h2 id='defence'>Defence vs position</h2>"
        "<p class='st-note'>Every NFL defence, toughest first: 1 gives up the least, the "
        "last place the most. <b>DEF</b> runs the other way: what that team's offence "
        "hands a defence.</p>"
        + defence
        + page.SCHEDULE_JS + _mark_built(lg.mine())
        + my_league_data.JS + my_league.JS + READER_JS)


def generate():
    lg = League()
    html = body(lg)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(add_front_matter(layout.HEAD + html, "NFL Matchup Strength",
                                    f"{UPCOMING_YEAR} — fantasy points allowed by position"),
                   encoding="utf-8")
    print(f"Wrote NFL Matchup Strength -> {OUT}")
    # Kept from the last good build when a source is missing; written with no
    # weeks at all once the season has none left, so a reader's page says so.
    if lg.ratings and lg.board:
        DATA_OUT.write_text(json.dumps(lg.payload(), separators=(",", ":")), encoding="utf-8")
        print(f"Wrote matchup strength data ({len(lg.board)} players, weeks "
              f"{lg.ship[:1] + lg.ship[-1:]}) -> {DATA_OUT}")


if __name__ == "__main__":
    generate()
