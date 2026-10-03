"""
The shared game preview (gordstats.preview_page): the call in words, unit
against unit, the form against our line, and the pages it writes and removes.
No network and no site: games are built here in the adapters' shape.
"""
import pandas as pd

from gordstats import preview_page as pv
from gordstats import preview_page


def _team(name, abbr, tid, **kw):
    t = {"id": tid, "name": name, "abbr": abbr, "logo": f"https://logo/{tid}.png",
         "rank": None, "record": "3-1", "href": f"/cfb/teams/{name.lower()}/", "score": None}
    t.update(kw)
    return t


def _game(**kw):
    g = {"sport": "cfb", "id": "401", "label": "Week 5", "state": "pre", "status": "",
         "ko": pd.Timestamp("2026-10-03T19:30Z"), "tk": True, "tv": "ABC",
         "venue": "Sanford Stadium", "place": "Athens, GA", "note": "", "neutral": False,
         "weather": None,
         "away": _team("Texas", "TEX", "251", rank=7),
         "home": _team("Georgia", "UGA", "61", rank=3),
         # We like Georgia by 4.5, the book by 7: the lean is Texas +7.
         "call": {"margin": 4.5, "prob": 0.63, "total": 52.0, "spread": -7.0,
                  "book_total": 47.5, "book": "DraftKings", "others": [], "watch": 81.2,
                  "tags": ["Top 25 matchup"], "call_min": 0.5, "edge": 3.0,
                  "record_url": "/cfb/predictions/"},
         "units": {"away": [], "home": []}, "style": {}, "players": {}, "form": {},
         "words": {"off": "offense", "def": "defense"}, "schedule": "/cfb/schedule/#g=401",
         "notes": [("EPA", "Expected points added.")], "source": "CFBD.", "stats": "/cfb/stats/"}
    g.update(kw)
    return g


def _text(html):
    """The words, tags out - for reading sentences."""
    import html as h
    import re
    return h.unescape(re.sub(r"<[^>]+>", "", html)).replace("\u2014", "-")


# --------------------------------------------------------------------------- #
# The call
# --------------------------------------------------------------------------- #

def test_the_verdict_names_both_numbers_and_the_lean():
    got = _text(pv.verdict(_game(call={**_game()["call"], "margin": 3.5})))
    assert "GordStats likes Georgia by 3.5, the book by 7: a lean to Texas +7." in got, got
    # The total is a lean too (52 against 47.5), and the honesty line follows.
    assert "GordStats says 52 to the book's 47.5: a lean to the Over." in got, got
    assert "not a tip" in got


def test_a_small_gap_is_a_slight_lean_and_none_is_agreement():
    # 4.5 against 7 is under the field goal that makes a lean (edge).
    got = _text(pv.verdict(_game(call={**_game()["call"], "total": 47.0})))
    assert "likes Georgia by 4.5, the book by 7: a slight lean to Texas +7." in got, got
    assert "a slight lean to the Under" in got, got
    same = _game(call={**_game()["call"], "margin": 7.2, "total": 47.6})
    got = _text(pv.verdict(same))
    assert "the book by 7 - they agree, no lean." in got and "On the total" not in got, got
    assert "not a tip" not in got


def test_when_the_book_has_the_other_favourite_it_is_named():
    flipped = _game(call={**_game()["call"], "margin": -2.0, "spread": -3.0})
    got = _text(pv.verdict(flipped))
    assert "GordStats likes Texas by 2, the book has Georgia by 3: a lean to Texas +3." in got, got


def test_no_book_line_says_so_with_the_win_chance():
    got = _text(pv.verdict(_game(call={**_game()["call"], "spread": None})))
    assert got.startswith("GordStats likes Georgia by 4.5, 63% to win. No book line yet."), got


def test_a_final_is_past_tense_with_the_marks():
    # Georgia won by 3: our winner right, the Texas +7 lean covered, 55 points over 47.5.
    done = _game(state="post", status="Final",
                 away={**_game()["away"], "score": 26.0}, home={**_game()["home"], "score": 29.0})
    html = pv.verdict(done)
    got = _text(html)
    assert got.startswith("GordStats had Georgia by 4.5"), got
    assert "GordStats said 52" in got
    assert html.count("pv-mk ok") == 3, html
    head = pv.header(done)
    assert ">26</b>" in head and ">29</b>" in head and "Final" in head


