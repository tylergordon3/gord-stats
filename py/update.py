import median
import schedule
import bestball
import player_db
import players_to_json
import html_builder as htmb
# median_main -> args: bool update_all
#   Calculates median for every week if true
#   Always generates the landing page

# schedule_main -> args: bool update_all
#   If true - updates and saves rosters with schedule data
#   Always calculates and saves the all schedules table

# bestball_main -> args: bool update_all
#   If true - Updates all best ball pages
#   Always generates landing page

# update_all = True
update_all = False
players_to_json.player_json()
player_db.scrape_injuries()
median.median_main(update_all)
bestball.bestball_main(update_all)
schedule.schedule_main(update_all)
htmb.generate_index()