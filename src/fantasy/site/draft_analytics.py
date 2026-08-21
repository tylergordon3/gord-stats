"""
Draft Analytics: everything about the draft, as sections of one page.

Four pages became this one. Recap, report and DNA were merged first because
they all answered questions about the same event; Draft vs ADP followed once
its tables were re-ranked on where players finished rather than on the market,
at which point it was asking the same question as the rest of the page. Each
section still owns its own switchers and anchors.

    python -m fantasy.site.draft_analytics

The old URLs 301 to this page — see docs/_redirects.
"""

from fantasy import paths
from fantasy.site import adp, draft_dna, draft_recap, draft_report, layout
from gordstats.frontmatter import add_front_matter

# (anchor, summary shown on the closed section, jump-bar label)
SECTIONS = [
    ("board", "Draft Board &mdash; the boards as they happened, pick by pick", "Board"),
    ("values", "Values &amp; Busts &mdash; the picks that beat their slot, and the ones that sank", "Values"),
    ("report", "Manager Draft Report &mdash; how well each manager drafted", "Report"),
    ("dna", "Draft DNA &mdash; how each manager drafts", "DNA"),
]

INTRO = (
    "<p>Everything about the draft in one place: the boards as they happened, the "
    "best and worst picks by where players actually finished, how well each "
    "manager did against their slots, and the habits that show up across drafts. "
    "Consensus ADP appears throughout as draft-day context, never as the grade. "
    "Open a section to read it &mdash; each keeps its own season and round "
    "controls.</p>"
)


def body() -> str:
    """Compose the three draft sections into a single page body."""
    # DNA's intro points at the report; on this page that's a section anchor,
    # not another URL.
    content = {
        "board": draft_recap.body(),
        "values": adp.body(),
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
    page = add_front_matter(layout.HEAD + body(), "Draft Analytics")
    out = paths.WEB_DRAFT
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"Wrote Draft Analytics -> {out}")


if __name__ == "__main__":
    generate()
