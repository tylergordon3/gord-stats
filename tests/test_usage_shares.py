"""A share on the usage page is a share of the TEAM's total, quarterback
included. The fantasy page used to drop QBs before summing the team, so every
back's carry share was his share of the non-QB carries: James Cook read 92%
against a real 60%. The college page already did it in the right order.
"""
import pandas as pd
import pytest

from fantasy.league.usage import STATS


def _row(player, pos, rush_att=0, rec_tgt=0):
    row = {stat: 0.0 for stat in STATS}
    row.update(week=1, sleeper_id=player, player=player, pos=pos, team="BUF",
               opp="MIA", rush_att=float(rush_att), rec_tgt=float(rec_tgt),
               off_snp=50.0, tm_off_snp=60.0)
    return row


def test_a_backs_carry_share_counts_his_quarterbacks_carries():
    from fantasy.site import usage

    frame = pd.DataFrame([_row("qb", "QB", rush_att=10),
                          _row("rb", "RB", rush_att=10, rec_tgt=2),
                          _row("wr", "WR", rec_tgt=8)])
    recent, season = usage.share_tables(frame)

    assert set(recent["pos"]) == {"RB", "WR"}, "QBs are still left off the table"
    rb = recent.set_index("player").loc["rb"]
    assert rb["car_share"] == pytest.approx(0.5)
    assert season.set_index("player").loc["rb", "car_share"] == pytest.approx(0.5)
