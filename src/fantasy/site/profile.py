"""
docs/profile/ - the account page: who is signed in, which leagues are synced
and which teams are followed.

Everything on it can still be done where it belongs - a league from any page
that shows one, a team from the row it appears on. This is where to see the
lot and take something off.

Written from the fantasy build because that is where the league half comes
from, but the page itself is site-wide: the followed teams are college
football and basketball, not fantasy.

    python -m fantasy.site.profile
"""
from fantasy import paths
from fantasy.site import layout
from gordstats import league_sync, profile_page
from gordstats.frontmatter import add_front_matter


def generate():
    # The names behind the starred keys, read off the stars the rest of the
    # site has already rendered.
    profile_page.write_index(paths.DOCS)

    out = paths.DOCS / "profile" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        add_front_matter(layout.HEAD + profile_page.body(league_sync.body()),
                         "Your profile",
                         "Your account, leagues and followed teams"),
        encoding="utf-8")
    print(f"Wrote profile -> {out}")


if __name__ == "__main__":
    generate()
