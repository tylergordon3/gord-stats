'''
    Module to format schedule stats page
'''
import schedule_stats
import html_builder as htmb
import league_data

#       ****** MAIN ******
def schedule_main(season_str):
    # Set up
    html = ''
    # All Play Standings
    html += '<h2>All-Play Standings</h2>'
    html += '<p>Whole league goes H2H, every week.</p>'
    html += '<div class="table-scroll">'
    html += schedule_stats.calc_roto(season_str).to_html()
    html += '</div>'

    html += '<h2>Strength of Schedule & Victory</h2>'
    html += "<p><strong>SOS:</strong> Strength of Schedule - Difficulty of Schedule (<a href=https://hackastat.eu/en/learn-a-stat-strength-of-schedule-sos/>Learn More</a>)</p>"
    html += "<p><strong>SOV:</strong> Strength of Victory - Combined Win-Loss percentage of defeated opponents</p>"
    html += "<p><strong>Exp Wins:</strong> Expected Wins (vs Actual), used Pythagorean Expectation to estimate wins based on PF and PA</p>"
    html += '<p>*Sorted by SOS</p>'
    html += '<div class="table-scroll">'
    html += schedule_stats.schedule_metrics(season_str).to_html()
    html += '</div>'

    # All-Play Stats
    html += '<h2>Records vs Every Schedule</h2>'
    html += '<p>Left to right - All teams (columns) compared to 1 schedule (row) </p>'
    html += '<p>Top to bottom - 1 team (column) compared to every schedule (row)</p> '
    html += '<div class="table-scroll">'
    html += schedule_stats.schedule_compare(season_str).to_html(index=False)
    html += '</div>'
    lines = html.split("\n")
    
    # Make first row and column freeze on scroll
    for i, line in enumerate(lines):
        if "<td>" in line:
            line = line.replace("<td>", '<td class="first-col">', 1)
            lines[i] = line
    new_html = "\n".join(lines)
    formal_season = league_data.get_formal_season(season_str)
    output = htmb.add_front_matter(new_html, f'Schedule Stats {formal_season}')
    with open(f'./docs/{season_str}/schedule/index.html', 'w') as f:
        f.write(output)