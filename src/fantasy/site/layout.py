"""
Small HTML layout helpers: in-page jump nav + collapsible sections.

Include HEAD once per page, then use section_nav() and details().
"""

HEAD = """<style>
.section-nav{margin:10px 0 18px;padding:8px 14px;background:#dfe6ee;border-radius:6px;font-size:14px}
.section-nav a{display:inline-block;margin:3px 16px 3px 0;text-decoration:none;white-space:nowrap}
details.section{margin:14px 0;border:1px solid #b9c4d0;border-radius:6px;overflow:hidden;background:#fbfcfe}
details.section>summary{cursor:pointer;font-weight:bold;font-size:17px;padding:10px 14px;
  background:#dfe6ee;color:#17293b;list-style:none}
details.section>summary:hover{background:#d1dbe7}
details.section>summary::-webkit-details-marker{display:none}
details.section>summary::before{content:'\\25B8 ';color:#4a6178}
details.section[open]>summary::before{content:'\\25BE ';color:#4a6178}
details.section[open]>summary{border-bottom:1px solid #b9c4d0}
details.section>*:not(summary){margin:10px 14px}
/* Phones: the 14px gutters cost real table width, and wrapped nav links need
   room to breathe once they stop fitting on one line. */
@media (max-width:600px){
  .section-nav{margin:8px 0 14px;padding:8px 10px;line-height:1.5}
  .section-nav a{margin-right:14px}
  details.section{margin:10px 0}
  details.section>summary{font-size:16px;padding:10px}
  details.section>*:not(summary){margin:10px 8px}
}
</style>
<script>
function openHashTarget(){var h=location.hash.slice(1);if(!h)return;var e=document.getElementById(h);
  if(e&&e.tagName==='DETAILS'){e.open=true;e.scrollIntoView();}}
window.addEventListener('hashchange',openHashTarget);
window.addEventListener('load',openHashTarget);
</script>"""


def internal_link(path: str, label: str) -> str:
    """Link to another page of this site.

    Emits Liquid `relative_url` rather than a bare "/path/" so the link keeps
    working under the GitHub Pages project baseurl (/fantasy_insights). Generated
    pages carry front matter, so Jekyll resolves this on build.
    """
    return "<a href=\"{{ '%s' | relative_url }}\">%s</a>" % (path, label)


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
@media (max-width:600px){
  .view-switch{gap:5px;margin:8px 0}
  .view-switch button{padding:6px 11px;font-size:14px}
  /* Label on its own line so the season buttons wrap as an even grid. */
  .view-switch .switch-label{flex:1 1 100%;min-width:0;margin:0 0 2px}
}
</style>"""


def view_switcher(views, group: str = "v", label: str = "") -> str:
    """Button-toggled views. `views`: list of (view_id, label, html). First shown."""
    buttons, divs = [], []
    if label:
        buttons.append(f'<span class="switch-label">{label}</span>')
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
