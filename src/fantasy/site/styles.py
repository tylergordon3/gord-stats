"""
Pandas Styler helpers for generated tables (ported from py/html_util.py, subset
needed by the homepage).
"""
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
GRID_TH = {
    "selector": "th",
    "props": [("border", "1px solid #e2e8f0"), ("padding", "8px 10px"), ("text-align", "center"),
              ("background-color", "#eef2f7"), ("color", "#334155"), ("font-weight", "700"),
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
            .background_gradient(cmap=cmap, subset=gradient_cols)
            .set_table_styles([GRID_TD, GRID_TH, TABLE_STYLE], overwrite=False)
            .set_table_attributes('class="sticky-table"'))


# --- Win-Loss record helpers (for all-play / schedule-comparison tables) ----- #

def _record_parts(text) -> tuple[int, int]:
    m = re.search(r"(\d{1,2})-(\d{1,2})", str(text))
    return int(m.group(1)), int(m.group(2))


def _record_color(text) -> str:
    wins, loss = _record_parts(text)
    color = "#CCDDAA" if wins > loss else "#FFCCCC" if wins < loss else "#F1EABE"
    return f"background-color: {color}"


def highlight_roto(col):
    """Green for the most wins in a column, red for the fewest."""
    wins = col.apply(lambda x: int(str(x).split("-")[0]))
    hi, lo = wins.max(), wins.min()
    return ["background-color: #c8e6c9" if w == hi
            else "background-color: #ffcdd2" if w == lo else "" for w in wins]


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
