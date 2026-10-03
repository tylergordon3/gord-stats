"""
Where the "How this works" chips sit (gordstats.how): beside the rankings,
predictions and fantasy numbers they explain, in place of the paragraphs and
folds that used to explain them on the page (the owner's ask, 2026-10-02:
"a small 'How this works' next to different things that opens a window with
the explanation, so the explanation is not in the page too").

What has to hold: every explainer is reachable from a page; each generator
that puts a chip down also loads gs-how.js (itself, or through the shared
module that draws the page); the hand-written pages carry how.button()
exactly as it renders, with the script; the old inline methodology is gone
while the legends a reader needs to read a table stay; and the footer links
/how/. Most pages need the season's data to build, so this reads their
source; the shared renderers are checked built in their own tests
(test_preview_page, test_watch, test_stakes, test_nfl_stats, ...).
"""
import re

import pytest

from conftest import CSS, DOCS, ROOT
from gordstats import how

SRC = ROOT / "src"

# Generator -> the explainers it puts a chip down for.
PLACED = {
    "cfb/site/power.py": {"cfb-rankings"},
    "cfb/site/home.py": {"cfb-rankings", "bets-record"},
    "cbb/render/render_home.py": {"cfb-rankings", "bets-record", "cbb-rankings"},
    "cfb/site/predictions.py": {"cfb-predictions"},
    "cfb/site/schedule.py": {"cfb-predictions"},
    "nfl/site/power.py": {"nfl-rankings"},
    "nfl/site/predictions.py": {"nfl-predictions", "nfl-rankings", "bets-record"},
    "gordstats/playoff_page.py": {"playoff-odds"},
    "cfb/site/previews.py": {"cfb-predictions", "game-previews"},
    "nfl/site/previews.py": {"nfl-predictions", "game-previews"},
    "cbb/render/render_previews.py": {"cbb-predictions"},
    "cfb/site/watch.py": {"watch-guide"},
    "nfl/site/watch.py": {"watch-guide"},
    "gordstats/watch_all.py": {"watch-guide"},
    "cbb/render/render_watch.py": {"cbb-watch"},
    "cfb/site/stats.py": {"team-stats"},
    "nfl/site/stats.py": {"team-stats"},
    "fantasy/site/power.py": {"fantasy-power", "fantasy-stakes"},
    "cfb/site/league_power.py": {"cfb-league", "fantasy-stakes"},
    "fantasy/site/matchups.py": {"fantasy-projections"},
    "cfb/site/matchups.py": {"fantasy-projections"},
    "fantasy/site/roster.py": {"injuries"},
    "fantasy/site/trade.py": {"trade-analyzer"},
    "cfb/site/trade.py": {"trade-analyzer"},
    "fantasy/site/usage.py": {"usage"},
    "cfb/site/usage.py": {"usage"},
    "fantasy/site/strength.py": {"schedule-strength"},
    "cfb/site/strength.py": {"schedule-strength"},
    "fantasy/site/schedule.py": {"schedule-strength"},
    "cfb/site/league.py": {"schedule-strength"},
    "gordstats/recap.py": {"recaps"},
    "gordstats/my_recap.py": {"recaps"},
    "cbb/predictions.py": {"cbb-rankings"},
    "cbb/render/render_conferences.py": {"cbb-rankings"},
}
# A generator whose chips the shared module drawing its page loads the script for.
SCRIPT_FROM = {
    "cfb/site/previews.py": "gordstats/preview_page.py",
    "nfl/site/previews.py": "gordstats/preview_page.py",
    "cbb/render/render_previews.py": "gordstats/preview_page.py",
    "cfb/site/watch.py": "gordstats/watch_page.py",
    "nfl/site/watch.py": "gordstats/watch_page.py",
    "gordstats/watch_all.py": "gordstats/watch_page.py",
    "cbb/render/render_watch.py": "gordstats/watch_page.py",
    "gordstats/my_recap.py": "fantasy/site/recap.py",
}
# The hand-written pages Jekyll runs as they are: the chip as how.button()
# renders it, and the script by LIQUID_TAG.
STATIC = {
    "men/index.html": "cbb-rankings",
    "women/index.html": "cbb-rankings",
    "men/predict_2026-03-15.html": "cbb-rankings",
    "women/predict_2026-03-15.html": "cbb-rankings",
    "_includes/prediction_archive.html": "cbb-rankings",
}


