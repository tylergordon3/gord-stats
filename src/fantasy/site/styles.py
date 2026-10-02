"""
Pandas Styler helpers for generated tables (ported from py/html_util.py, subset
needed by the homepage).

Render every Styler with `to_html(styler)` below, never `styler.to_html()`:
pandas' own output is mostly per-cell ids and per-cell CSS rules.
"""
import hashlib
import html
import re

import matplotlib as mpl
import matplotlib.colors as mcolors
from matplotlib.colors import Normalize
from gordstats import contrast

# Table cell / header / layout styles (shared across all generated tables).
# Palette matches the site theme in docs/assets/css/custom.css (slate grays,
# soft borders); the styles are inline because pandas id-scopes them, so this
# is the authoritative look of every generated table.
# NB: no background on td — `#T_x td` outranks pandas' per-cell gradient ids,
# so a background here would erase every heatmap. The white surface comes from
# the .table-scroll card around the table.
GRID_TD = {
    "selector": "td",
    "props": [("border", "1px solid #eef2f7"), ("padding", "6px 10px"), ("text-align", "center")],
}
# No background or colour on th either, and for the same reason as td below:
# pandas emits these as `#T_xxx th`, an ID rule that outranks custom.css, so a
# colour here is a colour in both themes. The site styles `.sticky-table th`
# per theme and every table carrying GRID_TH is a `.sticky-table`.
GRID_TH = {
    "selector": "th",
    "props": [("border", "1px solid #e2e8f0"), ("padding", "8px 10px"), ("text-align", "center"),
              ("font-weight", "700"),
              ("font-size", "12px"), ("text-transform", "uppercase"),
              ("letter-spacing", "0.03em")],
}
TABLE_STYLE = {
    "selector": "",
    # `auto` side margins, not 0: the site centres .sticky-table with
    # `margin: 0 auto`, but pandas emits this block as an ID rule (#T_xxx),
    # which outranks the class. With `6px 0` the tables carrying TABLE_STYLE
    # sat flush left while the ones without it stayed centred, on the same
    # page — that's the Draft vs ADP mismatch between By Owner / Full Draft
    # and Best Values.
    "props": [("border-collapse", "collapse"), ("margin", "6px auto"), ("font-size", "14px")],
}


def _font_for_bg(rgb) -> str:
    """Pick black or white text — whichever actually contrasts better.

    Thin wrapper over gordstats.contrast so the board and the test suite agree
    on what "readable" means. This used to threshold ITU-BT.601 luma at 0.5,
    which is the wrong measure and the wrong cut: perceived brightness is not
    linear in sRGB, and on the RdYlGn scale the draft board uses, the mid
    oranges and greens sat right at that boundary and took black text at about
    3:1.
    """
    return contrast.best_text_on(rgb)


def default_style(df, gradient_cols, cmap: str = "RdYlGn"):
    """Styled table: hidden index, grid borders, sticky, + a gradient on `gradient_cols`."""
    return (df.style.hide(axis="index")
            .background_gradient(text_color_threshold=GRADIENT_INK, cmap=cmap, subset=gradient_cols)
            .set_table_styles([GRID_TD, GRID_TH, TABLE_STYLE], overwrite=False)
            .set_table_attributes('class="sticky-table"'))


# --- Compact rendering -------------------------------------------------------- #
#
# pandas gives every cell an id (`T_<random uuid>_row3_col2`) and paints each
# coloured cell with an ID rule in the table's <style> block - one rule per
# gradient cell, its selector spelled out in full. On the draft page that was
# 9,318 ids and ~168 KB of CSS, half of a 1 MB page. `to_html` renders the same
# table with the colour as a style attribute on the cells that carry one, no id
# on the cells that don't, and a uuid that is a hash of the table (so a rebuild
# with the same data is byte-identical).
#
# The cascade is unchanged. An ID rule (1,0,0) and a style attribute both beat
# every class rule the site has, and lose to the same !important ones, so the
# only rules that ranked between the two are the table's own (`#T_x td`, 1,0,1),
# which outrank the per-cell rule but not the attribute. A cell whose colour
# could collide with one of those - same property, or a shorthand of it - keeps
# its ID rule, exactly as pandas wrote it.
#
# pandas' bookkeeping classes go too (`data row3 col2`, `col_heading level0`):
# nothing on the site selects them - no stylesheet, script or test - except a
# table's own rules (schedule's `td.col0`), and a class those name is kept.
# Indentation between table tags goes as well; a cell's content is untouched.

