"""
What a game preview (gordstats.preview_page) says about itself in search
results and link previews - its front matter's `description` - for the three
sport adapters (cfb.site.previews, nfl.site.previews,
cbb.render.render_previews), so they word it the same way.

Before kickoff it is the matchup, the day and what the page holds. Once the
game is final it leads with the score: a college or NFL preview stays up for
the rest of the season after its game (the adapters' prune keeps finished
games), so most of the time a search lands on one, the game is over.
"""
import pandas as pd

from gordstats import preview_page


def _day(game) -> str:
    """"Sat, Sep 26": the kickoff's day in Eastern, US order."""
    if game.get("ko") is None:
        return ""
    return f"{pd.Timestamp(game['ko']).tz_convert(preview_page.ET):%a, %b %-d}"


def _final(game) -> tuple | None:
    """((winner, points), (loser, points)) for a final, else None. A tie keeps
    the away side first, as the title does."""
    if game.get("state") != "post":
        return None
    sides = []
    for side in ("away", "home"):
        team = game.get(side) or {}
        score = preview_page._v(team.get("score"))
        if score is None:
            return None
        sides.append((str(team.get("name") or ""), int(score)))
    return tuple(sorted(sides, key=lambda s: -s[1]))


def describe(game) -> str:
    """The page's one-line description: the score once final, else the pick."""
    day = _day(game)
    final = _final(game)
    if final:
        (win, w), (lose, l) = final
        when = f" ({day})" if day else ""
        return (f"{win} {w}, {lose} {l}{when}: how GordStats' pick against the line did, "
                "and how the offenses and defenses matched up.")
    when = f", {day}" if day else ""
    return (f"{preview_page.title(game)}{when}: GordStats' pick against the line, and how the "
            "offenses and defenses match up.")
