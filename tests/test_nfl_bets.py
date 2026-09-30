"""The NFL bets card on the home page (nfl.site.homecards on the shared
gordstats.bets_card): which games it may take, when it locks, how it grades,
and where the home page puts it. No network: the season frame and the
prediction archive are built here."""
import json
from datetime import date, datetime

import pandas as pd
import pytest

from gordstats import bets_card
from nfl.config import TZ
from nfl.site import homecards

UTC = "UTC"


def _game(gid, week, kick, home, away, margin, spread, total=45.0, book_total=45.0,
          seasontype=2, home_id=None, away_id=None, played=False, score=None):
    home_id = home_id or f"h{gid}"
    away_id = away_id or f"a{gid}"
    hs, as_ = score if score else (None, None)
    return {"game_id": str(gid), "week": week, "seasontype": seasontype,
            "date": pd.Timestamp(kick, tz=UTC), "home": home, "away": away,
            "home_id": home_id, "away_id": away_id, "home_abbr": home[:3].upper(),
            "away_abbr": away[:3].upper(), "pred_margin": margin, "pred_total": total,
            "home_win_prob": 0.5, "book_spread": spread, "book_total": book_total,
            "played": played, "completed": played, "state": "post" if played else "pre",
            "home_score": hs, "away_score": as_,
            # The schedule's own points-scored column, which the card must not
            # mistake for the book's total.
            "total": (hs + as_) if played else None}


def _week4():
    """Thursday night, then Sunday: spreads of every size against the gates."""
    return pd.DataFrame([
        _game(1, 4, "2026-10-02T00:15Z", "Browns", "Steelers", 2.0, -1.0),     # 1: no call
        _game(2, 4, "2026-10-04T17:00Z", "Giants", "Cardinals", 1.9, 2.5),     # 4.4: Giants +2.5
        _game(3, 4, "2026-10-04T17:00Z", "Bucs", "Packers", 1.4, 3.5),         # 4.9: Bucs +3.5
        _game(4, 4, "2026-10-04T17:00Z", "Bears", "Jets", 9.7, -3.5),          # 6.2: over the cap
        _game(5, 4, "2026-10-04T20:25Z", "Raiders", "Chiefs", -4.5, 4.5,       # a 4.7 under
              total=42.8, book_total=47.5),
        _game(6, 4, "2026-10-06T00:15Z", "Saints", "Falcons", 0.0, -2.5),      # Monday night
        _game(7, 5, "2026-10-09T00:15Z", "Rams", "49ers", 3.0, -3.0),
    ])


def test_the_gates_take_the_widest_disagreements_inside_the_cap():
    frame = _week4()
    now = datetime(2026, 9, 30, 12, tzinfo=TZ)
    picks = bets_card.pick_week(homecards._candidates(frame, 4, now), 4,
                                homecards.EDGE_MIN, homecards.EDGE_MAX)
    # Jets-Bears is the widest gap and the one ruled out: past EDGE_MAX it is
    # more likely news than an edge.
    assert picks["single"]["team"] == "Bucs" and picks["single"]["line"] == 3.5
    assert picks["single"]["model"] == 1.4 and picks["single"]["edge"] == 4.9
    legs = [(p["kind"], p.get("side"), p["team"]) for p in picks["parlay"]]
    assert legs == [("total", "Under", "Chiefs at Raiders"), ("spread", None, "Giants")]
    assert all(p["game_id"] != "4" for p in [picks["single"]] + picks["parlay"])
    assert homecards.EDGE_MIN == 3 and homecards.EDGE_MAX == 6


def test_games_already_kicked_off_and_unknown_playoff_teams_are_not_candidates():
    frame = pd.concat([_week4(), pd.DataFrame([
        _game(8, 1, "2027-01-16T21:30Z", "TBD", "TBD", 2.1, None, seasontype=3,
              home_id="-1", away_id="-2")])], ignore_index=True)
    # Sunday 2 PM: the Thursday and 1 o'clock games are under way.
    now = datetime(2026, 10, 4, 14, tzinfo=TZ)
    got = homecards._candidates(frame, 4, now)
    assert sorted(got["game_id"]) == ["5", "6"]
    assert homecards._candidates(frame, 19, now).empty


def test_the_card_is_about_the_week_being_played_until_its_last_game_is_over():
    frame = _week4()
    week, first = homecards._current_week(frame, datetime(2026, 9, 30, 18, tzinfo=TZ))
    assert week == 4 and first == datetime(2026, 10, 1, 20, 15, tzinfo=TZ)
    # Monday night kicks off at 8:15; the card moves on four hours later.
    assert homecards._current_week(frame, datetime(2026, 10, 5, 23, tzinfo=TZ))[0] == 4
    assert homecards._current_week(frame, datetime(2026, 10, 6, 0, 30, tzinfo=TZ))[0] == 5


def test_picks_lock_on_thursday_morning_and_stay_locked(tmp_path, monkeypatch):
    monkeypatch.setattr(homecards, "BETS_DIR", tmp_path)
    frame = _week4()
    first = datetime(2026, 10, 1, 20, 15, tzinfo=TZ)
    wed = datetime(2026, 9, 30, 18, tzinfo=TZ)
    picks, when, frozen = homecards.locked_picks(frame, 4, first, wed)
    assert not frozen and when == datetime(2026, 10, 1, 9, tzinfo=TZ)
    assert not list(tmp_path.iterdir())                  # nothing frozen early
    thu = datetime(2026, 10, 1, 9, 5, tzinfo=TZ)
    picks, when, frozen = homecards.locked_picks(frame, 4, first, thu)
    assert frozen and (tmp_path / "2026_wk04.json").exists()
    assert json.loads((tmp_path / "2026_wk04.json").read_text())["locked"].endswith("-04:00")
    # The model moves on Friday; the card does not.
    moved = frame.assign(pred_margin=frame["pred_margin"] * -1)
    again, _when, frozen = homecards.locked_picks(moved, 4, first,
                                                  datetime(2026, 10, 2, 12, tzinfo=TZ))
    assert frozen and again["single"] == picks["single"]


