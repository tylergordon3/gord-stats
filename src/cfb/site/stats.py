"""
CFB team stats (/cfb/stats/): every FBS team's offence and defence on expected
points and success rate, adjusted for the opponents faced, with the raw splits,
the box score and player leaderboards beside them - the numbers behind the
numbers, from CollegeFootballData (cfb.advanced). Drawn by the shared
gordstats.stats_page; the NFL's twin is nfl.site.stats.

The headline figures are CFBD's opponent-adjusted ones: an offence that has
played three top-20 defences is not graded like one that has played three
FCS teams. The raw, garbage-time-free splits (explosiveness, stuff rate, havoc,
points per trip) and the box score (third downs, turnovers, sacks, penalties)
are as played.

    python -m cfb.site.stats
"""
from cfb import advanced, cfbd, espn
from cfb.config import SEASON, WEB_DIR
from cfb.site import teams as teams_page, write_page
from gordstats import how, logos, stats_page

OUT = WEB_DIR / "stats" / "index.html"

CONFERENCES = {"SEC": "SEC", "B1G": "Big Ten", "ACC": "ACC", "B12": "Big 12", "PAC": "Pac-12",
               "AAC": "American", "MWC": "Mountain West", "SBC": "Sun Belt", "MAC": "MAC",
               "CUSA": "Conference USA", "Ind": "Independents"}
POWER4 = {"SEC", "B1G", "ACC", "B12"}


def _c(key, label, tip, fmt, better, *views):
    return {"key": key, "label": label, "tip": tip, "fmt": fmt, "better": better, "views": views}


COLUMNS = [
    _c("rec", "Rec", "Won-lost this season.", "rec", None, "overview"),
    _c("adj_net", "Net EPA", "Offensive EPA per play minus defensive EPA per play allowed, adjusted "
       "for opponents: points better than the opponent per snap.", "epa", "high", "overview"),
    _c("adj_off", "Off EPA", "Expected points added per offensive play, adjusted for the defenses "
       "faced.", "epa", "high", "overview", "offense"),
    _c("adj_def", "Def EPA", "Expected points added per play by opponents, adjusted for the "
       "offenses faced. Lower is better.", "epa", "low", "overview", "defense"),
    _c("adj_sr", "Success", "Share of offensive plays that were a success - 50% of the yards needed "
       "on first down, 70% on second, all of them on third and fourth. Opponent-adjusted.",
       "pct", "high", "overview", "offense"),
    _c("adj_sr_a", "Success allowed", "Opponents' success rate, adjusted. Lower is better.",
       "pct", "low", "overview", "defense"),
    _c("talent_rank", "Talent", "Rank in 247Sports' team talent composite - the recruiting ratings "
       "of the roster.", "int", "low", "overview"),
    # Offence
    _c("adj_off_pass", "Pass EPA", "EPA per passing play, opponent-adjusted.", "epa", "high", "offense"),
    _c("adj_off_rush", "Rush EPA", "EPA per rushing play, opponent-adjusted.", "epa", "high", "offense"),
    _c("adj_sr_sd", "Std downs", "Success rate on standard downs (first down, second and 7 or less, "
       "third and fourth and 4 or less), adjusted.", "pct", "high", "offense"),
    _c("adj_sr_pd", "Pass downs", "Success rate on passing downs - the long-yardage ones - adjusted.",
       "pct", "high", "offense"),
    _c("adj_expl", "Explosive", "Average EPA of the successful plays: how big the good plays are, "
       "adjusted.", "num2", "high", "offense"),
    _c("adj_line", "Line yds", "Line yards per carry: the rushing yards credited to the offensive "
       "line (the first 0-4 yards count fully, 5-10 at half, beyond 10 not at all; losses at "
       "120%). Adjusted.", "num2", "high", "offense"),
    _c("off_stuff", "Stuffed", "Share of runs stopped at or behind the line.", "pct", "low", "offense"),
    _c("off_ppo", "Pts/trip", "Points per scoring opportunity - drives that reach the opponent's "
       "40.", "num2", "high", "offense"),
    _c("off_havoc", "Havoc allowed", "Share of plays that ended in a tackle for loss, a forced "
       "fumble, an interception or a pass defended.", "pct", "low", "offense"),
    _c("third", "3rd down", "Third downs converted.", "pct", "high", "offense"),
    _c("off_start", "Start", "Average starting field position, as the offense's own yard line.",
       "num1", "high", "offense"),
    # Defence
    _c("adj_def_pass", "Pass EPA allowed", "Opponents' EPA per passing play, adjusted.",
       "epa", "low", "defense"),
    _c("adj_def_rush", "Rush EPA allowed", "Opponents' EPA per rushing play, adjusted.",
       "epa", "low", "defense"),
    _c("adj_sr_sd_a", "Std downs allowed", "Opponents' success rate on standard downs, adjusted.",
       "pct", "low", "defense"),
    _c("adj_sr_pd_a", "Pass downs allowed", "Opponents' success rate on passing downs, adjusted.",
       "pct", "low", "defense"),
    _c("adj_expl_a", "Explosive allowed", "Average EPA of opponents' successful plays, adjusted.",
       "num2", "low", "defense"),
    _c("adj_line_a", "Line yds allowed", "Opponents' line yards per carry, adjusted.",
       "num2", "low", "defense"),
    _c("def_stuff", "Stuff rate", "Share of opponents' runs stopped at or behind the line.",
       "pct", "high", "defense"),
    _c("def_havoc", "Havoc", "Share of plays the defense ended in a tackle for loss, a forced "
       "fumble, an interception or a pass defended.", "pct", "high", "defense"),
    _c("def_havoc_f7", "Front 7 havoc", "Havoc by the defensive line and linebackers.",
       "pct", "high", "defense"),
    _c("def_havoc_db", "DB havoc", "Havoc by the secondary.", "pct", "high", "defense"),
    _c("def_ppo", "Pts/trip allowed", "Opponents' points per trip past the 40.", "num2", "low", "defense"),
    _c("third_a", "3rd down allowed", "Opponents' third downs converted.", "pct", "low", "defense"),
    _c("sacks_pg", "Sacks/g", "Sacks per game.", "num1", "high", "defense"),
    _c("tfl_pg", "TFL/g", "Tackles for loss per game.", "num1", "high", "defense"),
    # Situational
    _c("plays_pg", "Plays/g", "Offensive plays per game, every snap - tempo.", "num1", None,
       "situational"),
    _c("pass_rate", "Pass rate", "Share of offensive plays that were passes.", "pct", None,
       "situational"),
    _c("to_margin", "TO margin/g", "Takeaways minus giveaways, per game.", "epa", "high",
       "situational"),
    _c("to_pg", "Giveaways/g", "Turnovers lost per game.", "num2", "low", "situational"),
    _c("take_pg", "Takeaways/g", "Turnovers forced per game.", "num2", "high", "situational"),
    _c("fourth", "4th down", "Fourth downs converted.", "pct", "high", "situational"),
    _c("sacked_pg", "Sacked/g", "Sacks taken per game.", "num1", "low", "situational"),
    _c("pen_pg", "Penalties/g", "Accepted penalties per game.", "num1", "low", "situational"),
    _c("pen_yds_pg", "Pen yds/g", "Penalty yards per game.", "num1", "low", "situational"),
    _c("top_pg", "Possession", "Minutes of possession per game.", "num1", None, "situational"),
    _c("def_start", "Opp start", "Opponents' average starting field position, their own yard line. "
       "Lower is better.", "num1", "low", "situational"),
    _c("talent", "Talent pts", "247Sports' team talent composite.", "num1", "high", "situational"),
]


