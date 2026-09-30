"""
The 2026-09-29 phone audit of the college basketball pages, at 390px wide.

/cbb/power/ spent its four visible columns on a Move column of dots and a
T-Rank column that repeated the row number, behind ~160 words of intro; /men/
showed five filter chips and an empty "Past Games" fold with no games to
filter; the homepage said "tips off November 1" under a clock reading
"Monday, November 2", above a WNBA card for a season that was over.
"""
import re
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from conftest import DOCS

TEAMS = ["Duke", "Arizona", "Florida", "Houston"]


@pytest.fixture
def power(tmp_path, monkeypatch):
    """render_power.body() on four teams, no network, an archive in tmp."""
    from cbb.render import render_power as rp

    csv = tmp_path / "trank.csv"
    csv.write_text("x")                      # only its mtime is read, for the stamp
    frame = pd.DataFrame({
        "rank": [1, 2, 3, 4], "team": TEAMS, "conf": ["ACC", "B12", "SEC", "B12"],
        "record": ["0-0"] * 4, "adjoe": [120.0, 118.0, 117.0, 116.0],
        "adjde": [91.0, 92.0, 93.0, 94.0], "barthag": [.96, .95, .94, .93],
        "proj. W": [26, 23, 23, 22], "Proj. L": [6, 7, 7, 8]})
    monkeypatch.setattr(rp, "trank", lambda refresh=False: frame.copy())
    monkeypatch.setattr(rp, "bpi", lambda refresh=False: (None, None))
    monkeypatch.setattr(rp, "ap_poll", lambda refresh=False: (None, None))
    monkeypatch.setattr(rp, "_cache_path", lambda: csv)
    monkeypatch.setattr(rp, "HISTORY_DIR", tmp_path / "history")
    (tmp_path / "history").mkdir()
    return rp


def _snap(rp, ago: timedelta, order):
    at = datetime.now() - ago
    pd.DataFrame({"key": order, "rank": range(1, len(order) + 1)}).to_csv(
        rp.HISTORY_DIR / f"{at:%Y%m%d-%H%M%S}.csv", index=False)


def _heads(html: str) -> list:
    return re.findall(r"<th(?:\s[^>]*)?>(.*?)</th>", html.split("</thead>")[0])


def test_a_move_column_of_dots_is_left_off_and_comes_back_with_a_mover(power):
    _snap(power, timedelta(days=9), TEAMS)
    _snap(power, timedelta(hours=20), TEAMS)
    heads = _heads(power.body())
    assert "Move" not in heads and not any(h.endswith("d") and h[:-1].isdigit() for h in heads), \
        "nobody moved - a column of dots is a phone column wasted"

    _snap(power, timedelta(hours=13), ["Arizona", "Duke", "Florida", "Houston"])
    heads = _heads(power.body())
    assert "Move" in heads, "Duke and Arizona swapped since the last build"
    assert "9d" not in heads, "the week-old archive saw no change"


def test_the_week_column_says_how_far_back_it_really_goes(power):
    _snap(power, timedelta(days=29, hours=1), ["Florida", "Arizona", "Duke", "Houston"])
    _snap(power, timedelta(hours=20), TEAMS)
    heads = _heads(power.body())
    assert "29d" in heads and "7d" not in heads, \
        "the newest snapshot a week old was a month old - '7d' misread it"


def test_t_rank_is_not_a_second_row_number(power, monkeypatch):
    html = power.body()
    heads = _heads(html)
    assert "T-Rank" not in heads, "ordered on T-Rank alone, it repeats the rank beside the team"
    assert heads[:2] == ["Team", "Proj W-L"], "what a phone shows first, beside the frozen team"

    # With this season's BPI the order is the average, and T-Rank says something again.
    bpi = {"duke": 3, "arizona": 1, "florida": 2, "houston": 4}
    monkeypatch.setattr(power, "bpi", lambda refresh=False: (
        {k: {"espn_id": str(i), "bpi_rank": r} for i, (k, r) in enumerate(bpi.items())}, 2027))
    heads = _heads(power.body())
    assert "T-Rank" in heads and heads.index("BPI") == heads.index("T-Rank") + 1


def test_last_seasons_bpi_goes_to_the_far_end(power, monkeypatch):
    monkeypatch.setattr(power, "bpi", lambda refresh=False: (
        {"duke": {"espn_id": "1", "bpi_rank": 5}}, 2026))
    heads = _heads(power.body())
    assert heads[-1] == "BPI '25-26", heads


