"""
Team favourites: the markup half.

A favourite is a ``(sport, team)`` pair, and the pair has to survive a rebuild —
a reader who stars Georgia today must still have Georgia starred after tomorrow
morning's refresh renders the page again. That rules out anything positional
(row index, rank) and anything the season changes (record, rating). What is
left is the identifier each section already keys its own data on, which differs
per section and is *not* worth unifying:

    cfb         ESPN team id            "333"
    cbb-men     slugified school name   "michigan-state"
    cbb-women   slugified school name   "south-carolina"
    wnba        Ball Don't Lie team id  "8"

So the key carries its section with it — ``cfb:333`` cannot collide with
``cbb-men:333`` even if both numbers exist. Sections stay free to change how
they name teams internally; only the value passed in here matters, and changing
one silently drops that section's stars rather than corrupting another's.

The reading half lives in ``docs/assets/js/favorites.js``. This module only
emits markup: a ``data-fav`` attribute on the row and a star button in the team
cell. With JavaScript off, the attribute is inert and the button is not there at
all — the page is exactly what it was before.
"""

import re
from html import escape

from gordstats import charts

# Every section allowed to carry favourites. A typo in a caller is a broken
# key that silently never matches the reader's stored list, so it raises here
# rather than rendering a star that can't be un-starred.
SPORTS = ("cfb", "nfl", "cbb-men", "cbb-women", "wnba")

# Straight and curly, plus the accent some feeds use in its place.
_APOSTROPHE = re.compile(r"['\u2019\u02bc\u0060]")

# Rows the reader has starred are highlighted, not reordered: these tables are
# ranked, and moving a row out of rank order costs the reader the one thing the
# ranking is for. The filter in `controls()` is the opt-in that hides the rest.
_STAR = (
    "<button type='button' class='fav-star' data-fav-for='{key}' "
    "aria-pressed='false' aria-label='Follow {name}' title='Follow {name}'>"
    "<span aria-hidden='true'>&#9734;</span></button>"
)


def team_key(sport: str, team_id) -> str:
    """The canonical `sport:id` a star is stored under."""
    if sport not in SPORTS:
        raise ValueError(f"unknown sport {sport!r}; expected one of {SPORTS}")
    ident = str(team_id).strip()
    if not ident:
        raise ValueError(f"empty team id for sport {sport!r}")
    return f"{sport}:{ident}"


def name_key(sport: str, name: str) -> str:
    """`team_key` for the sections that identify a team by its name.

    Apostrophes come out before slugging rather than becoming separators:
    charts.slug would turn "St. John's" into ``st-john-s`` and "St. Johns"
    into ``st-johns``, and a source that writes the name both ways across two
    seasons would give the same school two keys. Every other difference a
    source can introduce is beyond what a slug can absorb.
    """
    return team_key(sport, charts.slug(_APOSTROPHE.sub("", str(name))))


def row_attr(sport: str, team_id) -> str:
    """The `<tr>` attribute that marks a row as belonging to one team.

    Rendered with a leading space so it drops straight into an f-string tag:
    ``f"<tr{row_attr('cfb', t['id'])}>"``.
    """
    return f' data-fav="{escape(team_key(sport, team_id), quote=True)}"'


def star(sport: str, team_id, name: str) -> str:
    """The follow button for a team cell.

    Goes *beside* the team's link, never inside it — a star nested in the
    anchor is a click that navigates instead of starring.
    """
    return _STAR.format(
        key=escape(team_key(sport, team_id), quote=True),
        name=escape(str(name), quote=True),
    )


def many_attr(sport: str, team_ids) -> str:
    """`row_attr` for something that belongs to more than one team.

    A game is the reason this exists: a schedule row or a matchup card is one
    of your teams' if *either* side is starred, so the element carries both
    keys space-separated and the reader's list is matched against all of them.
    Ids that are missing or empty are dropped rather than becoming a key like
    ``cfb:nan`` that can never match anything.
    """
    keys = [team_key(sport, t) for t in team_ids
            if t is not None and str(t).strip() and str(t).strip().lower() != "nan"]
    if not keys:
        return ""
    return f' data-fav="{escape(" ".join(keys), quote=True)}"'


