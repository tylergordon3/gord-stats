"""
The projected-playoff pages: the shared renderer (gordstats.playoff_page) and
the two adapters (cfb.site.playoff, nfl.site.playoff) on tiny hand-built
leagues - names from the feeds escaped and Liquid-safe, starred teams marked
in the table and the bracket, ESPN FPI's column beside ours (blank where it
has nothing), and the before-a-game, field-set and final states. No network:
the projections are stubbed with small simulations.
"""
from html import escape

import pytest

import test_playoff_cfb as cfb_fixture
import test_playoff_nfl as nfl_fixture
from cfb import playoff as cfb_playoff
from cfb.site import playoff as cfb_page
from gordstats import playoff_page
from gordstats.frontmatter import add_front_matter
from nfl import playoff as nfl_playoff
from nfl.site import playoff as nfl_page


def test_chances_print_as_whole_percents_with_honest_ends():
    assert playoff_page.pct_text(None) == ""
    assert "&middot;" in playoff_page.pct_text(0.0)
    assert playoff_page.pct_text(0.004) == "&lt;1"
    assert playoff_page.pct_text(0.006) == "1"
    assert playoff_page.pct_text(0.874) == "87"
    assert playoff_page.pct_text(0.996) == "&gt;99"
    assert playoff_page.pct_text(1.0) == "100"


EVIL = "<script>x</script>{% endraw %}{{ site.x }}"


def test_the_table_escapes_names_and_marks_favourites():
    rows = [{"id": "333", "name": EVIL, "full": EVIL, "link": "/cfb/teams/x/", "logo": "",
             "record": "4-0", "values": {"playoff": 0.5, "fpi": None, "seed": 4.25}}]
    cols = [{"key": "playoff", "label": "Playoff", "kind": "pct", "tip": "ours"},
            {"key": "fpi", "label": "FPI", "kind": "pct", "tip": "ESPN's"},
            {"key": "seed", "label": "Seed", "kind": "seed", "tip": "avg"}]
    html = playoff_page.odds_table(rows, cols, "cfb", sort_key="playoff")
    assert "<script>x" not in html and "&lt;script&gt;" in html
    assert 'data-fav="cfb:333"' in html and "data-fav-for='cfb:333'" in html
    assert "<td></td>" in html                       # ESPN has nothing: blank, not 0
    assert "data-v='4.250'>4.2<" in html or "data-v='4.250'>4.3<" in html
    page = add_front_matter(playoff_page.page(html), "T", updated=False)
    # Liquid sees nothing but the raw wrapping: the name's endraw is gone.
    assert page.count("{% raw %}") == page.count("{% endraw %}") == 1


def test_the_bracket_greys_a_team_that_lost():
    groups = [{"title": "AFC", "cards": [[{"label": "Bye", "lines": [
        {"seed": 1, "id": "12", "name": "Chiefs", "fig": "40%"}]},
        {"label": None, "lines": [{"seed": 2, "id": "2", "name": EVIL, "fig": "", "state": "lost"},
                                  {"seed": 7, "id": "3", "name": "Bears", "fig": ""}]}]]}]
    html = playoff_page.bracket(groups, "nfl")
    assert "po-line lost" in html and "&lt;script&gt;" in html and "<script>x" not in html
    assert 'data-fav="nfl:12"' in html
    assert html.count("class='po-line") == 3


# --------------------------------------------------------------------------- #
# The college page
# --------------------------------------------------------------------------- #

def _fpi_payload(teams: dict) -> dict:
    """An FPI pull in ESPN's shape: {id: playoff percent}."""
    names = ["fpi", "probmakeplayoffs", "probwinconf", "probwintitle"]
    return {"categories": [{"name": "fpi", "names": names}, {"name": "resume", "names": []}],
            "teams": [{"team": {"id": tid, "displayName": f"{tid.upper()} Full", "name": "Full",
                                "logos": [{"href": "x"}], "group": {"shortName": "SEC"}},
                       "categories": [{"name": "fpi", "values": [10.0, pct, 5.0, 1.0],
                                       "totals": ["10.0", str(pct), "5.0", "1.0"]}]}
                      for tid, pct in teams.items()]}


@pytest.fixture
def cfb_stub(monkeypatch):
    lg = cfb_fixture.league(cfb_fixture.RATINGS, cfb_fixture._season(False))
    lg.names = {**lg.names, "s1": EVIL}
    res = cfb_playoff.simulate(lg, n=300, seed=1)
    payload = _fpi_payload({"s1": 91.0, "t1": 80.0, "w2": 12.0})
    state = {"value": (res, lg, payload)}
    monkeypatch.setattr(cfb_page.playoff, "project", lambda *a, **k: state["value"])
    return state


def test_the_college_page_projects_a_twelve_team_bracket_beside_fpi(cfb_stub):
    html = cfb_page.body()
    assert "Projected bracket" in html and "Semifinal 1" in html and "Semifinal 2" in html
    assert html.count("class='po-line") == 12
    assert html.count("First round") == 4
    # ESPN's chance beside ours: 91% for s1, and w2 listed on FPI's say-so.
    assert "data-v='0.91000'" in html
    assert "W2" in html
    # The feed's name is escaped wherever it is drawn.
    assert "<script>x" not in html and "&lt;script&gt;" in html
    assert 'data-fav="cfb:s1"' in html
    assert "collegefootballplayoff.com" in html          # the format's source, in the note


