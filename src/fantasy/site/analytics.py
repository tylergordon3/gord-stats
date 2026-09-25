"""
Analytics (docs/fantasy/analytics/): the NFL league's occasional pages.

The sub-nav used to carry all eight of this league's pages, which wrapped to
three rows on a phone and gave equal billing to the page you read every week
and the one you read after the draft. The nav now holds League Home, Matchups,
My Team and Usage; everything else is gathered here.

    python -m fantasy.site.analytics
"""
from fantasy import paths
from fantasy.site import layout
from gordstats import hub
from gordstats.frontmatter import add_front_matter

CARDS = [
    ("/fantasy/history/", "&#127942;", "League History",
     "Champions, season by season and all-time head-to-head - for your own "
     "league once you have synced one, read live from Sleeper."),
    ("/fantasy/power/", "&#9889;", "Power Rankings",
     "Every roster played through the rest of the season ten thousand times: "
     "who is actually good, rather than who has had the schedule."),
    ("/fantasy/schedule/", "&#128197;", "Schedule Stats",
     "What the fixture list has been worth - who each team would have beaten, "
     "and the record they would have had with someone else's weeks."),
    ("/fantasy/draft/", "&#128203;", "Draft Analytics",
     "The board, what each pick returned against what it cost, and the habits "
     "that show up across every draft this league has held."),
    ("/fantasy/transactions/", "&#128260;", "Waivers & Trades",
     "Every claim, free-agent add and trade in this league, and what the "
     "players involved did afterwards."),
    ("/fantasy/draft-review/", "&#128203;", "Your league's drafts",
     "Every draft your league has held, with what each pick returned against "
     "where it was taken."),
    ("/fantasy/waivers/", "&#128220;", "Your league's waivers",
     "The same for your own league: who works the wire, what they paid, and "
     "every claim, add and trade across its seasons."),
    ("/fantasy/sync/", "&#128279;", "Sync your league",
     "Attach your own Sleeper or Yahoo league to your account, so these pages "
     "can show yours rather than this one."),
]


def body() -> str:
    return (hub.cards(CARDS)
            + "<p class='hub-note'>The pages read every week - matchups, your "
              "team and usage - are in the bar above.</p>")


def generate():
    out = paths.WEB_ANALYTICS
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(add_front_matter(layout.HEAD + body(), "Fantasy Analytics",
                                    "Power, schedule, draft and transactions"),
                   encoding="utf-8")
    print(f"Wrote Fantasy Analytics -> {out}")


if __name__ == "__main__":
    generate()
