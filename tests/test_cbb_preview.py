"""
The CBB game previews (cbb.render.render_previews): which games get a page,
the call from the scoreboard's model and theScore's line, the guide's watch
score, records and form from the season's results, the pages written and
pruned - and the watch guide's cards opening them. No network: the feed,
the tables and the results are built here.
"""
import json
import re
from html import unescape

import pandas as pd
import pytest
import requests

from cbb import game_model
from cbb.render import render_previews as rp
from cbb.render import render_watch as watch
from gordstats import paths as gs_paths
from gordstats import preview_page
from gordstats.js_assets import expand

ET = preview_page.ET
NOW = pd.Timestamp("2027-01-15 12:00", tz=ET)

# Torvik as game_model.ratings() leaves it: {name: (adj O, adj D, tempo)}.
TABLE = {"Alpha": (118.0, 94.0, 70.0), "Bravo": (110.0, 99.0, 66.0),
         "Charlie": (101.0, 104.0, 68.0), "Delta": (99.0, 107.0, 64.0)}
TRANK = {"Alpha": 5, "Bravo": 40, "Charlie": 200, "Delta": 300}
MASTER = {"team": {"0": "Alpha", "1": "Bravo", "2": "Charlie", "3": "Delta"},
          "names": {"0": ["ALP", "Alpha"], "1": ["BRV", "Bravo"], "2": ["CHA"], "3": ["DEL"]},
          "path": {"0": "alpha u.png", "1": "bravo.png", "2": "charlie.png", "3": "delta.png"}}


def _g(home, away, day, hour, status="pre_game", **kw):
    kick = pd.Timestamp(f"{day} {hour}", tz=ET)
    g = {"date": day, "start_time_utc": kick.tz_convert("UTC").isoformat(), "status": status,
         "home_team": home, "away_team": away, "home_abb": home[:3].upper(),
         "away_abb": away[:3].upper(), "home_score": None, "away_score": None,
         "home_rank": None, "away_rank": None, "home_model": 10, "away_model": 60,
         "conference_home": "Big East", "conference_away": "Big East",
         "venue": "Home Arena", "location": "Town, ST", "spread_close": None,
         "total_close": None, "game_type": "Regular Season", "game_description": "",
         "is_mm": False, "is_nit": False, "neutral": False, "period": None, "clock": None,
         "overtime": False}
    g.update(kw)
    return g


def _feed():
    return {"men": {
        # Today, both AP-ranked: our call against ALP -6.5.
        "101": _g("Alpha", "Bravo", "2027-01-15", "19:00", spread_close="ALP -6.5",
                  total_close=140.5, home_rank=5, away_rank=20, home_model=4, away_model=35),
        # Both outside T-Rank's top 150, in the regular season: no page...
        "102": _g("Charlie", "Delta", "2027-01-15", "20:00"),
        # ... but the same two in a tournament get one.
        "103": _g("Charlie", "Delta", "2027-01-16", "12:00",
                  game_description="Big East Tournament | Quarterfinal",
                  game_type="Postseason Tournament", neutral=True),
        # Yesterday's final; the feed lost its line, the archive kept it.
        "104": _g("Bravo", "Alpha", "2027-01-14", "21:00", status="final",
                  home_score=70, away_score=75, spread_close=" "),
        # A non-D1 opponent, a game too far ahead, one called off: none.
        "105": _g("Alpha", "Lynchburg", "2027-01-15", "18:00"),
        "106": _g("Alpha", "Bravo", "2027-01-18", "19:00"),
        "107": _g("Bravo", "Alpha", "2027-01-15", "17:00", status="postponed"),
        # The NCAA tournament: theScore's ranking is the seed.
        "108": _g("Alpha", "Delta", "2027-01-15", "14:00", is_mm=True, neutral=True,
                  home_rank=1, away_rank=16, game_type="Postseason Tournament",
                  game_description="NCAA Tournament | 1st Round")},
        "women": {"201": _g("Alpha", "Bravo", "2027-01-15", "19:00")}}


