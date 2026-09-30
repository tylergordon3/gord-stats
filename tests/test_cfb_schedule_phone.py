"""The CFB schedule on a phone: folded cards, one pinned row, nothing under 12px.

The 2026-09-29 phone audit (390x844) found every game card open by default at
about 410px - the lines table, the forecast, the projection sentence and the
season table all showing, two games to a screen - under a 146px pinned bar of
sort, conference, search, chips and weeks, with the data text shrunk to
10-11.5px by the phone block's own rules and team names 15px-tall targets.
"""
import re
from types import SimpleNamespace

import pandas as pd


def _game(**kw):
    g = dict(game_id="401", state="pre", detail="", neutral=False,
             home="Indiana", away="Northwestern", home_abbr="IU", away_abbr="NU",
             home_id="84", away_id="77", home_rank=5.0, away_rank=float("nan"),
             home_score=float("nan"), away_score=float("nan"),
             gs_margin=10.44, gs_wp=0.81, gs_total=47.2, gs_home=28.8, gs_away=18.4,
             dk_spread=-7.5, dk_total=49.5, ml_home=-300.0, ml_away=240.0,
             fpi_wp=0.77, last5_home=None, last5_away=None)
    g.update(kw)
    return SimpleNamespace(**g)


def _phone_blocks(css: str) -> list[str]:
    """The bodies of every `@media (max-width:700px){...}` block, braces balanced."""
    out = []
    for m in re.finditer(r"@media \(max-width:700px\)\{", css):
        depth, i = 1, m.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(css[i], 0)
            i += 1
        out.append(css[m.end():i - 1])
    return out


def test_a_folded_card_keeps_the_gordstats_and_draftkings_lines():
    from cfb.site import schedule

    got = schedule._lines_summary(_game(), None)
    assert got.startswith('<div class="ln-sum">'), got
    # Abbreviations, rounded like the table, so the line never wraps on a phone.
    assert "<b>IU -10.4</b> &middot; 81% &middot;" in got, got
    assert "O/U 47</span>" in got, got
    assert "IU -7.5 &middot; " in got and "O/U 49.5" in got, got
    assert got.index(">GS<") < got.index(">DK<")


def test_a_whole_number_spread_drops_its_point():
    from cfb.site import schedule

    got = schedule._lines_summary(_game(gs_margin=7.0, dk_spread=3.0, dk_total=None), None)
    assert "<b>IU -7</b>" in got, got
    assert "NU -3</span>" in got, got


def test_a_finished_game_marks_the_models_favourite():
    from cfb.site import schedule

    got = schedule._lines_summary(_game(state="post", home_score=20.0, away_score=24.0), False)
    assert 'class="mk miss"' in got, got


def test_a_game_with_neither_line_folds_its_lines_cell_away():
    """FPI and SP+ alone have nothing for the folded card to show, so the cell
    is marked and the fold hides it rather than printing a bare label."""
    from cfb.site import schedule

    bare = _game(gs_margin=None, gs_wp=None, gs_total=None, gs_home=None,
                 dk_spread=None, dk_total=None, ml_home=None, ml_away=None)
    assert schedule._lines_summary(bare, None) == ""
    cell = schedule._lines_cell(bare, None, None)
    assert 'class="ln d no-sum"' in cell, cell
    # Nothing at all: the old em-dash cell, marked the same way.
    cell = schedule._lines_cell(_game(**{**vars(bare), "fpi_wp": None}), None, None)
    assert "no-sum" in cell and "na" in cell, cell
    # Lines: the summary leads the cell, the full table stays behind it.
    cell = schedule._lines_cell(_game(), None, None)
    assert cell.index('class="ln-sum"') < cell.index('class="lnt"'), cell


def test_each_team_is_one_link_with_its_logo(monkeypatch):
    """The logo was a second, nameless link to the same team page, and the
    name a 15px-tall one; one link across the line is the target now."""
    from cfb.site import schedule

    monkeypatch.setattr(schedule, "_team_pages", lambda: frozenset({"indiana"}))
    row = schedule._side_row(_game(), "home", {})
    assert row.count("<a ") == 1, row
    link = row[row.index("<a "):row.index("</a>")]
    assert 'class="sc-team"' in link and "<img" in link and "Indiana" in link, link
    assert '<span class="rk">#5</span>' in link, link
    # No page (an FCS visitor): the same line, not a link.
    row = schedule._side_row(_game(), "away", {})
    assert "<a " not in row and 'class="sc-team"' in row, row


def test_only_the_week_row_is_pinned_the_filters_fold():
    from cfb.site import schedule

    html = schedule._switcher([4, 5], 5, {4: "", 5: "<p>rows</p>"},
                              controls='<div class="sc-controls"></div>')
    assert html.count('class="pin-bar') == 1, html
    pin = html[:html.index('<div id="cfb-weeks">')]
    fold = pin.index('id="sc-fold"')
    button = pin.index('id="sc-filt"')
    weeks = pin.index('class="view-switch"')
    assert fold < pin.index("sc-controls") < button < weeks, pin
    assert 'aria-controls="sc-fold"' in pin and 'aria-expanded="false"' in pin, pin
    # And the layout can still measure it: the one .pin-bar holds all of it.
    assert pin.count("<div") == pin.count("</div>"), pin


def test_the_phone_css_never_shrinks_text_below_12px():
    """The block's own comment said not to go under the desktop size, and it
    then set 10-11.5px on the lines table, the ratings, the W/L chips, the
    tags and the conference line. 12px floor; the pills 11.5px."""
    from cfb.site import schedule

    blocks = _phone_blocks(schedule._CSS)
    assert len(blocks) >= 2
    for block in blocks:
        for rule in re.finditer(r"([^{}]+)\{([^{}]*)\}", block):
            for size in re.findall(r"font-size:([\d.]+)px", rule.group(2)):
                sel = rule.group(1)
                floor = 11.5 if re.search(r"\.tag\b|\.l5\b", sel) else 12
                assert float(size) >= floor, (sel.strip(), size)


def test_what_a_folded_card_hides_comes_back_without_js():
    """No JS, no More button - so the no-script style must undo every part
    of the fold, or a reader without scripts loses those figures outright."""
    from cfb.site import schedule

    hidden = re.search(r"((?:table\.cfb-sched>tbody>tr\.g:not\(\.open\) [^,{]+,?\s*)+)"
                       r"\{display:none\}", schedule._CSS).group(1)
    parts = [p.strip().split(":not(.open) ")[1] for p in hidden.split(",") if p.strip()]
    assert {".sc-stat", ".t-wx", "td.frm", "td.ln>.c"} <= set(parts), parts
    for part in parts:
        if part == "td.ln.no-sum":
            continue
        assert f":not(.open) {part}" in schedule._NOSCRIPT, part
    assert ".ln-sum{display:none}" in schedule._NOSCRIPT


def test_the_small_print_lives_in_the_legend():
    from cfb.site import schedule

    assert "{built}" in schedule._LEGEND
    assert "Picks of the day" in schedule._LEGEND
    assert "/cfb/predictions/" in schedule._LEGEND
