import schedule
import data_manager
import html_builder as htmb
import draft

data_manager.main(season_str='2526', season='2025')
data_manager.main(season_str='2425', season='2024')
data_manager.main(season_str='2324', season='2023')

draft.main(season_str='2526')
draft.main(season_str='2425')
draft.main(season_str='2324')

schedule.schedule_main(season_str='2526')
schedule.schedule_main(season_str='2425')
schedule.schedule_main(season_str='2324')
htmb.generate_index()