"""
Which WNBA season the section is talking about.

The league plays inside a single calendar year — tip-off in May, the final in
October — so unlike the NFL's or college basketball's, the season *is* the
year. That makes it derivable rather than something to be typed in four files
and forgotten, which is what it was: `SEASON = 2026` appeared in
`wnba_fantasy`, `wnba_defense` and `wnba_schedule`, and twice more as a bare
literal default inside `wnba_remaining.get_avg_points` / `get_avg_minutes`.

Those two were the dangerous ones. They look a player's average up by a stat id
built from the year (`002026`), and a year with no such id does not raise — it
returns 0.0. Next May every player would have averaged nothing, the page would
have rendered, and nothing would have said so.

Out of season the answer is the season just played: from November the new year
has not started, and before May the latest real numbers are last year's.
"""
from datetime import date

#: The month the season tips off. Before it, the year's numbers do not exist yet.
FIRST_MONTH = 5


def current_season(today: date = None) -> int:
    """The season in play, or the most recent one played."""
    today = today or date.today()
    return today.year if today.month >= FIRST_MONTH else today.year - 1


#: Opening night, which is not derivable: the league moves it every year. The
#: date matters because the defence stats are filtered on it and ESPN is asked
#: for whole months, so a start a week early quietly admits the preseason.
#: Add a line each spring; a season with no line falls back to the first of the
#: month, which is a safe lower bound for the regular season and nothing worse
#: than what the page did before anyone wrote an opener down.
OPENERS = {
    2026: "2026-05-08",
}


def season_start(season: int = None) -> str:
    """The ISO date of the season's first game, or a safe lower bound."""
    season = season or current_season()
    return OPENERS.get(season, f"{season}-{FIRST_MONTH:02d}-01")
