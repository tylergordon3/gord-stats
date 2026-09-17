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
        out.append(
            f'<tr data-team="{escape(r["team"], quote=True)}" data-conf=""'
            f' data-pos="{escape(r["pos"], quote=True)}" data-own="{escape(own, quote=True)}"'
            f' data-name="{escape(str(r["player"]).lower(), quote=True)}">'
            f'<td class="us-name">{escape(str(r["player"]))}</td>'
            f'<td class="us-team">{escape(r["team"])}</td><td>{escape(r["pos"])}</td>'
            f'<td class="us-own">{label}</td>' + ui.num(r["games"])
            + f'<td data-v="{ui.v(r["snap_share"])}">{ui.bar(r["snap_share"])}</td>'
            f'<td class="us-lead" data-v="{ui.v(before("snap_share"))}">{ui.pct(before("snap_share"))}</td>'
            + ui.num(r["rush_att"])
            + f'<td data-v="{ui.v(r["car_share"])}">{ui.bar(r["car_share"])}</td>'
            f'<td class="us-lead" data-v="{ui.v(before("car_share"))}">{ui.pct(before("car_share"))}</td>'
            + ui.num(r["rec_tgt"])
            + f'<td data-v="{ui.v(r["tgt_share"])}">{ui.bar(r["tgt_share"])}</td>'
            f'<td class="us-lead" data-v="{ui.v(before("tgt_share"))}">{ui.pct(before("tgt_share"))}</td>'
            + ui.num(r["rec"])
            + f'<td data-v="{ui.v(r["air_share"])}">{ui.pct(r["air_share"])}</td>'
            + ui.num(rz) + ui.num(r["rush_yd"] + r["rec_yd"]) + ui.num(r["rush_td"] + r["rec_td"])
            + f'<td data-v="{ui.v(per_game)}">'
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
    frame = frame[frame["pos"].isin(usage_mod.POSITIONS)]
    weeks = sorted(int(w) for w in frame["week"].unique())
    recent_weeks = weeks[-RECENT_WEEKS:]
    recent = usage_mod.shares(frame, weeks=RECENT_WEEKS)
    season = usage_mod.shares(frame)
    recent = recent[(recent["rush_att"] + recent["rec_tgt"] >= MIN_TOUCHES)
                    | (recent["pos"] == "QB") & (recent["pass_att"] >= 10)]
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
        f"<label>Position <select id='us-pos'><option value=''>All</option>"
        f"{ui.options(usage_mod.POSITIONS)}</select></label>"
        "<label>Find <input id='us-find' type='search' placeholder='player'></label>"
        "<label title='Keep each NFL team together, sorted inside by the chosen column'>"
        "<input id='us-group' type='checkbox'> Group by team</label>"
        "<button id='us-reset' type='button'>Reset</button>"
        "<span class='us-count' id='us-count'></span></div></div>")
    span = (f"week {recent_weeks[0]}" if len(recent_weeks) == 1
            else f"weeks {recent_weeks[0]}&ndash;{recent_weeks[-1]}")
    head = ("<tr><th data-k='text'>Player</th><th data-k='text'>Team</th>"
            "<th data-k='text'>Pos</th><th data-k='text'>Fantasy</th><th data-k='n'>G</th>"
            "<th data-k='n' title='Offensive snaps played out of the team&#39;s'>Snap share</th>"
            "<th data-k='n' class='us-lead'>Season</th>"
            "<th data-k='n'>Car</th><th data-k='n'>Car share</th>"
            "<th data-k='n' class='us-lead'>Season</th>"
            "<th data-k='n'>Tgt</th><th data-k='n'>Tgt share</th>"
            "<th data-k='n' class='us-lead'>Season</th><th data-k='n'>Rec</th>"
            "<th data-k='n' title='Share of the team&#39;s air yards: how far downfield "
            "the targets are, not just how many'>Air share</th>"
            "<th data-k='n' title='Red-zone carries plus red-zone targets'>RZ looks</th>"
            "<th data-k='n'>Yds</th><th data-k='n'>TD</th>"
            "<th data-k='n' title='PPR points per game played'>PPR/G</th></tr>")
    cfg = json.dumps({"mine": mine, "teams": names, "storage": "nflMyTeam",
                      "sort": SORT_COLUMN}).replace("</", "<\\/")
    return (
        ui.CSS
        + "<p>Every skill player's share of his team's snaps, carries, targets and air "
        f"yards over the last three played weeks (<strong>{span}</strong>), with the season "
        "share beside it in grey, and who in the league owns him. A back whose snap share "
        "is climbing while his carries are flat is about to get the carries.</p>"
        "<details class='section'><summary>How to use this page</summary>"
        "<p class='us-note'><strong>Click any column</strong> to sort by it, again to "
        "reverse. <strong>Fantasy</strong> narrows the table to one roster, to everybody "
        "rostered, or to the <span class='us-fa'>FA</span> free agents; <em>My team</em> is "
        "the roster chosen on the <a href='/fantasy/roster/'>team dashboard</a>. For one "
        "backfield pick the NFL team and Position RB; for all of them tick <strong>Group "
        "by team</strong>. The filters live in the page address, so a view can be "
        "bookmarked or shared.</p>"
        "<p class='us-note'>All from Sleeper's weekly stats. <strong>Snap share</strong> is "
        "offensive snaps played out of the team's. Carry, target and air-yard shares divide "
        "by the team's own players added up, so a share cannot exceed what the team ran. "
        "<strong>RZ looks</strong> are carries and targets inside the twenty, where the "
        "touchdowns come from. A week still being played counts what has been played."
        "</p></details>"
        + controls
        + f"<div class='us-scroll'><table class='us'><thead>{head}</thead>"
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
