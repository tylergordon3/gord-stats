"""
A page per NFL team (docs/nfl/teams/<slug>/), the twin of /cfb/teams/<slug>/:
how good the team is, what the rest of its season looks like, and how its
offense and defense measure up - on one phone screen before the schedule.

    header      record, GordStats rank of 32 and rating (nfl.predict)
    projected   the season's record by our model's game-by-game win chances
                beside ESPN FPI's simulation (nfl.fpi)
    advanced    eight of the Team Stats figures with where each ranks
                (nfl.advanced; the full table is /nfl/stats/)
    schedule    every game: the result, or our projected score, with the
                expected margin and win chance

One model fit serves all 32 pages, as on the college side: a refit per team
would give the same answer 32 times. A finished game's expected margin is
the one on record before kickoff (nfl.results), not the refit's, which has
seen the score. The look is the college team page's own (its stylesheet is
imported, like the predictions page imports the college card CSS), so a fix
there reaches both.

    python -m nfl.site.teams
"""
from html import escape

import numpy as np
import pandas as pd

from cfb.site.teams import _CSS, _ordinal
from gordstats import charts, favorites, logos, stats_page
from gordstats.frontmatter import add_front_matter
from nfl import advanced, fpi, predict, results
from nfl.config import SEASON, TZ, WEB_DIR

OUT_DIR = WEB_DIR / "teams"

# Playoff rounds as ESPN numbers them (seasontype 3); the Pro Bowl, week 4,
# is never in the schedule.
ROUNDS = {1: "WC", 2: "Div", 3: "Conf", 5: "SB"}
ROUND_NAMES = {1: "Wild Card", 2: "Divisional", 3: "Conference", 5: "Super Bowl"}

# nflverse (the stats) and ESPN (everything else) spell two teams differently.
_ESPN_ABBR = {"LA": "LAR", "WAS": "WSH"}


def team_slug(name: str) -> str:
    """The URL for a team: its nickname, which is unique in the league and -
    unlike the city or the abbreviation - survives a move."""
    return charts.slug(name)


def url(name: str) -> str:
    return f"/nfl/teams/{team_slug(name)}/"


def _logo(abbr, shown: int = 22) -> str:
    return logos.img("nfl", abbr, shown)


def _real(team_id) -> bool:
    """A team, not ESPN's TBD placeholder (-1/-2) for an unset playoff pairing."""
    return team_id is not None and str(team_id).strip() not in ("", "nan") \
        and not str(team_id).startswith("-")


def record_text(w: int, l: int, t: int = 0, dash: str = "-") -> str:
    return f"{w}{dash}{l}" + (f"{dash}{t}" if t else "")


def standings(frame: pd.DataFrame, model, names: dict, asof=None) -> pd.DataFrame:
    """One row per team on this season's schedule: rating, rank, record.

    `asof` counts only games before it toward the record - the history seed
    (nfl.site.power) rebuilds past weeks' tables with it."""
    teams = sorted({str(t) for t in pd.concat([frame["home_team"], frame["away_team"]])
                    if _real(t)})
    done = frame[frame["played"].astype(bool)]
    if asof is not None:
        done = done[done["date"] < asof]
    rows = []
    for team in teams:
        home, away = done[done["home_team"] == team], done[done["away_team"] == team]
        margins = pd.concat([home["actual_margin"], -away["actual_margin"]])
        name, abbr = names.get(team, (team, team))
        rows.append({"team": team, "name": name, "abbr": abbr,
                     "rating": model.rating(team), "pace": model.pace(team),
                     "wins": int((margins > 0).sum()), "losses": int((margins < 0).sum()),
                     "ties": int((margins == 0).sum())})
    table = pd.DataFrame(rows).sort_values("rating", ascending=False).reset_index(drop=True)
    table["rank"] = np.arange(1, len(table) + 1)
    return table


def week_label(week: int, seasontype: int) -> str:
    """The schedule's week cell: the number, or the playoff round."""
    return ROUNDS.get(int(week), f"P{int(week)}") if int(seasontype) == 3 else str(int(week))


def expected_record(frame: pd.DataFrame, team: str) -> tuple:
    """(wins, losses) over the whole schedule: results where a game is played
    (a tie half of each), this model's win chance where it is not."""
    wins = losses = 0.0
    for _, g in frame[(frame["home_team"] == team) | (frame["away_team"] == team)].iterrows():
        at_home = g["home_team"] == team
        if g["played"]:
            m = g["actual_margin"] if at_home else -g["actual_margin"]
            won = 1.0 if m > 0 else 0.5 if m == 0 else 0.0
        else:
            won = g["home_win_prob"] if at_home else 1 - g["home_win_prob"]
        wins, losses = wins + won, losses + (1 - won)
    return wins, losses


