"""
The game previews' sport adapters (cfb.site.previews, nfl.site.previews) and
the links into them from the schedule, predictions and watch pages. No
network: every frame, archive and stat line is built here.
"""
import pandas as pd
import pytest

from gordstats import preview_page

NAN = float("nan")


# --------------------------------------------------------------------------- #
# College football
# --------------------------------------------------------------------------- #

def _cfb(gid, week, kick, away, home, state="pre", score=None, **kw):
    ids = {"Alpha": "1", "Bravo": "2", "Charlie": "3", "Delta": "4", "Foxtrot FCS": "9"}
    hs, as_ = score if score else (0.0, 0.0)
    row = {"week": week, "game_id": str(gid), "date_utc": kick, "time_valid": True,
           "home_id": ids[home], "away_id": ids[away], "home": home, "away": away,
           "home_abbr": home[:3].upper(), "away_abbr": away[:3].upper(),
           "home_rank": NAN, "away_rank": NAN, "home_score": hs, "away_score": as_,
           "neutral": False, "venue": "Field", "note": "", "place": "Town, ST", "tv": "ESPN",
           "state": state, "detail": "Final" if state == "post" else "",
           "gs_margin": 3.0, "gs_total": 50.0, "gs_wp": 0.6, "dk_spread": NAN, "dk_total": NAN,
           "dk_book": "DraftKings", "bd_spread": NAN, "fpi_wp": NAN, "mq": NAN, "weather": None}
    row.update(kw)
    return row


def _cfb_frame():
    return pd.DataFrame([
        _cfb(31, 3, "2026-09-19T19:00Z", "Alpha", "Bravo", "post", (17.0, 20.0)),
        _cfb(32, 3, "2026-09-19T19:00Z", "Charlie", "Delta", "post", (24.0, 10.0)),
        # Week 4, played; Charlie won at Alpha by 3 where we had Alpha by 3.
        _cfb(41, 4, "2026-09-26T19:00Z", "Charlie", "Alpha", "post", (28.0, 31.0)),
        _cfb(42, 4, "2026-09-26T19:00Z", "Delta", "Bravo", "post", (21.0, 14.0)),
        _cfb(43, 4, "2026-09-26T16:00Z", "Foxtrot FCS", "Charlie", "post", (45.0, 3.0)),
        # Week 5, to come: Charlie favoured by 6.5 at home, the book by 3.
        _cfb(51, 5, "2026-10-03T19:30Z", "Bravo", "Charlie", gs_margin=6.5, gs_wp=0.69,
             gs_total=55.0, dk_spread=-3.0, dk_total=51.5, bd_spread=-3.0, fpi_wp=0.64,
             mq=72.0, home_rank=12.0,
             weather={"temp": 58.0, "cond": 12, "precip": 70.0, "wind": 14.0}),
        _cfb(52, 5, "2026-10-03T23:00Z", "Alpha", "Delta"),
        # Week 6: only the game with a book line gets a page.
        _cfb(61, 6, "2026-10-10T19:30Z", "Alpha", "Charlie", dk_spread=-1.5, dk_total=49.0),
        _cfb(62, 6, "2026-10-10T19:30Z", "Bravo", "Delta"),
    ])


CFB_NOW = pd.Timestamp("2026-09-30T12:00Z")


@pytest.fixture
def cfbp(monkeypatch):
    from cfb.site import previews
    monkeypatch.setattr(previews, "FBS_GAMES", 2)         # Foxtrot plays once: FCS
    return previews


def test_cfb_window_is_last_this_and_lined_next_week_fbs_only(cfbp):
    got = cfbp.window(_cfb_frame(), CFB_NOW)
    assert sorted(got["game_id"]) == ["41", "42", "51", "52", "61"]


