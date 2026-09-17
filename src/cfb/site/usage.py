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
from cfb.config import MY_TEAM, SEASON, WEB_DIR
from cfb.site import write_page
from gordstats.usage_page import CSS as _CSS, JS as _JS, bar as _bar, num as _num
from gordstats.usage_page import options as _options, pct as _pct, v as _v

RECENT_WEEKS = 3
MIN_TOUCHES = 4                 # below this a share is one carry of noise
POSITIONS = ("QB", "RB", "WR", "TE")

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
            f' data-name="{escape(str(r["player"]).lower(), quote=True)}">'
            f'<td class="us-name">{escape(str(r["player"]))}</td>'
            f'<td class="us-team">{escape(str(r["team"]))}</td>'
            f'<td>{escape(str(r["pos"]))}</td>'
            f'<td class="us-own">{own}</td>'
            + _num(r["games"]) + _num(r["carries"])
            + f'<td data-v="{_v(r["car_share"])}">{_bar(r["car_share"])}</td>'
            f'<td class="us-lead" data-v="{_v(was("car_share"))}">{_pct(was("car_share"))}</td>'
            + _num(r["targets"])
            + f'<td data-v="{_v(r["tgt_share"])}">{_bar(r["tgt_share"])}</td>'
            f'<td class="us-lead" data-v="{_v(was("tgt_share"))}">{_pct(was("tgt_share"))}</td>'
            + _num(r["rec"])
            + f'<td data-v="{_v(r["rec_share"])}">{_pct(r["rec_share"])}</td>'
            f'<td data-v="{_v(catch)}">{_pct(catch)}</td>'
            + _num(yards) + _num(tds)
            + f'<td data-v="{_v(per_game)}">'
            + ("&mdash;" if per_game is None or pd.isna(per_game) else f"{per_game:.1f}") + "</td>"
            f'<td data-v="{_v(r["ppa"])}">'
            + ("&mdash;" if pd.isna(r["ppa"]) else f"{r['ppa']:+.2f}") + "</td></tr>")
    return "".join(out)


