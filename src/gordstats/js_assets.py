"""
The site's shared browser libraries, served as files instead of inline.

window.GSAPI, the league bar, window.GSL, the watch guide's engine and the
rest used to be inline <script> blocks, repeated on every page that used them:
GSAPI and the bar alone were ~50 KB on each of fourteen fantasy pages,
downloaded and parsed again on every view, and again after every one of the
Pi's publishes (the 2026-10-02 ops review). Each is a file under
docs/assets/js/ now (gs-*.js), loaded through `| fingerprint`
(docs/_plugins/fingerprint.rb): a content-hashed URL the browser keeps for a
year, so a reader downloads each once.

A module keeps its old attribute (`JS`, `SIM_JS`, ...) as the inline script -
the browser tests run those in Chromium - and adds a `..._TAG` twin, which is
what the pages carry. Both are read from the same file, so they cannot drift.

Nothing page- or season-specific is in a file. What used to be substituted
into a script when the page was built (this season's league id, the watch
guide's night, the recap's Share button) is set just ahead of it by
`config()`, merged into `window.GSCFG`, which the file reads as it runs.

The tags are plain `<script src>`, neither defer nor async: the inline script
that follows one (an adapter calling GSWatch, a page reading GSL) must find
it defined, exactly as when it was inline, so the order is unchanged.
"""
import re

from gordstats import paths
from gordstats.frontmatter import liquid
from gordstats.jsonio import script_json

DIR = paths.DOCS / "assets" / "js"


def source(name: str) -> str:
    """The library's code, as the file holds it."""
    return (DIR / name).read_text(encoding="utf-8")


def config(**values) -> str:
    """JavaScript that sets `values` on window.GSCFG, keeping what is there."""
    return ("window.GSCFG=Object.assign(window.GSCFG||{},"
            + script_json(values, separators=(",", ":")) + ");\n")


def inline(name: str, cfg: dict | None = None, attrs: str = "", raw: bool = True) -> str:
    """The library as one inline <script>, its config first - what the page
    used to carry, and what the tests run."""
    body = f"<script{attrs}>" + (config(**cfg) if cfg else "") + source(name) + "</script>"
    return "{% raw %}" + body + "{% endraw %}" if raw else body


def _url(name: str) -> str:
    return liquid("{{ '/assets/js/" + name + "' | fingerprint | relative_url }}")


def tag(name: str, cfg: dict | None = None, attrs: str = "") -> str:
    """The library by its content-hashed URL, behind its config. Only for a
    page body that goes through frontmatter.add_front_matter, which lets the
    marked Liquid through."""
    return ((f"<script>{config(**cfg)}</script>" if cfg else "")
            + f'<script{attrs} src="{_url(name)}"></script>')


_HEAD, _TAIL = (re.escape(part) for part in _url("\0").split("\0"))
_TAGGED = re.compile(r'<script([^>]*) src="' + _HEAD + r'([\w.-]+\.js)' + _TAIL + r'"></script>')


def expand(html: str) -> str:
    """`html` with every tag() put back inline: a page body served without
    Jekyll (the browser tests) has nothing to resolve the hashed URL with.
    The configs are already there, ahead of each."""
    return _TAGGED.sub(lambda m: f"<script{m.group(1)}>" + source(m.group(2)) + "</script>", html)
