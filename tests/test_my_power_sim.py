"""
The JavaScript season simulation agrees with the Python one.

/fantasy/power/ ranks a reader's own league in the browser, because the rosters
and the rules only exist at Sleeper. That means two implementations of
`fantasy.league.power.simulate`, and the browser's one is the only thing
standing between a reader and a confidently wrong ranking.

Exact agreement is not available - two random number streams - so the two
halves are checked differently. Everything deterministic (the bracket, the slot
order, the seeding) is compared exactly. The simulation itself is compared
where a Monte Carlo can be: both are run over the same board, the same rosters
and the same schedule, and asked to land inside each other's sampling error.
That is a real check. A dropped flex slot, a bye applied to the wrong week or
an availability chain in the wrong state all move the answer far further than
the noise does.

The JS runs in headless Chromium, since the machine that builds this site has
no node; where Chromium is not available the test skips rather than pretending
to pass.
"""
import asyncio
import json
import re
import shutil
import subprocess
import time
import urllib.request

import numpy as np
import pandas as pd
import pytest

from fantasy.league import power
from gordstats import my_power

CHROME = next((p for p in ("/usr/bin/chromium-browser", "/usr/bin/chromium",
                           "/usr/bin/google-chrome") if shutil.which(p)), None)
pytestmark = pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")

PORT = 9477
POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"]
SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "K", "DEF"] + ["BN"] * 5
# The shape of a drafted roster: the ten starters, then a bench.
ROSTER_SHAPE = ["QB", "RB", "RB", "WR", "WR", "TE", "K", "DEF",
                "RB", "WR", "WR", "TE", "QB", "RB", "WR"]
TEAMS = 10
SIMS = 8000


def _engine() -> str:
    """The simulation, with the Jekyll and <script> wrappers stripped."""
    js = my_power.SIM_JS.replace("{% raw %}", "").replace("{% endraw %}", "")
    return re.sub(r"</?script[^>]*>", "", js)


class Browser:
    """Just enough CDP to evaluate an expression."""

    def __init__(self):
        subprocess.run(["fuser", "-k", f"{PORT}/tcp"], capture_output=True)
        self.proc = subprocess.Popen(
            [CHROME, "--headless=new", "--no-sandbox", "--disable-gpu",
             f"--remote-debugging-port={PORT}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            try:
                targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
                self.ws_url = next(t["webSocketDebuggerUrl"] for t in targets
                                   if t.get("type") == "page")
                return
            except Exception:                                   # noqa: BLE001
                time.sleep(0.5)
        raise RuntimeError("Chromium did not come up")

    def close(self):
        self.proc.terminate()
        self.proc.wait(timeout=10)

    def evaluate(self, expression):
        import websockets

        async def run():
            async with websockets.connect(self.ws_url, max_size=None) as ws:
                await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                                          "params": {"expression": expression,
                                                     "returnByValue": True}}))
                while True:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=180))
                    if msg.get("id") == 1:
                        result = msg.get("result", {})
                        if result.get("exceptionDetails"):
                            raise AssertionError(result["exceptionDetails"]["text"]
                                                 + " " + str(result["exceptionDetails"]
                                                             .get("exception", {})
                                                             .get("description", "")))
                        return result["result"].get("value")
        return asyncio.run(run())


@pytest.fixture(scope="module")
def browser():
    b = Browser()
    b.evaluate(_engine())
    yield b
    b.close()


