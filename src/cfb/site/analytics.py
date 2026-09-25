"""
Analytics (docs/cfb/analytics/): the college fantasy league's occasional pages.

The twin of fantasy.site.analytics. Both leagues' sub-navs now carry the same
four chips - League Home, Matchups, My Team, Usage - and this holds what used
to sit beside them.

    python -m cfb.site.analytics
"""
from cfb.config import WEB_DIR
from cfb.site import write_page
from gordstats import hub

CARDS = [
    ("/cfb/strength/", "&#128737;", "Matchup Strength",
     "Who each roster is about to play, and how hard a week it is - the "
     "schedule ahead rather than the one behind."),
    ("/cfb/live/", "&#128221;", "Draft Review",
     "The draft board as it happened, and what each pick has returned since."),
]


def body() -> str:
    return (hub.cards(CARDS)
            + "<p class='hub-note'>The pages read every week - matchups, your "
              "team and usage - are in the bar above.</p>")


def generate() -> None:
    write_page(WEB_DIR / "analytics" / "index.html", "CFB Fantasy Analytics",
               body(), subtitle="Matchup strength and the draft review")


if __name__ == "__main__":
    generate()