def _cfb_data(cfbp):
    rows = [{"id": "2", "name": "Bravo U", "adj_off_rush": 0.25, "adj_def_rush": 0.05,
             "adj_off": 0.2, "adj_def": 0.0, "plays_pg": 72.0, "pass_rate": 0.55},
            {"id": "3", "name": "Charlie St", "adj_off_rush": -0.1, "adj_def_rush": 0.2,
             "adj_off": 0.0, "adj_def": 0.1, "plays_pg": 60.0, "pass_rate": 0.4},
            {"id": "1", "name": "Alpha", "adj_off_rush": 0.0, "adj_def_rush": 0.0,
             "adj_off": 0.05, "adj_def": 0.05},
            {"id": "4", "name": "Delta", "adj_off_rush": 0.1, "adj_def_rush": -0.05,
             "adj_off": 0.1, "adj_def": -0.05}]
    ppa = [{"name": "Q One", "pos": "QB", "team": "Bravo U", "pass": 0.41, "pass_n": 120,
            "rush": None, "rush_n": 0},
           {"name": "Q Two", "pos": "QB", "team": "Bravo U", "pass": 0.9, "pass_n": 12,
            "rush": None, "rush_n": 0},
           {"name": "R Back", "pos": "RB", "team": "Bravo U", "pass": None, "pass_n": 0,
            "rush": 0.12, "rush_n": 60},
           {"name": "W One", "pos": "WR", "team": "Bravo U", "pass": 0.5, "pass_n": 30,
            "rush": None, "rush_n": 0},
           {"name": "T End", "pos": "TE", "team": "Bravo U", "pass": 0.2, "pass_n": 20,
            "rush": None, "rush_n": 0},
           {"name": "W Two", "pos": "WR", "team": "Bravo U", "pass": 1.0, "pass_n": 5,
            "rush": None, "rush_n": 0}]
    return {"frame": _cfb_frame(), "ranks": preview_page.rank_table(rows, cfbp.BETTER),
            "rows": {r["id"]: r for r in rows}, "names": {r["id"]: r["name"] for r in rows},
            "ppa": ppa, "qualified": {"QB": [ppa[0]], "WR": [ppa[3]]},
            "playoff": {}, "pages": frozenset({"charlie"})}


def test_cfb_game_carries_the_schedules_numbers_and_the_watch_score(cfbp):
    games = {g["id"]: g for g in cfbp.build(_cfb_data(cfbp), CFB_NOW)}
    g = games["51"]
    assert g["label"] == "Week 5" and g["state"] == "pre"
    assert g["away"]["name"] == "Bravo" and g["home"]["rank"] == 12
    assert g["home"]["href"] == "/cfb/teams/charlie/" and g["away"]["href"] is None
    # Records going in: Bravo lost at home to Alpha and beat Delta; Charlie lost at
    # Delta, then won at Alpha and beat Foxtrot.
    assert g["away"]["record"] == "1-1" and g["home"]["record"] == "2-1"
    c = g["call"]
    assert (c["margin"], c["prob"], c["total"], c["spread"], c["book_total"]) == \
        (6.5, 0.69, 55.0, -3.0, 51.5)
    assert c["others"] == [("ESPN FPI", "CHA 64%", "win chance")]
    assert c["watch"] is not None and c["edge"] == 3 and c["call_min"] == 0.5
    assert g["weather"]["text"].startswith("58°") and "rain 70%" in g["weather"]["sub"]
    assert g["schedule"] == "/cfb/schedule/#w=5&g=51"
    # A played game has no watch score.
    assert "watch" not in games["41"]["call"] and games["41"]["state"] == "post"


def test_cfb_units_players_and_form(cfbp):
    g = {g["id"]: g for g in cfbp.build(_cfb_data(cfbp), CFB_NOW)}["51"]
    run = next(r for r in g["units"]["away"] if r["label"] == "Run EPA")
    assert run["off"][1] == 1 and run["def"][1] == 4          # Bravo's run game vs the worst
    said = preview_page.mismatches(g)
    assert "Bravo&#x27;s offense (1st)</b> meets Charlie&#x27;s defense (4th)" in said[0][1]
    players = g["players"]["away"]
    assert [p["name"] for p in players] == ["Q One", "R Back", "W One", "T End"]
    assert players[0]["rank"] == "1st of 1 QBs" and players[1]["rank"] == ""
    assert g["style"]["away"] == "72 plays a game (1st most) · passes on 55% of plays"
    form = g["form"]["home"]
    # Newest first: beat Foxtrot, then won at Alpha by 3 where we had Alpha by 3 (+6).
    assert [f["opp"] for f in form] == ["Alpha", "Foxtrot FCS", "Delta"]
    assert form[0]["vs_line"] == 6.0 and form[0]["at"] == "at"


