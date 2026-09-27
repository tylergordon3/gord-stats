"""
The live proxies share one upstream answer per window, and ask only sane questions.

/api/cfb-scores and /api/cfb-matchups went upstream on every hit - one call to
ESPN, or eleven to Yahoo, for every poll of every open tab, and for anyone
with a loop. They now keep a 200 in the Workers cache for 20-30 s, keyed on
the validated question (so the page's own `_=<time>` does not defeat it), and
refuse weeks and seasons no college season has.

Run in headless Chromium with caches.default and fetch stubbed
(tests/functions_harness.py).
"""
import json

import pytest

from functions_harness import CHROME, FUNCTIONS, Worker

pytestmark = pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")

SCORES = "https://www.gordstats.com/api/cfb-scores"
MATCHUPS = "https://www.gordstats.com/api/cfb-matchups"

# Two teams in one matchup, one player each: just enough of Yahoo's shape.
YAHOO = r"""
window.yahooStub = () => {
  const team = (n, pts) => ({ team: [[{ team_key: "474.l.21318.t." + n }, { name: "T" + n }],
                                     { team_points: { total: String(pts) } }] });
  T.routes = [
    ["/scoreboard;week=", () => ({ body: { fantasy_content: { league: [{ league_key: "x" },
      { scoreboard: { "0": { matchups: { count: 1, "0": { matchup: { "0": {
        teams: { count: 2, "0": team(1, 10.5), "1": team(2, 3) } } } } } } } }] } } })],
    ["/roster;week=", (url) => ({ body: { fantasy_content: { team: [{ team_key: "k" },
      { roster: { "0": { players: { count: 1, "0": { player: [
        [{ player_id: url.includes(".t.1/") ? "11" : "22" }, { display_position: "QB" }],
        { player_points: { total: "12" } },
        { player_stats: { stats: [{ stat: { stat_id: "4", value: "250" } }] } }] } } } } }] } } })],
  ];
};
"""


@pytest.fixture
def worker():
    with Worker() as w:
        w.load(FUNCTIONS / "api" / "cfb-scores.js", "scores")
        w.load(FUNCTIONS / "api" / "cfb-matchups.js", "matchups")
        w.js(YAHOO + """
          window.edge = T.cache();
          Object.defineProperty(window, "caches",
            { value: { default: edge }, configurable: true });
          window.espnCalls = 0;
          window.espn = (status = 200) => {
            T.routes = [["site\\\\.api\\\\.espn\\\\.com", () =>
              ({ status, body: { events: [], call: ++espnCalls } })]];
          };
        """)
        yield w


def get(w, fn, url):
    got = w.call(fn, url)
    w.js("await T.settle();")                       # let waitUntil's cache.put land
    return got


def test_scores_are_shared_across_polls_and_spellings(worker):
    worker.js("espn();")
    first = get(worker, "scores.onRequestGet", f"{SCORES}?week=5&dates=2026")
    assert first["status"] == 200 and first["json"]["call"] == 1
    assert first["headers"]["cache-control"] == "no-store"
    assert first["headers"]["access-control-allow-origin"] == "*"
    for url in (f"{SCORES}?week=05&dates=2026", f"{SCORES}?dates=2026&week=5&_=123"):
        again = get(worker, "scores.onRequestGet", url)
        assert again["json"]["call"] == 1 and again["headers"]["cache-control"] == "no-store"
    assert worker.js("return espnCalls;") == 1
    # What sits in the cache says how long it may.
    stored = worker.js("""
      return [...edge.store].map(([k, r]) => [k, r.headers.get("cache-control")]);""")
    assert stored == [["https://www.gordstats.com/api/cfb-scores?week=5&dates=2026",
                       "public, max-age=20"]]

    # Once the entry is gone, the next poll asks ESPN again.
    worker.js("edge.store.clear();")
    assert get(worker, "scores.onRequestGet", f"{SCORES}?week=5&dates=2026")["json"]["call"] == 2


@pytest.mark.parametrize("query", [
    "week=21&dates=2026", "week=-1&dates=2026", "week=abc&dates=2026", "week=5",
    "week=5&dates=1999", "week=5&dates=20266", "week=5&dates=2090", "week=100&dates=2026",
])
def test_scores_refuse_what_no_season_asks(worker, query):
    worker.js("espn();")
    got = worker.call("scores.onRequestGet", f"{SCORES}?{query}")
    assert got["status"] == 400 and worker.js("return espnCalls;") == 0


def test_scores_failures_pass_through_and_are_not_kept(worker):
    worker.js("espn(503);")
    for call in (1, 2):
        got = get(worker, "scores.onRequestGet", f"{SCORES}?week=0&dates=2026")
        assert got["status"] == 503 and got["json"]["call"] == call
    worker.js("T.routes = [['espn', () => new TypeError('network down')]];")
    down = get(worker, "scores.onRequestGet", f"{SCORES}?week=1&dates=2027")
    assert down["status"] == 502 and down["json"]["ok"] is False
    assert worker.js("return edge.store.size;") == 0


def test_matchups_ask_yahoo_once_per_window_whatever_the_page_appends(worker):
    worker.js("yahooStub();")
    one = get(worker, "matchups.onRequestGet", f"{MATCHUPS}?week=3&_=1")
    assert one["status"] == 200, one["text"]
    body = one["json"]
    assert body["ok"] and body["week"] == 3
    assert body["teams"]["474.l.21318.t.1"]["points"] == 10.5
    assert body["teams"]["474.l.21318.t.1"]["players"]["11"] == {
        "points": 12, "line": "250 pass yds"}
    assert len(worker.js("return T.fetches;")) == 3               # scoreboard + 2 rosters

    two = get(worker, "matchups.onRequestGet", f"{MATCHUPS}?week=03&_=2")
    assert two["json"] == body and len(worker.js("return T.fetches;")) == 3
    assert worker.js("return [...edge.store.keys()];") == [
        "https://www.gordstats.com/api/cfb-matchups?week=3"]

    for bad in ("0", "21", "x", ""):
        assert worker.call("matchups.onRequestGet", f"{MATCHUPS}?week={bad}")["status"] == 400
    assert len(worker.js("return T.fetches;")) == 3


def test_matchups_do_not_keep_a_failed_scoreboard(worker):
    worker.js("T.routes = [['yahoo', () => ({ status: 500, body: {} })]];")
    for n in (1, 2):
        got = get(worker, "matchups.onRequestGet", f"{MATCHUPS}?week=4")
        assert got["status"] == 502
        assert len(worker.js("return T.fetches;")) == n
    assert worker.js("return edge.store.size;") == 0


def test_without_a_workers_cache_they_still_answer(worker):
    """caches.default is a no-op on *.pages.dev and absent outside Workers."""
    worker.js("""Object.defineProperty(window, "caches", { value: undefined, configurable: true });
                 espn();""")
    for call in (1, 2):
        got = worker.call("scores.onRequestGet", f"{SCORES}?week=2&dates=2026")
        assert got["status"] == 200 and got["json"]["call"] == call
    assert json.loads(got["text"])["events"] == []