_PLACEHOLDER = "gs0uuid0"
_STYLE_BLOCK = re.compile(r'\s*<style type="text/css">\n(.*?)</style>\n', re.S)
_CSS_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_CSS_DECL = re.compile(r"^[ \t]*([^:\s][^:\n]*?)[ \t]*:[ \t]*(.*?)[ \t]*;?[ \t]*$", re.M)
# A cell's opening tag up to its class, then whether the tag closes there.
_CELL_TAG = re.compile(r'<(td|th)(?: id="T_' + _PLACEHOLDER + r'_([^"]+)")? class="([^"]*)" ?(>?)')
_PANDAS_CLASS = re.compile(r"^(?:data|blank|index_name|col_heading|row_heading|"
                           r"level\d+|row\d+|col\d+|col_trim|row_trim)$")
_COMPOUND = re.compile(r"^(td|th|tr|thead|tbody)?((?:\.[\w-]+)*)$")
_IMPORTANT = re.compile(r"!\s*important\s*$", re.I)
_TABLE_WS = re.compile(r"\n[ \t]*(?=</?(?:table|thead|tbody|tr|th|td)\b)")


def _may_match(rest: str, tag: str, classes: set, in_head: bool) -> bool:
    """Could the table rule `#T_x <rest>` select this cell? Unsure means yes."""
    if not rest:
        return False                      # the table itself
    if "," in rest:
        return True
    parts = rest.split()
    last = _COMPOUND.match(parts[-1])
    if not last:
        return True
    if last.group(1) and last.group(1) != tag:
        return False
    if not set(filter(None, last.group(2).split("."))) <= classes:
        return False
    for part in parts[:-1]:
        anc = _COMPOUND.match(part)
        if not anc or anc.group(2):
            return True
        if (anc.group(1) == "thead" and not in_head) or (anc.group(1) == "tbody" and in_head):
            return False
    return True


def _overlaps(p: str, q: str) -> bool:
    return p == q or p.startswith(q + "-") or q.startswith(p + "-")


def _inlinable(decls, info, table_rules) -> bool:
    """True when moving these declarations into a style attribute can't change
    what wins: nothing in the table's own rules competes, or the cell's side is
    !important and the table's is not (inline !important wins all the same)."""
    tag, classes, in_head = info
    for rest, tdecls in table_rules:
        if not _may_match(rest, tag, classes, in_head):
            continue
        for p, v in decls:
            for q, w in tdecls:
                if _overlaps(p, q) and not (_IMPORTANT.search(v) and not _IMPORTANT.search(w)):
                    return False
    return True


def _css(decls) -> str:
    return ";".join(f"{p}:{v}" for p, v in decls)


def to_html(styler, uuid: str | None = None) -> str:
    """Render a Styler compactly: colours inline, ids only where a rule needs
    one, no unused pandas classes, a stable table id. Same look as
    `styler.to_html()`, a fraction of the bytes. `uuid` names the table; the
    default is a hash of its markup."""
    styler.cell_ids = False
    raw = styler.to_html(table_uuid=_PLACEHOLDER)
    m = _STYLE_BLOCK.match(raw)
    if not m:                             # an unfamiliar template: leave it be
        out = raw
    else:
        tid = f"#T_{_PLACEHOLDER}"
        table_rules, cell_rules = [], []  # (selector, decls), ([ids], decls)
        for rule in _CSS_RULE.finditer(m.group(1)):
            sel = " ".join(rule.group(1).split())
            decls = _CSS_DECL.findall(rule.group(2))
            parts = [s.strip() for s in sel.split(",")]
            if all(s.startswith(tid + "_") and " " not in s for s in parts):
                cell_rules.append(([s[len(tid) + 1:] for s in parts], decls))
            else:
                table_rules.append((sel, decls))
        body = raw[m.end():]
        head_end = body.find("</thead>")
        cells = {c.group(2): (c.group(1), set(c.group(3).split()), c.start() < head_end)
                 for c in _CELL_TAG.finditer(body) if c.group(2)}
        tables = [(sel[len(tid):].strip(), decls) for sel, decls in table_rules
                  if sel == tid or sel.startswith(tid + " ")]
        unknown = [d for sel, d in table_rules if not (sel == tid or sel.startswith(tid + " "))]
        per_cell: dict = {}
        for ids, decls in cell_rules:
            for eid in ids:
                per_cell.setdefault(eid, []).extend(decls)
        inline = {eid: decls for eid, decls in per_cell.items()
                  if eid in cells and not unknown
                  and _inlinable(decls, cells[eid], tables)}
        named = set(re.findall(r"\.([\w-]+)", " ".join(sel for sel, _ in table_rules)))

        def tag(c):
            eid, attrs = c.group(2), ""
            if eid in inline:
                attrs = f' style="{html.escape(_css(inline[eid]), quote=True)}"'
            elif eid:
                attrs = f' id="T_{_PLACEHOLDER}_{eid}"'
            keep = [k for k in c.group(3).split() if k in named or not _PANDAS_CLASS.match(k)]
            if keep:
                attrs += f' class="{" ".join(keep)}"'
            return f"<{c.group(1)}{attrs}{c.group(4) or ' '}"

        body = _CELL_TAG.sub(tag, _TABLE_WS.sub("", body))
        rules = [f"{sel}{{{_css(decls)}}}" for sel, decls in table_rules]
        for ids, decls in cell_rules:
            kept = [eid for eid in ids if eid not in inline]
            if kept:
                rules.append(", ".join(f"{tid}_{eid}" for eid in kept) + f"{{{_css(decls)}}}")
        style = f'<style type="text/css">\n{chr(10).join(rules)}\n</style>\n' if rules else ""
        out = style + body
    name = uuid or hashlib.sha1(out.encode("utf-8")).hexdigest()[:8]
    return out.replace(f"T_{_PLACEHOLDER}", f"T_{name}")


