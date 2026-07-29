"""
Pandas Styler helpers for generated tables (ported from py/html_util.py, subset
needed by the homepage).
"""
import re

import matplotlib as mpl
import matplotlib.colors as mcolors
from matplotlib.colors import Normalize

# Table cell / header / layout styles.
GRID_TD = {"selector": "td", "props": [("border", "1px solid black")]}
GRID_TH = {"selector": "th", "props": [("border", "1px solid black")]}
TABLE_STYLE = {
    "selector": "th.col_heading,td",
    "props": [("width", "100px"), ("text-align", "center"), ("table-layout", "fixed")],
}


def _font_for_bg(rgb) -> str:
    """White text on dark backgrounds, black on light (ITU-BT.601 luma)."""
    r, g, b = rgb
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return "#ffffff" if luminance < 0.5 else "#000000"


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
                styled.loc[idx, col] = "background-color: #373737"
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