LOGS = {
    "Alpha": {"2026-03-01": {"win": True, "location": "home", "score": 90, "opponent": "Delta",
                             "opponent_score": 50},             # last season: not counted
              "2027-01-10": {"win": True, "location": "home", "score": 80, "opponent": "Bravo",
                             "opponent_score": 70},
              "2027-01-12": {"win": False, "location": "away", "score": 60,
                             "opponent": "Charlie", "opponent_score": 65}},
    "Bravo": {"2027-01-10": {"win": False, "location": "away", "score": 70, "opponent": "Alpha",
                             "opponent_score": 80}},
}

ARCHIVE = {"men:104": {"league": "men", "spread": "ALP -2.5", "total": 150.0},
           "men:9": {"league": "men", "date": "2027-01-12", "home_team": "Charlie",
                     "away_team": "Alpha", "game_description": "Big East Tournament | Final"}}


def _data(**kw):
    lk = rp.master_lookup(MASTER)
    rows = [{"id": "Alpha", "adjoe": 118.0, "adjde": 94.0, "tempo": 70.0, "efg": 0.56,
             "efg_d": 0.46, "r3": 0.41},
            {"id": "Bravo", "adjoe": 110.0, "adjde": 99.0, "tempo": 66.0, "efg": 0.50,
             "efg_d": 0.49},
            {"id": "Charlie", "adjoe": 101.0, "adjde": 104.0, "tempo": 68.0},
            {"id": "Delta", "adjoe": 99.0, "adjde": 107.0, "tempo": 64.0}]
    data = {"feed": _feed(), "lookup": lk, "trank": TRANK,
            "ranks": preview_page.rank_table(rows, rp.BETTER), "rows": {r["id"]: r for r in rows},
            "played": True, "logs": LOGS, "table_on": lambda day: TABLE, "lines": ARCHIVE,
            "neutral_on": rp.neutral_sites(ARCHIVE), "tv": {"101": "ESPN2, ESPN+"},
            "generated": "2027-01-15T16:00:00+00:00"}
    data.update(kw)
    return data


def _text(html):
    return unescape(re.sub(r"<[^>]+>", "", html)).replace("—", "-")


# --------------------------------------------------------------------------- #
# Names and lines
# --------------------------------------------------------------------------- #

def test_the_line_is_the_home_sides_whoever_theScore_names():
    alias = rp.master_lookup(MASTER)["alias"]
    assert rp.home_line("ALP -6.5", "Alpha", "Bravo", alias) == -6.5
    assert rp.home_line("ALP -6.5", "Bravo", "Alpha", alias) == 6.5
    assert rp.home_line("BRV PK", "Alpha", "Bravo", alias) == 0.0
    # A code that is neither team's, a blank, nothing: no line, not a guess.
    for text in ("CHA -3", " ", "", None, "ALP"):
        assert rp.home_line(text, "Alpha", "Bravo", alias) is None


def test_master_names_and_logos():
    lk = rp.master_lookup(MASTER)
    assert lk["alias"]["ALP"] == "Alpha" and lk["alias"]["Delta"] == "Delta"
    assert lk["logo"]["Alpha"] == "/assets/images/alpha%20u.png"      # a space, quoted
    # T-Rank's own spelling becomes the scoreboard's.
    assert rp.site_name("McNeese St.", {}) == "McNeese"


# --------------------------------------------------------------------------- #
# Which games
# --------------------------------------------------------------------------- #

def test_the_window_is_yesterday_to_tomorrow_rated_and_worth_a_page():
    # By tip-off: last night's final, today's two, tomorrow's tournament game.
    got = [gid for gid, _g in rp.window(_feed(), NOW, TRANK)]
    assert got == ["104", "108", "101", "103"]


