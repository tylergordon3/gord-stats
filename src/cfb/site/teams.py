"""
Team ratings and a page per team (docs/cfb/teams/).

The predictions page answers "what happens on Saturday". This answers the two
questions it raises and cannot fit on a card: how good is this team, and what
does the rest of its season look like.

The index ranks every FBS team on the same number the predictions run on --
points better than an average FBS side, from `cfb.ratings` -- and each team
page carries its whole schedule: results where they exist, this model's
predicted score where they do not.

One model fit serves all of it. Refitting per team would give the same answer
136 times, and refitting per week would make a team's own schedule disagree
with itself about how good the team is today.

    python -m cfb.site.teams
"""
from html import escape
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from cfb import games as games_mod
from cfb import predict
from cfb.config import WEB_DIR
from cfb.site import write_page
from gordstats import charts, palette

ET = ZoneInfo("America/New_York")
LOGO = "https://a.espncdn.com/i/teamlogos/ncaa/500/{team_id}.png"

_CSS = ("""<style>
.tm-note{color:#475569;font-size:14px;line-height:1.55}
.tm-scroll{overflow-x:auto}
table.tm{width:100%;border-collapse:collapse;font-size:14px}
table.tm th{background:#eef2f7;color:#334155;padding:7px 10px;text-align:center;
  font-size:12px;text-transform:uppercase;letter-spacing:.03em;white-space:nowrap;
  border:1px solid #e2e8f0}
table.tm td{padding:6px 10px;border:1px solid #eef2f7;color:#0f172a;background:#fff;
  text-align:center;white-space:nowrap}
table.tm td.tm-name{text-align:left;font-weight:600}
table.tm tbody tr:nth-child(even) td{background:#f8fafc}
table.tm a{text-decoration:none;color:#0f172a}
table.tm a:hover{text-decoration:underline}
/* The Slate theme frames every img; these are inline badges, not figures. */
table.tm img,.tm-head img{border:none;padding:0;box-shadow:none;background:none;
  border-radius:0;margin:0}
table.tm img{width:22px;height:22px;object-fit:contain;vertical-align:middle;
  margin-right:8px}
.tm-head{display:flex;align-items:center;gap:14px;margin:6px 0 4px}
.tm-head img{width:56px;height:56px;object-fit:contain}
.tm-head .tm-title{font-size:24px;font-weight:700;color:#0f172a}
.tm-head .tm-sub{color:#64748b;font-size:13px;margin-top:2px}
.tm-tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
  gap:12px;margin:16px 0 22px}
.tm-tile{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:12px 14px}
.tm-tile .t-label{font-size:11px;text-transform:uppercase;letter-spacing:.05em;
  color:#64748b;font-weight:600}
.tm-tile .t-value{font-size:23px;font-weight:700;color:#0f172a;margin-top:3px}
.tm-tile .t-sub{font-size:12px;color:#64748b;margin-top:2px}
.tm-win{color:{good};font-weight:700}
.tm-loss{color:{bad};font-weight:700}
</style>""").replace("{good}", "#15803d").replace("{bad}", "#b91c1c")

GOOD, BAD = "#15803d", "#b91c1c"


def team_slug(name: str) -> str:
    return charts.slug(name)


def _logo(team_id: str) -> str:
    return f"<img src='{LOGO.format(team_id=escape(str(team_id)))}' alt='' loading='lazy'>"


def _standings(frame: pd.DataFrame, model, names: dict) -> pd.DataFrame:
    """One row per rated FBS team: rating, rank, record so far."""
    rows = []
    for team in model.teams:
        if team == games_mod.FCS:
            continue
        home = frame[frame["home_team"] == team]
        away = frame[frame["away_team"] == team]
        played_home = home[home["played"]]
        played_away = away[away["played"]]
        wins = int((played_home["actual_margin"] > 0).sum()
                   + (played_away["actual_margin"] < 0).sum())
        losses = int((played_home["actual_margin"] < 0).sum()
                     + (played_away["actual_margin"] > 0).sum())
        rows.append({"team": team, "name": names.get(team, team),
                     "rating": model.rating(team), "pace": model.pace(team),
                     "wins": wins, "losses": losses,
                     "games": len(home) + len(away)})
    table = pd.DataFrame(rows).sort_values("rating", ascending=False).reset_index(drop=True)
    table["rank"] = np.arange(1, len(table) + 1)
    return table