def test_the_tiles_carry_ours_the_book_and_the_watch_score():
    html = pv.call_block(_game())
    assert "UGA by 4.5" in html and "63% to win" in html
    assert "UGA -7" in html and "O/U 47.5" in html
    assert ">81<" in html and "Top 25 matchup" in html
    # The win chance labels sit above the bar; the favourite's half is marked.
    assert "pv-wpl" in html and "class='pv-wph fav'" in html


# --------------------------------------------------------------------------- #
# Unit against unit
# --------------------------------------------------------------------------- #

UNITS = [{"label": "Run EPA", "off": "off_rush", "def": "def_rush", "fmt": "epa",
          "off_phrase": "run game", "def_phrase": "run defense"},
         {"label": "Havoc", "off": "off_havoc", "def": "def_havoc", "fmt": "pct"}]


def test_rank_table_ranks_each_way_and_skips_holes():
    rows = [{"id": "a", "off_rush": 0.2, "def_rush": 0.1}, {"id": "b", "off_rush": 0.1},
            {"id": "c", "off_rush": None, "def_rush": -0.1}]
    got = pv.rank_table(rows, {"off_rush": "high", "def_rush": "low"})
    assert got["a"]["off_rush"] == (0.2, 1, 2) and got["b"]["off_rush"] == (0.1, 2, 2)
    assert got["c"]["def_rush"] == (-0.1, 1, 2) and "off_rush" not in got["c"]


def test_pair_units_needs_both_sides():
    off = {"off_rush": (0.2, 4, 130), "off_havoc": (0.1, 9, 130)}
    dfn = {"def_rush": (0.15, 98, 130)}
    rows = pv.pair_units(UNITS, off, dfn)
    assert [r["label"] for r in rows] == ["Run EPA"]
    assert rows[0]["off"] == (0.2, 4, 130) and rows[0]["def"] == (0.15, 98, 130)


def test_the_biggest_mismatch_is_said_in_words_the_right_way_round():
    run = lambda o, d: {"label": "Run EPA", "fmt": "epa", "off": (0.2, o, 130),
                        "def": (0.1, d, 130), "off_phrase": "run game",
                        "def_phrase": "run defense"}
    g = _game(units={"away": [run(4, 98)],          # Texas's run game has the edge
                     "home": [run(110, 3)]})        # Texas's run defense has it
    said = [t for _s, t in pv.mismatches(g)]
    assert len(said) == 2
    text = [_text(t) for t in said]
    assert "Texas' run game (4th) meets Georgia's run defense (98th)." in text, text
    assert "Texas' run defense (3rd) meets Georgia's run game (110th)." in text, text
    # Close ranks are not a mismatch.
    assert pv.mismatches(_game(units={"away": [run(40, 60)], "home": []})) == []


def test_unit_rows_draw_both_ranks_and_bars():
    g = _game(units={"away": pv.pair_units(UNITS, {"off_rush": (0.21, 4, 130)},
                                           {"def_rush": (0.12, 98, 130)}), "home": []},
              style={"away": "70 plays a game"})
    html = pv.units_block(g)
    assert "<b>4th</b><small>+0.21</small>" in html and "<b>98th</b>" in html
    assert "i class='o win'" in html and "i class='d lose'" in html
    assert "Texas offense <span>vs</span> Georgia defense" in html
    assert "Texas: 70 plays a game" in html and "href='/cfb/stats/'" in html