def test_cfb_generate_writes_pages_and_prunes_the_old(cfbp, monkeypatch, tmp_path):
    """A finished game's page outlives the window, so a shared link or a search
    result still opens; a page for a game not played this season goes."""
    monkeypatch.setattr(preview_page.paths, "DOCS", tmp_path)
    monkeypatch.setattr(cfbp, "load", lambda: _cfb_data(cfbp))
    kept = preview_page.write({**_stub_game("cfb", "31")}, root=tmp_path, updated=False)
    gone = preview_page.write({**_stub_game("cfb", "29")}, root=tmp_path, updated=False)
    cfbp.generate(now=CFB_NOW)
    base = tmp_path / "cfb" / "game"
    assert sorted(p.name for p in base.iterdir()) == ["31", "41", "42", "51", "52", "61"]
    assert kept.exists() and not gone.exists()
    page = (base / "51" / "index.html").read_text()
    assert "title: Bravo at Charlie" in page and "Week 5 preview" in page
    assert "description: \"Bravo at Charlie, Sat, Oct 3: GordStats' pick against" in page
    final = (base / "41" / "index.html").read_text()
    assert "description: \"Charlie 31, Alpha 28 (Sat, Sep 26): how GordStats' pick" in final


# --------------------------------------------------------------------------- #
# NFL
# --------------------------------------------------------------------------- #

def _nfl(gid, week, kick, away, home, score=None, seasontype=2, **kw):
    ids = {"Bears": "3", "Lions": "8", "Jets": "20", "Bills": "2", "TBD": "-1"}
    played = score is not None
    hs, as_ = score if played else (0.0, 0.0)
    row = {"game_id": str(gid), "week": week, "seasontype": seasontype,
           "date": pd.Timestamp(kick), "home": home, "away": away,
           "home_id": ids[home], "away_id": "-2" if away == "TBD" else ids[away],
           "home_abbr": {"Bears": "CHI", "Lions": "DET", "Jets": "NYJ", "Bills": "BUF"}.get(home, "TBD"),
           "away_abbr": {"Bears": "CHI", "Lions": "DET", "Jets": "NYJ", "Bills": "BUF"}.get(away, "TBD"),
           "home_score": hs, "away_score": as_, "home_record": "", "away_record": "",
           "played": played, "completed": played, "state": "post" if played else "pre",
           "detail": "Final" if played else "TBD" if away == "TBD" else "10/4 - 1:00 PM EDT",
           "tv": "CBS", "neutral": False, "venue": "Stadium", "place": "City, ST",
           "indoor": False, "pred_margin": 3.0, "pred_total": 44.0, "home_win_prob": 0.6,
           "book_spread": -2.5, "book_total": 44.5}
    row.update(kw)
    return row


def _nfl_frame():
    return pd.DataFrame([
        # Week 2: the Lions beat the Bears at home (scores are home, away).
        _nfl(1, 2, "2026-09-20T17:00Z", "Bears", "Lions", score=(27.0, 20.0)),
        # Week 3, played: we had the Bills by 6 on record, they won by 3.
        _nfl(2, 3, "2026-09-27T17:00Z", "Jets", "Bills", score=(23.0, 20.0), pred_margin=9.0),
        # Week 4, to come.
        _nfl(3, 4, "2026-10-04T17:00Z", "Lions", "Bears", pred_margin=-1.5, pred_total=47.0,
             home_win_prob=0.45, book_spread=2.5, book_total=46.5, indoor=True),
        # Week 5: one with a line, one without.
        _nfl(4, 5, "2026-10-11T17:00Z", "Bills", "Lions"),
        _nfl(5, 5, "2026-10-11T17:00Z", "Jets", "Bears", book_spread=NAN),
        _nfl(6, 1, "2027-01-16T21:30Z", "TBD", "TBD", seasontype=3),
    ])


NFL_NOW = pd.Timestamp("2026-09-30T12:00Z")
NFL_RECORD = {"2": {"game_id": "2", "pred_margin": 6.0, "pred_total": 41.0,
                    "home_win_prob": 0.7, "market_spread": -4.5, "market_total": 42.5}}


