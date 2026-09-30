"""
CBB team stats (cbb.render.render_stats): Torvik's T-Rank table and, once he
publishes it, his four-factors file, on the shared stats table.
"""
import os
import time

import pandas as pd

from cbb.render import render_stats

FF = ("TeamName,eFG%,Rk,eFG% Def,Rk,FTR,Rk,FTR Def,Rk,OR%,Rk,DR%,Rk,TO%,Rk,TO% Def.,Rk,3P%,rk,3pD%,rk,"
      "2p%,rk,2p%D,rk,ft%,rk,ft%D,rk,3P rate,rk,3P rate D,rk,arate,rk,arateD,rk\n"
      "Duke,56.1,3,45.2,10,33.0,50,25.1,20,35.5,30,75.0,12,14.1,20,19.0,40,37.0,30,31.0,15,"
      "57.0,5,45.0,8,75.5,40,70.0,100,40.0,120,35.0,90,55.0,80,48.0,70\n")


def _trank(played=False):
    return pd.DataFrame([{
        "rank": 1, "team": "Duke", "conf": "ACC", "record": "3-1" if played else "0-0",
        "adjoe": 120.8, "adjde": 91.0, "barthag": 0.963, "adjt": 69.3, "proj. W": 25.8,
        "Proj. L": 6.2, "Pro Con W": 14.3, "Pro Con L": 3.7, "sos": 0.61, "ncsos": 0.55,
        "Proj. SOS": 0.72, "Proj. Noncon SOS": 0.61, "WAB": 2.5}])


def test_the_four_factors_file_is_values_between_ranks(tmp_path, monkeypatch):
    cache = tmp_path / "ff.csv"
    cache.write_text(FF)
    monkeypatch.setattr(render_stats, "FF_CACHE", cache)
    os.utime(cache, (time.time(), time.time()))                  # fresh: no fetch
    got = render_stats.four_factors()["Duke"]
    assert got["efg"] == 0.561 and got["efg_d"] == 0.452 and got["tov_d"] == 0.19
    assert got["ast_d"] == 0.48 and len(got) == len(render_stats.FF_FIELDS)


def test_preseason_rows_use_the_projections(monkeypatch):
    monkeypatch.setattr(render_stats.render_power, "star_teams", lambda names: {})
    row = render_stats.rows(_trank(), {})[0]
    assert row["net"] == 29.8 and row["proj"] == "26-6" and row["conf_proj"] == "14-4"
    assert row["sos"] == 0.72 and row["rec"] is None and row["wab"] is None
    assert row["tags"] == ["Power"]
    keys = [c["key"] for c in render_stats.columns(have_ff=False, played=False)]
    assert "rec" not in keys and "wab" not in keys and "efg" not in keys


def test_in_season_rows_add_the_record_and_four_factors(monkeypatch):
    monkeypatch.setattr(render_stats.render_power, "star_teams", lambda names: {})
    row = render_stats.rows(_trank(played=True), {"Duke": {"efg": 0.561}})[0]
    assert row["rec"] == "3-1" and row["sos"] == 0.61 and row["wab"] == 2.5 and row["efg"] == 0.561
    keys = [c["key"] for c in render_stats.columns(have_ff=True, played=True)]
    assert "rec" in keys and "efg_d" in keys