def body() -> str:
    frame = usage_mod.load()
    if frame.empty:
        return (_CSS + "<p>No games have been played yet — this page fills in once "
                "<code>python -m cfb.usage</code> has a week to read.</p>")
    fbs = set(schools_mod.load()["schools"])
    frame = frame[frame["team"].isin(fbs)].copy()
    lg = yahoo.league()
    frame["fpts"] = players.fantasy_points(frame, lg)
    weeks = sorted(int(w) for w in frame["week"].unique())
    recent_weeks = weeks[-RECENT_WEEKS:]

    recent = usage_mod.shares(frame, weeks=RECENT_WEEKS)
    season = usage_mod.shares(frame)
    recent = recent[recent["pos"].isin(POSITIONS)]
    recent = recent[(recent["carries"] + recent["targets"] + recent["rec"]) >= MIN_TOUCHES]
    recent = recent.sort_values(["car_share", "tgt_share"], ascending=False)
    recent = ownership.attach(recent)

    conf = _conferences()
    teams = sorted(recent["team"].unique())
    confs = sorted({conf.get(t) for t in teams if conf.get(t)})
    league_teams = {t["team_key"]: t["name"] for t in lg["teams"]}
    mine = next((k for k, n in league_teams.items() if n == MY_TEAM), "")
    by_name = sorted(league_teams, key=lambda k: league_teams[k].lower())
    controls = (
        "<div class='pin-bar'><div class='us-controls'>"
        "<label>Fantasy <select id='us-own'><option value=''>Everyone</option>"
        "<option value='mine'>My team</option><option value='fa'>Free agents</option>"
        "<option value='held'>Rostered</option>"
        f"<optgroup label='Teams'>{_options(by_name, league_teams)}</optgroup></select></label>"
        f"<label>Conference <select id='us-conf'><option value=''>All</option>"
        f"{_options(confs)}</select></label>"
        f"<label>School <select id='us-team'><option value=''>All</option>"
        f"{_options(teams, data=conf)}</select></label>"
        f"<label>Position <select id='us-pos'><option value=''>All</option>"
        f"{_options(POSITIONS)}</select></label>"
        "<label>Find <input id='us-find' type='search' placeholder='player'></label>"
        "<label title='Keep each school together, sorted inside by the chosen column'>"
        "<input id='us-group' type='checkbox'> Group by school</label>"
        "<button id='us-reset' type='button'>Reset</button>"
        "<span class='us-count' id='us-count'></span>"
        "</div></div>")

    span = (f"week {recent_weeks[0]}" if len(recent_weeks) == 1
            else f"weeks {recent_weeks[0]}&ndash;{recent_weeks[-1]}")
    head = ("<tr><th data-k='text'>Player</th><th data-k='text'>School</th>"
            "<th data-k='text'>Pos</th><th data-k='text'>Fantasy</th><th data-k='n'>G</th>"
            "<th data-k='n'>Car</th><th data-k='n'>Car share</th>"
            "<th data-k='n' class='us-lead'>Season</th>"
            "<th data-k='n'>Tgt</th><th data-k='n'>Tgt share</th>"
            "<th data-k='n' class='us-lead'>Season</th>"
            "<th data-k='n'>Rec</th><th data-k='n'>Rec share</th>"
            "<th data-k='n' title='Catches per target'>Catch%</th>"
            "<th data-k='n'>Yds</th><th data-k='n'>TD</th>"
            "<th data-k='n' title='League fantasy points per game played'>FPts/G</th>"
            "<th data-k='n'>PPA</th></tr>")
    cfg = json.dumps({"mine": mine, "teams": league_teams, "storage": "cfbMyTeam",
                      "sort": 6}).replace("</", "<\\/")
    return (
        _CSS
        + f"<p>Every FBS skill player's share of his own team's carries, targets and catches "
        f"over the last three played weeks (<strong>{span}</strong>), with the season share "
        "beside it, and who in the league owns him. The two share columns together are the "
        "backfield answer: a back at 55% of the carries over three weeks against 40% on the "
        "season is taking the job.</p>"
        "<details class='section'><summary>How to use this page</summary>"
        "<p class='us-note'><strong>Click any column</strong> to sort by it, again to "
        "reverse. <strong>Fantasy</strong> narrows the table to one roster, to everybody "
        "rostered, or to the <span class='us-fa'>FA</span> free agents; <em>My team</em> is "
        "the roster chosen on the <a href='/cfb/roster/'>team dashboard</a>. For a whole "
        "conference's backfields, pick the conference, set Position to RB and tick "
        "<strong>Group by school</strong>: each school stays together, its backs ordered by "
        "the column you sorted on, with free agents flagged in green. The filters live in "
        "the page address, so a filtered view can be bookmarked or shared.</p>"
        "<p class='us-note'>Carries, receptions and yards are the box scores; the "
        "denominators are the team's own players added up, so a share cannot exceed what "
        "the team ran. <strong>Targets</strong> are not published anywhere as a stat — "
        "they are counted out of the play-by-play text, matching the intended receiver "
        "inside his own team by jersey number and surname, then by initial and surname, so "
        "a pass whose receiver cannot be matched counts for the team but not for a player. "
        "<strong>Rec share</strong> is his catches out of the team's. <strong>FPts/G</strong> "
        "is the league's scoring on passing, rushing and receiving (interceptions and "
        "fumbles are not in this feed). <strong>PPA</strong> is CollegeFootballData's "
        "predicted points added per play, the efficiency number beside the volume ones. "
        "Snap counts do not exist free for college football; share of touches is the honest "
        "substitute. A player counts as a free agent when no roster in the league holds "
        "him.</p></details>"
        + controls
        + f"<div class='us-scroll'><table class='us'><thead>{head}</thead>"
        f"<tbody>{_rows(recent, season, conf)}</tbody></table></div>"
        + f"<script type='application/json' id='us-cfg'>{cfg}</script>" + _JS)


def generate():
    write_page(WEB_DIR / "usage" / "index.html", "CFB Usage", body(),
               subtitle=f"{SEASON} — carry, target and catch share, and who owns them")


if __name__ == "__main__":
    generate()
