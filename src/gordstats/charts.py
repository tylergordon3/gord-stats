"""
Write matplotlib charts to files instead of inlining them as base64.

A page that embeds its charts as data: URIs makes the browser download every
chart before it can show any of them — including charts behind a view switcher
that the reader may never open. The draft report was 2.3MB that way, 84% of it
base64, for a page that shows one view at a time.

Writing them out instead means the browser fetches only what it displays (the
rest are lazy), the files cache across page loads, and — because an unchanged
chart produces an identical file — git stores one blob for it no matter how
many times the site is rebuilt. Inlined, any single change rewrote the whole
page blob every day.

"Identical" has a condition attached: the same machine. matplotlib stamps its
own version into every PNG (stripped below, since it was the one thing that
changed between otherwise identical builds), but font rendering still differs
between the Pi and a laptop, so a chart built here and a chart built there are
different bytes for the same picture. The Pi's own daily runs commit no chart
changes; a local rebuild rewrites every chart in the section. Don't commit the
latter - `git checkout -- docs/assets/images/charts` before committing, and let
the Pi regenerate them.
"""

import re
import matplotlib.pyplot as plt
from PIL import Image                   # matplotlib's own dependency

from gordstats.paths import ASSET_IMG_DIR

CHART_DIR = ASSET_IMG_DIR / "charts"


def slug(text: str) -> str:
    """Filename-safe token from arbitrary chart/section text."""
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", str(text).lower())).strip("-")


def clear(section: str) -> None:
    """Drop a section's charts before regenerating it.

    Without this, renaming or removing a chart leaves the old file behind
    forever — committed, uploaded, and never referenced again.
    """
    d = CHART_DIR / section
    if d.is_dir():
        for f in d.glob("*.png"):
            f.unlink()


def save(section: str, name: str, alt: str = "", lazy: bool = True,
         dpi: int = 90) -> str:
    """Save the current matplotlib figure and return an <img> tag for it.

    `section` groups the files on disk (one directory per page); `name` must be
    unique within it. Closes the figure, matching the previous inline helper.
    """
    d = CHART_DIR / section
    d.mkdir(parents=True, exist_ok=True)
    fname = f"{slug(name)}.png"
    # No Software tag: it carries the matplotlib version, which is the one
    # thing that differed between byte-identical charts across an upgrade.
    plt.savefig(d / fname, format="png", bbox_inches="tight", dpi=dpi,
                metadata={"Software": None})
    plt.close()

    # The PNG's own size, so the page reserves the chart's box before the
    # (lazy) file arrives instead of jumping when it lands; CSS scales it.
    with Image.open(d / fname) as png:
        width, height = png.size

    # relative_url keeps the path correct if the site ever moves under a
    # baseurl; generated pages carry front matter, so Jekyll resolves it.
    src = "{{ '/assets/images/charts/%s/%s' | relative_url }}" % (section, fname)
    attrs = ' loading="lazy" decoding="async"' if lazy else ""
    # .gs-chart (custom.css) takes off the frame the Slate theme puts on every
    # <img> - 5px of padding and a border on top of max-width:100%, which also
    # panned the page 2px sideways on a phone. The box is a scroller there:
    # squeezed to 370px an 800-990px chart set its labels at about 6px, so a
    # phone shows it wider and lets it be swiped, like the wide tables.
    return (f'<div class="gs-chart-box"><img class="gs-chart" src="{src}" alt="{alt}" '
            f'width="{width}" height="{height}"{attrs}/></div>')
