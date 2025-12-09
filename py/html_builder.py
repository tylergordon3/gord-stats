import os
import schedule

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
        .format( lambda x: f"{x:.3f}" if isinstance(x, (int, float)) else x) 
        .background_gradient(cmap="RdYlGn_r", subset=["SOS"]) 
        .background_gradient(cmap="RdYlGn", subset=["SOV"])
        .background_gradient(cmap="RdYlGn_r", subset=["Scoring Luck"])
        .format('{:.2%}', subset=['Scoring Luck'])
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
    <h1>Regular Season Standings</h1>
    <div class="table-scroll">
    {styler.to_html(classes='sticky-table')}
    </div>
    <br><h3>Site Update Log</h3>
    <p>Tue 12/09/25 -  7 am - Site updated for week 14, regular season completed</p>
    <p>Sun 12/07/25 -  9 pm - Updated stats for all week 14 games up to SNF</p>
    <p>Tue 12/02/25 - 12 pm - Updated all pages post week 13, updated playoff scenarios on home.</p>
    <p>Mon 12/01/25 -  7 am - Updated week 13 pages with all games prior to MNF & playoff scenarios.</p>
    <p>Sun 11/30/25 -  9 pm - Updated Edited median to (hopefully) stop including injured players as "To Play"</p>
  </body>
</html>
'''
    page = add_front_matter(page, 'Home')
    with open('docs/index.html', "w", encoding="utf-8") as f:
        f.write(page)