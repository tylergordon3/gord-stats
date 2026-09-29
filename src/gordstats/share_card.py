"""
A page's own link-preview card: the picture a text or a group chat shows under
a link, drawn from what the page says right now.

Every page used to preview as the one site card (assets/images/brand/share.png,
the wordmark and four sports), so a recap texted to the league looked exactly
like a link to the home page. These are 1200x630 PNGs in the same style - the
site's navy and orange, DejaVu from matplotlib's own fonts so the Pi needs
nothing installed - carrying the week's scores, the matchups or the rankings.

    card = share_card.games("nfl-recap", "NFL FANTASY", "Week 4 Recap",
                            "Zelk Team Fantasy Football",
                            [("Team A", 142.3, 98.1, "Team B"), ...])
    add_front_matter(html, title, image=card)       # front matter's `image`

The file name carries a hash of what is drawn (share/<slug>-<hash>.png), so a
chat app that has cached last week's card is handed a new address when the
card changes, and the older cards for that slug are deleted as a new one is
written. They are generated like the rest of the site and not committed.
"""
import functools
import hashlib
import os
import unicodedata
from pathlib import Path

import matplotlib
from PIL import Image, ImageDraw, ImageFont

from gordstats import paths as site_paths

W, H = 1200, 630
PAD = 64
NAVY, ORANGE, RULE = "#1b2340", "#ee8434", "#3a466c"
WHITE, MUTED, DIM = "#ffffff", "#aab7c9", "#7f8ea3"
GREEN = "#5fd08f"

OUT_DIR = site_paths.DOCS / "assets" / "images" / "share"
URL_DIR = "/assets/images/share"

