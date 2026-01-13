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

update_all = False

data_manager.main()

#median.median_main(update_all)
#bestball.bestball_main(update_all)

schedule.schedule_main()
htmb.generate_index()