def _record_table(frame: pd.DataFrame, team: str, espn: dict) -> str:
    """Projected full-season record from every source that publishes one."""
    sources = [("GordStats", expected_record(frame, team),
                "Results so far plus this model's win chance in each game left")]
    e = espn.get(str(team)) or {}
    if e.get("projectedw") is not None and e.get("projectedl") is not None:
        sources.append(("ESPN FPI", (e["projectedw"], e["projectedl"]),
                        "ESPN's simulation of the full schedule"))
    rows = "".join(f"<tr><td class='tm-name'>{src}</td><td>{w:.1f}&ndash;{l:.1f}</td>"
                   f"<td class='tm-src-note'>{note}</td></tr>"
                   for src, (w, l), note in sources)
    return ("<h3>Projected record</h3><div class='tm-scroll'><table class='tm tm-rec'>"
            "<thead><tr><th>Source</th><th>W&ndash;L</th><th>How</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div>")


# The advanced block: eight of the Team Stats page's figures, each with where
# it ranks among the 32 (nfl.advanced). Offense leads, as on the stats page;
# the turnover pair is the one defense figure that is not mostly noise early.
_ADVANCED = [("off_adj", "Offense EPA/play", "epa", "high"),
             ("def_adj", "Defense EPA/play", "epa", "low"),
             ("off_sr", "Success rate", "pct", "high"),
             ("off_xpl", "Explosive plays", "pct", "high"),
             ("off_third", "3rd down", "pct", "high"),
             ("off_rz", "Red zone TD", "pct", "high"),
             ("off_to", "Giveaway rate", "pct", "low"),
             ("def_to", "Takeaway rate", "pct", "high")]


def advanced_ranks(names: dict, data: dict = None) -> tuple:
    """({ESPN id: {key: (value, rank, of)}}, through week) for the block, or
    ({}, None) before nflverse has the season. The stats are keyed by
    nflverse's abbreviation; the bridge is ESPN's, the nickname as a check."""
    if data is None:
        try:
            data = advanced.refresh() or {}
        except Exception as exc:                        # noqa: BLE001 - the pages stand without it
            print(f"  ! NFL team pages: no advanced stats ({exc})")
            data = {}
    by_abbr = {abbr: tid for tid, (_name, abbr) in names.items() if _real(tid)}
    by_nick = {name: tid for tid, (name, _abbr) in names.items() if _real(tid)}
    rows = []
    for t in data.get("teams") or []:
        tid = by_abbr.get(_ESPN_ABBR.get(t.get("abbr"), t.get("abbr"))) or by_nick.get(t.get("name"))
        if tid:
            rows.append({**t, "id": tid})
    out = {}
    for key, _label, _fmt, better in _ADVANCED:
        have = [r for r in rows if r.get(key) is not None]
        have.sort(key=lambda r: r[key], reverse=better == "high")
        for i, r in enumerate(have, 1):
            out.setdefault(r["id"], {})[key] = (r[key], i, len(have))
    return out, data.get("through_week")


_ADV_CSS = ("<style>.tm-adv{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));"
            "gap:8px;margin:6px 0 4px}.tm-adv-c{border:1px solid #e2e8f0;border-radius:10px;"
            "padding:8px 10px;background:#fff}.tm-adv-c span{display:block;font-size:12px;"
            "color:#64748b;font-weight:700}.tm-adv-c b{font-size:18px}.tm-adv-c small{display:block;"
            "font-size:12px;color:#475569}@media (prefers-color-scheme: dark){.tm-adv-c{"
            "background:#16203a;border-color:#2b3852}.tm-adv-c span,.tm-adv-c small{color:#aab7c9}}"
            "</style>")


def _advanced_block(ranks: dict, week=None) -> str:
    if not ranks:
        return ""
    cells = "".join(
        f"<div class='tm-adv-c'><span>{escape(label)}</span><b>{stats_page.fmt(ranks[key][0], fmt)}</b>"
        f"<small>{ranks[key][1]}{_ordinal(ranks[key][1])} of {ranks[key][2]}</small></div>"
        for key, label, fmt, _better in _ADVANCED if key in ranks)
    through = f" through Week {week}" if week else ""
    return (_ADV_CSS + "<h3>Advanced</h3><div class='tm-adv'>" + cells + "</div>"
            f"<p class='tm-note'>EPA is opponent-adjusted{through}, garbage time out; every "
            "team, every figure, on <a href='/nfl/stats/'>Team Stats</a>.</p>")


