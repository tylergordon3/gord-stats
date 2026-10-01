"""
NFL playoff odds (docs/nfl/playoff/): the field projected on this site's own
model (nfl.playoff), drawn by the shared renderer (gordstats.playoff_page) -
the likeliest seven a conference, every team's chances beside ESPN FPI's, and
the method, folded. The college page's twin (cfb.site.playoff).

Before Week 1 there is nothing to project and it says so. Once the regular
season is over the seeds are the real ones and the figure becomes the chance
to win the Super Bowl; after it, the final bracket with the losers greyed.

    python -m nfl.site.playoff
"""
from html import escape

from gordstats import logos, playoff_page, share_card
from gordstats.frontmatter import add_front_matter
from nfl import fpi, playoff
from nfl.config import SEASON, WEB_DIR
from nfl.site import teams as teams_page

OUT = WEB_DIR / "playoff" / "index.html"
DESCRIPTION = ("Who makes the NFL playoffs: every team's chance of a playoff spot, the "
               "division, the 1 seed and the Super Bowl from 10,000 simulations on the "
               "GordStats model, the projected bracket, and ESPN FPI's chances beside ours.")


def _record(rec) -> str:
    return teams_page.record_text(*rec)


def _line(res, league, i: int, seed: int, state: str, losers: set, recs: dict) -> dict:
    tid = league.teams[i]
    nick, abbr = league.names[tid]
    if state == "final":
        fig = ""
    elif state == "set":
        fig = f"{playoff_page.pct_text(res.title[i])}%"
    else:
        fig = f"{playoff_page.pct_text(res.playoff[i])}%"
    return {"seed": seed, "id": tid, "name": nick, "link": teams_page.url(nick),
            "logo": logos.img("nfl", abbr, 22), "record": _record(recs[i]), "fig": fig,
            "state": "lost" if i in losers else None}