def test_the_call_and_the_units_carry_the_adapters_how_this_works_chips():
    """How the call and the units are made is an explainer each (gordstats.how),
    opened from a chip on the section's heading; the adapter names which. A
    section it names none for has no chip, and a page with none has no script."""
    from gordstats import how
    units = {"away": pv.pair_units(UNITS, {"off_rush": (0.21, 4, 130)},
                                   {"def_rush": (0.12, 98, 130)}), "home": []}
    g = _game(units=units, how={"call": "cfb-predictions", "units": "game-previews"})
    assert f"<h2>The call {how.button('cfb-predictions')}</h2>" in pv.call_block(g)
    assert f"<h2>Unit vs unit {how.button('game-previews')}</h2>" in pv.units_block(g)
    assert pv.body(g).count(how.JS_TAG) == 1
    bare = _game(units=units, how={"call": "cbb-predictions"})
    assert "<h2>Unit vs unit</h2>" in pv.units_block(bare)
    assert "<h2>The call</h2>" in pv.call_block(_game(units=units))
    assert how.JS_TAG not in pv.body(_game(units=units))


# --------------------------------------------------------------------------- #
# Records and form
# --------------------------------------------------------------------------- #

SEASON = [
    {"game_id": "1", "date": "2026-09-05T19:00Z", "home_id": "61", "away_id": "9",
     "home": "Georgia", "away": "Clemson", "home_score": 31, "away_score": 20,
     "played": True, "pred_margin": 7.0},
    {"game_id": "2", "date": "2026-09-12T19:00Z", "home_id": "251", "away_id": "61",
     "home": "Texas", "away": "Georgia", "home_score": 24, "away_score": 21,
     "played": True, "pred_margin": -3.0},          # we had Georgia by 3 on the road
    {"game_id": "3", "date": "2026-09-19T19:00Z", "home_id": "61", "away_id": "251",
     "home": "Georgia", "away": "Texas", "home_score": None, "away_score": None,
     "played": False, "pred_margin": None},
]


def test_records_are_the_ones_going_in():
    rec = pv.records_going_in(SEASON)
    assert rec["1"] == ("0-0", "0-0")
    assert rec["2"] == ("1-0", "0-0")               # Georgia away, 1-0
    assert rec["3"] == ("1-0", "1-1")               # Texas 1-0, Georgia 1-1


def test_form_is_newest_first_with_the_margin_against_our_line():
    form = pv.recent_form(SEASON, "61", "2026-09-19T19:00Z")
    assert [f["r"] for f in form] == ["L", "W"]
    # Lost by 3 where we had Georgia by 3 on the road: 6 short of our line.
    assert form[0] == {"r": "L", "score": "21-24", "at": "at", "opp": "Texas", "vs_line": -6.0}
    assert form[1]["vs_line"] == 4.0
    html = pv.form_block(_game(form={"home": form}))
    assert "&minus;6</span>" in html and "+4</span>" in html


def test_weather_lines_and_indoors():
    assert pv.weather({"indoors": True}) == {"indoors": True}
    got = pv.weather({"temp": 41.0, "precip": 60.0, "gust": 22.0}, "&#9729;", "Showers")
    assert got == {"icon": "&#9729;", "text": "41° Showers", "sub": "rain 60% · gusts 22 mph"}
    assert pv.weather({}) is None and pv.weather(None) is None


# --------------------------------------------------------------------------- #
# The page on disk
# --------------------------------------------------------------------------- #

def test_names_are_escaped_and_the_body_is_liquid_safe(tmp_path):
    g = _game(away=_team("Tex{{as}} <A&M>", "TAM", "245"), notes=[("{% raw %}", "x")])
    path = pv.write(g, subtitle="Week 5 preview", description="d", root=tmp_path,
                    updated=False)
    assert path == tmp_path / "cfb" / "game" / "401" / "index.html"
    html = path.read_text()
    assert "<A&M>" not in html and "&lt;A&amp;M&gt;" in html
    assert "title: Tex{{as}} &lt;A&amp;M&gt; at Georgia" in html
    body = html.split("---", 2)[2]
    # Everything after the front matter is inside one raw block: Liquid runs nothing.
    assert body.strip().startswith("{% raw %}") and body.count("{% raw %}") == 1
    assert pv.MARK in html


def test_exists_and_href(tmp_path):
    assert pv.href("nfl", "77", root=tmp_path) is None
    pv.write(_game(sport="nfl", id="77"), root=tmp_path, updated=False)
    assert pv.exists("nfl", "77", root=tmp_path)
    assert pv.href("nfl", "77", root=tmp_path) == "/nfl/game/77/"
    assert not pv.exists("nfl", None, root=tmp_path) and not pv.exists("nfl", "nan", root=tmp_path)