_FONTS = Path(os.path.dirname(matplotlib.__file__)) / "mpl-data" / "fonts" / "ttf"
_cache = {}


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    key = (size, bold)
    if key not in _cache:
        _cache[key] = ImageFont.truetype(
            str(_FONTS / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")), size)
    return _cache[key]


def clean(text) -> str:
    """Text DejaVu can draw: emoji and other pictographs (team names are full
    of them) would be empty boxes, so they go, and the spaces they leave
    close up."""
    out = "".join(c for c in str(text or "")
                  if unicodedata.category(c) not in ("So", "Cs", "Co", "Cn", "Sk")
                  and c not in "‍️")
    return " ".join(out.split())


def fit(draw: ImageDraw.ImageDraw, text: str, fnt, width: float) -> str:
    """`text`, cut with an ellipsis to fit `width` pixels."""
    text = clean(text)
    if draw.textlength(text, font=fnt) <= width:
        return text
    while text and draw.textlength(text + "…", font=fnt) > width:
        text = text[:-1]
    return text.rstrip() + "…"


def num(v) -> str:
    if v is None:
        return "—"
    return f"{float(v):.1f}"


def _frame(kicker: str, title: str, sub: str = "") -> tuple:
    """The card without its rows: the wordmark, kicker, title and footer.
    Returns (image, draw, y where the rows start)."""
    im = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(im)
    # The wordmark, as the site header draws it: GORD | STATS.
    f = font(30, True)
    d.text((PAD, 40), "GORD", font=f, fill=WHITE)
    x = PAD + d.textlength("GORD", font=f) + 12
    d.rectangle([x, 44, x + 4, 72], fill=ORANGE)
    d.text((x + 16, 40), "STATS", font=f, fill=WHITE)
    if kicker:
        fk = font(24, True)
        k = fit(d, kicker.upper(), fk, W - 2 * PAD - 320)
        d.text((W - PAD - d.textlength(k, font=fk), 44), k, font=fk, fill=ORANGE)
    d.rectangle([PAD, 96, W - PAD, 99], fill=RULE)
    y = 116
    ft = font(54, True)
    d.text((PAD, y), fit(d, title, ft, W - 2 * PAD), font=ft, fill=WHITE)
    y += 70
    if sub:
        fs = font(26)
        d.text((PAD, y), fit(d, sub, fs, W - 2 * PAD), font=fs, fill=MUTED)
        y += 40
    fo = font(24, True)
    d.text((PAD, H - 52), "gordstats.com", font=fo, fill=ORANGE)
    return im, d, y + 14


def _rows(rows: list, y: int) -> tuple:
    """(rows that fit, font size, row height): as large as five rows allow -
    a chat shows the card at about a quarter of its size - and six a little
    smaller, for a twelve-team league's week."""
    size, step = (34, 60) if len(rows) <= 5 else (30, 50)
    return rows[:max(1, (H - 80 - y) // step)], size, step


def _save(im: Image.Image, slug: str, alt: str) -> dict:
    """Write under a name that changes with the picture, drop the slug's older
    cards, and return front matter's `image`."""
    buf = im.quantize(colors=64, method=Image.Quantize.MEDIANCUT)
    digest = hashlib.sha1(im.tobytes()).hexdigest()[:10]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{slug}-{digest}.png"
    path = OUT_DIR / name
    if not path.exists():
        buf.save(path, optimize=True)
    for old in OUT_DIR.glob(f"{slug}-*.png"):
        if old.name != name and old.stem[len(slug) + 1:].isalnum() \
                and len(old.stem) == len(slug) + 11:
            old.unlink()
    return {"path": f"{URL_DIR}/{name}", "width": W, "height": H, "alt": clean(alt)}


def _safe(fn):
    """A card is a nicety: if drawing one fails, the page is built without it
    (the site's own card stands in) rather than not at all."""
    @functools.wraps(fn)
    def run(*a, **k):
        try:
            return fn(*a, **k)
        except Exception as exc:                            # noqa: BLE001
            print(f"  ! share card {a[0] if a else ''}: {type(exc).__name__}: {exc}")
            return None
    return run


@_safe
def games(slug: str, kicker: str, title: str, sub: str, rows: list,
          alt: str = "", final: bool = True) -> dict:
    """Head-to-head games, one a row: (name a, points a, points b, name b).
    With `final`, the winner is put first, bright, and the loser dimmed;
    without, both stay bright (projections, or a game still being played)."""
    im, d, y = _frame(kicker, title, sub)
    rows, size, step = _rows(rows, y)
    fn = fv = font(size, True)
    mid = W // 2
    for a, pa, pb, b in rows:
        if final and pa is not None and pb is not None and pb > pa:
            a, pa, pb, b = b, pb, pa, a            # the winner reads first
        wa = final and pa is not None and pb is not None and pa > pb
        wb = final and pa is not None and pb is not None and pb > pa
        ca = WHITE if (wa or not final) else DIM
        cb = WHITE if (wb or not final) else DIM
        sa, sb = num(pa), num(pb)
        d.text((mid - 30 - d.textlength(sa, font=fv), y), sa, font=fv,
               fill=GREEN if wa else ca)
        d.text((mid - 8, y), "–", font=fv, fill=DIM)
        d.text((mid + 30, y), sb, font=fv, fill=GREEN if wb else cb)
        room = mid - 30 - d.textlength("000.0", font=fv) - PAD - 18
        d.text((PAD, y), fit(d, a, fn, room), font=fn, fill=ca)
        nb = fit(d, b, fn, room)
        d.text((W - PAD - d.textlength(nb, font=fn), y), nb, font=fn, fill=cb)
        y += step
    return _save(im, slug, alt or f"{title}: {sub}")


@_safe
def ranked(slug: str, kicker: str, title: str, sub: str, rows: list,
           alt: str = "") -> dict:
    """A ranked list, one a row: (rank or label, name, value)."""
    im, d, y = _frame(kicker, title, sub)
    rows, size, step = _rows(rows, y)
    fr, fn, fv = font(size, True), font(size, True), font(size)
    for rank, name, value in rows:
        d.text((PAD, y), clean(rank), font=fr, fill=ORANGE)
        v = clean(value)
        vw = d.textlength(v, font=fv)
        d.text((W - PAD - vw, y), v, font=fv, fill=MUTED)
        d.text((PAD + 70, y), fit(d, name, fn, W - 2 * PAD - 70 - vw - 24), font=fn, fill=WHITE)
        y += step
    return _save(im, slug, alt or f"{title}: {sub}")


@_safe
def matchups(slug: str, kicker: str, week: int, pairs: list, started: bool,
             final: bool, league: str = "", asof: str = "") -> dict | None:
    """The week on a matchups page, as it stands: GordStats' projections
    before kickoff, the live score while it is played, the result once it is
    over. `pairs`: (name a, points a, projection a, name b, points b,
    projection b).

    Live only once somebody has scored: Yahoo takes a week off "preevent" at
    the start of its window, days before a kickoff, and "Week 5: Live" over
    ten 0.0s is the preview that produced."""
    started = started and any((p[1] or 0) > 0 or (p[4] or 0) > 0 for p in pairs)
    if final:
        rows = [(a, pa, pb, b) for a, pa, _ga, b, pb, _gb in pairs]
        return games(slug, kicker, f"Week {week}: Final", league, rows,
                     alt=f"Week {week} final scores, {league}")
    if started:
        rows = [(a, pa or 0.0, pb or 0.0, b) for a, pa, _ga, b, pb, _gb in pairs]
        return games(slug, kicker, f"Week {week}: Live",
                     f"Points as of {asof}" if asof else league, rows, final=False,
                     alt=f"Week {week} live scores, {league}")
    rows = [(a, ga, gb, b) for a, _pa, ga, b, _pb, gb in pairs]
    return games(slug, kicker, f"Week {week} Matchups", "GordStats projections", rows,
                 final=False, alt=f"Week {week} matchups and projections, {league}")


def matchups_line(week: int, pairs: list, started: bool, final: bool) -> str:
    """What a Share of a matchups page says: the same three states as its
    card (matchups(), above) - projections, live once somebody has scored,
    or final."""
    live = started and any((p[1] or 0) > 0 or (p[4] or 0) > 0 for p in pairs)
    if final:
        return f"Week {week} final scores"
    if live:
        return f"Week {week}, live"
    return f"Week {week} matchups, with GordStats projections"
