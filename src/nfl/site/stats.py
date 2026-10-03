"""
The NFL team stats page (/nfl/stats/): every team's EPA, success and
explosive rates, drive and situational rates, opponent-adjusted EPA, and QB,
RB and receiver leaderboards - the nerd page, the twin of /cfb/stats/, on the
shared engine (gordstats.stats_page). The figures are nfl.advanced's, read
from its cache (which it refreshes from nflverse when stale).

    python -m nfl.site.stats
"""
from datetime import datetime

from gordstats import logos, paths, stats_page
from gordstats.frontmatter import add_front_matter
from nfl import advanced
from nfl.config import SEASON
from nfl.site import teams as teams_page

OUT = paths.DOCS / "nfl" / "stats" / "index.html"

# nflverse says LA for the Rams; ESPN's logo file is lar (logos fixes WAS).
_ESPN = {"LA": "lar"}


def _col(key, label, tip, fmt, better, *views):
    return {"key": key, "label": label, "tip": tip, "fmt": fmt, "better": better,
            "views": views}


# Offence and defence share labels, each under its own tab; the Overview's
# copies of the headline figures are aliases (ov_*) so every key is one column.
COLUMNS = [
    _col("rec", "Rec", "Record", "rec", None, "overview"),
    _col("net_adj", "Adj Net", "Adjusted EPA/play on offense minus adjusted EPA/play allowed",
         "epa", "high", "overview"),
    _col("ov_off", "Adj Off", "Offense EPA/play, adjusted for the defenses faced", "epa", "high",
         "overview"),
    _col("ov_def", "Adj Def", "EPA/play allowed, adjusted for the offenses faced", "epa", "low",
         "overview"),
    _col("ov_osr", "Off SR", "Offense success rate: plays with positive EPA", "pct", "high",
         "overview"),
    _col("ov_dsr", "Def SR", "Success rate allowed", "pct", "low", "overview"),
    _col("ov_oppd", "Off Pts/Dr", "Points per possession", "num2", "high", "overview"),
    _col("ov_dppd", "Def Pts/Dr", "Points allowed per possession", "num2", "low", "overview"),

    _col("off_adj", "Adj EPA", "EPA/play, adjusted for the defenses faced", "epa", "high",
         "offense"),
    _col("off_epa", "EPA", "EPA/play as played", "epa", "high", "offense"),
    _col("off_pass", "Pass EPA", "EPA per dropback (sacks and scrambles included)", "epa", "high",
         "offense"),
    _col("off_rush", "Rush EPA", "EPA per designed run", "epa", "high", "offense"),
    _col("off_sr", "Success", "Plays with positive EPA", "pct", "high", "offense"),
    _col("off_xpl", "Explosive", "Dropbacks of 20+ yards and runs of 10+, per play", "pct", "high",
         "offense"),
    _col("off_ppd", "Pts/Dr", "Points per possession", "num2", "high", "offense"),
    _col("off_to", "TO %", "Possessions ending in an interception or lost fumble", "pct", "low",
         "offense"),
    _col("off_sack", "Sack %", "Sacks per dropback", "pct", "low", "offense"),
    _col("off_ppg", "Plays/G", "Dropbacks and runs per game", "num1", None, "offense"),

    _col("def_adj", "Adj EPA", "EPA/play allowed, adjusted for the offenses faced", "epa", "low",
         "defense"),
    _col("def_epa", "EPA", "EPA/play allowed as played", "epa", "low", "defense"),
    _col("def_pass", "Pass EPA", "EPA per dropback allowed", "epa", "low", "defense"),
    _col("def_rush", "Rush EPA", "EPA per designed run allowed", "epa", "low", "defense"),
    _col("def_sr", "Success", "Success rate allowed", "pct", "low", "defense"),
    _col("def_xpl", "Explosive", "Explosive plays allowed, per play", "pct", "low", "defense"),
    _col("def_ppd", "Pts/Dr", "Points allowed per possession", "num2", "low", "defense"),
    _col("def_to", "TO %", "Opponent possessions ending in a takeaway", "pct", "high", "defense"),
    _col("def_sack", "Sack %", "Sacks per opponent dropback", "pct", "high", "defense"),
    _col("def_ppg", "Plays/G", "Opponent dropbacks and runs per game", "num1", None, "defense"),

    _col("off_third", "3rd %", "Third downs converted", "pct", "high", "situational"),
    _col("def_third", "Opp 3rd %", "Opponents' third downs converted", "pct", "low", "situational"),
    _col("off_rz", "RZ TD %", "Red-zone possessions ending in a touchdown", "pct", "high",
         "situational"),
    _col("def_rz", "Opp RZ TD %", "Opponents' red-zone possessions ending in a touchdown", "pct",
         "low", "situational"),
    _col("off_npr", "Early Pass %", "Dropbacks on neutral early downs", "pct", None, "situational"),
    _col("off_proe", "PROE", "That pass rate over what the situation predicts", "pct", None,
         "situational"),
    _col("off_pace", "Sec/Play", "Game clock between neutral snaps: lower is faster", "num1", None,
         "situational"),
]