def _schedule_rows(frame: pd.DataFrame, team: str, names: dict, record: dict) -> str:
    mine = frame[(frame["home_team"] == team) | (frame["away_team"] == team)]
    rows = []
    for _, g in mine.sort_values("date").iterrows():
        at_home = g["home_team"] == team
        side = "away" if at_home else "home"
        opp_id = str(g[f"{side}_id"])
        opp_name = str(g[side])
        prefix = "vs" if at_home or g["neutral"] else "at"
        link = (f"<a href='{url(names.get(opp_id, (opp_name,))[0])}'>{escape(opp_name)}</a>"
                if _real(opp_id) else escape(opp_name))
        cell = f"{_logo(g[f'{side}_abbr']) if _real(opp_id) else ''}{prefix} {link}"

        # What was on record before kickoff for a finished game; the model as
        # it stands for the rest.
        rec = record.get(str(g["game_id"]))
        home_margin = (rec["pred_margin"] if g["played"] and rec is not None
                       and pd.notna(rec["pred_margin"]) else g["pred_margin"])
        margin = home_margin if at_home else -home_margin
        if g["played"]:
            got = g["home_score"] if at_home else g["away_score"]
            gave = g["away_score"] if at_home else g["home_score"]
            mark = "W" if got > gave else "L" if got < gave else "T"
            cls = {"W": " class='tm-win'", "L": " class='tm-loss'", "T": ""}[mark]
            result = f"<span{cls}>{mark} {got:.0f}&ndash;{gave:.0f}</span>"
            chance = "&mdash;"
        else:
            mine_pts = g["pred_home"] if at_home else g["pred_away"]
            opp_pts = g["pred_away"] if at_home else g["pred_home"]
            result = f"<span class='tm-proj'>proj {mine_pts:.0f}&ndash;{opp_pts:.0f}</span>"
            prob = g["home_win_prob"] if at_home else 1 - g["home_win_prob"]
            chance = f"{prob:.0%}"
        # Keyed on the opponent: on the Chiefs' page the row worth lighting is
        # the one against a team you follow, not every row on the page.
        rows.append(f"<tr{favorites.row_attr('nfl', opp_id) if _real(opp_id) else ''}>"
                    f"<td class='tm-name'><span class='row-rank'>"
                    f"{week_label(g['week'], g['seasontype'])}</span>{cell}</td>"
                    f"<td>{g['date'].tz_convert(TZ):%-d %b}</td>"
                    f"<td>{result}</td><td>{margin:+.1f}</td><td>{chance}</td></tr>")
    head = ("<tr><th>Opponent</th><th>Date</th>"
            "<th>Result</th><th>Expected</th><th>Win</th></tr>")
    return (favorites.table_css("table.tm") + "<div class='tm-scroll'><table class='tm'>"
            f"<thead>{head}</thead><tbody>{''.join(rows)}</tbody></table></div>")


def _team_page(row, frame: pd.DataFrame, table: pd.DataFrame, names: dict,
               espn: dict, adv: dict, week=None, record: dict = None) -> str:
    team = row["team"]
    rank, total = int(row["rank"]), len(table)
    e = espn.get(str(team)) or {}
    where = e.get("div") or ""
    head = (f"<div class='tm-head'>{_logo(row['abbr'], 56)}<div>"
            f"<div class='tm-title'>"
            f"{record_text(int(row['wins']), int(row['losses']), int(row['ties']), '&ndash;')}"
            f" &middot; {rank}{_ordinal(rank)} of {total}</div>"
            f"<div class='tm-sub'>Rated <b>{row['rating']:+.1f}</b> points vs an average team"
            + (f" &middot; {escape(where)}" if where else "") + "</div></div></div>")
    note = ("<p class='tm-note'><strong>Expected</strong> is this model's margin from this "
            "team's side - for a finished game, the one on record before kickoff. "
            "<strong>Win</strong> is the chance of winning a game still to play. "
            "How it has done: <a href='/nfl/'>predictions</a>.</p>")
    return (_CSS + head + _record_table(frame, team, espn)
            + _advanced_block(adv.get(str(team), {}), week)
            + "<h3>Schedule</h3>" + _schedule_rows(frame, team, names, record or {}) + note)


def _on_record() -> dict:
    try:
        return {str(r["game_id"]): r for _, r in results.on_record(SEASON).iterrows()}
    except Exception as exc:                            # noqa: BLE001
        print(f"  ! NFL team pages: no prediction archive ({exc})")
        return {}


def generate() -> None:
    frame, model, names = predict.season()
    table = standings(frame, model, names)
    espn = fpi.by_id()
    adv, week = advanced_ranks(names)
    record = _on_record()
    for _, row in table.iterrows():
        full = (espn.get(str(row["team"])) or {}).get("full") or row["name"]
        out = OUT_DIR / team_slug(row["name"]) / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(add_front_matter(
            _team_page(row, frame, table, names, espn, adv, week, record), escape(full),
            description=f"{full}: {SEASON} rating, projected record, advanced stats and "
                        "every game with a result or projected score"), encoding="utf-8")
    print(f"Wrote {len(table)} NFL team pages -> {OUT_DIR}")


if __name__ == "__main__":
    generate()
