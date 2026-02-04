import os
import schedule_stats
import draft

def add_front_matter(html, title, subnav=None):
    if subnav:
        fm = f"""---
layout: default
title: {title}
subnav_id: {subnav}
---
"""
    else:
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
    standings = schedule_stats.all_time_metrics()
    missed_games = draft.all_time_missed()
    page=f'''
<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8">
    <title>Home</title>
  </head>
  <body>
    <h1>All-Time Metrics</h1>
    <p><strong>SOS - Strength of Schedule</strong>: Green, Easier Schedule -> Red, Harder Schedule</p>
    <p><strong>SOV - Strength of Victory</strong>: Green, More wins vs. good teams -> Red, Less wins vs. good teams</p>
    <p><strong>Exp W (Actual) - Expected H2H Wins vs Actual H2H Wins</strong>: Green, Outperformed expectations -> Red, underperformed.<br>
    *Expected Wins calculated using Pythagorean Wins formula using a constant of 2.37.</p> 
    <div class="table-scroll">
    {standings.to_html()}
    </div>
    <h1>All-Time Injury Impacts</h1>
    <div class="table-scroll">
    {missed_games.to_html()}
    </div>
    <p>Currently only factors in players drafted by team.<br>
    Trades, drops, additions will not be properly reflected.<br>
    Players on IR when drafted not counted. Kickers and D/ST not counted.<br>
    Future versions will account for these nuances, however this is still a good look at raw injury luck.<br>
    Season-by-season breakdown can be found in the 'Drafts' section.</p>
  </body>
</html>
'''
    page = add_front_matter(page, 'Home')
    with open('docs/index.html', "w", encoding="utf-8") as f:
        f.write(page)