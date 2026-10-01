"""
College football playoff odds (docs/cfb/playoff/): the College Football
Playoff projected on this site's own model (cfb.playoff), drawn by the shared
renderer (gordstats.playoff_page) - the likeliest bracket, then every
contender's chances beside ESPN FPI's, then the method, folded.

The page has three states. Before a game is played there is nothing to
project from and it says so. Once the CFP games have teams in them the
bracket is the real one and its figure becomes the chance to win it all;
after the title game it is the final bracket with the losers greyed.

    python -m cfb.site.playoff
"""
from html import escape

from cfb import playoff
from cfb.config import SEASON, WEB_DIR
from cfb.site import power
from cfb.site import teams as teams_page
from gordstats import logos, playoff_page
from gordstats.frontmatter import add_front_matter

OUT = WEB_DIR / "playoff" / "index.html"
# Who the table lists: a 1% chance by our count or by ESPN's.
OURS_AT_LEAST = 0.01
FPI_AT_LEAST = 0.01
DESCRIPTION = ("Who makes the 12-team College Football Playoff: every contender's odds "
               "from 10,000 simulations of the rest of the season on the GordStats model, "
               "the projected bracket, and ESPN FPI's chances beside ours.")


def fpi_odds(payload: dict) -> dict:
    """{ESPN id: {"playoff", "conf", "title", "full"}} from the FPI pull, as
    shares (ESPN prints percents); a figure ESPN has not computed is None."""
    out = {}
    try:
        rows = power._rows(payload) if payload else []
    except Exception as exc:                            # noqa: BLE001 - the column goes blank
        print(f"  ! playoff: FPI unreadable ({exc})")
        rows = []
    for t in rows:
        def share(v):
            return None if v is None else float(v) / 100.0
        out[t["id"]] = {"playoff": share(t.get("probmakeplayoffs")),
                        "conf": share(t.get("probwinconf")),
                        "title": share(t.get("probwintitle")), "full": t.get("name")}
    return out


def _link(name: str) -> str:
    return f"/cfb/teams/{teams_page.team_slug(name)}/"


def _record(rec) -> str:
    w, l = rec
    return f"{w}-{l}"


