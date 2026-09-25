"""
Draft review (docs/fantasy/draft-review/) for whichever league the reader has
picked - rendered in the browser from Sleeper. See gordstats.my_draft.

The built league's own draft analytics live at /fantasy/draft/ and are
unchanged; those have this site's ADP behind them, which a stranger's league
does not.

    python -m fantasy.site.draft_review
"""
from fantasy import paths
from fantasy.site import layout
from gordstats import my_draft, my_league, my_league_data
from gordstats.frontmatter import add_front_matter


def body() -> str:
    return (my_league.bar()
            + my_draft.section()
            + my_league_data.JS + my_league.JS + my_draft.JS)


def generate():
    out = paths.WEB_DRAFT_REVIEW_OWN
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(add_front_matter(layout.HEAD + body(), "Draft Review",
                                    "Your league's drafts, and what each pick returned"),
                   encoding="utf-8")
    print(f"Wrote Draft Review -> {out}")


if __name__ == "__main__":
    generate()