@pytest.fixture(scope="module")
def league():
    """A board and ten rosters, deliberately uneven so a ranking has work to do.

    Every player is given the same catch rate as his position, so the PPR run
    both sides do is comparing like with like: the basis rescaling is checked
    on its own, below.
    """
    rng = np.random.default_rng(4242)
    rows, rosters = [], []
    pid = 0
    for team in range(TEAMS):
        held = []
        for slot, pos in enumerate(ROSTER_SHAPE):
            pid += 1
            key = str(pid)
            # A spread of quality, so teams are not interchangeable.
            base = {"QB": 17, "RB": 12, "WR": 11, "TE": 8, "K": 8, "DEF": 7}[pos]
            quality = base * (0.55 + 0.9 * rng.random()) * (1.0 - 0.05 * slot)
            rows.append({"sleeper_id": key, "pos": pos,
                         "bye": int(rng.integers(5, 15)),
                         "mu": round(max(quality, 0.5), 3),
                         "sd": round(max(quality * 0.55, 1.0), 3),
                         "mu_se": round(max(quality * 0.18, 0.5), 3),
                         "avail": round(0.62 + 0.36 * rng.random(), 3)})
            held.append(key)
        rosters.append({"roster_id": team + 1, "players": held})
    board = pd.DataFrame(rows)
    roster_frame = pd.DataFrame([{"roster_id": r["roster_id"], "sleeper_id": p}
                                 for r in rosters for p in r["players"]])
    # One fixed schedule, so neither side is drawing its own.
    schedule = _round_robin(TEAMS, power.FANTASY_REG_WEEKS)
    return board, roster_frame, rosters, schedule


