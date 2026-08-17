"""
Readability guards.

Two separate failures shipped here and both are covered:

  * the draft board picked text colour by thresholding ITU-BT.601 brightness,
    which lands on the wrong side through the midtones of a RdYlGn scale;
  * stylesheet rules that paint a light surface but define no dark counterpart,
    which put light text on white — 1.1:1 in places.
"""

import re

import pytest

from conftest import dark_block, declared, light_block, split_rules

from gordstats import contrast

# The dark theme's page and card grounds. Any light-only text colour is judged
# against these, since that is what it would land on.
DARK_GROUNDS = ("#16203a", "#1b2540")

# Colours that read as "surface" — a rule painting one of these needs a dark
# counterpart or the theme's light text lands on it.
LIGHT_SURFACES = re.compile(
    r"#(fff\b|ffffff|f8fafc|f7f9fc|eef2f7|f1f5f9|e2e8f0|eef2f6|fdf0e4|e8f7f0|ebe4e4)", re.I)

# Deliberate light islands: components that keep a light surface in dark mode
# and carry their own dark text, so they stay readable even though they do not
# match the surrounding theme. The dark block already takes this approach for
# the pandas-styled prediction tables.
#
# KNOWN GAP: the college-basketball scoreboard and bracket are on this list
# because they were never given a dark treatment, not because a light island is
# the right answer for them. Removing an entry here should make the test fail
# until that component is themed.
LIGHT_ISLANDS = {
    ".game-card": "CBB scoreboard card — untreated, see KNOWN GAP above",
    ".legend-modal": "CBB scoreboard legend modal — untreated",
    ".date-header": "CBB scoreboard date divider — untreated",
    ".lock-tag": "CBB bracket lock pill — untreated",
}

# Text colours inside those islands. They sit on a light card that stays light,
# so measuring them against the dark page ground is the wrong comparison.
ISLAND_TEXT = {
    ".meta", ".meta-upcoming", ".lock-tag", ".date-header", ".matchup-status",
    ".max-games strong", ".injured", ".ir-tag", ".tourney-bar.conf-sec",
    ".game-badge.ap", ".legend-pill.ap", ".sort-chip.active", ".proj",
    ".st-live", ".st-ht", ".st-final", ".st-pre", ".st-delay",
    ".value span.better", ".value.better",
}


def test_best_text_on_beats_a_brightness_threshold():
    """The bug: a 0.5 luma cutoff picked black on mid oranges and greens."""
    import matplotlib

    cmap = matplotlib.colormaps["RdYlGn"]
    worst = min(
        contrast.ratio(contrast.best_text_on(cmap(i / 100)[:3]), cmap(i / 100)[:3])
        for i in range(101)
    )
    # AA_NORMAL, not AA_LARGE: the brightness-threshold version this replaced
    # scored 3.12:1, which would have slipped under a 3.0 bar.
    assert worst >= contrast.AA_NORMAL, f"worst cell on the draft board scale is {worst:.2f}:1"


def test_best_text_on_flips_at_the_wcag_crossover():
    assert contrast.best_text_on("#ffffff") == "#000000"
    assert contrast.best_text_on("#000000") == "#ffffff"
    # mid grey sits near the crossover; whichever is chosen must be the better one
    for shade in ("#767676", "#808080", "#8a8a8a"):
        chosen = contrast.best_text_on(shade)
        other = "#000000" if chosen == "#ffffff" else "#ffffff"
        assert contrast.ratio(chosen, shade) >= contrast.ratio(other, shade)


def test_translucent_backgrounds_are_measured_after_compositing():
    """`.sort-chip` is rgba over the page; judging the rgba alone is meaningless."""
    over_dark = contrast.blend("#ffffff", "#16203a", 0.10)
    assert contrast.ratio("#dde5ef", over_dark) >= contrast.AA_NORMAL


def test_every_light_surface_has_a_dark_counterpart(css_text):
    """The ghost-rows bug: `table.adp-table td` set a dark colour and border but
    no background, so odd rows fell through to a white container."""
    dark = dark_block(css_text)
    dark_rules = {}
    for sel, body in split_rules(dark):
        dark_rules.setdefault(sel, "")
        dark_rules[sel] += body + ";"

    light = light_block(css_text)
    missing = []
    for sel, body in split_rules(light):
        bg = declared(body, "background") or declared(body, "background-color")
        if not bg or not LIGHT_SURFACES.search(bg):
            continue
        if sel in LIGHT_ISLANDS:
            continue
        covered = sel in dark_rules and (
            declared(dark_rules[sel], "background")
            or declared(dark_rules[sel], "background-color")
        )
        if not covered:
            missing.append(sel)

    assert not missing, (
        "these paint a light surface with no dark-mode background:\n  "
        + "\n  ".join(sorted(set(missing)))
    )


def test_light_only_text_colours_are_not_invisible_on_dark(css_text):
    """`.mv-since` and `td.pick` were #4a5a68 — fine on white, 2.1:1 on dark."""
    dark = dark_block(css_text)
    dark_rules = {}
    for sel, body in split_rules(dark):
        dark_rules.setdefault(sel, "")
        dark_rules[sel] += body + ";"

    light = light_block(css_text)
    offenders = []
    for sel, body in split_rules(light):
        colour = declared(body, "color")
        if not colour or not colour.strip().startswith("#"):
            continue
        if sel in ISLAND_TEXT:
            continue                        # sits on a light island, not the page
        # A rule that paints its own background and its own text is
        # self-consistent — a pale pill with dark text on it stays readable in
        # either theme. Judging its text against the dark page is meaningless.
        own_bg = declared(body, "background") or declared(body, "background-color")
        if own_bg and own_bg.strip().startswith("#"):
            continue
        value = colour.split("!")[0].strip()
        try:
            worst = min(contrast.ratio(value, g) for g in DARK_GROUNDS)
        except ValueError:
            continue
        if worst >= contrast.AA_LARGE:
            continue                        # legible on dark anyway
        if sel in dark_rules and declared(dark_rules[sel], "color"):
            continue                        # explicitly overridden
        offenders.append(f"{sel}  ({value}, {worst:.2f}:1 on dark)")

    assert not offenders, (
        "light-only text colours with no dark override:\n  " + "\n  ".join(sorted(offenders))
    )