def _bracket(res, league, seeds: dict, state: str) -> str:
    """One card a conference: the bye, then Wild Card weekend's three games."""
    recs = playoff.records(league)
    losers = {i if w != i else j for (i, j), w in league.results.items()}
    groups = []
    for conf, order in seeds.items():
        blocks = [{"label": "Bye", "lines": [_line(res, league, order[0], 1, state, losers, recs)]}]
        for k, hi in enumerate(range(playoff.BYES, playoff.BYES + (playoff.SEEDS - playoff.BYES) // 2)):
            lo = playoff.SEEDS - 1 - (hi - playoff.BYES)
            blocks.append({"label": "Wild card" if k == 0 else None,
                           "lines": [_line(res, league, order[hi], hi + 1, state, losers, recs),
                                     _line(res, league, order[lo], lo + 1, state, losers, recs)]})
        groups.append({"title": conf, "cards": [blocks]})
    return playoff_page.bracket(groups, "nfl")


def _table(res, league, espn: dict) -> str:
    recs = playoff.records(league)
    avg = res.avg_seed()
    rows = []
    for i, tid in enumerate(league.teams):
        nick, abbr = league.names[tid]
        e = espn.get(tid) or {}
        theirs = e.get("probmakeplayoffs")
        rows.append({
            "id": tid, "name": nick, "full": e.get("full") or nick, "link": teams_page.url(nick),
            "logo": logos.img("nfl", abbr, 22), "record": _record(recs[i]),
            "values": {"playoff": float(res.playoff[i]),
                       "fpi": None if theirs is None else float(theirs) / 100.0,
                       "div": float(res.division[i]), "top": float(res.top_seed[i]),
                       "sb": float(res.title[i]),
                       "seed": float(avg[i]) if res.playoff[i] >= 0.01 else None},
        })
    rows.sort(key=lambda r: (-r["values"]["playoff"], -(r["values"]["fpi"] or 0)))
    # The link preview: the five likeliest, as the table lists them.
    _CARD["rows"] = [(str(k + 1), r["name"], f"{r['values']['playoff']:.0%}")
                     for k, r in enumerate(rows[:5])]
    columns = [
        {"key": "playoff", "label": "Playoff", "kind": "pct",
         "tip": "Our chance of one of the conference's seven seeds"},
        {"key": "fpi", "label": "FPI", "kind": "pct",
         "tip": "ESPN FPI's chance of making the playoffs, from its own simulations"},
        {"key": "div", "label": "Div", "kind": "pct", "tip": "Chance of winning the division"},
        {"key": "top", "label": "#1", "kind": "pct",
         "tip": "Chance of the 1 seed and the conference's only bye"},
        {"key": "sb", "label": "SB", "kind": "pct", "tip": "Chance of winning the Super Bowl"},
        {"key": "seed", "label": "Seed", "kind": "seed",
         "tip": "Average seed in the runs where the team makes the playoffs"},
    ]
    return playoff_page.odds_table(rows, columns, "nfl", sort_key="playoff")


def _method(n: int) -> str:
    return playoff_page.method([
        f"Every game left is played {n:,} times on <a href='/nfl/'>the GordStats model</a>, "
        "with the win chances the predictions page prints. Each team's rating also drifts "
        "from run to run, a little more for every week ahead - sized to how far teams really "
        "strayed from the model in 2015-2025 - so a team better than we think wins its games "
        "together. A simulated game is never a tie; a real one counts half.",
        "<strong>Seeds:</strong> the four division winners are 1-4 by record, then three wild "
        "cards; the 1 seed alone has a bye. Wild Card weekend is 2 v 7, 3 v 6 and 4 v 5, the "
        "divisional round reseeds, and the higher seed hosts until the Super Bowl.",
        "<strong>Tiebreaks</strong>, the NFL's own order as far as it goes here: in a division "
        "head-to-head, then division record, then conference record; for seeds and wild cards "
        "head-to-head (with three or more teams only a sweep counts), then conference record - "
        "a wild-card tie inside one division settled the division's way first. Common games, "
        "strength of victory and the rest are not modelled: a coin stands in for them.",
        "The bracket above takes each division's likeliest winner and the three likeliest of the "
        "rest, seeded by their average seeds. <strong>FPI</strong> is ESPN's own simulation's "
        "playoff chance.",
    ])


def body() -> str:
    res, league = playoff.project()
    if res is None:
        return playoff_page.page(playoff_page.empty(
            "The projection starts once the first week of games is played."))
    try:
        espn = fpi.by_id()
    except Exception as exc:                            # noqa: BLE001 - the column goes blank
        print(f"  ! NFL playoff: no FPI ({exc})")
        espn = {}
    season_over = not (~league.games["played"]).any()
    state = "final" if league.final else "set" if season_over else "projected"
    seeds = playoff.projected_bracket(res)
    if state == "final":
        champ = next((league.names[league.teams[i]][0] for i in range(len(league.teams))
                      if res.title[i] >= 0.999), None)
        head = "<h2>The bracket</h2>" + (
            f"<p class='po-note'>The {escape(champ)} won the Super Bowl.</p>" if champ else "")
    elif state == "set":
        head = ("<h2>The bracket</h2><p class='po-note'>The regular season is over. % is the "
                "chance to win the Super Bowl.</p>")
    else:
        head = ("<h2>Projected bracket</h2><p class='po-note'>The likeliest seven a "
                "conference; % is each team's chance to make it.</p>")
    table_head = ("<h2>Every team</h2><p class='po-note'>Chances in percent, ours beside "
                  "ESPN FPI's. Tap a column to sort.</p>")
    return playoff_page.page(head, _bracket(res, league, seeds, state), table_head,
                             _table(res, league, espn), _method(res.n))


_CARD: dict = {}


def card() -> dict | None:
    """The page's link preview (gordstats.share_card), once there are odds."""
    rows = _CARD.get("rows")
    if not rows:
        return None
    return share_card.ranked("nfl-playoff", f"NFL \u00b7 {SEASON}", "NFL Playoff Odds",
                             "Chance to make the playoffs, on our model", rows)


def generate():
    _CARD.clear()
    html = body()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(add_front_matter(html, "NFL Playoff Odds",
                                    f"{SEASON} season &middot; {playoff.N_SIMS:,} simulations",
                                    description=DESCRIPTION, updated=True, image=card()),
                   encoding="utf-8")
    print(f"Wrote NFL Playoff Odds -> {OUT}")


if __name__ == "__main__":
    generate()