def _round_robin(teams: int, weeks: int) -> list:
    """A plain circle schedule, the same one for both implementations."""
    order = list(range(teams))
    fixed, rotating = order[0], order[1:]
    table = []
    for _ in range(weeks):
        row = [0] * teams
        row[fixed], row[rotating[0]] = rotating[0], fixed
        for i in range(1, teams // 2):
            a, b = rotating[i], rotating[-i]
            row[a], row[b] = b, a
        table.append(row)
        rotating = rotating[1:] + rotating[:1]
    return table


def _js(board, rosters, schedule, **extra) -> dict:
    """The spec the browser is handed, mirroring the Python call."""
    payload = {str(r.sleeper_id): [POSITIONS.index(r.pos), int(r.bye),
                                   float(r.mu), float(r.sd), float(r.mu_se),
                                   float(r.avail),
                                   {"RB": 3.0, "WR": 4.0, "TE": 3.0}.get(r.pos, 0.0),
                                   0]
               for r in board.itertuples()}
    spec = {"board": payload, "posNames": POSITIONS, "rosters": rosters,
            "slots": SLOTS, "basis": 0, "weeks": power.FANTASY_REG_WEEKS,
            "playoffTeams": power.PLAYOFF_TEAMS, "median": True,
            "schedule": schedule, "sims": SIMS, "seed": 20260821}
    spec.update(extra)
    return spec


@pytest.fixture(scope="module")
def both(browser, league):
    board, roster_frame, rosters, schedule = league
    mine = power.simulate(board, roster_frame, sims=SIMS,
                          fixed_schedule=np.array(schedule))
    theirs = browser.evaluate(
        "JSON.stringify(GSPower.run(" + json.dumps(_js(board, rosters, schedule)) + "))")
    return mine, json.loads(theirs)


def _by_roster(result) -> dict:
    return {int(t["roster_id"]): t for t in result["teams"]}


# --------------------------------------------------------------------------- #
# The deterministic half: compared exactly.
# --------------------------------------------------------------------------- #

def test_the_bracket_is_the_one_the_python_plays(browser):
    """Six teams, two byes, 3v6 and 4v5 - the shape `power._bracket` hardcodes,
    arrived at here from `playoff_teams` alone."""
    order = browser.evaluate("JSON.stringify(GSPower.bracketOrder(8))")
    assert json.loads(order) == [1, 8, 4, 5, 2, 7, 3, 6]
    rounds = browser.evaluate("JSON.stringify([4,6,8].map(GSPower.bracketRounds))")
    assert json.loads(rounds) == [2, 3, 3]
    # Six teams over three weeks is what the built page simulates, and what
    # this arrives at without being told.
    assert browser.evaluate("GSPower.bracketRounds(6)") == power.PLAYOFF_WEEKS


def test_narrow_slots_choose_before_the_flex(browser):
    """A flex takes what a dedicated slot could have taken, so filling it first
    strands an eligible player on the bench."""
    found = json.loads(browser.evaluate(
        "JSON.stringify(GSPower.startingSlots("
        "['QB','RB','RB','WR','WR','TE','FLEX','SUPER_FLEX','K','DEF','BN','IR']))"))
    names = [s["name"] for s in found["slots"]]
    assert names.index("FLEX") > names.index("TE")
    assert names.index("SUPER_FLEX") > names.index("FLEX")
    assert "BN" not in names and "IR" not in names


def test_a_slot_we_cannot_project_is_reported_not_guessed(browser):
    """An IDP league gets a ranking with a caveat rather than a made-up one."""
    found = json.loads(browser.evaluate(
        "JSON.stringify(GSPower.startingSlots(['QB','RB','WR','TE','LB','DB','BN']))"))
    assert found["unsupported"] == ["LB", "DB"]
    assert [s["name"] for s in found["slots"]] == ["QB", "RB", "WR", "TE"]


# --------------------------------------------------------------------------- #
# The Monte Carlo half: compared inside its own noise.
# --------------------------------------------------------------------------- #

def test_projected_points_agree(both):
    """The generative model is the same: the same gamma, the same availability
    chain, the same lineup. A season's points is the tightest thing to compare
    because every week of every simulation contributes to it."""
    mine, theirs = both
    other = _by_roster(theirs)
    for row in mine.itertuples():
        js = other[int(row.roster_id)]
        assert abs(js["projPoints"] - row.proj_points) < 0.02 * row.proj_points, (
            f"roster {row.roster_id}: python {row.proj_points:.0f}, "
            f"js {js['projPoints']:.0f}")


def test_the_two_orderings_agree(both):
    """Ranking is what the page publishes, so it is what has to match. Teams
    within a point of each other may swap - that is the Monte Carlo, not a bug
    - so the check is on the correlation of the two orders, not on equality."""
    mine, theirs = both
    other = _by_roster(theirs)
    ours = [row.power for row in mine.itertuples()]
    them = [other[int(row.roster_id)]["power"] for row in mine.itertuples()]
    assert np.corrcoef(ours, them)[0, 1] > 0.99


def test_projected_wins_agree(both):
    mine, theirs = both
    other = _by_roster(theirs)
    for row in mine.itertuples():
        js = other[int(row.roster_id)]
        assert abs(js["projWins"] - row.proj_wins) < 0.5, (
            f"roster {row.roster_id}: python {row.proj_wins:.2f}, "
            f"js {js['projWins']:.2f}")


def test_playoff_and_title_odds_agree(both):
    """Sampling error on a proportion at 8,000 draws is under a point, so three
    points of tolerance is generous and still catches a real disagreement."""
    mine, theirs = both
    other = _by_roster(theirs)
    for row in mine.itertuples():
        js = other[int(row.roster_id)]
        assert abs(js["playoffOdds"] - row.playoff_odds) < 0.04, (
            f"roster {row.roster_id} playoffs: python {row.playoff_odds:.3f}, "
            f"js {js['playoffOdds']:.3f}")
        assert abs(js["titleOdds"] - row.title_odds) < 0.04, (
            f"roster {row.roster_id} title: python {row.title_odds:.3f}, "
            f"js {js['titleOdds']:.3f}")


def test_the_odds_are_a_distribution(both):
    """Six of ten make the playoffs and one of them wins, in every simulation."""
    _, theirs = both
    assert abs(sum(t["playoffOdds"] for t in theirs["teams"]) - power.PLAYOFF_TEAMS) < 1e-6
    assert abs(sum(t["titleOdds"] for t in theirs["teams"]) - 1.0) < 1e-6


def test_power_is_centred_on_a_hundred(both):
    _, theirs = both
    mean = sum(t["power"] for t in theirs["teams"]) / len(theirs["teams"])
    assert abs(mean - 100) < 1e-6


# --------------------------------------------------------------------------- #
# The page. A container without its script is the bug that shipped before.
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def page_html(monkeypatch_module):
    """The page, built without running the model.

    `body()` normally simulates this site's league, which is a network call and
    ten thousand seasons - and writes a snapshot into data/, so running it from
    a test put a second snapshot minutes after the Pi's and made the Move
    column's baseline arbitrary. Making the ranking unavailable takes the
    page's other branch, which carries the same reader's-league wiring and is
    the branch most of the year serves anyway.

    `charts.clear` is stubbed for the same reason and it is not fussiness: it
    deletes the section's rendered charts, and the branch taken here does not
    draw them again, so one test run left the published page with two missing
    images.
    """
    from fantasy.league import power as model
    from fantasy.site import power as page
    from gordstats import charts

    def unavailable(*args, **kwargs):
        raise model.NoRosters("no rosters yet")

    monkeypatch_module.setattr(model, "rankings", unavailable)
    monkeypatch_module.setattr(charts, "clear", lambda *a, **k: None)
    monkeypatch_module.setattr(page.charts, "clear", lambda *a, **k: None)
    return page.body()


def test_the_page_carries_the_container_and_every_script(page_html):
    """The roster page once shipped the league control's container without the
    control's script, and only passed testing because localStorage had been set
    by hand. Nothing here renders without all four."""
    assert "id='mp-host'" in page_html
    assert 'id="gs-power-sim"' in page_html, "the simulation itself is missing"
    assert "root.GSPower" in page_html
    assert "window.GSL" in page_html, "the shared league loader is missing"
    assert "id='ml-bar'" in page_html, "no way to pick a league"


def test_the_simulation_is_defined_before_the_page_asks_for_it(page_html):
    """The page builds its Worker from the simulation's own <script> element,
    so that element has to exist by the time the page script runs."""
    assert page_html.index('id="gs-power-sim"') < page_html.index("gs-power-sim'")


def test_the_readers_league_is_offered_before_the_draft_too(page_html):
    """For most of the year this site has no roster to rank and the page is the
    method write-up. A reader's league is drafted long before this one's data
    exists, and the page they land on must still be able to rank it."""
    assert "Your League" in page_html


def test_the_page_says_it_is_not_the_blended_rating():
    """The published Rating averages our simulation with FantasyPros, which is
    keyed to this league. A reader's league gets the simulation alone, and a
    smaller number beside a bigger one with no explanation is worse than no
    number."""
    assert "blends an outside source" in my_power.JS


# --------------------------------------------------------------------------- #
# Leagues that are not this one.
# --------------------------------------------------------------------------- #

OTHER_LEAGUES = [
    ("superflex, four playoff teams, no median win",
     12, 16, ["QB", "QB", "RB", "RB", "WR", "WR", "WR", "TE", "K", "DEF",
              "RB", "WR", "TE", "QB", "RB", "WR"],
     ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "K",
      "DEF"] + ["BN"] * 5, 4, False, 2, 13),
    ("fourteen teams, eight in the playoffs, two half-flexes, half-PPR",
     14, 15, ROSTER_SHAPE,
     ["QB", "RB", "RB", "WR", "WR", "TE", "REC_FLEX", "WRRB_FLEX", "K",
      "DEF"] + ["BN"] * 5, 8, True, 1, 14),
    ("four teams, and slots this site cannot project",
     4, 12, ["QB", "RB", "RB", "WR", "WR", "TE", "K", "DEF", "RB", "WR", "TE", "QB"],
     ["QB", "RB", "WR", "TE", "FLEX", "LB", "DB", "K", "DEF"] + ["BN"] * 3,
     2, False, 0, 14),
]


