"""
The last of the 2026-09-29 phone audit's open items, at 390px.

  * /cfb/power/'s pinned bar was two rows - "Show:" and its two tabs, then
    "Change since:" and a sideways-scrolling row of a dozen window buttons -
    111px of bar, 139px with the favourites filter. The windows are one menu
    now, and tabs, menu and filter share a single 61px row.
  * /cfb/schedule/'s picks of the day stood between the week buttons and the
    first game: a heading and two cards, ~350px (620px on a three-leg day).
    They fold to one line that still says who, how likely, and the grade.

The reader's own power table (gordstats.my_power) is pinned in
test_my_power_page.py, beside the tests it replaced.
"""
import re
from datetime import date, datetime

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------- #
# /cfb/power/: one pinned row
# --------------------------------------------------------------------------- #

def _bases():
    at = datetime(2026, 9, 24, 11, 44)
    return {"pre4": {"label": "Before Wk 4", "at": at, "group": "time"},
            "1d": {"label": "1 day", "at": datetime(2026, 9, 28, 17, 3), "group": "time"},
            "season": {"label": "Season start", "at": datetime(2026, 8, 25, 19, 6),
                       "group": "time"},
            "w3": {"label": "Wk 3", "at": at, "group": "week", "week": 3}}


def test_the_windows_are_one_menu_opening_on_the_first():
    from cfb.site import power

    html = power._window_picker(_bases())
    assert html.count("<select") == 1 and "win-btn" not in html
    opts = [o for o in html.split("<option")[1:]]
    assert len(opts) == 4
    assert ' value="pre4" selected' in opts[0]
    assert sum(" selected" in o for o in opts) == 1
    # Read after the label "Since": "Since 1 day ago", "Since end of Wk 3".
    assert ">1 day ago</option>" in html
    assert ">Season start</option>" in html
    assert '<optgroup label="After the week">' in html
    assert html.index("<optgroup") < html.index(">End of Wk 3</option>")
    assert power._window_picker({}) == ""


def test_the_pinned_bar_is_tabs_menu_and_filter():
    from cfb.site import power

    src = open(power.__file__).read()
    assert "<div class='pin-bar pwr-pin'>\" + _switcher() + _window_picker(bases)" in src
    assert "rankmoves.window_switch(" not in src, "the button row is back"
    assert "Show:" not in power._switcher(), "the tabs say what they are"
    # The script reads the menu and fires the event the buttons used to.
    assert "document.querySelector('.win-sel')" in power._JS
    assert "new CustomEvent('winchange'" in power._JS
    assert ".win-btn" not in power._JS


def test_the_pinned_bar_never_wraps_on_a_phone():
    from cfb.site import power

    css = power._CSS
    phone = css[css.index("@media (max-width:700px){\n  /* One row on a phone"):]
    phone = phone[:phone.index("\n}\n")]
    assert ".pin-bar.pwr-pin{flex-wrap:nowrap" in phone
    assert ".win-sel{min-height:42px" in phone, "the menu is a thumb target"
    # Starred, the filter is its star and the menu drops its label - what
    # keeps four controls on the one row.
    assert ".pwr-pin .fav-filter{font-size:0;min-width:42px" in phone
    assert ".pwr-pin:has(.fav-filter:not([hidden])) .win-pick .switch-label{display:none}" in phone


# --------------------------------------------------------------------------- #
# /cfb/schedule/: the picks fold to a line
# --------------------------------------------------------------------------- #

PICKS = {
    "underdog": {"game_id": "401858245", "side": "away", "team": "Pitt",
                 "opp": "Virginia Tech", "p": 0.5771, "book_p": 0.3425, "ml": 180.0,
                 "line": 6.0, "kick": "Fri 7:00p"},
    "legs": [
        {"kind": "spread", "side": "away", "line": 6.0, "p": 0.7141, "book": 0.5,
         "text": "Pitt +6.0", "game_id": "401858245", "game": "PITT at VT · Fri 7:00p"},
        {"kind": "total", "over": False, "total": 48.5, "p": 0.5263, "book": 0.5,
         "text": "Under 48.5", "game_id": "401858476", "game": "PSU at NU · Fri 8:00p"},
    ],
}


def _slate():
    # Pitt won at Virginia Tech; the second leg's game is still to play.
    return pd.DataFrame([
        {"game_id": "401858245", "state": "post", "home_score": 20.0, "away_score": 24.0},
        {"game_id": "401858476", "state": "pre", "home_score": np.nan, "away_score": np.nan},
    ])


def test_the_picks_are_one_folded_line(monkeypatch):
    from cfb.site import schedule

    monkeypatch.setattr(schedule, "_picks_for_day", lambda df, current: (
        PICKS, date(2026, 10, 2), "Sat Sep 26, 11:10 PM"))
    html = schedule._picks(_slate(), 5)
    assert html.startswith('<details class="gs-picks-fold">'), html[:80]
    assert "<details class=\"gs-picks-fold\" open" not in html, "folded by default"
    summary = html[html.index("<summary"):html.index("</summary>")]
    # Who, how likely, graded - the whole point of the cards, in one line.
    assert "<b>Fri picks</b>" in summary
    assert "Pitt +6.0 <span class=\"gp-p\">58%</span>" in summary
    assert "&#10003;" in summary, "the underdog won and the line does not say so"
    assert "Parlay <span class=\"gp-p\">38%</span>" in summary
    assert "&#10007;" not in summary, "a leg still to play is not a miss"
    text = re.sub(r"<[^>]+>|&[a-z#0-9]+;", " ", summary)
    assert len(text.split()) <= 12, text
    # The cards and when they were locked are inside the fold, not above it.
    rest = html[html.index("</summary>"):]
    assert '<div class="gs-picks">' in rest and "Locked Sat Sep 26, 11:10 PM" in rest
    assert html.endswith("</details>")


def test_a_missed_parlay_says_so_on_the_line(monkeypatch):
    from cfb.site import schedule

    monkeypatch.setattr(schedule, "_picks_for_day", lambda df, current: (
        PICKS, date(2026, 10, 2), "Sat Sep 26, 11:10 PM"))
    slate = _slate()
    slate.loc[0, ["home_score", "away_score"]] = [35.0, 10.0]   # Pitt lost by 25
    summary = schedule._picks(slate, 5).split("</summary>")[0]
    assert summary.count("&#10007;") == 2, summary   # the dog, and the parlay


def test_the_fold_is_themed_both_ways():
    from cfb.site import schedule

    css = schedule._CSS
    light = css[:css.index("@media (prefers-color-scheme: dark)")]
    dark = css[css.index("@media (prefers-color-scheme: dark)"):]
    assert ".gs-picks-fold>summary{" in light
    assert ".gs-picks-fold>summary{background:#16203a" in dark
