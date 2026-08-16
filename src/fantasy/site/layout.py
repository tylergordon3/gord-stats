"""
Small HTML layout helpers: in-page jump nav + collapsible sections.

Include HEAD once per page, then use section_nav() and details().

The styling for every class emitted here (.section-nav, details.section,
.view-switch) lives in docs/assets/css/custom.css with the rest of the site
theme, so light/dark mode and mobile rules cascade normally.
"""

HEAD = """<script>
function openHashTarget(){var h=location.hash.slice(1);if(!h)return;var e=document.getElementById(h);
  if(e&&e.tagName==='DETAILS'){e.open=true;e.scrollIntoView();}}
window.addEventListener('hashchange',openHashTarget);
window.addEventListener('load',openHashTarget);
</script>"""


def internal_link(path: str, label: str) -> str:
    """Link to another page of this site.

    Emits Liquid `relative_url` rather than a bare "/path/" so the link stays
    correct if the site ever moves under a baseurl. Generated pages carry front
    matter, so Jekyll resolves this on build.
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


# .view-switch styling lives in docs/assets/css/custom.css (site theme).


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
    return f'<div class="view-switch">{"".join(buttons)}</div>' + "".join(divs) + js


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

    return (f'<div class="view-switch"><span class="switch-label">{row_label}</span>{btns(rows, "r")}</div>'
            + f'<div class="view-switch"><span class="switch-label">{col_label}</span>{btns(cols, "c")}</div>'
            + "".join(divs) + js)
