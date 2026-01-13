import re
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
import pandas as pd


light_grid_style_data = {
    'selector': 'td',
    'props': [
        ('border', '1px solid black')
    ]
}
light_grid_style_header = {
    'selector': 'th',
    'props': [
        ('border', '1px solid black')
    ]
}

table_style = {
        "selector": "th.col_heading,td",
        "props": [
        ("width", "100px"), # px instead of %
        ("text-align", "center"), # optional ?
    ]}

def highlight_roto(col):
    max_w = col.apply(lambda x: int(x.split('-')[0])).max()
    min_w = col.apply(lambda x: int(x.split('-')[0])).min()
    return ['background-color: #c8e6c9' if int(x.split('-')[0]) == max_w
            else 'background-color: #ffcdd2' if int(x.split('-')[0]) == min_w
            else '' for x in col]

def getIndValues(str):
    pattern = r"(\d{1,2})-(\d{1,2})"
    match = re.search(pattern, str)
    wins = int(match.group(1))
    loss = int(match.group(2))
    return [wins, loss]

def highlight_on_record(styles):
    def getColor(val):
        [wins, loss] = getIndValues(val)
        if wins > loss:
            color = '#CCDDAA'
        elif wins < loss:
            color = '#FFCCCC'
        else: 
            color = "#F1EABE"
        return f'background-color: {color}'
    ret = map(getColor, list(styles))
    return list(ret)

def bg_from_pythag_str(series, cmap='RdYlGn'):
        numeric_values = series.str.extract(r'([+-]?[0-9]*[.]?[0-9]+) \(([+-]?[0-9]*[.]?[0-9]+)\)').astype(float).squeeze()
        diff = numeric_values.iloc[:, 1] - numeric_values.loc[:, 0]
        norm = Normalize(vmin=diff.min(), vmax=diff.max())
        cmap_obj = plt.cm.get_cmap(cmap)
        styles = []
        for val in diff:
            # a) normalised value → colour (as RGBA)
            rgba = cmap_obj(norm(val))

            # b) drop the alpha channel, keep only RGB (0‑1 range)
            rgb = rgba[:3]

            # c) background as hex string
            bg_hex = mcolors.rgb2hex(rgb)

            # d) font colour based on luminance
            fg_hex = _font_color_for_bg(rgb)

            # e) combine both CSS rules
            styles.append(f'background-color:{bg_hex};color:{fg_hex}')
        return styles

def style_last_row(row):
    # Apply border-top and border-bottom to all cells in the last row
    return ['border-top: 3px solid black !important; border-bottom: 3px solid black !important;' for _ in row]

def allPlay_border(col):
    return ['border-left: 3px solid black !important;' for _ in col]

def style_last_col(col):
    # Apply border-left and border-right to all cells in the last column
    return ['font-weight: bold' for _ in col]

def _font_color_for_bg(rgb):
        """
        Return '#ffffff' (white) if the background rgb is "dark",
        otherwise '#000000' (black).  Uses the ITU‑BT.601 luma formula.
        """
        # rgb is a tuple/list of three floats in [0, 1]
        r, g, b = rgb
        # luma = 0.299 R + 0.587 G + 0.114 B  (standard TV luminance)
        luminance = 0.299 * r + 0.587 * g + 0.114 * b
        return "#ffffff" if luminance < 0.5 else "#000000"

def highlightSpec(styles):
    def getColor(val):
        [wins, loss] = getIndValues(val)
        if wins > loss:
            color = '#CCDDAA'
        elif wins < loss:
            color = '#FFCCCC'
        else: 
            color = "#F1EABE"
        return f'background-color: {color}'
    ret = map(getColor, list(styles))
    return list(ret)

def highlightActualRecords(df):
    # each row
    styles = pd.DataFrame('', index=df.index, columns=df.columns)
    styles = df.apply(lambda x: highlightSpec(x))
    
    for idx in df.index:
        for col in df.columns:
            if idx == col:
                styles.loc[idx, col] = 'background-color: #373737'
            elif (idx == 'Schedule Total') & (col == 'Team Total Record'):
                styles.loc[idx, col] = 'background-color: #DDDDDD'
    return styles