def _src(rel: str) -> str:
    return (SRC / rel).read_text(encoding="utf-8")


def test_every_explainer_has_a_chip_somewhere():
    placed = set().union(*PLACED.values()) | set(STATIC.values())
    assert placed == set(how.BY_ID), f"no chip for {set(how.BY_ID) - placed}"


@pytest.mark.parametrize("rel", sorted(PLACED))
def test_each_generator_names_its_explainers_and_loads_the_script(rel):
    src = _src(rel)
    for topic in PLACED[rel]:
        assert re.search(rf"[\"']{re.escape(topic)}[\"']", src), f"{rel}: no chip for {topic}"
    loader = _src(SCRIPT_FROM.get(rel, rel))
    assert "how.JS_TAG" in loader or "how.LIQUID_TAG" in loader, f"{rel}: gs-how.js not loaded"


@pytest.mark.parametrize("rel", sorted(STATIC))
def test_the_hand_written_pages_carry_the_chip_as_it_renders(rel):
    page = (DOCS / rel).read_text(encoding="utf-8")
    assert page.count(how.button(STATIC[rel])) == 1, f"{rel}: the chip has drifted from how.button()"
    assert page.count(how.LIQUID_TAG) == 1


def test_the_scoreboards_chip_sits_in_the_heading_and_the_legend_is_gone():
    """The Legend button and its modal are the cbb-rankings explainer now
    (its "Seed" line was wrong anyway: the column is the AP rank)."""
    for league, head in (("men", "NCAAM"), ("women", "NCAAW")):
        page = (DOCS / league / "index.html").read_text(encoding="utf-8")
        assert f"<h1>{head} Live Scoreboard {how.button('cbb-rankings')}</h1>" in page
        assert "legend" not in page.lower() and "modal.html" not in page
    assert not (DOCS / "_includes" / "modal.html").exists()
    assert not re.search(r"\.legend-(btn|overlay|modal|close|list|icon|pill)\b",
                         CSS.read_text(encoding="utf-8"))
    live = (DOCS / "assets" / "js" / "live.js").read_text(encoding="utf-8")
    assert "legend" not in live.lower()


# Explanations that were inline and are an explainer now: (file, words).
GONE = [
    ("cfb/site/power.py", "About these rankings"),
    ("nfl/site/power.py", "About these rankings"),
    ("cfb/site/predictions.py", "def _method"),
    ("cfb/site/predictions.py", "How it Works"),
    ("nfl/site/predictions.py", "def _method"),
    ("nfl/site/predictions.py", "How it Works"),
    ("cfb/site/playoff.py", "def _method"),
    ("nfl/site/playoff.py", "def _method"),
    ("gordstats/playoff_page.py", "po-method"),
    ("gordstats/watch_page.py", "How games are ranked"),
    ("cfb/site/watch.py", "\nHOW = ("),
    ("nfl/site/watch.py", "\nHOW = ("),
    ("gordstats/watch_all.py", "\nHOW = ("),
    ("cbb/render/render_watch.py", "\nHOW = ("),
    ("nfl/site/stats.py", "def _explainer"),
    ("cfb/site/stats.py", "Source: CollegeFootballData.com"),
    ("fantasy/site/power.py", "usage ridge regression"),
    ("fantasy/site/power.py", "Out/IR/PUP"),
    ("cfb/site/league_power.py", "<summary>How it works</summary>"),
    ("fantasy/site/matchups.py", "the power model's points per game"),
    ("fantasy/site/matchups.py", "ten seasons of"),
    ("cfb/site/matchups.py", "season projection spread over"),
    ("fantasy/site/roster.py", "ten seasons of"),
    ("fantasy/site/trade.py", "METHOD = "),
    ("cfb/site/trade.py", "METHOD = "),
    ("fantasy/site/usage.py", "How to read it"),
    ("cfb/site/usage.py", "How to read it"),
    ("fantasy/site/strength.py", "How this is worked out"),
    ("cfb/site/strength.py", "How this is worked out"),
    ("gordstats/schedule_luck.py", "The median game is left out"),
    ("gordstats/stakes.py", "split on that game"),
    ("gordstats/recap.py", "'difference - points left on the bench"),
    ("cbb/predictions.py", "<summary>How the field is built"),
    ("cbb/render/render_previews.py", '("The call",'),
]


