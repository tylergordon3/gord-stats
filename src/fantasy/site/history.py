"""
League history (docs/fantasy/history/): champions, season by season and
all-time head-to-head, for whichever league the reader has picked.

Rendered in the browser from Sleeper, because it is their league rather than
this one - see gordstats.my_history. The page itself is only the frame and the
league control.

    python -m fantasy.site.history
"""
from fantasy import paths
from fantasy.site import layout
from gordstats import my_history, my_league, my_league_data
from gordstats.frontmatter import add_front_matter


def body() -> str:
    return (my_league.bar()
            + my_history.section()
            + my_league_data.JS + my_league.JS + my_history.JS)


def generate():
    out = paths.WEB_HISTORY
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(add_front_matter(layout.HEAD + body(), "League History",
                                    "Champions, records and head-to-head"),
                   encoding="utf-8")
    print(f"Wrote League History -> {out}")


if __name__ == "__main__":
    generate()
