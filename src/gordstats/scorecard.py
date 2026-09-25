"""
The record, at the top of a predictions page: four calls, each simply right or
wrong, for both the college and the NFL model.

Both pages asked the same four questions and answered them in different shapes
- the college page with rate tiles and a benchmark drawn on a bar, the NFL page
with a different four tiles and no benchmark - so this is the one renderer.
It takes a `results.summary()` dict and nothing else.

The four:

  Winners          did we name the team that won. The mark is the book's
                   favourite on the same games, which is the honest benchmark.
  Our spread       did the side we favoured beat the margin we gave it. This
                   one is calibration, not skill: an unbiased projection wins
                   it about half the time by construction, so the mark is even
                   money and the note says which way we lean. Printed without
                   that framing it reads as a coin flip next to an 87% winner
                   rate, which is the opposite of what it means.
  Spread vs book   where our number differed from the book's by three points
                   or more, did our side cover. The mark is what a bet has to
                   clear to break even at standard juice.
  Over/under       the same, for the total.

A record is shown as a fraction until it has enough games to carry a
percentage: "1 of 5" is honest about its own size, where "20%" is not.
"""

MIN_FOR_PCT = 20          # bets before a rate means anything
BREAK_EVEN = 0.524        # what -110 needs


def _cell(label: str, wins: int, games: int, sub: str, benchmark=None,
          mark_label: str = "break-even", note: str = "", target: bool = False,
          min_for_pct: int = MIN_FOR_PCT) -> str:
    """One tile. Below `min_for_pct` games the fraction is the headline and no
    bar is drawn - a meter under five games invites a conclusion it cannot
    support."""
    if not games:
        return (f"<div class='rec-cell'><div class='rec-label'>{label}</div>"
                f"<div class='rec-value rec-none'>&mdash;</div>"
                f"<div class='rec-sub'>nothing scored yet</div></div>")

    if games < min_for_pct:
        return (f"<div class='rec-cell'><div class='rec-label'>{label}</div>"
                f"<div class='rec-value rec-frac'>{wins}<span class='rec-of'>"
                f" of {games}</span></div>"
                f"<div class='rec-sub'>{sub}</div>"
                + (f"<div class='rec-note'>{note}</div>" if note else "")
                + "</div>")

    pct = wins / games
    mark = tail = ""
    if benchmark is not None:
        mark = f"<span class='t-mark' style='left:{benchmark * 100:.1f}%'></span>"
        if target:
            # A calibration figure has nothing to beat: sitting on the mark is
            # the good outcome, so "3 points clear" would read as praise for
            # being wrong.
            tail = f"{mark_label} is the target, not a bar to clear"
        else:
            gap = round((benchmark - pct) * 100)
            tail = (f"the mark is {mark_label} at {benchmark:.0%} &middot; "
                    f"{abs(gap)} point{'' if abs(gap) == 1 else 's'} "
                    + ("clear" if gap <= 0 else "under"))
    full = " &middot; ".join(x for x in (tail, note) if x)
    return (f"<div class='rec-cell'><div class='rec-label'>{label}</div>"
            f"<div class='rec-value'>{pct:.0%}</div>"
            f"<div class='rec-sub'>{wins} of {games} {sub}</div>"
            f"<div class='rec-meter'><i style='width:{pct * 100:.0f}%'></i>{mark}</div>"
            + (f"<div class='rec-note'>{full}</div>" if full else "")
            + "</div>")


def _lean(bias) -> str:
    """Which way the projections lean, in points, for the calibration tile."""
    if bias is None:
        return ""
    if abs(bias) < 0.25:
        return "we are not leaning either way"
    side = "too many" if bias > 0 else "too few"
    return f"we give favourites {abs(bias):.1f} pts {side}"


def band(stat: dict, *, min_for_pct: int = MIN_FOR_PCT,
         break_even: float = BREAK_EVEN) -> str:
    """The four tiles, from a `results.summary()` dict."""
    if not stat or not stat.get("games"):
        return ""
    book_rate = ((stat["book_correct"] / stat["book_games"])
                 if stat.get("book_games") else None)
    cells = [
        _cell("Winners called right", stat["correct"], stat["games"], "games",
              book_rate, "the book's favourite", min_for_pct=min_for_pct),
        _cell("Our projected spread", stat.get("cover_wins", 0),
              stat.get("cover_games", 0), "games the side we picked beat our number",
              0.50, "even money", target=True,
              note=_lean(stat.get("fav_bias")), min_for_pct=min_for_pct),
        _cell("Spread calls vs the book", stat["ats_wins"], stat["ats_games"],
              "bets where we differed from the book by 3+", break_even,
              min_for_pct=min_for_pct),
        _cell("Over/under vs the book", stat["ou_wins"], stat["ou_games"],
              "bets where we differed from the book by 3+", break_even,
              min_for_pct=min_for_pct),
    ]
    return "<div class='pred-record'>" + "".join(cells) + "</div>"
