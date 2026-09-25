"""
Usage (docs/fantasy/usage/): who is on the field, and who the ball goes to.

The NFL twin of the college usage page, sharing its table (gordstats.usage_page):
every skill player's share of his team's snaps, carries, targets and air yards
over the last three played weeks, the season share beside it in grey, his
red-zone looks, and who in the league owns him - so it filters to one roster,
to the free agents, or to one NFL team's backfield.

Unlike the college game, snap counts exist here: Sleeper's weekly stats carry
the player's offensive snaps and the team's.

    python -m fantasy.site.usage
"""
import json
from html import escape

import pandas as pd

from fantasy import paths
from fantasy.config import MY_MANAGER, UPCOMING_SEASON, UPCOMING_YEAR
from fantasy.league import matchups as matchups_mod
from fantasy.league import usage as usage_mod
from fantasy.site import layout
from gordstats import usage_page as ui
from gordstats.frontmatter import add_front_matter

RECENT_WEEKS = 3
MIN_TOUCHES = 3                 # carries + targets; below it a share is noise
SORT_COLUMN = 5                 # snap share

# Quarterbacks, kickers and defences are not what this page is for: it is about
# who the ball goes to among the backs and receivers. QB usage is a passing
# stat and belongs with the passing numbers, not beside a carry share.
SHOWN = ("RB", "WR", "TE")

# The page is read one position at a time. Each view keeps its own positions,
# opens on the share that matters for them, and ranks only players with enough
# volume for a share to mean anything - a back with two carries can top a carry
# share table on a wet Sunday. Unqualified players still appear, greyed.
VIEWS = [
    {"key": "overall", "label": "Overall", "sort": "snap_share"},
    {"key": "rb", "label": "RB", "pos": ["RB"], "sort": "car_share",
     "min": {"field": "car", "n": 15,
             "label": "Ranked among backs with 15+ carries over these weeks."}},
    {"key": "wr", "label": "WR", "pos": ["WR"], "sort": "tgt_share",
     "min": {"field": "tgt", "n": 12,
             "label": "Ranked among receivers with 12+ targets over these weeks."}},
    {"key": "te", "label": "TE", "pos": ["TE"], "sort": "tgt_share",
     "min": {"field": "tgt", "n": 8,
             "label": "Ranked among tight ends with 8+ targets over these weeks."}},
]


def owners(year: int = UPCOMING_YEAR) -> tuple:
    """({sleeper_id: roster key}, {roster key: "Team (Manager)"}) from the
    newest week on the matchups archive - the same rosters the dashboard reads."""
    weeks = matchups_mod.archived_weeks(year)
    if not weeks:
        return {}, {}
    data = matchups_mod.week_matchups(weeks[-1], year)
    held = {str(pid): str(side["roster_id"]) for m in data["matchups"] for side in m["sides"]
            for pid in side.get("players") or []}
    names = {}
    for key, t in (data.get("teams") or {}).items():
        name, mgr = t.get("name") or "", t.get("manager") or ""
        names[str(key)] = name + (f" ({mgr})" if mgr and mgr not in name else "")
    return held, names


# Which views each column belongs to. A back's page does not need air-yard
# share and a receiver's does not need carries, so a column a view has no use
# for is hidden rather than printed empty.
ALL = "v-overall v-rb v-wr v-te"
POSV = "v-rb v-wr v-te"                 # the rank column: position views only
OVR = "v-overall"
RUSH = "v-overall v-rb"
CATCH = "v-overall v-wr v-te"
RECV = "v-wr v-te"