@pytest.mark.parametrize("name,teams,per,shape,slots,playoff_teams,median,basis,weeks",
                         OTHER_LEAGUES, ids=[c[0] for c in OTHER_LEAGUES])
def test_a_league_that_is_not_this_one_still_ranks(
        browser, name, teams, per, shape, slots, playoff_teams, median, basis, weeks):
    """The built page hardcodes this league's ten slots, six playoff teams and
    weekly median. Every one of those is a league setting, and getting any of
    them wrong is a ranking that looks fine and is not."""
    rng = np.random.default_rng(99)
    board, rosters, pid = {}, [], 0
    for team in range(teams):
        held = []
        for j in range(per):
            pid += 1
            pos = shape[j % len(shape)]
            board[str(pid)] = [POSITIONS.index(pos), int(rng.integers(5, 15)),
                               round(3 + 17 * rng.random(), 2), 6.0, 3.0, 0.85,
                               2.5 if pos in ("RB", "WR", "TE") else 0.0, 0]
            held.append(str(pid))
        rosters.append({"roster_id": team + 1, "players": held})

    spec = {"board": board, "posNames": POSITIONS, "rosters": rosters,
            "slots": slots, "basis": basis, "weeks": weeks,
            "playoffTeams": playoff_teams, "median": median,
            "sims": 600, "seed": 11}
    result = json.loads(browser.evaluate(
        "JSON.stringify(GSPower.run(" + json.dumps(spec) + "))"))

    assert len(result["teams"]) == teams
    # However many make the playoffs, that many do - in every simulation.
    assert abs(sum(t["playoffOdds"] for t in result["teams"]) - playoff_teams) < 1e-6
    assert abs(sum(t["titleOdds"] for t in result["teams"]) - 1.0) < 1e-6
    mean = sum(t["power"] for t in result["teams"]) / teams
    assert abs(mean - 100) < 1e-6
    # A four-team bracket is two weeks, not three.
    assert result["playoffWeeks"] == my_power_rounds(playoff_teams)