def test_a_playoff_round_locks_to_its_own_file(tmp_path, monkeypatch):
    monkeypatch.setattr(homecards, "BETS_DIR", tmp_path)
    frame = pd.DataFrame([_game(9, 1, "2027-01-16T21:30Z", "Bills", "Jaguars", 8.0, -3.0,
                                seasontype=3)])
    key, first = homecards._current_week(frame, datetime(2027, 1, 12, tzinfo=TZ))
    assert key == 19 and homecards.week_label(key) == "Wild Card"
    homecards.locked_picks(frame, key, first, datetime(2027, 1, 16, 10, tzinfo=TZ))
    assert (tmp_path / "2026_wk19.json").exists()


def test_the_close_is_the_archive_s_last_look_before_kickoff(monkeypatch):
    archive = pd.DataFrame({
        "game_id": ["2", "3"], "market_spread": [3.0, 3.5], "market_total": [44.5, None],
        "kickoff": [pd.Timestamp("2026-10-04T17:00Z"), pd.Timestamp("2026-10-11T17:00Z")]})
    monkeypatch.setattr(homecards.results, "on_record", lambda season=None: archive)
    closes = homecards._closes(datetime(2026, 10, 5, tzinfo=TZ))
    assert closes == {"2": (3.0, 44.5)}                 # game 3 has not kicked off


def test_the_season_record_grades_units_and_the_close(tmp_path, monkeypatch):
    monkeypatch.setattr(homecards, "BETS_DIR", tmp_path)
    frame = _week4()
    picks = bets_card.pick_week(homecards._candidates(frame, 4, datetime(2026, 9, 30, tzinfo=TZ)),
                                4, homecards.EDGE_MIN, homecards.EDGE_MAX)
    (tmp_path / "2026_wk04.json").write_text(json.dumps(dict(picks, locked="2026-10-01T09:05:00-04:00")))
    # Bucs +3.5 lose by 3: covered. Chiefs-Raiders 20-17: under 47.5, won.
    # Giants +2.5 lose by 7: lost - so the parlay lost.
    finals = {"3": (-3.0, 41.0), "5": (-3.0, 37.0), "2": (-7.0, 41.0)}
    closes = {"3": (3.0, 41.5), "5": (4.5, 46.5), "2": (3.0, 44.5)}
    got = homecards._season_record(finals, closes)
    assert "<strong>2-1</strong>" in got
    assert "&minus;0.1 units" in got                  # +0.9 on the single, -1 on the parlay
    # Bucs took 3.5 against a 3 close (the home side's +3 is the Bucs' +3):
    # better. The under at 47.5 against a 46.5 close: better. Giants +2.5
    # against +3: worse.
    assert "<strong>2 better</strong>, <strong>1 worse</strong>" in got


def test_the_card_names_the_sport_and_links_the_nfl_record(tmp_path, monkeypatch):
    monkeypatch.setattr(homecards, "BETS_DIR", tmp_path)
    monkeypatch.setattr(homecards.results, "on_record", lambda season=None: pd.DataFrame())
    html = homecards.bets_html(datetime(2026, 9, 30, 18, tzinfo=TZ), frame=_week4())
    assert "Bucs +3.5" in html and "we have them -1.4, the book +3.5" in html
    assert "3-leg parlay" not in html and "2-leg parlay" in html
    assert "GordStats&#x27; NFL Week 4 bet: Bucs +3.5 vs Packers, plus a 2-leg parlay" in html
    assert "href='/nfl/'" in html
    assert "data-lock='2026-10-01T09:00:00-04:00'" in html and "Locks Thu 9 AM ET" in html
    # The countdown follows the card, so its first tick finds the lock.
    assert html.index("class='hc-lock'") < html.index("__hcLockTick")
    assert not list(tmp_path.iterdir())


def test_a_week_with_no_disagreement_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(homecards, "BETS_DIR", tmp_path)
    frame = _week4().assign(pred_margin=lambda f: -f["book_spread"].fillna(0),
                            pred_total=lambda f: f["book_total"])
    html = homecards.bets_html(datetime(2026, 9, 30, 18, tzinfo=TZ), frame=frame)
    assert "agree to within 3 points on every game this week" in html


def test_home_places_the_card_in_season_once_it_exists(tmp_path, monkeypatch):
    from cbb.render import render_home
    monkeypatch.setattr(render_home.paths, "DOCS", tmp_path)
    (tmp_path / "_includes").mkdir()
    assert render_home._nfl_graphics(date(2026, 9, 30)) == ""        # not built yet
    (tmp_path / "_includes" / "nfl_bets.html").write_text("card")
    got = render_home._nfl_graphics(date(2026, 9, 30))
    assert "{% include nfl_bets.html %}" in got and "This week's NFL bets" in got
    assert "href=\"/nfl/\"" in got
    assert render_home._nfl_graphics(date(2027, 2, 10)) != ""        # Super Bowl week
    assert render_home._nfl_graphics(date(2027, 7, 1)) == ""         # the summer


@pytest.mark.parametrize("key,label", [(4, "Week 4"), (18, "Week 18"), (19, "Wild Card"),
                                       (20, "Divisional"), (21, "Conference"), (23, "Super Bowl")])
def test_weeks_are_named_as_the_predictions_page_names_them(key, label):
    assert homecards.week_label(key) == label