_ALIASES = {"ov_off": "off_adj", "ov_def": "def_adj", "ov_osr": "off_sr", "ov_dsr": "def_sr",
            "ov_oppd": "off_ppd", "ov_dppd": "def_ppd"}

# The glossary names each figure once; defense is the same figure turned round.
GLOSSARY = [
    {"label": "EPA", "tip": "Expected points added per play: how much a snap changed the points "
     "the offense could expect from the drive, given down, distance, field position and clock. "
     "League average this season is about zero; +0.10 is very good, +0.20 elite."},
    {"label": "Adj EPA", "tip": "EPA/play less how much better or worse than average the "
     "defenses a team has met have been (on defense, the offenses it has met) - see above."},
    {"label": "Pass EPA / Rush EPA", "tip": "EPA per dropback (passes, sacks and scrambles) and "
     "per designed run."},
    {"label": "Success (SR)", "tip": "Share of plays with positive EPA - how often a snap "
     "helped the offense at all."},
    {"label": "Explosive", "tip": "Share of plays that were dropbacks gaining 20+ yards or runs "
     "gaining 10+."},
    {"label": "Pts/Dr", "tip": "Points per possession, the try after a touchdown included and "
     "defensive and return scores not."},
    {"label": "TO %", "tip": "Share of possessions ending in an interception or lost fumble; on "
     "defense, takeaways."},
    {"label": "Sack %", "tip": "Sacks per dropback (scrambles count as dropbacks)."},
    {"label": "Plays/G", "tip": "Dropbacks and runs per game - style, not quality, so not "
     "colored."},
    {"label": "3rd %", "tip": "Third downs converted, by a gain or a penalty."},
    {"label": "RZ TD %", "tip": "Possessions with a snap inside the opponent's 20 that end in a "
     "touchdown."},
    {"label": "Early Pass %", "tip": "How often a team drops back on 1st and 2nd down in neutral "
     "situations: win chance 20-80%, outside the last two minutes of a half."},
    {"label": "PROE", "tip": "Pass rate over expected: that neutral pass rate above or below "
     "what nflverse's model expects from down, distance, field position and clock."},
    {"label": "Sec/Play", "tip": "Seconds of game clock between an offense's snaps in neutral "
     "situations. Incompletions stop the clock, so pass-heavy teams read quicker."},
]


def _record(t) -> str:
    return f"{t['w']}-{t['l']}" + (f"-{t['t']}" if t.get("t") else "")


def rows(data: dict) -> list:
    out = []
    for t in data["teams"]:
        r = dict(t)
        r.update({k: t.get(src) for k, src in _ALIASES.items()})
        r["rec"] = _record(t)
        # A team links to its page once it has one (nfl.site.teams builds
        # first); nflverse's nickname is the one the page's URL is made from.
        page = teams_page.OUT_DIR / teams_page.team_slug(t["name"]) / "index.html"
        r["link"] = teams_page.url(t["name"]) if page.exists() else None
        r["logo"] = logos.url("nfl", _ESPN.get(t["abbr"], t["abbr"]), logos.fetch_px(20))
        r["group"] = t.get("div") or ""
        r["tags"] = [t["conf"]] if t.get("conf") else []
        out.append(r)
    return out


def filters(data: dict) -> list:
    confs = sorted({t["conf"] for t in data["teams"] if t.get("conf")})
    divs = sorted({t["div"] for t in data["teams"] if t.get("div")})
    return [("", "All teams")] + [(c, c) for c in confs] + [(d, d) for d in divs]


# The leaderboard's sub line is escaped by stats_page: plain characters, no entities.
def _signed(v) -> str:
    return "\u2014" if v is None else f"{v:+.1f}"


def _pct(v) -> str:
    return "\u2014" if v is None else f"{v * 100:.0f}%"