def my_power_rounds(teams: int) -> int:
    size = 1
    while size < teams:
        size *= 2
    return int(round(np.log2(size)))


def test_a_league_with_no_schedule_yet_still_ranks(browser):
    """Before Sleeper builds the schedule there are no opponents, and a page
    that needed them would be blank for the whole preseason."""
    board = {str(i): [i % 6, 7, 10.0, 6.0, 3.0, 0.85, 2.0, 0] for i in range(1, 121)}
    rosters = [{"roster_id": t + 1,
                "players": [str(t * 12 + j + 1) for j in range(12)]}
               for t in range(10)]
    spec = {"board": board, "posNames": POSITIONS, "rosters": rosters,
            "slots": SLOTS, "basis": 0, "weeks": 14, "playoffTeams": 6,
            "median": True, "schedule": None, "sims": 400, "seed": 3}
    result = json.loads(browser.evaluate(
        "JSON.stringify(GSPower.run(" + json.dumps(spec) + "))"))
    assert abs(sum(t["playoffOdds"] for t in result["teams"]) - 6) < 1e-6


def test_players_the_board_has_never_heard_of_are_depth_not_zeroes(browser):
    """Scoring an unrecognised player zero quietly punishes whoever rostered
    him, which on a ten-team board is a visible number of places. The built
    page stands him in at replacement level for the same reason."""
    rosters = [{"roster_id": t + 1, "players": ["ghost%d" % (t * 10 + j)
                                                for j in range(10)]}
               for t in range(6)]
    spec = {"board": {}, "posNames": POSITIONS, "rosters": rosters,
            "slots": SLOTS, "basis": 0, "weeks": 14, "playoffTeams": 4,
            "median": True, "sims": 400, "seed": 5}
    result = json.loads(browser.evaluate(
        "JSON.stringify(GSPower.run(" + json.dumps(spec) + "))"))
    assert result["unknownPlayers"] == 60
    assert all(t["projPoints"] > 0 for t in result["teams"])


def test_the_same_league_ranks_the_same_way_twice(browser):
    """A ranking that changes when you reload is not a ranking."""
    board = {str(i): [i % 6, 7, 5 + (i % 13), 6.0, 3.0, 0.85, 2.0, 0]
             for i in range(1, 91)}
    rosters = [{"roster_id": t + 1,
                "players": [str(t * 9 + j + 1) for j in range(9)]}
               for t in range(10)]
    spec = {"board": board, "posNames": POSITIONS, "rosters": rosters,
            "slots": SLOTS, "basis": 0, "weeks": 14, "playoffTeams": 6,
            "median": True, "sims": 300, "seed": 20260821}
    call = "JSON.stringify(GSPower.run(" + json.dumps(spec) + ").teams)"
    assert browser.evaluate(call) == browser.evaluate(call)


