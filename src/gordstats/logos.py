"""
Team logos from ESPN's CDN, fetched at the size they are shown.

ESPN's logo files are 500px squares - about 6 KB for a simple college mark,
40 KB for an NFL one - and every page drew them at 14-56px: /cfb/power/ moved
1.6 MB for 48 logos, /nfl/ 1.7 MB. The CDN's image combiner resizes on ESPN's
edge in the same single request (`/combiner/i?img=<path>&w=&h=`), so an 80px
copy of the same file is 1-4 KB.

The URL was written out in six generators; it lives here now so the size and
the Washington fix are decided once.
"""
from html import escape

CDN = "https://a.espncdn.com"

# Sleeper (and so the fantasy pages) says WAS; ESPN's file is wsh.
_NFL_FIX = {"was": "wsh"}


def url(league: str, key, px: int = 80) -> str:
    """The logo for ESPN team `key` ("ncaa" id, or "nfl" abbreviation), resized
    to `px` square on ESPN's edge. `px` is pixels fetched, not shown - see
    `fetch_px`."""
    key = str(key).lower() if league == "nfl" else str(key)
    if league == "nfl":
        key = _NFL_FIX.get(key, key)
    return f"{CDN}/combiner/i?img=/i/teamlogos/{league}/500/{key}.png&w={px}&h={px}"


def fetch_px(shown: int) -> int:
    """Pixels to fetch for a logo drawn `shown` CSS pixels wide: twice that, for
    a phone's 2x screen, in two steps rather than one per size, so the small
    logos on every page are the same URL and the browser caches one copy."""
    return 80 if shown <= 40 else 160


def img(league: str, key, shown: int, cls: str = "") -> str:
    """An <img> for a logo drawn at `shown` CSS pixels: lazy, decoded off the
    main thread, and with width/height so the row does not jump when it lands.
    The page's own CSS still sets the drawn size; the attributes are the
    fallback and the layout hint."""
    # No team yet (ESPN's -1/-2 for a bowl before its pairing), no team at
    # all: nothing, rather than a request for a logo that does not exist.
    if key is None or str(key).strip() in ("", "nan", "None") or str(key).startswith("-"):
        return ""
    # gs-logo on every one: on the dark theme custom.css sets each mark on a
    # pale disc, since Ohio State's, Army's, the Raiders' and a dozen others
    # are near-black and vanished into the navy (2026-10-02).
    klass = f" class='{escape(' '.join(['gs-logo', cls]).strip(), quote=True)}'"
    src = escape(url(league, key, fetch_px(shown)), quote=True)
    return (f"<img{klass} src='{src}' alt='' width='{shown}' height='{shown}' "
            f"loading='lazy' decoding='async'>")