def test_states_and_tournaments():
    assert [rp.state(s) for s in ("pre_game", "", "in_progress", "half_over", "final")] == \
        ["pre", "pre", "in", "in", "post"]
    assert rp.state("Postponed") is None and rp.state("cancelled") is None
    assert rp.tournament({"is_mm": True}) == 2
    assert rp.tournament({"is_nit": True}) == 1
    assert rp.tournament({"game_description": "ACC Tournament | Final"}) == 1
    assert rp.tournament({"game_description": "", "game_type": "Regular Season"}) == 0


# --------------------------------------------------------------------------- #
# The watch score: the guide's formula
# --------------------------------------------------------------------------- #

def test_the_watch_score_is_the_guides():
    from test_cbb_watch import _score
    for hm, am, p, top25, tour in ((3, 12, 0.6, True, 0), (100, 110, 0.5, False, 1),
                                   (300, 320, 0.5, False, 0), (1, 300, 0.97, False, 2)):
        got, _tags = rp.watch_score(hm, am, p, top25, tour)
        assert round(got) == _score(hm, am, p, lifts=int(top25) + tour), (hm, am, p)
    # The docstring's: #1 v #5 at 55-45 about 94, #1 v #300 about 11.
    assert round(rp.watch_score(1, 5, 0.55)[0]) == 94
    assert round(rp.watch_score(1, 300, 0.99)[0]) in (10, 11)
    assert rp.watch_score(3, 12, 0.6, True)[1] == ["Top 25 matchup", "Upset watch"]
    assert rp.watch_score(100, 110, 0.5, False, 1)[1] == ["Toss-up", "Tournament"]
    # Unranked and no call: the guide's stand-ins, not an error.
    score, tags = rp.watch_score("", None, None)
    assert 0 < score < 10 and tags == []


# --------------------------------------------------------------------------- #
# Records and form
# --------------------------------------------------------------------------- #

def test_the_record_is_this_seasons_going_in():
    assert rp.record_before(LOGS["Alpha"], "2027-01-15") == "1-1"
    assert rp.record_before(LOGS["Alpha"], "2027-01-12") == "1-0"
    assert rp.record_before(LOGS["Alpha"], "2026-11-03") == ""        # no game yet
    assert rp.record_before(None, "2027-01-15") == ""


def test_form_is_newest_first_against_our_line_neutral_where_it_was():
    neutral = rp.neutral_sites(ARCHIVE)
    got = rp.form(LOGS, "Alpha", "2027-01-15", lambda d: TABLE, neutral)
    assert [(f["r"], f["score"], f["at"], f["opp"]) for f in got] == \
        [("L", "60-65", "vs", "Charlie"), ("W", "80-70", "vs", "Bravo")]
    # At Charlie in the conference tournament: no home court in our line.
    at_charlie = game_model.predict("Charlie", "Alpha", TABLE, neutral=True)
    line = at_charlie["pred_away"] - at_charlie["pred_home"]          # Alpha's margin
    assert got[0]["vs_line"] == pytest.approx(-5 - line)
    home = game_model.predict("Alpha", "Bravo", TABLE)
    assert got[1]["vs_line"] == pytest.approx(10 - (home["pred_home"] - home["pred_away"]))
    # Against a team no table rates there is no line to beat.
    logs = {"Alpha": {"2027-01-11": {"win": True, "location": "home", "score": 90,
                                     "opponent": "Lynchburg", "opponent_score": 40}}}
    assert rp.form(logs, "Alpha", "2027-01-15", lambda d: TABLE)[0]["vs_line"] is None


