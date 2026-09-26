"""
A dark body for the site's table, on the sections that draw their own rows.

`.sticky-table` is what every built table on this site is, and in dark mode
custom.css gives its cells a light slate (#cbd5e1) with dark text. That is a
deliberate choice and a reasonable one *there*: those tables are pandas
Stylers, most of their cells carry a per-cell colour from a heatmap, and the
slate is only the handful of cells the styler left alone.

The sections rendered in the browser - a reader's league history, its drafts,
its waivers, its power ranking - have no styler. Every cell falls through to
the slate, so a whole page of them came out light on a dark screen, which is
how it was reported.

The rule cannot simply be changed in custom.css: `styles.style_win_loss` and
its neighbours set a light `background-color` per cell and rely on inheriting
that dark text, so flipping the shared colour would leave light text on a pale
green cell on several other pages. So the dark body is scoped to the wrappers
that need it, and the site's own dark table - `table.mu-roster`, `table.rd` -
is what it matches.

Inline colours still win: a reader's power table shades Power, Luck and
Playoffs per cell, setting both background and text, and those are ID-free
inline styles that outrank anything here.
"""

#: The site's dark table, as the matchup and dashboard tables define it.
_BODY = "#16203a"
_STRIPE = "#1b2540"
_HEAD = "#223052"
_EDGE = "#2b3852"
_INK = "#dde5ef"


def dark_rows(*selectors: str) -> str:
    """Dark-mode `<style>` for `.sticky-table`s inside each wrapper."""
    rules = []
    for sel in selectors:
        rules.append(
            f"{sel} table.sticky-table th{{background:{_HEAD};color:{_INK};"
            f"border-color:{_EDGE};border-bottom-color:{_EDGE}}}"
            f"{sel} table.sticky-table td{{background:{_BODY};color:{_INK};"
            f"border-color:{_EDGE};border-bottom-color:{_EDGE}}}"
            f"{sel} table.sticky-table tbody tr:nth-child(even) td{{background:{_STRIPE}}}"
            # The frozen first column sits over the rows scrolling under it, so
            # it needs a background of its own rather than the body's.
            f"{sel} table.sticky-table th:first-child,"
            f"{sel} table.sticky-table td:first-child{{background:{_STRIPE};"
            f"color:{_INK};border-right-color:{_EDGE}}}"
            f"{sel} table.sticky-table tbody tr:hover td{{background:{_HEAD}}}"
        )
    return ("<style>@media (prefers-color-scheme: dark){"
            + "".join(rules) + "}</style>")
