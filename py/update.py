import schedule
import data_manager
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

data_manager.main(season_str='2526', season='2025')
data_manager.main(season_str='2425', season='2024')

#median.median_main(update_all)
#bestball.bestball_main(update_all)
schedule.schedule_main(season_str='2526')
schedule.schedule_main(season_str='2425')
#htmb.generate_index()