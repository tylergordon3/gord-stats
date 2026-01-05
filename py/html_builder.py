import os
import schedule
import matplotlib.colors as mcolors
from matplotlib.colors import Normalize
import matplotlib.pyplot as plt


def add_front_matter(html, title):
    fm = f"""---
layout: default
title: {title}
---
"""
    header = f'<h1>{title}</h1>'
    new_html = fm + header + html
    return new_html.lstrip()

def generate_landing(folder, file, title):
    """
    Generates a landing page with links to all week files in the folder.

    Args:
        folder (str): Folder containing the week HTML files
        output_file (str): Path to write the landing HTML page
        title (str): Title of the landing page
    """
    # Scan folder for files matching "week*_bestball.html"
    week_files = [f for f in os.listdir(folder) if f.startswith("week") and f.endswith(f"_{file}.html")]
    
    # Sort by week number descending (week11 -> week1)
    def week_sort_key(f):
        import re
        match = re.search(fr"week(\d+)_{file}.html", f)
        return int(match.group(1)) if match else 0

    week_files.sort(key=week_sort_key, reverse=True)

    # Start HTML content
    html_body = ''
    
    if title == "Best Ball":
        html_body = f"<p>Outcomes if every lineup had max points possible for a given week.</p>\n"
        html_body += '<p><a href="summary_bestball.html">Standings</a></p>\n'

    for f in week_files:
        week_name = f.split("_")[0].capitalize() 
        html_body += f'<p><a href="{f}">{week_name}</a></p>\n'

    # Add front matter
    fm = add_front_matter(html_body, f'{title}')
    output_file = os.path.join(folder, file) + '.html'
    # Write file
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(fm)

    print(f"Landing page generated: {output_file}")

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

def generate_index():
    #  htmb.generate_landing('docs/median', 'median', 'Median')
    standings = schedule.standings()
    table_style = {
        "selector": "th.col_heading,td",
        "props": [
        ("width", "100px"), # px instead of %
        ("text-align", "center"), # optional ?
    ]}
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
    styler = (
        standings
        .style
        .hide(axis="index") 
        .format( lambda x: f"{x:.3f}" if isinstance(x, float) else x) 
        .background_gradient(cmap="RdYlGn_r", subset=["SOS"]) 
        .background_gradient(cmap="RdYlGn", subset=["SOV"])
        .apply(bg_from_pythag_str, subset=["Exp W (Actual)"])
        .set_table_styles([light_grid_style_data, light_grid_style_header, table_style], overwrite=False)
        )
    
    page=f'''
<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8">
    <title>Home</title>
  </head>
  <body>
    <p><strong>Schedule:</strong> <strong>Easiest:</strong> Big Booty Bowers | <strong>Hardest:</strong> padgett</p>
    <p><strong>H2H Wins:</strong> <strong>Weakest:</strong> Clanker Barrel | <strong>Strongest:</strong> The Standard & Lotta Cox</p>
    <h1>Regular Season Standings</h1>
    <p><strong>SOS:</strong> Green = easier schedule, red = harder schedule</p>
    <p><strong>SOV:</strong> Green = better victories, red = easier victories</p>
    <p><strong>Exp W (Actual):</strong> Expected H2H wins using Pythagorean Wins versus actual H2H wins.</p> 
    <p>Green = outperformed expectations, red = underperformed.</p>
    <div class="table-scroll">
    {styler.to_html(classes='sticky-table')}
    </div>
  </body>
</html>
'''
    page = add_front_matter(page, 'Home')
    with open('docs/index.html', "w", encoding="utf-8") as f:
        f.write(page)