def _nfl_data():
    from nfl.site import previews
    teams = [{"abbr": "CHI", "off_adj": 0.1, "def_adj": 0.0, "off_pace": 27.0, "off_proe": 0.04},
             {"abbr": "DET", "off_adj": 0.2, "def_adj": -0.1, "off_pace": 30.0, "off_proe": -0.02},
             {"abbr": "NYJ", "off_adj": -0.1, "def_adj": 0.1},
             {"abbr": "BUF", "off_adj": 0.0, "def_adj": 0.05}]
    ids = {"CHI": "3", "DET": "8", "NYJ": "20", "BUF": "2"}
    rows = [{**t, "id": ids[t["abbr"]]} for t in teams]
    stats = {"teams": teams, "players": {
        "qb": [{"id": "q1", "name": "Q Lion", "team": "DET", "pos": "QB", "n": 120, "epa": 0.3,
                "cpoe": 2.5}],
        "rb": [], "wr": [{"id": "w1", "name": "W Bear", "team": "CHI", "pos": "WR", "n": 25,
                          "epa": 0.5, "catch": 0.7}]}}
    names = {"3": ("Bears", "CHI"), "8": ("Lions", "DET"), "20": ("Jets", "NYJ"),
             "2": ("Bills", "BUF")}
    return {"frame": _nfl_frame(), "names": names, "record": NFL_RECORD, "stats": stats,
            "ranks": preview_page.rank_table(rows, previews.BETTER),
            "rows": {r["id"]: r for r in rows}, "nflverse": {r["id"]: r["abbr"] for r in rows},
            "quality": {"3": {"mq": 64.0, "fw": 0.47}}, "weather": {}}


def test_nfl_window_skips_unset_playoff_games_and_unlined_next_week():
    from nfl.site import previews
    got = previews.window(_nfl_frame(), NFL_NOW)
    assert sorted(got["game_id"]) == ["2", "3", "4"]


def test_nfl_kicked_game_shows_the_numbers_on_record(monkeypatch, tmp_path):
    from nfl.site import previews
    monkeypatch.setattr(previews.teams_page, "OUT_DIR", tmp_path)
    (tmp_path / "bears").mkdir()
    (tmp_path / "bears" / "index.html").write_text("x")
    games = {g["id"]: g for g in previews.build(_nfl_data(), NFL_NOW)}
    done = games["2"]["call"]
    assert (done["margin"], done["spread"], done["total"], done["book_total"]) == \
        (6.0, -4.5, 41.0, 42.5)
    assert "watch" not in done
    g = games["3"]
    c = g["call"]
    assert (c["margin"], c["prob"], c["spread"], c["book_total"], c["total"]) == \
        (-1.5, 0.45, 2.5, 46.5, 47.0)
    assert c["watch"] is not None and c["others"] == [("ESPN", "DET 53%", "win chance")]
    assert g["weather"] == {"indoors": True}
    assert g["home"]["href"] == "/nfl/teams/bears/" and g["away"]["href"] is None
    assert g["home"]["record"] == "0-1" and g["away"]["record"] == "1-0"
    assert g["label"] == "Week 4" and g["schedule"] == "/nfl/schedule/#wk-4"
    assert g["words"] == {"off": "offense", "def": "defense"}
    assert g["players"]["away"][0]["name"] == "Q Lion"
    assert g["players"]["away"][0]["rank"] == "1st of 1"
    assert g["style"]["home"] == "27.0 sec a snap (1st fastest) · passes 4% more than expected"
    # The Bills' last game: won by 3 where we had them by 6 on record.
    assert games["4"]["form"]["away"][0]["vs_line"] == -3.0


# --------------------------------------------------------------------------- #
# Links in: only to a page that exists
# --------------------------------------------------------------------------- #

def _stub_game(sport, gid):
    team = {"id": "1", "name": "A", "abbr": "A", "logo": "", "rank": None, "record": "",
            "href": None, "score": None}
    return {"sport": sport, "id": gid, "label": "Week 1", "state": "pre", "ko": None,
            "away": team, "home": {**team, "name": "B", "abbr": "B"}, "call": {}}


@pytest.fixture
def docs(monkeypatch, tmp_path):
    monkeypatch.setattr(preview_page.paths, "DOCS", tmp_path)
    return tmp_path