def test_the_table_is_the_newest_on_or_before_the_day(tmp_path, monkeypatch):
    def snap(adj_o):
        return json.dumps({"headers": ["Rk", "Team", "AdjOE", "AdjDE", "Adj T."],
                           "rows": [["1", "Alpha", str(adj_o), "95", "70"]]})
    for stem, o in (("2026-03-15", 101), ("2026-11-20", 102), ("2026-12-01", 103),
                    ("2027-01-14", 104)):
        (tmp_path / f"{stem}.json").write_text(snap(o))
    (tmp_path / "notes.json").write_text("{}")                     # not a dated table
    monkeypatch.setattr(game_model, "trank_table", lambda day: {"T-Rank": (1, 1, 1)})
    on = rp.tables(tmp_path)
    assert on("2027-01-13")["Alpha"][0] == 103
    assert on("2027-01-14")["Alpha"][0] == 104                     # the day's own, pre-game
    assert on("2027-01-16")["Alpha"][0] == 104
    # Before this season's first: T-Rank's preseason table, never last March's.
    assert on("2026-11-10") == {"T-Rank": (1, 1, 1)}


# --------------------------------------------------------------------------- #
# One game, built
# --------------------------------------------------------------------------- #

def _built():
    return {g["id"]: g for g in rp.build(_data(), NOW)}


def test_the_call_is_the_scoreboards_model_against_the_book():
    g = _built()["101"]
    pick = game_model.predict("Alpha", "Bravo", TABLE)
    call = g["call"]
    assert call["margin"] == pytest.approx(pick["pred_home"] - pick["pred_away"], abs=0.051)
    assert call["prob"] == pick["home_win_prob"]
    assert call["spread"] == -6.5 and call["book_total"] == 140.5
    assert call["record_url"] is None and call["call_min"] == rp.EDGE
    # The guide's watch score on the feed's GordStats ranks; both AP-ranked.
    assert (call["watch"], call["tags"]) == rp.watch_score(4, 35, pick["home_win_prob"], True, 0)
    assert g["tv"] == "ESPN2, ESPN+" and g["venue"] == "Home Arena" and g["place"] == "Town, ST"
    assert g["home"]["rank"] == 5 and g["away"]["rank"] == 20 and not g["home"]["rank_text"]
    assert g["home"]["record"] == "1-1 · Big East"
    assert g["home"]["logo"] == "/assets/images/alpha%20u.png" and g["home"]["href"] is None
    assert [r["label"] for r in g["units"]["home"]] == ["Adj. efficiency", "Effective FG%"]
    assert g["style"]["home"] == "70.0 possessions a game (1st fastest) · 41% of shots from three"
    assert ("Watch Guide", "/cbb/watch/") in g["links"] and g["schedule"] is None


def test_a_final_keeps_the_archived_line_and_no_watch_score():
    g = _built()["104"]
    assert g["state"] == "post" and g["status"] == "Final"
    # "ALP -2.5" with Alpha the visitor: Bravo, at home, +2.5.
    assert g["call"]["spread"] == 2.5 and g["call"]["book_total"] == 150.0
    assert "watch" not in g["call"]
    html = _text(preview_page.verdict(g))
    assert html.startswith("GordStats had"), html


def test_after_tip_off_the_close_beats_the_feeds_line():
    feed = _feed()
    feed["men"]["104"].update(spread_close="ALP -9.5", total_close=160.0)   # moved in-game
    feed["men"]["101"]["status"] = "in_progress"
    archive = {**ARCHIVE, "men:101": {"league": "men", "spread": "ALP -5", "total": 139.0}}
    games = {g["id"]: g for g in rp.build(_data(feed=feed, lines=archive), NOW)}
    assert (games["104"]["call"]["spread"], games["104"]["call"]["book_total"]) == (2.5, 150.0)
    assert (games["101"]["call"]["spread"], games["101"]["call"]["book_total"]) == (-5.0, 139.0)
    # Before it, the feed's is the latest.
    assert _built()["101"]["call"]["spread"] == -6.5