# --- Win-Loss record helpers (for all-play / schedule-comparison tables) ----- #

def _record_parts(text) -> tuple[int, int]:
    m = re.search(r"(\d{1,2})-(\d{1,2})", str(text))
    return int(m.group(1)), int(m.group(2))


#: When pandas puts *light* text on a gradient fill: it does so below this
#: luminance, so a bigger number means more white text, not less. The default
#: 0.408 sits a hair above the RdYlGn mid-greens (#66bd63 is 0.397), which is
#: why the middle of every scale on this site came out white-on-green at about
#: 2:1. At 0.22 white is kept for the deep ends of the ramp, where it really is
#: the readable choice (#d73027 takes white at 5.2:1 and dark at 4.0:1), and
#: everything from the mid-oranges up takes dark ink.
GRADIENT_INK = 0.22

#: Dark ink, stated rather than inherited. These fills are light in both
#: themes - a pale green record cell is a pale green record cell at night too -
#: so the text on them cannot come from the table, which is dark after hours.
ON_LIGHT = "color: #0f172a"


def _record_color(text) -> str:
    wins, loss = _record_parts(text)
    color = "#CCDDAA" if wins > loss else "#FFCCCC" if wins < loss else "#F1EABE"
    return f"background-color: {color}; {ON_LIGHT}"


def highlight_roto(col):
    """Green for the most wins in a column, red for the fewest."""
    wins = col.apply(lambda x: int(str(x).split("-")[0]))
    hi, lo = wins.max(), wins.min()
    return [f"background-color: #c8e6c9; {ON_LIGHT}" if w == hi
            else f"background-color: #ffcdd2; {ON_LIGHT}" if w == lo else "" for w in wins]


def highlight_on_record(col):
    """Green/red/yellow per cell based on its W-L record."""
    return [_record_color(v) for v in col]


def highlight_actual_records(df):
    """Color a schedule-comparison matrix by record, with dark diagonal cells."""
    styled = df.apply(lambda col: [_record_color(v) for v in col])
    for idx in df.index:
        for col in df.columns:
            if idx == col or (idx == "Team Totals" and col == "Schedule Totals"):
                styled.loc[idx, col] = "background-color: #334155; color: #f1f5f9"
    return styled


def style_total_bottom(_):
    return ["font-weight: bold; border-top: 3px solid black !important;" for _ in _]


def style_total_right(_):
    return ["font-weight: bold; border-left: 3px solid black !important;" for _ in _]


def bg_from_pythag_str(series, cmap: str = "RdYlGn"):
    """Color an "expected (actual)" column by how much actual beats expected.

    Values look like "8.4 (10)"; we color by (actual - expected).
    """
    nums = series.str.extract(r"([+-]?[0-9]*[.]?[0-9]+) \(([+-]?[0-9]*[.]?[0-9]+)\)").astype(float)
    diff = nums.iloc[:, 1] - nums.iloc[:, 0]
    norm = Normalize(vmin=diff.min(), vmax=diff.max())
    cmap_obj = mpl.colormaps[cmap]

    styles = []
    for val in diff:
        rgb = cmap_obj(norm(val))[:3]
        styles.append(f"background-color:{mcolors.rgb2hex(rgb)};color:{_font_for_bg(rgb)}")
    return styles
