"""
Check the built site's internal links before it is uploaded.

    python deploy/linkcheck.py docs/_site            # exit 1 = a page's script
    python deploy/linkcheck.py --quiet docs/_site    # or stylesheet is missing

Nothing looked at the built site before publish: Jekyll succeeding was the
only check, and Jekyll is happy to write a page whose <script src> points at
nothing. Since 2026-10-02 every page's CSS and JS come from content-hashed
paths a plugin writes (docs/_plugins/fingerprint.rb) - a mistake there is a
site with no styling and no JavaScript, on every page, published 80 times on a
Saturday. That is what fails the run here: a script or stylesheet that is not
in the build. Missing link and image targets are listed as warnings and
publish anyway - one stale link is not worth holding back the day's data
(the 2026-09-23 lesson: one failure must not cancel the whole publish).

Not checked: fragments (most are read by page scripts, #w=5&g=..., not
element ids), data-* attributes (data-src="gs" names a projection source, not
a URL), /api/ and /auth/ (Pages Functions, not files), other hosts.
Runs in a few seconds over the ~420 pages; stdlib only, so it needs no venv.
"""
import os
import sys
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

HOSTS = ("www.gordstats.com", "gordstats.com")
SKIP_PREFIXES = ("/api/", "/auth/", "/cdn-cgi/")
# (tag, attribute) pairs that name a URL the browser fetches or follows.
URL_ATTRS = {("a", "href"), ("link", "href"), ("script", "src"), ("img", "src"),
             ("img", "srcset"), ("source", "src"), ("source", "srcset"),
             ("iframe", "src"), ("video", "src"), ("video", "poster"), ("audio", "src")}


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found = []                         # (kind, url); kind "asset" fails the run

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for name, value in attrs:
            if (tag, name) not in URL_ATTRS or not value:
                continue
            if tag == "link" and "stylesheet" not in (a.get("rel") or "").lower().split():
                # icons, the manifest, canonical: worth a warning, not a stop.
                kind = "link"
            elif tag == "script" or tag == "link":
                kind = "asset"
            else:
                kind = "link"
            urls = ([p.strip().split(" ")[0] for p in value.split(",")]
                    if name == "srcset" else [value])
            self.found += [(kind, u.strip()) for u in urls if u.strip()]


def redirects(site: str) -> list:
    """Sources in Cloudflare's _redirects (a trailing * is a prefix)."""
    try:
        with open(os.path.join(site, "_redirects"), encoding="utf-8") as fh:
            return [ln.split()[0] for ln in fh if ln.strip() and not ln.startswith("#")]
    except FileNotFoundError:
        return []


def resolves(site: str, path: str, redirect_from: list) -> bool:
    """Whether Cloudflare Pages would serve `path`: the file, its clean URL
    (x for x.html), a directory's index.html, or a _redirects source."""
    full = os.path.join(site, path.lstrip("/"))
    if path.endswith("/"):
        if (os.path.isfile(os.path.join(full, "index.html"))
                or os.path.isfile(full.rstrip("/") + ".html")):
            return True
    elif (os.path.isfile(full) or os.path.isfile(full + ".html")
          or os.path.isfile(os.path.join(full, "index.html"))):
        return True
    return any(path.startswith(r[:-1]) if r.endswith("*") else path == r
               for r in redirect_from)


def target(page: str, url: str):
    """The site path a URL on `page` points at, or None when it is not ours to check."""
    if "{{" in url or "{%" in url:
        return url                              # Liquid that never rendered: broken
    parts = urlsplit(url)
    if parts.scheme in ("http", "https"):
        if parts.netloc not in HOSTS:
            return None
    elif parts.scheme or parts.netloc:
        return None                             # mailto:, data:, //cdn...
    path = unquote(parts.path)
    if not path:
        return None                             # a bare #fragment or ?query
    if not path.startswith("/"):
        base = page if page.endswith("/") else page.rsplit("/", 1)[0] + "/"
        path = os.path.normpath(base + path) + ("/" if path.endswith("/") else "")
    if path.startswith(SKIP_PREFIXES):
        return None
    return path


def check(site: str):
    """({missing asset: pages}, {missing link: pages}, pages scanned)."""
    redirect_from = redirects(site)
    assets, links, pages = {}, {}, 0
    for dirpath, _dirs, files in os.walk(site):
        for name in files:
            if not name.endswith(".html"):
                continue
            pages += 1
            full = os.path.join(dirpath, name)
            page = "/" + os.path.relpath(full, site).replace(os.sep, "/")
            parser = _Links()
            with open(full, encoding="utf-8", errors="replace") as fh:
                parser.feed(fh.read())
            for kind, url in parser.found:
                path = target(page, url)
                if path is None or resolves(site, path, redirect_from):
                    continue
                (assets if kind == "asset" else links).setdefault(path, set()).add(page)
    return assets, links, pages


def _report(title: str, missing: dict, limit: int = 25) -> None:
    print(f"{title}: {len(missing)}")
    for path, pages in sorted(missing.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:limit]:
        print(f"  {path}  <- {len(pages)} page(s), e.g. {sorted(pages)[0]}")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # --quiet: say nothing unless the run fails (the live tick, every ten
    # minutes; the daily run lists the warnings once each run instead).
    quiet = "--quiet" in argv
    args = [a for a in argv if a != "--quiet"]
    site = args[0] if args else "docs/_site"
    if not os.path.isfile(os.path.join(site, "index.html")):
        print(f"linkcheck: no built site at {site}")
        return 1
    assets, links, pages = check(site)
    if not quiet:
        print(f"linkcheck: {pages} pages")
        if links:
            _report("  ⚠️ links and images to nothing (published anyway)", links)
    if assets:
        _report("  ❌ scripts/stylesheets missing from the build", assets)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