def test_the_tournament_shows_seeds_and_its_round():
    g = _built()["108"]
    assert g["home"]["rank_text"] == "1 seed" and g["home"]["rank"] is None
    assert g["note"] == "NCAA Tournament · 1st Round" and g["neutral"]
    head = _text(preview_page.header(g))
    assert "1 seed Alpha" in head and "16 seed Delta" in head and "vs" in head
    # A neutral floor: no home court in the call.
    pick = game_model.predict("Alpha", "Delta", TABLE, neutral=True)
    assert g["call"]["prob"] == pick["home_win_prob"]
    assert "Tournament" in g["call"]["tags"]


def test_preseason_says_projections():
    g = rp.build(_data(played=False), NOW)[0]
    assert "preseason projections" in g["source"]


# --------------------------------------------------------------------------- #
# The pages
# --------------------------------------------------------------------------- #

@pytest.fixture
def docs(tmp_path, monkeypatch):
    monkeypatch.setattr(gs_paths, "DOCS", tmp_path)
    return tmp_path


def _old_page(docs, gid="99"):
    g = rp.build(_data(), NOW)[0]
    preview_page.write({**g, "id": gid}, updated=False)
    return docs / "cbb" / "game" / gid / "index.html"


def test_generate_writes_the_window_and_prunes_the_rest(docs, monkeypatch, capsys):
    old = _old_page(docs)
    monkeypatch.setattr(rp, "feed", lambda: {"leagues": _feed(), "generated": "x"})
    monkeypatch.setattr(rp, "load", lambda now, got: _data())
    ids = rp.generate(NOW)
    assert sorted(ids) == ["101", "103", "104", "108"]
    assert not old.exists()
    page = (docs / "cbb" / "game" / "101" / "index.html").read_text(encoding="utf-8")
    assert "title: Bravo at Alpha" in page and "Men's college basketball preview" in page
    assert preview_page.MARK in page and "ESPN2, ESPN+" in page
    body = page.split("---", 2)[2]
    assert body.strip().startswith("{% raw %}") and body.count("{% raw %}") == 1
    assert len(page) < 25_000                                       # one small page
    assert "Wrote 4 CBB game previews" in capsys.readouterr().out
    assert preview_page.built("cbb", docs) == ["101", "103", "104", "108"]


def test_names_from_the_feed_are_text(docs, monkeypatch):
    feed = _feed()
    feed["men"]["101"]["away_team"] = "Bra{{vo}} <i onmouseover=1>"
    data = _data(feed=feed, trank={**TRANK, "Bra{{vo}} <i onmouseover=1>": 30})
    monkeypatch.setattr(rp, "feed", lambda: {"leagues": feed, "generated": "x"})
    monkeypatch.setattr(rp, "load", lambda now, got: data)
    rp.generate(NOW)
    page = (docs / "cbb" / "game" / "101" / "index.html").read_text(encoding="utf-8")
    front, body = page.split("---", 2)[1:]
    # The body escapes it; the front matter's title too, and its description
    # is a JSON string (jekyll-seo-tag escapes it), as on the CFB and NFL pages.
    assert "<i onmouseover" not in body and "&lt;i onmouseover=1&gt;" in body
    assert "title: Bra{{vo}} &lt;i onmouseover=1&gt; at Alpha" in front
    assert body.count("{% raw %}") == 1 and body.strip().startswith("{% raw %}")


def test_off_season_is_a_line_and_nothing_written(docs, monkeypatch, capsys):
    """Today's feed holds last April's games: no page, and why."""
    old = _old_page(docs)
    april = {"men": {"1": _g("Alpha", "Bravo", "2026-04-06", "20:50", status="final")}}
    monkeypatch.setattr(rp, "feed", lambda: {"leagues": april,
                                             "generated": "2026-04-08T01:00:21"})
    from cbb.render import render_power
    monkeypatch.setattr(render_power, "trank", lambda refresh=False: pd.DataFrame(
        {"team": list(TRANK), "rank": list(TRANK.values())}))
    later = pd.Timestamp("2026-09-30 12:00", tz=ET)
    assert rp.generate(later) == []
    out = capsys.readouterr().out
    assert "no men's games from 2026-09-29 to 2026-10-01" in out and "pushed 2026-04-08" in out
    assert not old.exists()                     # yesterday's page went with its window
    assert preview_page.built("cbb", docs) == []