def test_a_standard_league_scores_less_than_a_ppr_one(browser):
    """The only difference between Sleeper's bases is what a catch is worth,
    and the board ships the catch rate so the page does not have to guess."""
    board = {str(i): [2, 7, 12.0, 6.0, 3.0, 0.9, 4.0, 0] for i in range(1, 61)}
    rosters = [{"roster_id": t + 1,
                "players": [str(t * 10 + j + 1) for j in range(10)]}
               for t in range(6)]
    base = {"board": board, "posNames": POSITIONS, "rosters": rosters,
            "slots": ["WR"] * 4 + ["BN"] * 6, "weeks": 14,
            "playoffTeams": 4, "median": True, "sims": 400, "seed": 5}
    out = []
    for basis in (0, 1, 2):
        spec = dict(base, basis=basis)
        out.append(json.loads(browser.evaluate(
            "JSON.stringify(GSPower.run(" + json.dumps(spec) + "))"))["teams"][0])
    ppr, half, std = [t["projPoints"] for t in out]
    assert ppr > half > std
    # Four starting receivers, four catches each, fourteen weeks: a catch is
    # worth 224 points across the season and half of that at half-PPR.
    assert abs((ppr - std) - 4*4*14) < 0.12 * (4*4*14)
    assert abs((ppr - half) - (ppr - std)/2) < 0.12 * (ppr - std)/2


def test_an_odd_sized_league_gives_somebody_a_bye_not_a_phantom_fixture(browser):
    """The circle schedule leaves one team out each week when the league has an
    odd number of them. An opponent table filled with zeroes rather than -1
    scored that team against whoever sat at index 0 - a fixture that does not
    exist, every week, for the whole season."""
    teams = 11
    board = {str(i): [i % 6, 7, 10.0, 6.0, 3.0, 0.9, 2.0, 0]
             for i in range(1, teams * 12 + 1)}
    rosters = [{"roster_id": t + 1,
                "players": [str(t * 12 + j + 1) for j in range(12)]}
               for t in range(teams)]
    spec = {"board": board, "posNames": POSITIONS, "rosters": rosters,
            "slots": SLOTS, "basis": 0, "weeks": 14, "playoffTeams": 6,
            "median": False, "schedule": None, "sims": 500, "seed": 8}
    result = json.loads(browser.evaluate(
        "JSON.stringify(GSPower.run(" + json.dumps(spec) + "))"))

    # Eleven near-identical teams, one sitting out each week: nobody plays more
    # than the fourteen weeks there are, and the team at index 0 is not carrying
    # everyone else's missing fixture.
    for team in result["teams"]:
        assert 0 <= team["projWins"] <= 14
    wins = [t["projWins"] for t in result["teams"]]
    assert max(wins) - min(wins) < 3, (
        f"one team is playing a different season from the rest: {wins}")


def test_a_failure_that_is_not_a_missing_draft_is_not_the_pre_draft_page(monkeypatch):
    """Any error used to publish "the draft has not happened yet" - which a
    Sleeper glitch did, three weeks into the season. Only NoRosters means that;
    anything else fails the step and the page on disk stands, charts and all."""
    from fantasy.league import power as model
    from fantasy.site import power as page

    cleared = []

    def down(*args, **kwargs):
        raise ConnectionError("Sleeper dropped the handshake")

    monkeypatch.setattr(model, "rankings", down)
    monkeypatch.setattr(page.charts, "clear", lambda *a, **k: cleared.append(1))
    with pytest.raises(ConnectionError):
        page.body()
    assert not cleared, "the last good page's charts were deleted"