def test_the_college_page_before_a_game_says_so(cfb_stub):
    res, lg, payload = cfb_stub["value"]
    cfb_stub["value"] = (None, lg, payload)
    html = cfb_page.body()
    assert "starts once the first week" in html and "<table" not in html
    cfb_stub["value"] = (None, None, {})
    assert "No conference list" in cfb_page.body()


def test_the_college_page_once_the_field_is_real_and_once_it_is_over(cfb_stub):
    res, lg, payload = cfb_stub["value"]
    seeds = cfb_playoff.projected_field(res)
    lg.cfp_seeds = seeds
    res2 = cfb_playoff.simulate(lg, n=200, seed=1)
    cfb_stub["value"] = (res2, lg, payload)
    html = cfb_page.body()
    assert "The real field" in html and "chance to win the title" in html
    # Every game played, the top seed through each one: final.
    order = cfb_playoff.bracket_order(8)
    results = {}
    for hi, lo in cfb_playoff.first_round(12, 4):
        results[(seeds[hi - 1], seeds[lo - 1])] = seeds[hi - 1]
    alive = [seeds[s - 1] for s in order]
    while len(alive) > 1:
        nxt = []
        for i in range(0, len(alive), 2):
            a, b = alive[i], alive[i + 1]
            win = a if seeds.index(a) < seeds.index(b) else b
            results[(a, b)] = win
            nxt.append(win)
        alive = nxt
    lg.cfp_results, lg.final = results, True
    res3 = cfb_playoff.simulate(lg, n=200, seed=1)
    cfb_stub["value"] = (res3, lg, payload)
    html = cfb_page.body()
    champ = escape(lg.names[lg.teams[seeds[0]]])
    assert f"{champ} won the national title" in html
    assert html.count("po-line lost") == 11


def test_the_college_page_writes_its_front_matter(cfb_stub, tmp_path, monkeypatch):
    monkeypatch.setattr(cfb_page, "OUT", tmp_path / "playoff" / "index.html")
    cfb_page.generate()
    text = (tmp_path / "playoff" / "index.html").read_text()
    assert text.startswith("---\nlayout: default\ntitle: CFB Playoff Odds\ndescription: ")
    assert "page-updated" in text


# --------------------------------------------------------------------------- #
# The NFL page
# --------------------------------------------------------------------------- #

@pytest.fixture
def nfl_stub(monkeypatch):
    lg = nfl_fixture._league(False)
    first = lg.teams[0]
    lg.names = {**lg.names, first: (EVIL, "KC")}
    res = nfl_playoff.simulate(lg, n=300, seed=1)
    state = {"value": (res, lg)}
    monkeypatch.setattr(nfl_page.playoff, "project", lambda *a, **k: state["value"])
    monkeypatch.setattr(nfl_page.fpi, "by_id",
                        lambda *a, **k: {first: {"probmakeplayoffs": 64.0, "full": "Full Name"}})
    return state


def test_the_nfl_page_draws_both_conferences_beside_fpi(nfl_stub):
    html = nfl_page.body()
    assert "Projected bracket" in html
    assert "<h3 class='po-gh'>AFC</h3>" in html and "<h3 class='po-gh'>NFC</h3>" in html
    assert html.count("class='po-line") == 14
    assert html.count("<tr data-fav=") == 32
    assert "data-v='0.64000'" in html
    assert "<script>x" not in html and "&lt;script&gt;" in html


def test_the_nfl_page_before_a_game_and_after_the_season(nfl_stub):
    res, lg = nfl_stub["value"]
    nfl_stub["value"] = (None, lg)
    assert "starts once the first week" in nfl_page.body()
    done = nfl_fixture._league(True, round_robin=True)
    res = nfl_playoff.simulate(done, n=100, seed=1)
    nfl_stub["value"] = (res, done)
    html = nfl_page.body()
    assert "The regular season is over" in html and "win the Super Bowl" in html


# --------------------------------------------------------------------------- #
# The week's change, from the season's history (gordstats.playoff_history)
# --------------------------------------------------------------------------- #

def test_the_week_column_appears_once_there_is_a_week_old_snapshot(cfb_stub, monkeypatch):
    from datetime import datetime
    from gordstats import playoff_history
    res, lg, _payload = cfb_stub["value"]
    html = cfb_page.body()
    assert "data-k='wk'" not in html                     # no history yet: no column
    i = lg.teams.index("s1")
    then = float(res.playoff[i]) - 0.07
    monkeypatch.setattr(cfb_page, "_BASE", {"when": datetime(2026, 9, 27),
                                            "odds": {"s1": [then, 0.0]}})
    html = cfb_page.body()
    assert "data-k='wk'" in html and "since Sep 27" in html
    assert "class='po-chg up' data-v='0.0700'>+7<" in html
    # A team the old snapshot left out counted from zero, not left blank.
    other = next(t for t in lg.teams if t != "s1")
    j = lg.teams.index(other)
    want = playoff_history.change(res.playoff[j], {"s1": [then, 0.0]}, other)
    assert f"data-v='{want:.4f}'" in html


def test_a_test_build_neither_reads_nor_writes_the_seasons_history(cfb_stub, monkeypatch,
                                                                   tmp_path):
    hist = tmp_path / "hist.json"
    monkeypatch.setattr(cfb_page, "HISTORY", hist)
    monkeypatch.setattr(cfb_page, "OUT", tmp_path / "playoff" / "index.html")
    cfb_page.generate()
    assert not hist.exists()
