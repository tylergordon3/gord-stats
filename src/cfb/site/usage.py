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
from cfb.config import MY_TEAM, SEASON, WEB_DIR, league_school
from cfb.site import write_page
from gordstats.usage_page import JS as _JS, Col, bar as _bar, cell as _cell, css as _css
from gordstats.usage_page import fixed as _fixed, head as _head, num as _num
from gordstats.usage_page import options as _options, pct as _pct, pin as _pin
from gordstats.usage_page import sort_index as _sort_index, views_bar as _views_bar
from gordstats.jsonio import script_json

RECENT_WEEKS = 3
MIN_TOUCHES = 4                 # below this a share is one carry of noise
POSITIONS = ("QB", "RB", "WR", "TE")
# The page is about who the ball goes to, so it holds the three positions that
# answer that. A quarterback's usage is a passing stat and reads nothing like a
# carry share.
SHOWN = ("RB", "WR", "TE")

# Minimums are lower than the NFL page's: a college team runs more plays, but
# the archive only has the weeks the season has played.
VIEWS = [
    {"key": "overall", "label": "Overall", "sort": "car_share"},
    {"key": "rb", "label": "RB", "pos": ["RB"], "sort": "car_share",
     "min": {"field": "car", "n": 15,
             "label": "Ranked among backs with 15+ carries over these weeks."}},
    {"key": "wr", "label": "WR", "pos": ["WR"], "sort": "tgt_share",
     "min": {"field": "tgt", "n": 10,
             "label": "Ranked among receivers with 10+ targets over these weeks."}},
    {"key": "te", "label": "TE", "pos": ["TE"], "sort": "tgt_share",
     "min": {"field": "tgt", "n": 6,
             "label": "Ranked among tight ends with 6+ targets over these weeks."}},
]

# Which views own which columns. College has no published snap counts, so the
# receiver views lead on target share rather than on snaps.
ALL = "overall rb wr te"
POSV = "rb wr te"                       # the rank column: position views only
OVR = "overall"
RUSH = "overall rb"
CATCH = "overall wr te"

# The table, left to right. `_rows` writes its cells in this order.
COLUMNS = [
    Col("#", POSV, role="rank", title="Rank in this view, among players past the minimum"),
    Col("Player", ALL, "text", "name"),
    Col("School", ALL, "text", "team"),
    Col("Pos", OVR, "text"),
    Col("Fantasy", ALL, "text", "own"),
    Col("G", ALL, "n"),
    Col("Car", RUSH, "n", field="car"),
    Col("Car share", RUSH, "n", field="car_share"),
    Col("Season", RUSH, "n", "lead"),
    Col("Tgt", ALL, "n", field="tgt"),
    Col("Tgt share", ALL, "n", field="tgt_share"),
    Col("Season", ALL, "n", "lead"),
    Col("Rec", CATCH, "n"),
    Col("Rec share", CATCH, "n"),
    Col("Catch%", CATCH, "n", title="Catches per target"),
    Col("Yds", ALL, "n"),
    Col("TD", ALL, "n"),
    Col("FPts/G", ALL, "n", title="League fantasy points per game played"),
    Col("PPA", ALL, "n"),
]


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
            f' data-car="{int(r["carries"])}" data-tgt="{int(r["targets"])}">'
            "<td></td>"
            + _cell(escape(str(r["player"]))) + _cell(escape(str(r["team"])))
            + _cell(escape(str(r["pos"]))) + _cell(own, cls="us-own")
            + _num(r["games"]) + _num(r["carries"]) + _bar(r["car_share"])
            + _pct(was("car_share"))
            + _num(r["targets"]) + _bar(r["tgt_share"]) + _pct(was("tgt_share"))
            + _num(r["rec"]) + _pct(r["rec_share"]) + _pct(catch)
            + _num(yards) + _num(tds)
            + _fixed(per_game, "{:.1f}") + _fixed(r["ppa"], "{:+.2f}") + "</tr>")
    return "".join(out)


