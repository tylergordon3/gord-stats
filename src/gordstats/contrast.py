"""
WCAG contrast maths, in one place.

Used by the page generators to pick legible text on a coloured cell, and by the
test suite to assert the stylesheet stays readable in both themes. Both had
their own copy of this before, which is how the draft board ended up choosing
text with a naive brightness threshold while everything else used the real one.
"""

import re

AA_NORMAL = 4.5      # WCAG AA, body text
AA_LARGE = 3.0       # WCAG AA, large or bold text
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)


def parse(colour) -> tuple:
    """(r, g, b) 0-255 from '#abc', '#aabbcc', 'rgb(1,2,3)' or a 0-1 tuple."""
    if isinstance(colour, (tuple, list)):
        vals = list(colour)[:3]
        # matplotlib hands back 0-1 floats; CSS-style tuples are 0-255.
        if all(isinstance(v, float) and v <= 1.0 for v in vals):
            return tuple(round(v * 255) for v in vals)
        return tuple(int(v) for v in vals)

    text = str(colour).strip()
    if text.startswith("#"):
        h = text[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

    nums = re.findall(r"[\d.]+", text)
    if len(nums) < 3:
        raise ValueError(f"can't parse colour: {colour!r}")
    return tuple(round(float(n)) for n in nums[:3])


def relative_luminance(colour) -> float:
    """WCAG relative luminance. Not the same as perceived brightness."""
    def channel(v):
        v = v / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = parse(colour)
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def ratio(a, b) -> float:
    """Contrast ratio between two colours, 1.0 (identical) to 21.0."""
    la, lb = relative_luminance(a), relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def best_text_on(background) -> str:
    """'#ffffff' or '#000000' — whichever actually contrasts better.

    Compares both candidates rather than thresholding brightness: sRGB is not
    linear, so a single cutoff picks the wrong one through the midtones.
    """
    return "#ffffff" if ratio(WHITE, background) > ratio(BLACK, background) else "#000000"


def blend(foreground, background, alpha: float) -> tuple:
    """Composite a translucent colour over an opaque one.

    A rule like `background: rgba(17,24,39,.06)` takes on whatever is behind
    it, so its real contrast can only be measured after compositing.
    """
    f, b = parse(foreground), parse(background)
    return tuple(round(f[i] * alpha + b[i] * (1 - alpha)) for i in range(3))
