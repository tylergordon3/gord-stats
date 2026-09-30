"""NFL Schedule & Scores (/nfl/schedule/): the cards, the grading on record,
the week switcher and the live script. No network: the season frame and the
prediction archive are built here."""
import re

import pandas as pd
import pytest

from nfl.site import schedule

UTC = "UTC"


def _game(gid, week, kick, home, away, margin=3.0, spread=-2.5, total=44.5, seasontype=2,
          score=None, home_id=None, away_id=None, detail=None, tv="CBS", neutral=False,
          place="", prob=0.6):
    played = score is not None
    hs, as_ = score if played else (None, None)
    return {"game_id": str(gid), "week": week, "seasontype": seasontype,
            "date": pd.Timestamp(kick, tz=UTC), "home": home, "away": away,
            "home_id": home_id or home.lower(), "away_id": away_id or away.lower(),
            "home_abbr": home[:3].upper(), "away_abbr": away[:3].upper(),
            "home_score": hs, "away_score": as_, "played": played, "completed": played,
            "state": "post" if played else "pre",
            "detail": detail or ("Final" if played else "10/4 - 1:00 PM EDT"),
            "tv": tv, "neutral": neutral, "place": place, "pred_margin": margin,
            "pred_total": 45.0, "home_win_prob": prob, "book_spread": spread,
            "book_total": total}


def _record(rows):
    return pd.DataFrame([{"game_id": str(g), "pred_margin": m, "home_win_prob": p,
                          "market_spread": s, "market_total": t} for g, m, p, s, t in rows])


def _season():
    return pd.DataFrame([
        # Week 3, final: we took the Bears by 6 against a 2.5 - a lean; they
        # won by 3 - right winner, and covered the 2.5.
        _game(1, 3, "2026-09-27T17:00Z", "Bears", "Lions", score=(24, 21)),
        # Final, our winner wrong; the book and we within a lean: no ATS call.
        _game(2, 3, "2026-09-27T17:00Z", "Bills", "Jets", score=(17, 20)),
        # Final, and no prediction on record for it.
        _game(3, 3, "2026-09-27T20:25Z", "Rams", "Seahawks", score=(10, 10)),
        # Week 4, still to come.
        _game(4, 4, "2026-10-04T17:00Z", "Bears", "Jets", margin=9.7, spread=-3.5, prob=0.77),
        _game(5, 4, "2026-10-04T13:30Z", "Commanders", "Colts", margin=-2.3, spread=3.5,
              neutral=True, place="London, England", tv="NFL Net"),
        _game(6, 4, "2027-01-10T05:00Z", "Bills", "Lions", detail="TBD", tv=""),
        # The Wild Card round before its teams are known.
        _game(7, 1, "2027-01-16T21:30Z", "TBD", "TBD", seasontype=3, home_id="-1",
              away_id="-2", detail="TBD", tv=""),
    ])


RECORD = _record([("1", 6.0, 0.70, -2.5, 44.5), ("2", 1.0, 0.55, -2.5, 44.5)])
NOW = pd.Timestamp("2026-09-30T22:00Z")


def _cards(html):
    return {m.group(1): m.group(0) for m in
            re.finditer(r"<article class='ns-g' id='g-(\d+)'.*?</article>", html, re.S)}


def test_weeks_run_through_the_playoffs_with_the_predictions_page_s_keys():
    assert schedule.week_key(4, 2) == 4 and schedule.week_key(1, 3) == 19
    assert schedule.week_key(5, 3) == 23
    assert [schedule.week_label(k) for k in (1, 18, 19, 20, 21, 23)] == [
        "Week 1", "Week 18", "Wild Card", "Divisional", "Conference", "Super Bowl"]


def test_records_are_the_ones_going_into_each_game():
    frame = _season()
    got = schedule._records(frame)
    assert got["1"] == ("0-0", "0-0")
    # Week 4: the Bears beat the Lions, the Jets beat the Bills, and the Rams
    # and Seahawks tied.
    assert got["4"] == ("1-0", "1-0")
    frame = pd.concat([frame, pd.DataFrame([_game(8, 5, "2026-10-11T17:00Z", "Rams", "Seahawks")])],
                      ignore_index=True)
    assert schedule._records(frame)["8"] == ("0-0-1", "0-0-1")