def test_prune_removes_only_its_own_old_pages(tmp_path):
    for gid in ("1", "2", "3"):
        pv.write(_game(id=gid), root=tmp_path, updated=False)
    base = tmp_path / "cfb" / "game"
    (base / "3" / "notes.txt").write_text("someone else's")        # not only ours: kept
    (base / "4").mkdir()
    (base / "4" / "index.html").write_text("a page someone else wrote")  # no mark: kept
    (base / "about").mkdir()
    (base / "about" / "index.html").write_text(pv.MARK)            # not a game id: kept
    removed = pv.prune("cfb", {"2"}, root=tmp_path)
    assert removed == ["1"]
    assert not (base / "1").exists()
    assert (base / "2" / "index.html").exists() and (base / "3" / "index.html").exists()
    assert (base / "4" / "index.html").exists() and (base / "about").exists()
    assert pv.prune("nfl", set(), root=tmp_path) == []            # nothing there at all


# ----- the link-preview card ------------------------------------------------ #

def _card_game(**over):
    g = {"sport": "cfb", "id": "401", "label": "Week 5", "state": "pre",
         "ko": "2026-10-03T19:30:00Z", "tk": True, "tv": "ABC", "neutral": False,
         "away": {"name": "Texas"}, "home": {"name": "Georgia"},
         "call": {"margin": 4.5, "prob": 0.66, "spread": -7.0, "book_total": 52.5,
                  "call_min": 0.5, "watch": 88, "tags": ["Top 25 matchup"]}}
    g.update(over)
    return g


def test_the_card_says_our_call_the_books_and_the_lean(monkeypatch):
    drawn = {}
    monkeypatch.setattr(preview_page.share_card, "ranked",
                        lambda slug, kicker, title, sub, rows, alt="": drawn.update(
                            slug=slug, kicker=kicker, title=title, sub=sub, rows=rows))
    preview_page.card(_card_game())
    assert drawn["slug"] == "cfb-game-401" and drawn["title"] == "Texas at Georgia"
    assert drawn["kicker"] == "College football · Week 5"
    assert drawn["sub"] == "Sat, Oct 3 · 3:30 PM ET · ABC"
    assert drawn["rows"] == [("GS", "Georgia by 4.5", "66%"), ("Line", "Georgia -7", "O/U 52.5"),
                             ("Lean", "Texas +7", "slight")]


def test_a_finished_games_card_leads_with_the_score(monkeypatch):
    drawn = {}
    monkeypatch.setattr(preview_page.share_card, "ranked",
                        lambda slug, kicker, title, sub, rows, alt="": drawn.update(rows=rows))
    preview_page.card(_card_game(state="post", away={"name": "Texas", "score": 31},
                                 home={"name": "Georgia", "score": 24}))
    assert drawn["rows"][0] == ("Final", "Texas 31, Georgia 24", "")


def test_cards_are_drawn_for_the_site_and_pruned_with_their_page(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    share = docs / "assets" / "images" / "share"
    monkeypatch.setattr(preview_page.paths, "DOCS", docs)
    monkeypatch.setattr(preview_page.share_card, "OUT_DIR", share)
    preview_page.write(_card_game(), updated=False)
    cards = list(share.glob("cfb-game-401-*.png"))
    assert len(cards) == 1
    page = (docs / "cfb" / "game" / "401" / "index.html").read_text()
    assert cards[0].name in page                      # the front matter's image
    assert preview_page.prune("cfb", keep=set()) == ["401"]
    assert not list(share.glob("cfb-game-401-*.png"))


def test_a_test_folder_never_gets_the_sites_cards(tmp_path):
    before = set(preview_page.share_card.OUT_DIR.glob("*.png")) \
        if preview_page.share_card.OUT_DIR.exists() else set()
    preview_page.write(_card_game(id="402"), root=tmp_path, updated=False)
    after = set(preview_page.share_card.OUT_DIR.glob("*.png")) \
        if preview_page.share_card.OUT_DIR.exists() else set()
    assert after == before
