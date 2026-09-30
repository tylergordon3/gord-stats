"""
The NFL team pages (nfl.site.teams) on a four-team league: the table the
ranks come from (ties, the TBD playoff placeholder, a record as of a date),
the projected record beside ESPN's, the advanced block and its bridge from
nflverse's abbreviations, the schedule (results, projections, the margin on
record before kickoff), the pages written, and the Team Stats page linking
to them once they exist. No network.
"""
import re

import pandas as pd
import pytest

from gordstats import favorites
from nfl.site import stats as stats_page_mod
from nfl.site import teams

from test_nfl_power import TEAMS, Model, espn_rows, season_frame


@pytest.fixture(autouse=True)
def _nfl_stars(monkeypatch):
    # gordstats.favorites must list "nfl" (test_nfl_power says so on its own).
    if "nfl" not in favorites.SPORTS:
        monkeypatch.setattr(favorites, "SPORTS", favorites.SPORTS + ("nfl",))


def test_standings_rank_every_real_team_on_the_schedule():
    table = teams.standings(season_frame(), Model(), TEAMS)
    assert list(table["team"]) == ["12", "28", "25", "13"]           # TBD is nobody
    assert list(table["rank"]) == [1, 2, 3, 4]
    kc = table.iloc[0]
    assert (kc["wins"], kc["losses"], kc["ties"], kc["abbr"]) == (1, 0, 0, "KC")


def test_a_tie_is_a_tie_and_asof_counts_only_what_was_played_by_then():
    frame = season_frame()
    frame.loc[0, ["home_score", "away_score", "actual_margin"]] = [20, 20, 0]
    table = teams.standings(frame, Model(), TEAMS).set_index("team")
    assert (table.loc["12", "wins"], table.loc["12", "ties"]) == (0, 1)
    assert teams.record_text(0, 0, 1) == "0-0-1"
    early = teams.standings(frame, Model(), TEAMS, asof=pd.Timestamp("2026-09-01T00:00Z"))
    assert early[["wins", "losses", "ties"]].to_numpy().sum() == 0


def test_expected_record_is_results_plus_win_chances():
    frame = season_frame()
    wins, losses = teams.expected_record(frame, "12")
    p = 1 - frame.loc[2, "home_win_prob"]                 # KC away at SF in Week 2
    assert wins == pytest.approx(1 + p) and losses == pytest.approx(1 - p)


def test_the_projected_record_quotes_both_sources():
    html = teams._record_table(season_frame(), "12", espn_rows())
    assert "GordStats" in html and "ESPN FPI" in html and "11.9&ndash;5.0" in html
    # A team ESPN has nothing for gets ours alone.
    assert "ESPN FPI" not in teams._record_table(season_frame(), "28", espn_rows())


def adv_data():
    base = {k: None for k, *_ in teams._ADVANCED}

    def team(abbr, name, off, dfn, to):
        return {**base, "abbr": abbr, "name": name, "off_adj": off, "def_adj": dfn,
                "off_to": to, "off_sr": 0.45}
    return {"through_week": 3, "teams": [
        team("KC", "Chiefs", 0.17, 0.02, 0.06),
        team("WAS", "Commanders", 0.05, -0.10, 0.02),       # nflverse's WAS is ESPN's WSH
        team("SF", "49ers", 0.20, 0.05, 0.10),
        team("LV", "Raiders", -0.10, 0.12, 0.04)]}


def test_advanced_ranks_bridge_nflverse_and_turn_each_figure_the_right_way():
    ranks, week = teams.advanced_ranks(TEAMS, adv_data())
    assert week == 3 and set(ranks) == {"12", "28", "25", "13"}
    assert ranks["25"]["off_adj"] == (0.20, 1, 4)            # high is good
    assert ranks["28"]["def_adj"] == (-0.10, 1, 4)           # low is good
    assert ranks["28"]["off_to"] == (0.02, 1, 4)             # fewest giveaways
    assert ranks["12"]["off_sr"][2] == 4
    html = teams._advanced_block(ranks["12"], week)
    assert "Offense EPA/play" in html and "+0.17" in html and "2nd of 4" in html
    assert "href='/nfl/stats/'" in html and "through Week 3" in html
    assert teams._advanced_block({}) == ""


def test_the_schedule_reads_results_projections_and_the_call_on_record():
    frame = season_frame()
    record = {"1": {"pred_margin": 9.5}}                    # KC-LV, before kickoff
    html = teams._schedule_rows(frame, "12", TEAMS, record)
    rows = re.findall(r"<tr.*?</tr>", html.split("<tbody>")[1])
    assert len(rows) == 2                                    # the TBD playoff game is not KC's
    lv, sf = rows
    assert "vs <a href='/nfl/teams/raiders/'>Raiders</a>" in lv
    assert "W 24&ndash;10" in lv and "<td>+9.5</td>" in lv   # on record, not the refit
    assert "data-fav=\"nfl:13\"" in lv                       # keyed on the opponent
    assert "at <a href='/nfl/teams/49ers/'>49ers</a>" in sf and "proj " in sf
    assert re.search(r"<td>\d+%</td></tr>$", sf)
    assert "combiner/i?img=/i/teamlogos/nfl/500/lv.png" in lv


def test_the_week_cell_names_the_playoff_round():
    assert teams.week_label(5, 2) == "5" and teams.week_label(1, 3) == "WC"
    assert teams.week_label(5, 3) == "SB"


def test_generate_writes_a_page_per_team(monkeypatch, tmp_path):
    frame = season_frame()
    monkeypatch.setattr(teams, "OUT_DIR", tmp_path)
    monkeypatch.setattr(teams.predict, "season", lambda asof=None: (frame, Model(), TEAMS))
    monkeypatch.setattr(teams.fpi, "by_id", lambda refresh=False: espn_rows())
    monkeypatch.setattr(teams.advanced, "refresh", lambda: adv_data())
    monkeypatch.setattr(teams, "_on_record", lambda: {})
    teams.generate()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["49ers", "chiefs", "commanders",
                                                         "raiders"]
    page = (tmp_path / "chiefs" / "index.html").read_text()
    assert "title: Kansas City Chiefs" in page                # ESPN's full name
    assert "1&ndash;0 &middot; 1st of 4" in page and "Rated <b>+5.0</b>" in page
    assert "AFC West" in page and "<h3>Advanced</h3>" in page and "<h3>Schedule</h3>" in page
    # No FPI row for Washington: the nickname is the title.
    assert "title: Commanders" in (tmp_path / "commanders" / "index.html").read_text()


def test_team_stats_link_to_the_pages_that_exist(monkeypatch, tmp_path):
    monkeypatch.setattr(teams, "OUT_DIR", tmp_path)
    (tmp_path / "chiefs").mkdir()
    (tmp_path / "chiefs" / "index.html").write_text("x")
    rows = {r["abbr"]: r for r in stats_page_mod.rows(
        {"teams": [{"abbr": "KC", "name": "Chiefs", "w": 1, "l": 0},
                   {"abbr": "LV", "name": "Raiders", "w": 0, "l": 1}]})}
    assert rows["KC"]["link"] == "/nfl/teams/chiefs/" and rows["LV"]["link"] is None