def leader_groups(data: dict) -> list:
    players = data.get("players") or {}
    mins = advanced.MIN_PER_GAME

    qb = [{"name": p["name"], "team": p["team"], "value": p["epa"], "fmt": "epa",
           "vol": f"{p['n']} dropbacks",
           "sub": f"CPOE {_signed(p.get('cpoe'))} · {_pct(p.get('sr'))} success"}
          for p in players.get("qb", [])]
    rb = [{"name": p["name"], "team": p["team"], "value": p["epa"], "fmt": "epa",
           "vol": f"{p['n']} carries",
           "sub": f"{_pct(p.get('sr'))} success · {p.get('ypc') or 0:.1f} yds/carry"}
          for p in players.get("rb", [])]
    wr = [{"name": p["name"], "team": p["team"], "value": p["epa"], "fmt": "epa",
           "vol": f"{p['n']} targets",
           "sub": f"{_pct(p.get('catch'))} caught · {p.get('adot') or 0:.1f} aDOT"}
          for p in players.get("wr", [])]
    return [g for g in [
        {"key": "qb", "label": "QB", "metric": "EPA per dropback",
         "volume": f"at least {mins['qb']} dropbacks a team game", "rows": qb},
        {"key": "rb", "label": "RB", "metric": "EPA per carry",
         "volume": f"at least {mins['rb']} carries a team game", "rows": rb},
        {"key": "wr", "label": "WR/TE", "metric": "EPA per target",
         "volume": f"at least {mins['wr']} targets a team game", "rows": wr},
    ] if g["rows"]]


def _explainer() -> str:
    return (
        "<p>Defense columns are the same figures for what opponents did against a team: lower "
        "is better there, except takeaways and sacks.</p>"
        f"<p>EPA, success and explosive rates leave out garbage time &mdash; fourth-quarter snaps "
        f"with the offense's win chance under {advanced.GARBAGE_WP:.0%} or over "
        f"{1 - advanced.GARBAGE_WP:.0%}. The rest count every snap. A play is a dropback or a "
        "designed run, penalties that wiped one out included; two-point tries, kneels and spikes "
        "are not. Regular season only.</p>"
        "<p><strong>Adjusted</strong> EPA takes off how much better or worse than average the "
        "defenses a team has faced were in their other games (on defense, the offenses faced), "
        "those games adjusted the same way. A few weeks of any team is mostly noise &mdash; "
        "defense most of all &mdash; so opponents are pulled toward average until there is "
        "more of them, and the adjustment starts small and grows through the season.</p>"
        "<p><strong>Players</strong> leave out garbage time and plays a penalty wiped out. "
        "QBs are rated on nflverse's qb_epa, which does not charge a passer for his receiver's "
        "fumble; CPOE is completion percentage over expected. aDOT is average depth of target. "
        "Minimums grow with the season. From "
        "<a href='https://github.com/nflverse'>nflverse</a> play-by-play.</p>")


def body(data: dict) -> str:
    if not data or not data.get("teams"):
        return "<p>No numbers yet this season - they fill in after the first week's games.</p>"
    week = data.get("through_week")
    table = stats_page.table(rows(data), COLUMNS, filters=filters(data), filter_label="Show",
                             entity="Team", default_view="overview", sort_key="net_adj")
    return (
        f"<p>Every NFL offense and defense{f' through Week {week}' if week else ''} by expected "
        "points added, adjusted for the opponents faced. Tap a column to sort; the shading is "
        "where a team ranks.</p>"
        + table
        + "<h2>Player leaders</h2>"
        + stats_page.leaders(leader_groups(data), top=15)
        + stats_page.glossary(GLOSSARY, _explainer()))


def generate():
    data = advanced.refresh() or {}
    season, week = data.get("season", SEASON), data.get("through_week")
    updated = datetime.fromisoformat(data["updated"]) if data.get("updated") else True
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(add_front_matter(
        body(data), "Team Stats",
        subtitle=f"NFL {season}{f' &middot; through Week {week}' if week else ''}",
        description=(f"Every NFL team's {season} EPA per play, opponent-adjusted, with success "
                     "and explosive rates, third-down and red-zone rates, pace, and QB, RB and "
                     "receiver leaderboards, from nflverse play-by-play."),
        updated=updated), encoding="utf-8")
    print(f"Wrote NFL Team Stats -> {OUT}")


if __name__ == "__main__":
    generate()