def _bracket(res, league, field: list, state: str) -> str:
    """Two halves of two cards each: a bye team and the first-round game whose
    winner it meets - the halves meeting in the semifinals."""
    fmt = playoff.FORMAT
    recs = playoff.records(league)
    losers = {i if w != i else j for (i, j), w in league.cfp_results.items()}

    def line(seed: int) -> dict:
        i = field[seed - 1]
        tid = league.teams[i]
        name = league.names[tid]
        if state == "final":
            fig = ""
        elif state == "set":
            fig = f"{playoff_page.pct_text(res.title[i])}%"
        else:
            fig = f"{playoff_page.pct_text(res.playoff[i])}%"
        return {"seed": seed, "id": tid, "name": name, "link": _link(name),
                "logo": logos.img("ncaa", tid, 22), "record": _record(recs[i]), "fig": fig,
                "state": "lost" if i in losers else None}

    games = dict(playoff.first_round(fmt.field, fmt.byes))
    slots = playoff.bracket_order(fmt.byes + len(games))
    pods = []
    for s in slots:
        if s > fmt.byes:
            continue
        rival = 2 * fmt.byes + 1 - s
        blocks = [{"label": None, "lines": [line(s)]}]
        if rival in games:
            blocks.append({"label": "First round", "lines": [line(rival), line(games[rival])]})
        pods.append(blocks)
    half = max(1, len(pods) // 2)
    groups = [{"title": f"Semifinal {k + 1}", "cards": pods[k * half:(k + 1) * half]}
              for k in range((len(pods) + half - 1) // half)]
    return playoff_page.bracket(groups, "cfb")


def _table(res, league, espn: dict) -> str:
    recs = playoff.records(league)
    avg = res.avg_seed()
    rows = []
    for i, tid in enumerate(league.teams):
        ours, theirs = float(res.playoff[i]), (espn.get(tid) or {}).get("playoff")
        if ours < OURS_AT_LEAST and (theirs or 0) < FPI_AT_LEAST:
            continue
        name = league.names[tid]
        rows.append({
            "id": tid, "name": name, "full": (espn.get(tid) or {}).get("full") or name,
            "link": _link(name), "logo": logos.img("ncaa", tid, 22),
            "record": _record(recs[i]),
            "values": {"playoff": ours, "fpi": theirs, "bye": float(res.bye[i]),
                       "conf": (float(res.conf_title[i])
                                if league.conf[i] not in ("", playoff.INDEPENDENT) else None),
                       "title": float(res.title[i]),
                       "seed": float(avg[i]) if ours >= 0.01 else None},
        })
    rows.sort(key=lambda r: (-r["values"]["playoff"], -(r["values"]["fpi"] or 0)))
    columns = [
        {"key": "playoff", "label": "Playoff", "kind": "pct",
         "tip": "Our chance of making the 12-team field"},
        {"key": "fpi", "label": "FPI", "kind": "pct",
         "tip": "ESPN FPI's chance of making the playoff, from its own simulations"},
        {"key": "bye", "label": "Bye", "kind": "pct",
         "tip": "Chance of a top-four seed and a first-round bye"},
        {"key": "conf", "label": "Conf", "kind": "pct",
         "tip": "Chance of winning the conference title game"},
        {"key": "title", "label": "Title", "kind": "pct",
         "tip": "Chance of winning the national championship"},
        {"key": "seed", "label": "Seed", "kind": "seed",
         "tip": "Average seed in the runs where the team makes the field"},
    ]
    return playoff_page.odds_table(rows, columns, "cfb", sort_key="playoff")


def _method(n: int) -> str:
    fmt = playoff.FORMAT
    return playoff_page.method([
        f"Every game left is played {n:,} times on <a href='/cfb/predictions/'>the GordStats "
        "model</a>, with the win chances the predictions page prints. Each team's rating also "
        "drifts from run to run, a little more for every week ahead - sized to how far teams "
        "really strayed from the model in 2015-2025 - so a team better than we think wins its "
        "games together and a game in November is less certain than Saturday's.",
        "<strong>Conference title games</strong> pair the two best conference records (the Sun "
        "Belt: East v West). A tie goes to the record in games among the tied teams, then to our "
        "rating, standing in for the computer rankings conferences use late in their lists. "
        "Common opponents are not modelled.",
        "<strong>Selection.</strong> The committee has no formula, so a stand-in picks the field: "
        "strength of record (wins above what an average top-25 team would expect against the "
        f"same schedule) plus our rating, {playoff.RATING_PER_WIN:.0f} points of it counting as "
        f"one win. The {', '.join(fmt.power[:-1])} and {fmt.power[-1]} champions are in, so is the "
        "best Group of Six team, champion or not, and Notre Dame if it ranks in the top 12; the "
        f"best of the rest fill the {fmt.field}.",
        f"<strong>Seeding</strong> is straight off that order: the top {fmt.byes} get byes, "
        f"{fmt.byes + 1}-{fmt.field} play on the higher seed's field, and the bracket is fixed. "
        "The bracket above takes each Power 4 conference's likeliest champion and the likeliest "
        "Group of Six team, fills it with the likeliest of the rest and seeds by average seed.",
        "<strong>FPI</strong> is ESPN's own simulation's playoff chance. The format is "
        "2026-27's (collegefootballplayoff.com, NCAA.com).",
    ])


def body() -> str:
    res, league, payload = playoff.project()
    if league is None:
        return playoff_page.page(playoff_page.empty(
            "No conference list from ESPN this build, so there is nothing to project. "
            "Back on the next one."))
    if res is None:
        return playoff_page.page(playoff_page.empty(
            "The projection starts once the first week of games is played."))
    espn = fpi_odds(payload)
    state = "final" if league.final else "set" if league.cfp_seeds else "projected"
    field = playoff.projected_field(res)
    if state == "final":
        champ = next((league.names[league.teams[i]] for i in range(len(league.teams))
                      if res.title[i] >= 0.999), None)
        head = "<h2>The bracket</h2>" + (
            f"<p class='po-note'>{escape(champ)} won the national title.</p>" if champ else "")
    elif state == "set":
        head = ("<h2>The bracket</h2><p class='po-note'>The real field. % is the chance "
                "to win the title.</p>")
    else:
        head = ("<h2>Projected bracket</h2><p class='po-note'>The likeliest field; % is each "
                "team's chance to make it.</p>")
    table_head = ("<h2>Every contender</h2><p class='po-note'>Chances in percent, ours "
                  "beside ESPN FPI's, for every team at 1% or better by either. Tap a column "
                  "to sort.</p>")
    return playoff_page.page(head, _bracket(res, league, field, state), table_head,
                             _table(res, league, espn), _method(res.n))


def generate():
    html = body()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(add_front_matter(html, "CFB Playoff Odds",
                                    f"{SEASON} season &middot; {playoff.N_SIMS:,} simulations",
                                    description=DESCRIPTION, updated=True), encoding="utf-8")
    print(f"Wrote CFB Playoff Odds -> {OUT}")


if __name__ == "__main__":
    generate()