def test_a_final_is_graded_on_the_pick_on_record():
    html = schedule.body(NOW, _season(), RECORD)
    cards = _cards(html)
    bears = cards["1"]
    assert "<b>Bears by 6.0</b> &middot; 70%" in bears
    assert "Bears -2.5 &middot; O/U 44.5" in bears
    # Right winner, and the lean (Bears -2.5) covered by half a point.
    assert re.search(r"ns-mk ok' data-mk='win'>&#10003;", bears)
    assert "<b>Bears -2.5</b>" in bears and re.search(r"ns-mk ok' data-mk='ats'", bears)
    assert re.search(r"<span class='ns-pts'>24</span>", bears)
    # Wrong winner, and no lean to grade against the spread.
    bills = cards["2"]
    assert re.search(r"ns-mk no' data-mk='win'>&#10007;", bills)
    assert "data-mk='ats'" not in bills and "Lean" not in bills
    # A game before the archive: its score, and no borrowed prediction.
    assert "No pick on record" in cards["3"] and "Book" not in cards["3"]


def test_the_week_line_adds_up_the_ticks():
    html = schedule.body(NOW, _season(), RECORD)
    week3 = html[html.index('id="wk-view-3"'):html.index('id="wk-view-4"')]
    assert "Picked <b>1 of 2</b> winners &middot; leans <b>1-0</b> against the spread" in week3


def test_a_game_to_come_shows_today_s_numbers_for_the_live_script_to_grade():
    html = schedule.body(NOW, _season(), RECORD)
    bears = _cards(html)["4"]
    assert "<b>Bears by 9.7</b> &middot; 77%" in bears and "Bears -3.5" in bears
    assert "<b>Jets +3.5</b>" not in bears and "<b>Bears -3.5</b>" in bears   # lean 6.2 on the Bears
    assert "data-pm='9.70'" in bears and "data-sp='-3.5'" in bears and "data-lean='home'" in bears
    assert "data-ko='2026-10-04T17:00:00Z'" in bears and "data-tk='1'" in bears
    assert "<span class='ns-when' data-lt='1'>1:00 PM ET</span>" in bears
    assert "<span class='ns-mk' data-mk='win'></span>" in bears       # filled at the final
    london = _cards(html)["5"]
    assert "<span class='ns-at'>London</span>" in london and "NFL Net" in london
    assert "Colts by 2.3" in london and "Colts -3.5" in london
    tbd = _cards(html)["6"]
    assert "Time TBD" in tbd and "data-tk='0'" in tbd


def test_a_playoff_game_without_its_teams_has_no_logo_and_no_pick():
    card = _cards(schedule.body(NOW, _season(), RECORD))["7"]
    assert "<img" not in card and "ns-calls" not in card and "data-pm" not in card


def test_the_switcher_opens_on_the_week_being_played_and_names_the_rounds():
    html = schedule.body(NOW, _season(), RECORD)
    assert 'class="wk-btn active" onclick="show_wk(\'4\')"' in html
    assert 'id="wk-tab-19">Wild Card</button>' in html
    assert re.search(r'id="wk-view-3" class="wk-view" style=\'display:none\'', html)
    assert "<h3 class='ns-day'>Sunday, Oct 4</h3>" in html
    assert "data-st='3' data-wk='1'" in html                # the live query's week


def test_byes_are_listed_in_the_regular_season_only():
    html = schedule.body(NOW, _season(), RECORD)
    week4 = html[html.index('id="wk-view-4"'):html.index('id="wk-view-19"')]
    assert "<b>Bye</b> Rams, Seahawks" in week4
    assert "Bye" not in html[html.index('id="wk-view-19"'):]


def test_the_live_script_reads_espn_on_a_minute_and_stops_when_hidden():
    js = schedule._JS
    assert "site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard" in js
    assert "'&seasontype='" in js and "'&week='" in js
    # The clock is on the competition's status, not its type.
    assert "c.status||ev.status" in js and "s.displayClock" in js
    assert "setTimeout(poll,60e3)" in js
    assert "visibilitychange" in js and "document.hidden" in js


def test_lines_read_the_way_a_book_writes_them():
    assert schedule._num(3.0) == "3" and schedule._num(3.5) == "3.5"
    assert schedule._signed(-3.0) == "-3" and schedule._signed(7.5) == "+7.5"
    assert schedule._signed(0) == "pk"


@pytest.mark.parametrize("spread,shown", [(0.0, "Pick'em"), (6.5, "Jets -6.5")])
def test_the_book_row_names_its_favourite(spread, shown):
    frame = pd.DataFrame([_game(9, 4, "2026-10-04T17:00Z", "Bills", "Jets", spread=spread)])
    assert shown in schedule.body(NOW, frame, _record([]))
