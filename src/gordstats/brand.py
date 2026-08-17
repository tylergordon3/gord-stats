"""
Generate the site's brand assets from one definition.

    python -m gordstats.brand

The icon is the GordStats mark: GORD over an orange rule over STATS, white on
navy, in a rounded square. Everything a browser or phone might ask for is
rendered from that single description rather than hand-exported per size, so
the set can't drift apart.

Kept as code rather than checked-in binaries alone because the outputs *are*
committed — this is here so they can be regenerated when the mark changes.
"""

from PIL import Image, ImageDraw, ImageFont

from gordstats.paths import ASSET_IMG_DIR, DOCS

NAVY = (27, 35, 64)          # #1B2340
ORANGE = (238, 132, 52)      # #EE8434
WHITE = (255, 255, 255)

BRAND_DIR = ASSET_IMG_DIR / "brand"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# Rendered sizes and what each is for.
ICON_SIZES = {
    32: "browser tab",
    180: "apple-touch-icon",
    192: "android home screen",
    512: "PWA / social preview",
}


def _fit(draw, text, target_w, max_size):
    """Largest font size at which `text` still fits `target_w`."""
    size = max_size
    while size > 6:
        font = ImageFont.truetype(FONT, size)
        if draw.textlength(text, font=font) <= target_w:
            return font
        size -= 1
    return ImageFont.truetype(FONT, 6)


def icon(px: int, *, bg=NAVY, fg=WHITE, radius_ratio=0.22) -> Image.Image:
    """The stacked mark at `px` square."""
    # Drawn at 4x and downsampled: PIL has no antialiased rounded rectangle,
    # and the corner is the one place jaggies would show at 32px.
    scale = 4
    s = px * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * radius_ratio), fill=bg)

    inner = s * 0.72                      # text column width
    left = (s - inner) / 2
    f = _fit(d, "STATS", inner, int(s * 0.34))

    top_y = s * 0.20
    bar_y = s * 0.465
    bot_y = s * 0.56

    for text, y in (("GORD", top_y), ("STATS", bot_y)):
        w = d.textlength(text, font=f)
        d.text((left + (inner - w) / 2, y), text, font=f, fill=fg)

    bar_h = max(2, int(s * 0.035))
    d.rectangle([left, bar_y, left + inner, bar_y + bar_h], fill=ORANGE)

    return img.resize((px, px), Image.LANCZOS)


def main() -> None:
    BRAND_DIR.mkdir(parents=True, exist_ok=True)

    for px in ICON_SIZES:
        icon(px).save(BRAND_DIR / f"icon-{px}.png")

    # Light variant for anywhere the dark square would disappear.
    icon(512, bg=WHITE, fg=NAVY).save(BRAND_DIR / "icon-512-light.png")

    # A real .ico with several sizes in it: Windows and some feed readers still
    # ask for /favicon.ico by name regardless of the <link> tags.
    icon(64).save(DOCS / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])

    for px, use in ICON_SIZES.items():
        p = BRAND_DIR / f"icon-{px}.png"
        print(f"  {p.relative_to(DOCS)}  ({use}, {p.stat().st_size // 1024}kB)")
    print(f"  favicon.ico  ({(DOCS / 'favicon.ico').stat().st_size // 1024}kB)")


if __name__ == "__main__":
    main()
