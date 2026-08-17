"""
The draft page: recap, report and DNA as linked sections of one page.

These were three separate pages that all answered questions about the same
event, so reading them meant hopping between URLs and losing your place. They
are now three collapsible sections under one "Jump to" bar, each still owning
its own switchers and anchors.

    python -m fantasy.site.draft_center

The old URLs 301 to this page — see docs/_redirects.
"""

from fantasy import paths
from fantasy.site import draft_dna, draft_recap, draft_report, layout
from gordstats.frontmatter import add_front_matter

# (anchor, summary shown on the closed section, jump-bar label)
SECTIONS = [
    ("recap", "Draft Recap &mdash; the boards, pick by pick", "Recap"),
    ("report", "Manager Draft Report &mdash; how well each manager drafted", "Report"),
    ("dna", "Draft DNA &mdash; how each manager drafts", "DNA"),
]

INTRO = (
    "<p>Everything about the draft in one place: the boards as they happened, "
    "how well each manager did against where players actually finished, and the "
    "habits that show up across drafts. Open a section to read it &mdash; each "
    "keeps its own season and round controls.</p>"
)


def body() -> str:
    """Compose the three draft sections into a single page body."""
    # DNA's intro points at the report; on this page that's a section anchor,
    # not another URL.
    content = {
        "recap": draft_recap.body(),
        "report": draft_report.body(),
        "dna": draft_dna.body(report_href="#report"),
    }

    nav = layout.section_nav([(a, label) for a, _, label in SECTIONS])
    return INTRO + nav + "".join(
        layout.details(summary, content[a], open=(i == 0), anchor=a)
        for i, (a, summary, _) in enumerate(SECTIONS)
    )


def generate():
    """Build and write the combined draft page."""
    page = add_front_matter(layout.HEAD + body(), "Fantasy Draft")
    out = paths.WEB_DRAFT
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"Wrote combined draft page -> {out}")


if __name__ == "__main__":
    generate()
