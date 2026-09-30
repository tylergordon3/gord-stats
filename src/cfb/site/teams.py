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

from cfb import espn
from cfb import games as games_mod
from cfb import predict
from cfb.config import DATA_DIR, SEASON, WEB_DIR
from cfb.site import write_page
from gordstats import charts, favorites, logos, palette, rankmoves

# Every build's rank and rating, one CSV per build (at most two a day), so the
# index can say how far a team has moved since any point in the season.
HISTORY_DIR = DATA_DIR / "ratings_history" / str(SEASON)

ET = ZoneInfo("America/New_York")

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
table.tm img{width:22px;height:22px;max-width:none;object-fit:contain;vertical-align:middle;
  margin-right:8px}
table.tm td.win-cell{font-variant-numeric:tabular-nums}
""" + rankmoves.CSS + """
.tm-head{display:flex;align-items:center;gap:14px;margin:6px 0 4px}
.tm-head img{width:56px;height:56px;object-fit:contain}
.tm-head .tm-title{font-size:22px;font-weight:800;color:#0f172a}
.tm-head .tm-sub{color:#475569;font-size:13.5px;margin-top:2px;line-height:1.4}
.tm-tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
  gap:12px;margin:16px 0 22px}
.tm-tile{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:12px 14px}
.tm-tile .t-label{font-size:11px;text-transform:uppercase;letter-spacing:.05em;
  color:#64748b;font-weight:600}
.tm-tile .t-value{font-size:23px;font-weight:700;color:#0f172a;margin-top:3px}
.tm-tile .t-sub{font-size:12px;color:#64748b;margin-top:2px}
.tm-win{color:{good};font-weight:700}
.tm-loss{color:{bad};font-weight:700}
/* A projected score for an unplayed game, so it never reads as a final. */
.tm-proj{color:var(--gs-muted,#5d6b7e);font-style:italic}
/* Projected record, one row per source. */
table.tm-rec{width:auto;min-width:min(100%,420px);margin:0 0 20px}
table.tm-rec td.tm-name{font-weight:600}
table.tm-rec td.tm-src-note{text-align:left;color:#64748b;font-size:12px;white-space:normal}
/* Identity leads every table; pin it while the stats scroll. Every cell
   above carries an opaque background in both themes, so nothing bleeds
   through the frozen column. */
table.tm th:first-child,table.tm td:first-child{position:sticky;left:0;z-index:1}
@media (prefers-color-scheme: dark){
  .tm-note{color:#aab7c9}
  table.tm th{background:#223052;color:#dde5ef;border-color:#2b3852}
  table.tm td{background:#16203a;border-color:#2b3852;color:#dde5ef}
  table.tm tbody tr:nth-child(even) td{background:#1b2540}
  table.tm a{color:#dde5ef}
  .tm-head .tm-title{color:#f1f5f9}
  .tm-head .tm-sub{color:#aab7c9}
  .tm-tile{background:#16203a;border-color:#2b3852}
  .tm-tile .t-label,.tm-tile .t-sub{color:#aab7c9}
  .tm-tile .t-value{color:#f1f5f9}
  .tm-proj{color:#7f8ea3}
  table.tm-rec td.tm-src-note{color:#aab7c9}
  .tm-win{color:#8ff0bd}
  .tm-loss{color:#ffb4ab}
}
</style>""").replace("{good}", "#15803d").replace("{bad}", "#b91c1c")

GOOD, BAD = "#15803d", "#b91c1c"


def team_slug(name: str) -> str:
    return charts.slug(name)


def _logo(team_id: str, shown: int = 22) -> str:
    return logos.img("ncaa", team_id, shown)


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
            result = f"<span class='tm-proj'>proj {mine_pts:.0f}&ndash;{opp_pts:.0f}</span>"
            expected = f"{margin:+.1f}"
            chance = f"{prob:.0%}"

        # Keyed on the opponent: on Georgia's page the row you want lit is the
        # one against a team you follow, not every row on the page.
        rows.append(f"<tr{favorites.row_attr('cfb', opp_id)}><td class='tm-name'>"
                    f"<span class='row-rank'>{int(g['week'])}</span>{cell}</td>"
                    f"<td>{g['date'].astimezone(ET):%-d %b}</td>"
                    f"<td>{result}</td><td>{expected}</td><td>{chance}</td></tr>")
    head = ("<tr><th>Opponent</th><th>Date</th>"
            "<th>Result</th><th>Expected</th><th>Win</th></tr>")
    return (favorites.table_css("table.tm") + "<div class='tm-scroll'><table class='tm'>"
            f"<thead>{head}</thead><tbody>{''.join(rows)}</tbody></table></div>")


def _expected_record(frame: pd.DataFrame, team: str) -> tuple:
    """(wins, losses) over the whole schedule: results where a game is played,
    this model's win chance where it is not."""
    wins = losses = 0.0
    for _, g in frame[(frame["home_team"] == team) | (frame["away_team"] == team)].iterrows():
        at_home = g["home_team"] == team
        if g["played"]:
            won = (g["actual_margin"] > 0) == at_home
            wins, losses = wins + won, losses + (not won)
        else:
            p = g["home_win_prob"] if at_home else 1 - g["home_win_prob"]
            wins, losses = wins + p, losses + (1 - p)
    return wins, losses


def espn_projections() -> dict:
    """{espn team id: (projected wins, projected losses)} from the cached FPI
    payload the rankings page keeps, or {} when there is none."""
    from cfb.site import power      # power imports this module
    try:
        rows = power._rows(power.fpi())
    except Exception as exc:
        print(f"  ! FPI unavailable for team pages ({exc})")
        return {}
    return {t["id"]: (t["projectedw"], t["projectedl"]) for t in rows
            if t.get("projectedw") is not None and t.get("projectedl") is not None}


def _record_table(frame: pd.DataFrame, team: str, espn_proj: dict) -> str:
    """Projected full-season record from every source that publishes one."""
    sources = [("GordStats", _expected_record(frame, team),
                "Results so far plus this model's win chance in each game left")]
    if str(team) in espn_proj:
        sources.append(("ESPN FPI", espn_proj[str(team)],
                        "ESPN's simulation of the full schedule"))
    rows = "".join(f"<tr><td class='tm-name'>{src}</td><td>{w:.1f}&ndash;{l:.1f}</td>"
                   f"<td class='tm-src-note'>{note}</td></tr>"
                   for src, (w, l), note in sources)
    return ("<h3>Projected record</h3><div class='tm-scroll'><table class='tm tm-rec'>"
            "<thead><tr><th>Source</th><th>W&ndash;L</th><th>How</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div>")


# The advanced block: a handful of the team stats page's figures, each with
# where it ranks among FBS teams (cfb.advanced; the full table is /cfb/stats/).
_ADVANCED = [("adj_off", "Offense EPA/play", "epa", "high"),
             ("adj_def", "Defense EPA/play", "epa", "low"),
             ("adj_sr", "Success rate", "pct", "high"),
             ("adj_sr_a", "Success allowed", "pct", "low"),
             ("adj_expl", "Explosiveness", "num2", "high"),
             ("def_havoc", "Defensive havoc", "pct", "high"),
             ("third", "3rd down", "pct", "high"),
             ("to_margin", "Turnover margin/g", "epa", "high")]


def advanced_ranks() -> dict:
    """{ESPN id: {key: (value, rank, of)}} for the block, or {} before CFBD has
    the season."""
    from cfb import advanced
    try:
        rows = advanced.teams()
    except Exception as exc:                     # the pages stand without it
        print(f"  ! team pages: no advanced stats ({exc})")
        return {}
    out = {}
    for key, _label, _fmt, better in _ADVANCED:
        have = [r for r in rows if r.get(key) is not None]
        have.sort(key=lambda r: r[key], reverse=better == "high")
        for i, r in enumerate(have, 1):
            out.setdefault(str(r["id"]), {})[key] = (r[key], i, len(have))
    return out


def _advanced_block(ranks: dict) -> str:
    if not ranks:
        return ""
    from gordstats import stats_page
    cells = "".join(
        f"<div class='tm-adv-c'><span>{escape(label)}</span><b>{stats_page.fmt(ranks[key][0], fmt)}</b>"
        f"<small>{ranks[key][1]}{_ordinal(ranks[key][1])} of {ranks[key][2]}</small></div>"
        for key, label, fmt, _better in _ADVANCED if key in ranks)
    return ("<style>.tm-adv{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));"
            "gap:8px;margin:6px 0 4px}.tm-adv-c{border:1px solid #e2e8f0;border-radius:10px;"
            "padding:8px 10px;background:#fff}.tm-adv-c span{display:block;font-size:12px;"
            "color:#64748b;font-weight:700}.tm-adv-c b{font-size:18px}.tm-adv-c small{display:block;"
            "font-size:12px;color:#475569}@media (prefers-color-scheme: dark){.tm-adv-c{"
            "background:#16203a;border-color:#2b3852}.tm-adv-c span,.tm-adv-c small{color:#aab7c9}}"
            "</style><h3>Advanced</h3><div class='tm-adv'>" + cells + "</div>"
            "<p class='tm-note'>Opponent-adjusted where it can be; every team, every figure, "
            "on <a href='/cfb/stats/'>Team Stats</a>.</p>")


def _team_page(row, frame: pd.DataFrame, table: pd.DataFrame, names: dict,
               espn_proj: dict | None = None, adv: dict | None = None) -> str:
    team = row["team"]
    total = len(table)

    # One block under the page title, not three: the name was the title, the
    # header and again beside the logo, and rating and rank were a sentence
    # and then two tiles - 900px of phone before the schedule.
    rank = int(row["rank"])
    head = (f"<div class='tm-head'>{_logo(team, 56)}<div>"
            f"<div class='tm-title'>{int(row['wins'])}&ndash;{int(row['losses'])}"
            f" &middot; {rank}{_ordinal(rank)} of {total}</div>"
            f"<div class='tm-sub'>Rated <b>{row['rating']:+.1f}</b> points vs an average FBS "
            f"team &middot; scoring {row['pace']:+.1f} vs the average game</div>"
            f"</div></div>")

    note = ("<p class='tm-note'>Games without a final yet show this model's "
            "projected score, tagged <em>proj</em>. "
            "<strong>Expected</strong> is the margin this model "
            "gives the game, from this team's point of view, and it is shown for "
            "played games too so a result can be read against what was expected of "
            "it. <strong>Win</strong> is the chance of winning an upcoming game. "
            "How well any of this has worked is on the "
            "<a href='/cfb/predictions/'>predictions page</a>.</p>")
    return (_CSS + head + _record_table(frame, team, espn_proj or {})
            + _advanced_block((adv or {}).get(str(team), {}))
            + "<h3>Schedule</h3>" + _schedule_rows(frame, team, names) + note)


def _ordinal(n: int) -> str:
    if 11 <= (n % 100) <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def _index(table: pd.DataFrame, frame: pd.DataFrame) -> str:
    bases = rankmoves.baselines(HISTORY_DIR, weeks=espn.week_spans(),
                                  week_label=espn.short_week_label)
    show_delta = any("rating" in b["frame"].columns for b in bases.values())
    rows = []
    for _, r in table.iterrows():
        move = change = ""
        if bases:
            spans, _first = rankmoves.move_spans(bases, r["team"], int(r["rank"]))
            move = f"<td class='win-cell'>{spans}</td>"
        if show_delta:
            spans, _first = rankmoves.delta_spans(bases, r["team"], r["rating"], "rating")
            change = f"<td class='win-cell'>{spans}</td>"
        rows.append(
            f"<tr{favorites.row_attr('cfb', r['team'])}>"
            f"<td class='tm-name'><span class='row-rank'>{int(r['rank'])}</span>"
            f"{_logo(r['team'])}"
            f"<a href='/cfb/teams/{team_slug(r['name'])}/'>{escape(str(r['name']))}</a>"
            f"{favorites.star('cfb', r['team'], r['name'])}</td>"
            f"{move}<td>{r['rating']:+.1f}</td>{change}<td>{r['pace']:+.1f}</td>"
            f"<td>{int(r['wins'])}&ndash;{int(r['losses'])}</td></tr>")
    move_th = change_th = ""
    if bases:
        move_th = (f"<th class='win-th' data-tips='{rankmoves.window_tips(bases, 'Places climbed')}' "
                   f"title='Places climbed since {next(iter(bases.values()))['at']:%b %-d}'>Move</th>")
    if show_delta:
        change_th = (f"<th class='win-th' data-tips='{rankmoves.window_tips(bases, 'Rating change')}' "
                     f"title='Rating change since {next(iter(bases.values()))['at']:%b %-d}'>&Delta;</th>")
    head = (f"<tr><th>Team</th>{move_th}<th>Rating</th>{change_th}<th>Scoring</th>"
            "<th>Record</th></tr>")
    first = next(iter(bases.values()))["at"] if bases else None
    # The bar carries the favourites filter whether or not there is history to
    # switch between, so the control doesn't vanish early in a season.
    switch = ("<div class='pin-bar'>"
              + (rankmoves.window_switch(bases) if bases else "")
              + favorites.controls() + "</div>")
    history_note = (
        " <strong>Move</strong> is places climbed"
        + (" and <strong>&Delta;</strong> the rating's change" if show_delta else "")
        + " since the point the buttons pick - every build is archived, "
        f"so the choice runs from before this week's games (<strong>{first:%b %-d}</strong>) back "
        "to the season's first, or to the end of any week's games." if bases else
        " Every build is archived; a Move column and a change-since chooser appear "
        "with the second one.")
    spread = table["rating"].max() - table["rating"].min()
    note = (f"<p class='tm-note'>Every FBS team on the number the predictions run on: "
            f"points better than an average FBS side.</p>"
            "<details class='section'><summary>About these ratings</summary>"
            f"<p class='tm-note'>+14 beats -14 by four touchdowns on a neutral field. "
            f"The whole division fits in <strong>{spread:.0f} points</strong>. "
            f"<strong>Scoring</strong> is the same idea for the total &mdash; how many "
            f"points this team adds to a game, whichever sideline it is on. Ratings come "
            f"out of <a href='/cfb/predictions/'>the same model</a> that prices Saturday, "
            f"and carry the same caveats.{history_note}</p></details>")
    return (_CSS + favorites.table_css("table.tm") + note + switch
            + "<div class='tm-scroll'><table class='tm'>"
            f"<thead>{head}</thead><tbody>{''.join(rows)}</tbody></table></div>"
            + rankmoves.WINDOW_JS)


def generate() -> None:
    frame, model, names = predict.season()
    table = _standings(frame, model, names)
    rankmoves.snapshot(
        HISTORY_DIR, pd.Series(table["rank"].values, index=table["team"].astype(str)),
        extra=pd.DataFrame({"rating": table["rating"].round(2).values,
                            "pace": table["pace"].round(2).values,
                            "name": table["name"].values},
                           index=table["team"].astype(str)))

    # The index that lived at /cfb/teams/ is part of the rankings page now
    # (cfb.site.power carries the GordStats column); the URL redirects there.
    # `_index` stays, unused, should a standalone list be wanted again.
    espn_proj = espn_projections()
    adv = advanced_ranks()
    for _, row in table.iterrows():
        slug = team_slug(row["name"])
        write_page(WEB_DIR / "teams" / slug / "index.html",
                   escape(str(row["name"])), _team_page(row, frame, table, names, espn_proj, adv),
                   description=f"{row['name']} ratings, schedule and projected results")


if __name__ == "__main__":
    generate()