def name_attr(sport: str, name: str) -> str:
    """`row_attr` for the sections that identify a team by its name."""
    return f' data-fav="{escape(name_key(sport, name), quote=True)}"'


def name_star(sport: str, name: str) -> str:
    """`star` for the sections that identify a team by its name."""
    return _STAR.format(
        key=escape(name_key(sport, name), quote=True),
        name=escape(str(name), quote=True),
    )


def controls(label: str = "Only my teams") -> str:
    """The favourites bar, for a page's existing `.pin-bar`.

    Two states, and the empty one is the important one. Before anything is
    starred the bar carries a hint, because the stars in the table are quiet by
    design and a reader who is not told what they do will not find out. Once
    something is starred the hint gives way to the filter, which until then
    would be a control that can only blank the table.
    """
    return (
        "<div class='fav-controls'>"
        "<span class='fav-hint'>"
        "<span class='fav-hint-star' aria-hidden='true'>&#9734;</span> "
        "Tap a star to follow a team"
        "</span>"
        f"<button type='button' class='fav-filter' aria-pressed='false' hidden>"
        f"<span aria-hidden='true'>&#9733;</span> {escape(label)}"
        "</button>"
        "<span class='fav-count' aria-live='polite'></span>"
        "</div>"
    )
def table_css(selector: str) -> str:
    """Starred-row highlighting, scoped to one table's own <style>.

    This does not live in custom.css with the rest of the favourites styling,
    and the reason is the cascade. These tables paint their own row
    backgrounds — a zebra stripe and a Top 25 band — from rules like
    ``table.cfb-power tr.top25:nth-child(even) td``, which sit in a <style>
    inside the page body and therefore load *after* the shared stylesheet. A
    rule in custom.css would lose to them on exactly the top-of-the-table rows
    a reader is most likely to star, and the star would appear to do nothing.

    So the rules are emitted per table, at matching specificity, after the
    rules they have to beat — including the ``:nth-child(even)`` variant, which
    otherwise wins on every second row and tints half a reader's favourites and
    not the other half.

    The tint is mixed from the section's own accent, so a favourite reads as
    green in college football and orange on the college basketball pages rather
    than importing a colour from somewhere else. A flat fallback comes first
    for anything without color-mix().
    """
    light_mix = "color-mix(in srgb, var(--accent, #A34F0A) 13%, #ffffff)"
    dark_mix = "color-mix(in srgb, var(--accent-text, #F5A968) 20%, #14203a)"
    rail_light = "var(--accent, #A34F0A)"
    rail_dark = "var(--accent-text, #F5A968)"

    def block(tint_fallback, tint, rail):
        # Both the plain and the :nth-child(even) selector, because the Top 25
        # band defines both and the even one carries the higher specificity.
        #
        # `> td`, not ` td`. The CFB schedule puts whole tables inside its
        # cells - each game's season form, each game's lines - and a
        # descendant selector tinted their rows too and drew the 3px rail down
        # the left of every one of them, through the team abbreviation. A
        # starred row is the outer row; its nested tables are its contents.
        return "".join(
            f"{selector} tr.is-fav{stripe} > td{{background:{tint_fallback};"
            f"background:{tint}}}"
            f"{selector} tr.is-fav{stripe} > td:first-child{{"
            f"background:linear-gradient(to right,{rail} 0 3px,{tint_fallback} 3px);"
            f"background:linear-gradient(to right,{rail} 0 3px,{tint} 3px)}}"
            for stripe in ("", ":nth-child(even)")
        )

    return (
        "<style>"
        # The rail is drawn as part of `background` rather than a box-shadow:
        # the sticky first column on these tables already owns its box-shadow,
        # and overwriting it drops the shadow that separates the frozen column
        # from the rows scrolling under it.
        + block("#f4ece2", light_mix, rail_light)
        + "@media (prefers-color-scheme:dark){"
        + block("#33281c", dark_mix, rail_dark)
        + "}</style>"
    )
