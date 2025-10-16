'''
    This module fetches general NFL and player stats. 
'''
import nflreadpy as nfl
import pandas as pd
import constants as c


def get(week) -> pd.DataFrame:
    """Returns NFL fantasy player stats for a given week.

    :param week: Week of (current) NFL season to get stats for
    :type week: int
    :return: DataFrame with a wholllleee lotttaaa data
    :rtype: pd.DataFrame
    """
    # Load player game-level stats for multiple seasons
    player_stats = nfl.load_player_stats(nfl.get_current_season(), 'week')

    # nflreadpy uses Polars instead of pandas. Convert to pandas if needed:
    p_stats = player_stats.to_pandas()
    p_stats.columns = c.player_stats_headers
    pos_groups_remove = ["LB", "DL", "OL", "DB", "None"]
    spec_teams_remove = ["P", "LS"]
    p_stats_filter = p_stats[~p_stats.position_group.isin(pos_groups_remove)]
    p_stats = p_stats_filter[~p_stats_filter.position.isin(spec_teams_remove)]

    this_week = p_stats[p_stats['week'] == week]

    return this_week