def _rows(recent: pd.DataFrame, season: pd.DataFrame, held: dict, names: dict) -> str:
    whole = season.set_index("sleeper_id")
    out = []
    for _, r in recent.iterrows():
        was = whole.loc[r["sleeper_id"]] if r["sleeper_id"] in whole.index else None

        def before(col):
            return None if was is None else was[col]

        own = held.get(r["sleeper_id"], "")
        label = (escape(names.get(own, own)) if own else "<span class='us-fa'>FA</span>")
        rz = r["rush_rz_att"] + r["rec_rz_tgt"]
        per_game = r["pts_ppr"] / r["games"] if r["games"] else None
        # Targets per snap: the nearest thing we can publish to a target rate.
        # Routes run is the figure that belongs here, and neither Sleeper nor
        # nflverse/PFR carries it - it is charted data. Snaps are the honest
        # denominator we do have.
        snaps = r.get("off_snp")
        per_snap = (r["rec_tgt"] / snaps) if snaps else None
        out.append(
            f'<tr data-team="{escape(r["team"], quote=True)}" data-conf=""'
            f' data-pos="{escape(r["pos"], quote=True)}" data-own="{escape(own, quote=True)}"'
            f' data-car="{int(r["rush_att"])}" data-tgt="{int(r["rec_tgt"])}"'
            f' data-name="{escape(str(r["player"]).lower(), quote=True)}">'
            f'<td class="us-rank {POSV}"></td>'
            f'<td class="us-name {ALL}">{escape(str(r["player"]))}</td>'
            f'<td class="us-team {ALL}">{escape(r["team"])}</td>'
            f'<td class="{OVR}">{escape(r["pos"])}</td>'
            f'<td class="us-own {ALL}">{label}</td>' + ui.num(r["games"], cls=ALL)
            + f'<td class="{ALL}" data-v="{ui.v(r["snap_share"])}">{ui.bar(r["snap_share"])}</td>'
            f'<td class="us-lead {ALL}" data-v="{ui.v(before("snap_share"))}">{ui.pct(before("snap_share"))}</td>'
            + ui.num(r["rush_att"], cls=RUSH)
            + f'<td class="{RUSH}" data-v="{ui.v(r["car_share"])}">{ui.bar(r["car_share"])}</td>'
            f'<td class="us-lead {RUSH}" data-v="{ui.v(before("car_share"))}">{ui.pct(before("car_share"))}</td>'
            + ui.num(r["rec_tgt"], cls=ALL)
            + f'<td class="{ALL}" data-v="{ui.v(r["tgt_share"])}">{ui.bar(r["tgt_share"])}</td>'
            f'<td class="us-lead {ALL}" data-v="{ui.v(before("tgt_share"))}">{ui.pct(before("tgt_share"))}</td>'
            + f'<td class="{RECV}" data-v="{ui.v(per_snap)}">'
            + ("&mdash;" if per_snap is None else f"{per_snap:.2f}") + "</td>"
            + ui.num(r["rec"], cls=CATCH)
            + f'<td class="{CATCH}" data-v="{ui.v(r["air_share"])}">{ui.pct(r["air_share"])}</td>'
            + ui.num(rz, cls=ALL) + ui.num(r["rush_yd"] + r["rec_yd"], cls=ALL)
            + ui.num(r["rush_td"] + r["rec_td"], cls=ALL)
            + f'<td class="{ALL}" data-v="{ui.v(per_game)}">'
            + ("&mdash;" if per_game is None else f"{per_game:.1f}") + "</td></tr>")
    return "".join(out)