def body() -> str:
    frame = usage_mod.load()
    if frame.empty:
        return (_css() + "<p>No games have been played yet — this page fills in once "
                "<code>python -m cfb.usage</code> has a week to read.</p>")
    # Only schools whose players this league can roster: CFBD's box scores
    # cover all of FBS, and a Sun Belt back leading his team in carries is
    # someone nobody here can add.
    conf = _conferences()
    fbs = set(schools_mod.load()["schools"])
    frame = frame[frame["team"].isin(fbs)
                  & frame["team"].map(lambda t: league_school(t, conf.get(t, "")))].copy()
    lg = yahoo.league()
    frame["fpts"] = players.fantasy_points(frame, lg)
    weeks = sorted(int(w) for w in frame["week"].unique())
    recent_weeks = weeks[-RECENT_WEEKS:]

    recent = usage_mod.shares(frame, weeks=RECENT_WEEKS)
    season = usage_mod.shares(frame)
    recent = recent[recent["pos"].isin(SHOWN)]
    recent = recent[(recent["carries"] + recent["targets"] + recent["rec"]) >= MIN_TOUCHES]
    recent = recent.sort_values(["car_share", "tgt_share"], ascending=False)
    recent = ownership.attach(recent)

    teams = sorted(recent["team"].unique())
    confs = sorted({conf.get(t) for t in teams if conf.get(t)})
    league_teams = {t["team_key"]: t["name"] for t in lg["teams"]}
    mine = next((k for k, n in league_teams.items() if n == MY_TEAM), "")
    by_name = sorted(league_teams, key=lambda k: league_teams[k].lower())
    controls = _pin(
        "<label>Fantasy <select id='us-own'><option value=''>Everyone</option>"
        "<option value='mine'>My team</option><option value='fa'>Free agents</option>"
        "<option value='held'>Rostered</option>"
        f"<optgroup label='Teams'>{_options(by_name, league_teams)}</optgroup></select></label>"
        f"<label>Conference <select id='us-conf'><option value=''>All</option>"
        f"{_options(confs)}</select></label>"
        f"<label>School <select id='us-team'><option value=''>All</option>"
        f"{_options(teams, data=conf)}</select></label>"
        "<label>Find <input id='us-find' type='search' placeholder='player'></label>"
        "<label title='Keep each school together, sorted inside by the chosen column'>"
        "<input id='us-group' type='checkbox'> Group by school</label>"
        "<button id='us-reset' type='button'>Reset</button>")

    span = (f"week {recent_weeks[0]}" if len(recent_weeks) == 1
            else f"weeks {recent_weeks[0]}&ndash;{recent_weeks[-1]}")
    cfg = script_json({"mine": mine, "teams": league_teams, "storage": "cfbMyTeam",
                      "sort": _sort_index(COLUMNS, "car_share"), "views": VIEWS})
    return (
        _css(COLUMNS)
        # One sentence above the table: the subtitle already says what the
        # columns are, so the intro only says which weeks and how to read the
        # two shares together. The rest waits, folded, for whoever asks.
        + f"<p>Over <strong>{span}</strong>, with the season share beside it: a back at 55% "
        "of the carries lately against 40% on the season is taking the job.</p>"
        "<details class='section'><summary>How to read it</summary>"
        "<p class='us-note'>Tap a column to sort, again to reverse. <strong>Fantasy</strong> "
        "narrows to one roster, everyone rostered, or the <span class='us-fa'>FA</span> free "
        "agents (<em>My team</em> is the one picked on the <a href='/cfb/roster/'>team "
        "dashboard</a>). For a conference's backfields: the conference, the RB view, and "
        "<strong>Group by school</strong>. The filters live in the page address, so a view "
        "can be shared.</p>"
        "<p class='us-note'>Shares divide by the team's own players, so none can exceed what "
        "the team ran. <strong>Targets</strong> are not published; they are counted from the "
        "play-by-play, so a pass whose receiver cannot be matched counts for the team only. "
        "<strong>FPts/G</strong> is the league's scoring without interceptions and fumbles; "
        "<strong>PPA</strong> is CollegeFootballData's predicted points added per play. "
        "College snap counts are not free, so share of touches stands in.</p></details>"
        + _views_bar(VIEWS)
        + controls
        + f"<div class='us-scroll'><table class='us view-overall' data-sticky-head>"
        f"<thead>{_head(COLUMNS)}</thead>"
        f"<tbody>{_rows(recent, season, conf)}</tbody></table></div>"
        + f"<script type='application/json' id='us-cfg'>{cfg}</script>" + _JS)


def generate():
    write_page(WEB_DIR / "usage" / "index.html", "CFB Usage", body(),
               subtitle=f"{SEASON} — carry, target and catch share, and who owns them")


if __name__ == "__main__":
    generate()