def test_one_line_above_the_table_and_the_rest_folded(power):
    html = power.body()
    before = html[:html.index("<table")]
    lede = re.search(r"<p class='power-lede'>(.*?)</p>", before).group(1)
    assert len(re.sub(r"<[^>]+>", "", lede).split()) <= 16, lede
    folded = before[before.index("<details"):before.index("</details>")]
    assert "Barthag" in folded and "AdjOE" in folded, "the glossary lives in the fold"
    outside = re.sub(r"<details.*?</details>|<style>.*?</style>", "", before, flags=re.S)
    assert len(re.sub(r"<[^>]+>", " ", outside).split()) < 40, "the intro crept back"


def test_rank_numbers_are_at_least_12px(power):
    size = re.search(r"table\.cbb-power \.row-rank\{font-size:(\d+)px", power._CSS)
    assert size and int(size.group(1)) >= 12


def test_the_words_give_the_clocks_date_and_the_switch_stays_the_first_game(monkeypatch):
    from cbb.render import render_home as rh

    assert rh.CBB_TIPOFF == date(2026, 11, 1), "it switches the live tick on for the Rome game"
    clock = rh._countdown_targets()["cbb"].date()
    line = rh._season_status(date(2026, 10, 1), "-")
    assert f"{clock:%B %-d}" in line, line
    assert "days away" not in line, "the clock right above counts the days"

    # No clock, or last season's: the switch date rather than nothing.
    monkeypatch.setattr(rh, "_countdown_targets", lambda: {})
    assert rh._tipoff_shown() == rh.CBB_TIPOFF
    monkeypatch.setattr(rh, "_countdown_targets", lambda: {"cbb": datetime(2025, 11, 3)})
    assert rh._tipoff_shown() == rh.CBB_TIPOFF


def test_the_homepage_has_no_wnba_card(tmp_path, monkeypatch):
    from cbb import paths
    from cbb.render import render_home as rh

    monkeypatch.setattr(paths, "WEB_HOME", tmp_path / "index.html")
    monkeypatch.setattr(rh, "_my_teams", lambda today: "")
    rh.render_home()
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "WNBA" not in html and 'href="/wnba/' not in html
    assert "Fantasy Football" in html and "<h2>CFB</h2>" in html


def test_the_scoreboard_has_an_empty_state_ahead_of_its_controls():
    js = (DOCS / "assets" / "js" / "live.js").read_text(encoding="utf-8")
    poll = js[js.index("async function pollScores"):js.index("function etToday")]
    assert poll.index("hasCurrentGames(games)") < poll.index("renderGames("), \
        "the empty check has to come before the board is drawn"
    assert "renderNoGames()" in poll and "showControls(true)" in poll
    assert re.search(r"const STALE_DAYS = [2-9]\b", js), \
        "before 11 ET the Worker still holds last night's games - one day is too few"
    assert ".meta-bar" in js, "the chips, Expand All and the polling rate go with no games"


def test_the_account_buttons_fit_the_brand_row():
    """At 44px (the thumb rule) Sign in and Profile hung over the section
    links below them on every page (2026-09-29); they are sized with the rest
    of the account control, as tall as the brand row allows."""
    import re
    from conftest import ROOT
    css = (ROOT / "docs" / "assets" / "css" / "custom.css").read_text()
    thumb = css[css.index("Thumb-sized targets for every control"):]
    thumb = thumb[:thumb.index("min-height: 44px")]
    assert "a.acct-link" not in thumb
    phone = css[css.index("Pinning it to the corner"):]
    assert re.search(r"a\.acct-link \{[^}]*min-height: 34px", phone)


def test_cbb_tables_do_not_frame_their_logos():
    """The theme's img padding and margins made each CBB table row 61px for a
    22px logo."""
    from conftest import ROOT
    css = (ROOT / "docs" / "assets" / "css" / "custom.css").read_text()
    rule = css[css.index("img.team-logo {"):]
    rule = rule[:rule.index("}")]
    assert "padding: 0" in rule and "margin-top: 0" in rule


def test_the_cbb_home_top_ten_is_the_power_pages_order(monkeypatch):
    import pandas as pd
    from cbb.render import render_home, render_power
    rows = pd.DataFrame({"rk": [1, 2], "team": ["Duke", "A&M <b>"], "conf": ["ACC", "SEC"],
                         "pw": [25.8, 22.4], "pl": [6.2, 8.6]})
    monkeypatch.setattr(render_power, "top", lambda n=10: rows)
    html = render_home._top_ten()
    assert html.index("Duke") < html.index("A&amp;M &lt;b&gt;")
    assert "26&ndash;6" in html and "22&ndash;9" in html