def test_a_feed_that_does_not_load_leaves_the_pages(docs, monkeypatch, capsys):
    old = _old_page(docs)

    def down():
        raise requests.ConnectionError("no route")
    monkeypatch.setattr(rp, "feed", down)
    assert rp.generate(NOW) == []
    assert old.exists()
    assert "did not load" in capsys.readouterr().out


def test_tv_reads_theScores_us_listings(monkeypatch):
    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"id": 101, "tv_listings_by_country_code": {
                "us": [{"short_name": "CBS"}, {"short_name": "Paramount+"},
                       {"short_name": "CBS"}, {"short_name": "TruTV"}],
                "ca": [{"short_name": "TSN"}]}},
                    {"id": 102, "tv_listings_by_country_code": None}]
    asked = []
    monkeypatch.setattr(requests, "get", lambda url, **kw: asked.append(kw["params"]) or R())
    assert rp.tv(["101", "102"]) == {"101": "CBS, Paramount+"}
    assert asked == [{"id.in": "101,102"}]

    def fail(url, **kw):
        raise requests.Timeout("slow")
    monkeypatch.setattr(requests, "get", fail)
    assert rp.tv(["101"]) == {}                  # no TV, not no page


# --------------------------------------------------------------------------- #
# The shared module's additions
# --------------------------------------------------------------------------- #

def test_the_shared_page_takes_seeds_links_and_tenths():
    assert preview_page.fmt(0.4567, "pct1") == "45.7%"
    assert preview_page.possessive("St. John's") == "St. John's"
    assert preview_page.possessive("Texas") == "Texas'"
    g = _built()["108"]
    assert "<span class=pv-rk>1 seed</span>" in preview_page.header(g)
    links = preview_page.links_block(g, "t")
    assert "href='/men/'>Scores &rarr;" in links and "Schedule" not in links


# --------------------------------------------------------------------------- #
# The watch guide opens them
# --------------------------------------------------------------------------- #

def test_the_guide_is_told_which_games_have_a_preview(docs):
    assert watch.config()["pv"] == []
    for gid in ("101", "103"):
        preview_page.write({**rp.build(_data(), NOW)[0], "id": gid}, updated=False)
    assert watch.config()["pv"] == ["101", "103"]
    js = watch.body()
    assert "'/cbb/game/'+id+'/'" in js and '"pv":["101","103"]' in js


@pytest.fixture(scope="module")
def guide(tmp_path_factory):
    import functools
    import http.server
    import socketserver
    import threading
    root = tmp_path_factory.mktemp("cbbpv")
    cfg = {**watch.config(), "pv": ["v1", "w1"]}
    (root / "index.html").write_text(
        "<!doctype html><html><head><meta charset='utf-8'></head><body>"
        "<p class='page-updated' data-updated='2026-09-01T08:00-04:00'>Updated</p>"
        + expand(watch.body(cfg)) + "</body></html>", encoding="utf-8")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a: None
    server = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()


def test_a_card_opens_its_preview_in_the_browser(guide):
    from test_cbb_watch import CHROME, READ, _boot, _feed as watch_feed, _run
    if CHROME is None:
        pytest.skip("no Chromium to run the JS in")
    got = _run(guide, _boot(watch_feed()), [READ])
    evening = {g["id"]: g["href"] for g in got["Evening"]}
    assert evening["v1"] == "/cbb/game/v1/"                 # a preview on disk
    assert evening["v2"] == "/men/"                         # none: the scoreboard
    women = _run(guide, _boot(watch_feed(), league="women"), [READ])
    # The previews are the men's: a women's id never opens one.
    assert all(g["href"] == "/women/" for g in women["Evening"])
