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


_SWITCH_CSS = """<style>
.view-switch{margin:14px 0;display:flex;flex-wrap:wrap;gap:6px}
.view-switch button{padding:7px 16px;cursor:pointer;border:1px solid #888;background:#eee;
  border-radius:5px;font-size:15px}
.view-switch button.active{background:#3CB371;color:#fff;font-weight:bold;border-color:#2e8b57}
</style>"""


def view_switcher(views, group: str = "v") -> str:
    """Button-toggled views. `views`: list of (view_id, label, html). First shown."""
    buttons, divs = [], []
    for i, (vid, label, html) in enumerate(views):
        active = " active" if i == 0 else ""
        hidden = "" if i == 0 else ' style="display:none"'
        buttons.append(f'<button id="{group}-tab-{vid}" class="{group}-btn{active}" '
                       f"onclick=\"show_{group}('{vid}')\">{label}</button>")
        divs.append(f'<div id="{group}-view-{vid}" class="{group}-view"{hidden}>{html}</div>')
    js = f"""<script>
function show_{group}(v){{
  document.querySelectorAll('.{group}-view').forEach(function(e){{e.style.display='none';}});
  document.getElementById('{group}-view-'+v).style.display='';
  document.querySelectorAll('.{group}-btn').forEach(function(b){{b.classList.remove('active');}});
  document.getElementById('{group}-tab-'+v).classList.add('active');
}}
</script>"""
    return _SWITCH_CSS + f'<div class="view-switch">{"".join(buttons)}</div>' + "".join(divs) + js