def test_nfl_schedule_card_links_only_an_existing_preview(docs):
    from nfl.site import schedule
    g = pd.Series(_nfl(3, 4, "2026-10-04T17:00Z", "Lions", "Bears"))
    call = {"margin": 3.0, "prob": 0.6, "spread": -2.5, "total": 44.5}
    assert "/nfl/game/3/" not in schedule._card(g, call, {})
    preview_page.write(_stub_game("nfl", "3"), root=docs, updated=False)
    card = schedule._card(g, call, {})
    assert "href='/nfl/game/3/'" in card and ">Preview<" in card


def test_predictions_cards_link_only_an_existing_preview(docs):
    from cfb.site import predictions as cfb_pred
    from nfl.site import predictions as nfl_pred
    cfb = pd.Series({"game_id": "51", "home": "Charlie", "away": "Bravo", "home_id": "3",
                     "away_id": "2", "home_rank": NAN, "away_rank": NAN, "pred_margin": 6.5,
                     "pred_home": 30.0, "pred_away": 24.0, "pred_total": 54.0,
                     "home_win_prob": 0.69, "home_rating": 5.0, "away_rating": 1.0,
                     "date": pd.Timestamp("2026-10-03T19:30Z"), "tv": "ABC", "neutral": False,
                     "place": "Town", "note": "", "market_spread": -3.0, "time_valid": True})
    assert "/cfb/game/51/" not in cfb_pred._card(cfb)
    preview_page.write(_stub_game("cfb", "51"), root=docs, updated=False)
    assert "ABC &middot; <a href='/cfb/game/51/'>Preview &rarr;</a>" in cfb_pred._card(cfb)

    nfl = pd.Series(_nfl(3, 4, "2026-10-04T17:00Z", "Lions", "Bears", home_rating=1.0,
                         away_rating=0.0, pred_home=23.5, pred_away=20.5))
    assert "/nfl/game/3/" not in nfl_pred._card(nfl, {})
    preview_page.write(_stub_game("nfl", "3"), root=docs, updated=False)
    assert "<a href='/nfl/game/3/'>Preview &rarr;</a>" in nfl_pred._card(nfl, {})


def test_cfb_schedule_more_panel_links_only_an_existing_preview(docs):
    from types import SimpleNamespace
    from cfb.site import schedule
    g = SimpleNamespace(game_id="51", week=5, home_id="3", away_id="2", home="Charlie",
                        away="Bravo", home_abbr="CHA", away_abbr="BRA", dk_spread=-3.0,
                        dk_total=51.5, bd_spread_open=NAN, bd_total_open=NAN, ml_home=NAN,
                        ml_away=NAN, bd_ml_home_open=NAN, bd_ml_away_open=NAN, gs_wp=0.69,
                        gs_total=55.0, fpi_wp=NAN, note="", venue="Field", place="Town")
    assert "Full preview" not in schedule._detail(g, -3.0, 6.5, None, None)
    preview_page.write(_stub_game("cfb", "51"), root=docs, updated=False)
    assert '<a href="/cfb/game/51/">Full preview &rarr;</a>' in \
        schedule._detail(g, -3.0, 6.5, None, None)


def test_watch_cards_go_to_the_preview_when_there_is_one(docs, monkeypatch):
    from datetime import datetime
    from nfl.site import watch
    now = datetime(2026, 10, 1, 12, tzinfo=watch.ET)
    kick = pd.Timestamp(now).tz_convert("UTC") + pd.Timedelta(days=2)
    frame = pd.DataFrame([{
        "game_id": "401", "date": kick, "home": "Commanders", "away": "Cowboys",
        "home_id": "28", "away_id": "6", "home_abbr": "WSH", "away_abbr": "DAL",
        "home_record": "", "away_record": "", "home_score": None, "away_score": None,
        "pred_home": 24.0, "pred_away": 21.0, "pred_margin": 3.0, "home_win_prob": 0.6,
        "book_spread": -2.5, "neutral": False, "venue": "", "tv": "FOX", "state": "pre"}])
    monkeypatch.setattr(watch.predict, "season", lambda: (frame, None, None))
    assert "href" not in watch.games(now, espn={})[0]
    preview_page.write(_stub_game("nfl", "401"), root=docs, updated=False)
    assert watch.games(now, espn={})[0]["href"] == "/nfl/game/401/"
