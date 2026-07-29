"""
Small HTML layout helpers: in-page jump nav + collapsible sections.

Include HEAD once per page, then use section_nav() and details().
"""

HEAD = """<style>
.section-nav{margin:10px 0 18px;padding:8px 14px;background:#f4f4f4;border-radius:6px;font-size:14px}
.section-nav a{margin-right:16px;text-decoration:none;white-space:nowrap}
details.section{margin:12px 0;border:1px solid #ddd;border-radius:6px;padding:2px 12px}
details.section>summary{cursor:pointer;font-weight:bold;font-size:18px;padding:8px 0;list-style:none}
details.section>summary::-webkit-details-marker{display:none}
details.section>summary::before{content:'\\25B8 ';color:#888}
details.section[open]>summary::before{content:'\\25BE ';color:#888}
details.section[open]>summary{border-bottom:1px solid #eee;margin-bottom:8px}
</style>
<script>
function openHashTarget(){var h=location.hash.slice(1);if(!h)return;var e=document.getElementById(h);
  if(e&&e.tagName==='DETAILS'){e.open=true;e.scrollIntoView();}}
window.addEventListener('hashchange',openHashTarget);
window.addEventListener('load',openHashTarget);
</script>"""


def section_nav(items) -> str:
    """items: list of (anchor_id, label) -> a 'Jump to:' bar."""
    links = "".join(f'<a href="#{a}">{label}</a>' for a, label in items)
    return f'<nav class="section-nav"><strong>Jump to:</strong> {links}</nav>'


def details(summary: str, body: str, open: bool = False, anchor: str = None) -> str:
    """A collapsible <details> section (optionally with an id anchor)."""
    idattr = f' id="{anchor}"' if anchor else ""
    return f'<details class="section"{idattr}{" open" if open else ""}><summary>{summary}</summary>{body}</details>'
