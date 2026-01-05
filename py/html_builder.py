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

def bg_from_pythag_str(series, cmap='RdYlGn'):
        numeric_values = series.str.extract(r'([+-]?[0-9]*[.]?[0-9]+) \(([+-]?[0-9]*[.]?[0-9]+)\)').astype(float).squeeze()
        numeric_values = numeric_values.iloc[:, 1] - numeric_values.loc[:, 0]
        norm = Normalize(vmin=numeric_values.min(), vmax=numeric_values.max())
        cmap = plt.cm.get_cmap(cmap)
        colors = [mcolors.rgb2hex(c) for c in cmap(norm(numeric_values))]
        return ['background-color: %s' % color for color in colors]

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
    <p><a href="median/median.html">Median</a></p>
    <p><a href="bestball/bestball.html">Best Ball</a></p>
    <p><a href="schedule/schedule.html">Schedule Stats</a></p>
    <p><strong>Easiest Schedule:</strong> Big Booty Bowers</p>
    <p><strong>Hardest Schedule:</strong> padgett</p>
    <p><strong>Weakest (H2H) Wins:</strong> Clanker Barrel</p>
    <p><strong>Strongest (H2H) Wins:</strong> The Standard & Lotta Cox</p>
    <h1>Regular Season Standings</h1>
    <div class="table-scroll">
    {styler.to_html(classes='sticky-table')}
    </div>
  </body>
</html>
'''
    page = add_front_matter(page, 'Home')
    with open('docs/index.html', "w", encoding="utf-8") as f:
        f.write(page)