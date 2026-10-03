"""
Waivers and trades (docs/fantasy/waivers/) for whichever league the reader has
picked - rendered in the browser from Sleeper, because it is their league
rather than this one. See gordstats.my_waivers.

The built league's own log lives at /fantasy/transactions/ and is unchanged.

    python -m fantasy.site.waivers
"""
from fantasy import paths
from fantasy.site import layout
from gordstats import my_league, my_league_data, my_waivers
from gordstats.frontmatter import add_front_matter


def body() -> str:
    return (my_league.bar()
            + my_waivers.section()
            + my_league_data.JS_TAG + my_league.JS_TAG + my_waivers.JS_TAG)


def generate():
    out = paths.WEB_WAIVERS
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(add_front_matter(layout.HEAD + body(), "Your League's Waivers & Trades",
                                    "Every claim, add and trade in your league",
                                    description="Every waiver claim, free-agent add, drop and trade "
                                    "in your own Sleeper fantasy league, season by season, with "
                                    "FAAB bids and the claims that lost out."),
                   encoding="utf-8")
    print(f"Wrote Waivers & Trades -> {out}")


if __name__ == "__main__":
    generate()
