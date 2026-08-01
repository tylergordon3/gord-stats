"""
Small HTML layout helpers: in-page jump nav + collapsible sections.

Include HEAD once per page, then use section_nav() and details().
"""

HEAD = """<style>
.section-nav{margin:10px 0 18px;padding:8px 14px;background:#dfe6ee;border-radius:6px;font-size:14px}
.section-nav a{margin-right:16px;text-decoration:none;white-space:nowrap}
details.section{margin:14px 0;border:1px solid #b9c4d0;border-radius:6px;overflow:hidden;background:#fbfcfe}
details.section>summary{cursor:pointer;font-weight:bold;font-size:17px;padding:10px 14px;
  background:#dfe6ee;color:#17293b;list-style:none}
details.section>summary:hover{background:#d1dbe7}
details.section>summary::-webkit-details-marker{display:none}
details.section>summary::before{content:'\\25B8 ';color:#4a6178}
details.section[open]>summary::before{content:'\\25BE ';color:#4a6178}
details.section[open]>summary{border-bottom:1px solid #b9c4d0}
details.section>*:not(summary){margin:10px 14px}
</style>
<script>
function openHashTarget(){var h=location.hash.slice(1);if(!h)return;var e=document.getElementById(h);
  if(e&&e.tagName==='DETAILS'){e.open=true;e.scrollIntoView();}}
window.addEventListener('hashchange',openHashTarget);
window.addEventListener('load',openHashTarget);
</script>"""


_SEASON_CSS = """<style>
.season-bar{margin:12px 0;display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.season-bar .switch-label{font-weight:bold;margin-right:6px}
.season-bar a{padding:6px 14px;border:1px solid #888;border-radius:5px;background:#eee;
  text-decoration:none;color:#222;font-size:14px}
.season-bar a.active{background:#3CB371;color:#fff;font-weight:bold;border-color:#2e8b57}
</style>"""


def season_bar(current: str, path: str) -> str:
    """Per-page season selector: links to /<season>/<path>/, current highlighted."""
    from src.config import FORMAL_SEASON, LEAGUE_IDS
    links = "".join(
        f'<a class="{"active" if s == current else ""}" href="/{s}/{path}/">{FORMAL_SEASON[s]}</a>'
        for s in LEAGUE_IDS
    )
    return _SEASON_CSS + f'<div class="season-bar"><span class="switch-label">Season:</span>{links}</div>'


def section_nav(items) -> str:
    """items: list of (anchor_id, label) -> a 'Jump to:' bar."""
    links = "".join(f'<a href="#{a}">{label}</a>' for a, label in items)
    return f'<nav class="section-nav"><strong>Jump to:</strong> {links}</nav>'


def details(summary: str, body: str, open: bool = False, anchor: str = None) -> str:
    """A collapsible <details> section (optionally with an id anchor)."""
    idattr = f' id="{anchor}"' if anchor else ""
    return f'<details class="section"{idattr}{" open" if open else ""}><summary>{summary}</summary>{body}</details>'


_SWITCH_CSS = """<style>
.view-switch{margin:10px 0;display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.view-switch .switch-label{font-weight:bold;margin-right:6px;min-width:58px}
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


def two_axis_switcher(rows, cols, content, row_label="", col_label="", group="v") -> str:
    """Two independent button groups (rows x cols) selecting one content pane.

    rows/cols: list of (id, label). content: dict {(row_id, col_id): html}. First
    of each axis shown initially.
    """
    def btns(axis, kind):
        out = []
        for i, (aid, label) in enumerate(axis):
            active = " active" if i == 0 else ""
            out.append(f'<button class="{group}-{kind}{active}" data-{kind}="{aid}" '
                       f'onclick="{group}_pick(this)">{label}</button>')
        return "".join(out)

    divs = []
    for i, (rid, _) in enumerate(rows):
        for j, (cid, _) in enumerate(cols):
            hidden = "" if (i == 0 and j == 0) else ' style="display:none"'
            divs.append(f'<div class="{group}-view" id="{group}-{rid}-{cid}"{hidden}>{content[(rid, cid)]}</div>')

    js = f"""<script>
var {group}_r="{rows[0][0]}", {group}_c="{cols[0][0]}";
function {group}_pick(btn){{
  if(btn.dataset.r){{ {group}_r=btn.dataset.r;
    document.querySelectorAll('.{group}-r').forEach(function(b){{b.classList.toggle('active', b===btn);}}); }}
  if(btn.dataset.c){{ {group}_c=btn.dataset.c;
    document.querySelectorAll('.{group}-c').forEach(function(b){{b.classList.toggle('active', b===btn);}}); }}
  document.querySelectorAll('.{group}-view').forEach(function(v){{v.style.display='none';}});
  var el=document.getElementById('{group}-'+{group}_r+'-'+{group}_c); if(el) el.style.display='';
}}
</script>"""

    return (_SWITCH_CSS
            + f'<div class="view-switch"><span class="switch-label">{row_label}</span>{btns(rows, "r")}</div>'
            + f'<div class="view-switch"><span class="switch-label">{col_label}</span>{btns(cols, "c")}</div>'
            + "".join(divs) + js)