def _schedule_rows(frame: pd.DataFrame, team: str, names: dict) -> str:
    mine = frame[(frame["home_team"] == team) | (frame["away_team"] == team)]
    rows = []
    for _, g in mine.sort_values("date").iterrows():
        at_home = g["home_team"] == team
        opponent = g["away_team"] if at_home else g["home_team"]
        opp_name = escape(str(g["away"] if at_home else g["home"]))
        opp_id = g["away_id"] if at_home else g["home_id"]
        prefix = "vs" if at_home else "at"
        if g["neutral"]:
            prefix = "vs"

        link = (f"<a href='/cfb/teams/{team_slug(names.get(opponent, opp_name))}/'>"
                f"{opp_name}</a>" if opponent != games_mod.FCS else opp_name)
        cell = f"{_logo(opp_id)}{prefix} {link}"

        margin = g["pred_margin"] if at_home else -g["pred_margin"]
        mine_pts = g["pred_home"] if at_home else g["pred_away"]
        opp_pts = g["pred_away"] if at_home else g["pred_home"]
        prob = g["home_win_prob"] if at_home else 1 - g["home_win_prob"]

        if g["played"]:
            got = g["home_score"] if at_home else g["away_score"]
            gave = g["away_score"] if at_home else g["home_score"]
            won = got > gave
            result = (f"<span class='{'tm-win' if won else 'tm-loss'}'>"
                      f"{'W' if won else 'L'} {got:.0f}&ndash;{gave:.0f}</span>")
            expected = f"{margin:+.1f}"
            chance = "&mdash;"
        else:
            result = f"{mine_pts:.0f}&ndash;{opp_pts:.0f}"
            expected = f"{margin:+.1f}"
            chance = f"{prob:.0%}"

        rows.append(f"<tr><td>{int(g['week'])}</td>"
                    f"<td class='tm-name'>{cell}</td>"
                    f"<td>{g['date'].astimezone(ET):%-d %b}</td>"
                    f"<td>{result}</td><td>{expected}</td><td>{chance}</td></tr>")
    head = ("<tr><th>Wk</th><th>Opponent</th><th>Date</th>"
            "<th>Result</th><th>Expected</th><th>Win</th></tr>")
    return ("<div class='tm-scroll'><table class='tm'>"
            f"<thead>{head}</thead><tbody>{''.join(rows)}</tbody></table></div>")


def _team_page(row, frame: pd.DataFrame, table: pd.DataFrame, names: dict) -> str:
    team, name = row["team"], escape(str(row["name"]))
    total = len(table)
    played = int(row["wins"] + row["losses"])

    tiles = [("Rating", f"{row['rating']:+.1f}", "points vs an average FBS team"),
             ("Rank", f"{int(row['rank'])} of {total}", "by this model"),
             ("Record", f"{int(row['wins'])}&ndash;{int(row['losses'])}",
              f"{played} game{'s' if played != 1 else ''} played"),
             ("Scoring", f"{row['pace']:+.1f}",
              "points of shootout vs the average game")]
    tile_html = ("<div class='tm-tiles'>" + "".join(
        f"<div class='tm-tile'><div class='t-label'>{label}</div>"
        f"<div class='t-value'>{value}</div><div class='t-sub'>{sub}</div></div>"
        for label, value, sub in tiles) + "</div>")

    head = (f"<div class='tm-head'>{_logo(team)}<div><div class='tm-title'>{name}</div>"
            f"<div class='tm-sub'>Rated {row['rating']:+.1f}, "
            f"{int(row['rank'])}{_ordinal(int(row['rank']))} of {total} FBS teams"
            f"</div></div></div>")

    note = ("<p class='tm-note'><strong>Expected</strong> is the margin this model "
            "gives the game, from this team's point of view, and it is shown for "
            "played games too so a result can be read against what was expected of "
            "it. <strong>Win</strong> is the chance of winning an upcoming game. "
            "How well any of this has worked is on the "
            "<a href='/cfb/predictions/'>predictions page</a>.</p>")
    return (_CSS + head + tile_html + _schedule_rows(frame, team, names) + note)


def _ordinal(n: int) -> str:
    if 11 <= (n % 100) <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def _index(table: pd.DataFrame, frame: pd.DataFrame) -> str:
    rows = []
    for _, r in table.iterrows():
        rows.append(
            f"<tr><td>{int(r['rank'])}</td>"
            f"<td class='tm-name'>{_logo(r['team'])}"
            f"<a href='/cfb/teams/{team_slug(r['name'])}/'>{escape(str(r['name']))}</a></td>"
            f"<td>{r['rating']:+.1f}</td><td>{r['pace']:+.1f}</td>"
            f"<td>{int(r['wins'])}&ndash;{int(r['losses'])}</td></tr>")
    head = ("<tr><th>#</th><th>Team</th><th>Rating</th><th>Scoring</th><th>Record</th></tr>")
    spread = table["rating"].max() - table["rating"].min()
    note = (f"<p class='tm-note'>Every FBS team on the number the predictions run on: "
            f"points better than an average FBS side, so +14 beats -14 by four "
            f"touchdowns on a neutral field. The whole division fits in "
            f"<strong>{spread:.0f} points</strong>. <strong>Scoring</strong> is the "
            f"same idea for the total &mdash; how many points this team adds to a "
            f"game, whichever sideline it is on. Ratings come out of "
            f"<a href='/cfb/predictions/'>the same model</a> that prices Saturday, "
            f"and carry the same caveats.</p>")
    return (_CSS + note + "<div class='tm-scroll'><table class='tm'>"
            f"<thead>{head}</thead><tbody>{''.join(rows)}</tbody></table></div>")


def generate() -> None:
    frame, model, names = predict.season()
    table = _standings(frame, model, names)

    write_page(WEB_DIR / "teams" / "index.html", "CFB Team Ratings",
               _index(table, frame),
               subtitle="Every FBS team, on the number behind the predictions")

    for _, row in table.iterrows():
        slug = team_slug(row["name"])
        write_page(WEB_DIR / "teams" / slug / "index.html",
                   escape(str(row["name"])), _team_page(row, frame, table, names),
                   subtitle=f"{row['name']} ratings, schedule and projected results")


if __name__ == "__main__":
    generate()