def body() -> str:
    try:
        frame = usage_mod.capture(UPCOMING_YEAR)
    except Exception as exc:                                # noqa: BLE001
        print(f"[usage] using the archive only ({exc})")
        frame = usage_mod.load(UPCOMING_YEAR)
    if frame.empty:
        return (ui.CSS + f"<p>No {UPCOMING_SEASON} games have been played yet — this page "
                "fills in after the first one.</p>")
    frame = frame[frame["pos"].isin(SHOWN)]
    weeks = sorted(int(w) for w in frame["week"].unique())
    recent_weeks = weeks[-RECENT_WEEKS:]
    recent = usage_mod.shares(frame, weeks=RECENT_WEEKS)
    season = usage_mod.shares(frame)
    recent = recent[recent["rush_att"] + recent["rec_tgt"] >= MIN_TOUCHES]
    recent = recent.sort_values(["snap_share", "tgt_share"], ascending=False)

    held, names = owners()
    mine = next((k for k, n in names.items() if n.endswith(f"({MY_MANAGER})")
                 or n == MY_MANAGER), "")
    by_name = sorted(names, key=lambda k: names[k].lower())
    teams = sorted(recent["team"].unique())
    controls = (
        "<div class='pin-bar'><div class='us-controls'>"
        "<label>Fantasy <select id='us-own'><option value=''>Everyone</option>"
        "<option value='mine'>My team</option><option value='fa'>Free agents</option>"
        "<option value='held'>Rostered</option>"
        f"<optgroup label='Teams'>{ui.options(by_name, names)}</optgroup></select></label>"
        f"<label>NFL team <select id='us-team'><option value=''>All</option>"
        f"{ui.options(teams)}</select></label>"
        "<label>Find <input id='us-find' type='search' placeholder='player'></label>"
        "<label title='Keep each NFL team together, sorted inside by the chosen column'>"
        "<input id='us-group' type='checkbox'> Group by team</label>"
        "<button id='us-reset' type='button'>Reset</button>"
        "<span class='us-count' id='us-count'></span></div></div>")
    span = (f"week {recent_weeks[0]}" if len(recent_weeks) == 1
            else f"weeks {recent_weeks[0]}&ndash;{recent_weeks[-1]}")
    head = (f"<tr><th class='{POSV}' title='Rank in this view, among players past the "
            f"minimum'>#</th>"
            f"<th data-k='text' class='{ALL}'>Player</th>"
            f"<th data-k='text' class='{ALL}'>Team</th>"
            f"<th data-k='text' class='{OVR}'>Pos</th>"
            f"<th data-k='text' class='us-own {ALL}'>Fantasy</th>"
            f"<th data-k='n' class='{ALL}'>G</th>"
            f"<th data-k='n' class='{ALL}' data-field='snap_share' "
            f"title='Offensive snaps played out of the team&#39;s'>Snap share</th>"
            f"<th data-k='n' class='us-lead {ALL}'>Season</th>"
            f"<th data-k='n' class='{RUSH}' data-field='car'>Car</th>"
            f"<th data-k='n' class='{RUSH}' data-field='car_share'>Car share</th>"
            f"<th data-k='n' class='us-lead {RUSH}'>Season</th>"
            f"<th data-k='n' class='{ALL}' data-field='tgt'>Tgt</th>"
            f"<th data-k='n' class='{ALL}' data-field='tgt_share'>Tgt share</th>"
            f"<th data-k='n' class='us-lead {ALL}'>Season</th>"
            f"<th data-k='n' class='{RECV}' data-field='tgt_per_snap' "
            f"title='Targets per offensive snap - the closest stand-in we can publish "
            f"for a target rate, since routes run is charted data no free source carries'>"
            f"Tgt/snap</th>"
            f"<th data-k='n' class='{CATCH}'>Rec</th>"
            f"<th data-k='n' class='{CATCH}' title='Share of the team&#39;s air yards: how "
            f"far downfield the targets are, not just how many'>Air share</th>"
            f"<th data-k='n' class='{ALL}' title='Red-zone carries plus red-zone targets'>"
            f"RZ looks</th>"
            f"<th data-k='n' class='{ALL}'>Yds</th><th data-k='n' class='{ALL}'>TD</th>"
            f"<th data-k='n' class='{ALL}' title='PPR points per game played'>PPR/G</th></tr>")
    cfg = json.dumps({"mine": mine, "teams": names, "storage": "nflMyTeam",
                      "sort": SORT_COLUMN, "views": VIEWS}).replace("</", "<\\/")
    return (
        ui.CSS
        + "<p>Backs, receivers and tight ends: each one's share of his team's snaps, "
        f"carries and targets over the last three played weeks (<strong>{span}</strong>), "
        "with the season share beside it in grey, and who in the league owns him. A back "
        "whose snap share is climbing while his carries are flat is about to get the "
        "carries.</p>"
        "<details class='section'><summary>How to use this page</summary>"
        "<p class='us-note'><strong>Overall / RB / WR / TE</strong> picks both the "
        "players and the columns: the RB view leads on carry share, the receiver views on "
        "target share, and each ranks only players past a minimum, since a back with two "
        "carries can otherwise top a carry-share table. Players under it still appear, "
        "greyed, with no rank - <strong>Qualified only</strong> hides them. "
        "<strong>Click any column</strong> to sort by it, again to reverse. "
        "<strong>Fantasy</strong> narrows the table to one roster, to everybody rostered, "
        "or to the <span class='us-fa'>FA</span> free agents; <em>My team</em> is the "
        "roster chosen on the <a href='/fantasy/roster/'>team dashboard</a>. For one "
        "backfield pick the NFL team and the RB view; for all of them tick <strong>Group "
        "by team</strong>. The filters live in the page address, so a view can be "
        "bookmarked or shared.</p>"
        "<p class='us-note'>All from Sleeper's weekly stats. <strong>Snap share</strong> is "
        "offensive snaps played out of the team's. Carry, target and air-yard shares divide "
        "by the team's own players added up, so a share cannot exceed what the team ran. "
        "<strong>RZ looks</strong> are carries and targets inside the twenty, where the "
        "touchdowns come from. A week still being played counts what has been played. "
        "<strong>Tgt/snap</strong> stands in for a target rate: routes run is the figure "
        "that belongs there, and it is charted data that no free source publishes, so "
        "snaps are the honest denominator we have. Quarterbacks, kickers and defences are "
        "not on this page - it is about who the ball goes to."
        "</p></details>"
        + ui.views_bar(VIEWS)
        + controls
        + f"<div class='us-scroll'><table class='us view-overall'><thead>{head}</thead>"
        f"<tbody>{_rows(recent, season, held, names)}</tbody></table></div>"
        + f"<script type='application/json' id='us-cfg'>{cfg}</script>" + ui.JS)


def generate():
    out = paths.WEB_USAGE
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(add_front_matter(layout.HEAD + body(), "NFL Usage",
                                    "Snap, carry and target share, and who owns them"),
                   encoding="utf-8")
    print(f"Wrote NFL Usage -> {out}")


if __name__ == "__main__":
    generate()
