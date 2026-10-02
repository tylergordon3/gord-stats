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

from gordstats.frontmatter import liquid
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


def _write(section: str, name: str, dpi: int) -> tuple:
    """Save and close the current figure; (src, width, height) of the PNG."""
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
    src = liquid("{{ '/assets/images/charts/%s/%s' | relative_url }}" % (section, fname))
    return src, width, height


def save(section: str, name: str, alt: str = "", lazy: bool = True,
         dpi: int = 90) -> str:
    """Save the current matplotlib figure and return an <img> tag for it.

    `section` groups the files on disk (one directory per page); `name` must be
    unique within it. Closes the figure, matching the previous inline helper.
    """
    src, width, height = _write(section, name, dpi)
    attrs = ' loading="lazy" decoding="async"' if lazy else ""
    # .gs-chart (custom.css) takes off the frame the Slate theme puts on every
    # <img> - 5px of padding and a border on top of max-width:100%, which also
    # panned the page 2px sideways on a phone. The box is a scroller there:
    # squeezed to 370px an 800-990px chart set its labels at about 6px, so a
    # phone shows it wider and lets it be swiped, like the wide tables.
    return (f'<div class="gs-chart-box"><img class="gs-chart" src="{src}" alt="{alt}" '
            f'width="{width}" height="{height}"{attrs}/></div>')


# The phone drawing of a <picture> is made for the screen, so it fits the box
# rather than being swiped like a desktop chart (custom.css lets those run to
# 640px on a phone).
_PICTURE_CSS = "<style>.gs-chart-box picture img.gs-chart{max-width:100%}</style>"


def save_picture(section: str, name: str, phone, alt: str = "", lazy: bool = True,
                 dpi: int = 90, media: str = "(max-width: 600px)") -> str:
    """The current figure for a desktop and `phone()`'s for a phone, as one
    <picture>: the browser fetches only the one it shows.

    `phone` is a callable that draws the same chart laid out for a phone - a
    grid of small multiples in two columns rather than five, with bigger type.
    A wide chart only shrinks on a phone (a 980px grid of ten panels read at
    about 5px), and swiping one around is no way to compare ten panels. The
    phone file is drawn at twice the density and sized at half, so its text
    is sharp on a phone's screen.
    """
    src, width, height = _write(section, name, dpi)
    phone()
    psrc, pw, ph = _write(section, f"{name}-phone", dpi * 2)
    attrs = ' loading="lazy" decoding="async"' if lazy else ""
    return (_PICTURE_CSS + '<div class="gs-chart-box"><picture>'
            f'<source media="{media}" srcset="{psrc}" width="{round(pw / 2)}" '
            f'height="{round(ph / 2)}">'
            f'<img class="gs-chart" src="{src}" alt="{alt}" width="{width}" '
            f'height="{height}"{attrs}/></picture></div>')