@pytest.mark.parametrize("rel, words", GONE)
def test_the_inline_explanation_is_gone(rel, words):
    assert words not in _src(rel)


def test_the_reader_recap_and_the_tracked_bracket_match():
    js = (DOCS / "assets" / "js" / "gs-recap.js").read_text(encoding="utf-8")
    assert "total maximum" not in js and "'<h2>Awards'+how+'</h2>'" in js
    final = (DOCS / "men" / "predict_2026-03-15.html").read_text(encoding="utf-8")
    assert "How the field is built" not in final


# What a reader needs to read the table stays on the page (or in a header's
# tooltip): (file, words).
KEPT = [
    ("cfb/site/power.py", "Shaded rows are FPI's top 25"),
    ("cfb/site/power.py", "Strength-of-record rank"),
    ("cfb/site/schedule.py", "Picks of the day"),
    ("nfl/site/stats.py", "lower is better there"),
    ("cfb/site/league_power.py", "title='Value over a replacement-level player"),
    ("cfb/site/usage.py", "Predicted points added per play"),
    ("cfb/site/usage.py", "without interceptions and fumbles"),
    ("fantasy/site/matchups.py", "Median Tracker"),
    ("fantasy/site/matchups.py", "<b>locked</b>"),
    ("fantasy/site/matchups.py", "<b>Med</b> is each team's margin"),
    ("fantasy/site/strength.py", "usual starters are"),
    ("gordstats/stakes.py", "Playoff odds with a win minus with a loss"),
]


@pytest.mark.parametrize("rel, words", KEPT)
def test_what_reads_the_table_stays(rel, words):
    assert words in _src(rel)


def test_strength_says_the_bench_counts_too():
    """strength_page.price() weighs every player it is handed by projection;
    the NFL page hands it the whole roster but injured reserve, bench too
    (roster_players), and marks starters only to count the byes."""
    from fantasy.site import strength
    import inspect
    assert "less the reserve list" in inspect.getsource(strength.roster_players)
    for rel in ("fantasy/site/strength.py", "cfb/site/strength.py"):
        assert "bench included" in _src(rel)
        assert "only easy where a roster starts" not in _src(rel)


def test_the_cfb_previews_say_which_figures_are_adjusted():
    from cfb.site import previews
    assert "havoc and points per trip as played" in previews.SOURCE
    assert previews.HOW == {"call": "cfb-predictions", "units": "game-previews"}


def test_the_footer_links_every_explainer():
    layout = (DOCS / "_layouts" / "default.html").read_text(encoding="utf-8")
    footer = layout[layout.index("<footer"):layout.index("</footer>")]
    assert "<a href=\"{{ '/how/' | relative_url }}\">How it works</a>" in footer


def test_the_changelog_says_so():
    from gordstats import changelog
    assert any(link == "/how/" for *_, link in changelog.ENTRIES[:3])


def test_the_playoff_heading_carries_the_chip_and_the_page_its_script():
    from gordstats import playoff_page
    head = playoff_page.heading("Projected bracket")
    assert head == f"<h2>Projected bracket {how.button('playoff-odds')}</h2>"
    assert playoff_page.page(head).count(how.JS_TAG) == 1
    assert how.JS_TAG not in playoff_page.page(playoff_page.empty("Nothing yet."))