def _names_by_id() -> dict:
    """ESPN id -> the name the site's team pages are built under."""
    full = espn.schedule()
    out = {}
    for side in ("home", "away"):
        for tid, name in zip(full[f"{side}_id"].astype(str), full[side]):
            out.setdefault(tid, name)
    return out


def rows() -> list:
    records = cfbd.records()
    names = _names_by_id()
    out = []
    for t in advanced.teams():
        tid = t["id"]
        slug = teams_page.team_slug(names.get(tid, t["name"]))
        linked = (WEB_DIR / "teams" / slug / "index.html").exists()
        out.append({**t,
                    "link": f"/cfb/teams/{slug}/" if linked else None,
                    "logo": logos.url("ncaa", tid, 40) if tid else None,
                    "rec": (records.get(tid) or {}).get("total", ""),
                    "group": t["conf"],
                    "tags": ["Power4"] if t["conf"] in POWER4 or t["name"] == "Notre Dame" else []})
    return out


def _leaders(fbs: set) -> str:
    got = advanced.players(fbs)
    groups = []
    for pos, label, kind, minimum, metric, vol in advanced.GROUPS:
        groups.append({"key": pos.lower(), "label": label,
                       "metric": f"{metric}, garbage time out", "volume": f"min {minimum} {vol}",
                       "fmt": "epa",
                       "rows": [{"name": r["name"], "team": r["team"], "value": r[kind],
                                 "vol": f"{r[f'{kind}_n']} {vol}"} for r in got.get(pos, [])]})
    return stats_page.leaders(groups)


def body() -> str:
    table_rows = rows()
    if not table_rows:
        return "<p>No numbers yet this season - they fill in after the first week's games.</p>"
    confs = sorted({r["conf"] for r in table_rows if r["conf"]},
                   key=lambda c: (c not in POWER4, CONFERENCES.get(c, c)))
    filters = [("", "All FBS"), ("Power4", "Power 4")] + [(c, CONFERENCES.get(c, c)) for c in confs]
    return (
        "<p>Every FBS offense and defense on expected points and success rate, adjusted for the "
        "opponents faced. Tap a column to sort; the shading is where a team ranks. "
        + how.button("team-stats") + "</p>"
        + stats_page.table(table_rows, COLUMNS, filters=filters, filter_label="Show",
                           sort_key="adj_net")
        + "<h2>Player leaders</h2>"
        + _leaders({r["name"] for r in table_rows})
        # What EPA is and which figures are adjusted is the team-stats
        # explainer (gordstats.how), opened from the chip in the intro.
        + stats_page.glossary(COLUMNS)
        + how.JS_TAG)


def generate() -> None:
    write_page(OUT, "Team Stats", body(), subtitle=f"{SEASON} season, the advanced numbers",
               description="Every FBS team's offense and defense on EPA, success rate, "
                           "explosiveness, havoc and more - opponent-adjusted - with player "
                           "leaders.")


if __name__ == "__main__":
    generate()
