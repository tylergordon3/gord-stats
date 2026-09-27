"""The season being played is not graded as if it were over.

Two weeks in, 2026-27 was counted against a fourteen-week window: healthy
stars led the injury list (Josh Allen "11 games missed"), 69 drafted players
"sat out too much of the season", Exp W scaled two games up to fourteen, and
the draft recap listed the season twice.
"""
import pytest


def test_the_live_season_is_over_only_once_sleepers_clock_passes_week_14(monkeypatch):
    from fantasy.league import matchups

    for over, expected in ((2, False), (13, False), (14, True), (99, True), (None, False)):
        monkeypatch.setattr(matchups, "weeks_over", lambda year, o=over: o)
        assert matchups.regular_season_over("2627") is expected, over


def test_a_past_season_is_over_without_asking_sleeper(monkeypatch):
    from fantasy.league import matchups

    def ask(year):
        raise AssertionError("a finished season needs no request")

    monkeypatch.setattr(matchups, "weeks_over", ask)
    assert matchups.regular_season_over("2526")
    assert matchups.played_seasons(["2526", "2425"]) == ["2526", "2425"]


def test_the_injury_archive_skips_the_season_being_played(monkeypatch):
    from fantasy.league import matchups
    from fantasy.site import injuries

    monkeypatch.setattr(matchups, "weeks_over", lambda year: 2)
    kept = injuries._played({"2026-2027": {}, "2025-2026": {}})
    assert list(kept) == ["2025-2026"]


def test_draft_values_grade_only_played_seasons(monkeypatch):
    from fantasy.league import matchups
    from fantasy.site import adp

    monkeypatch.setattr(matchups, "weeks_over", lambda year: 2)
    assert "2627" not in adp._graded()


def test_expected_wins_count_the_games_actually_played():
    """2026-27 has two weeks on file: nobody can expect more than two wins."""
    from fantasy.site import schedule

    table = schedule.schedule_metrics("2627").data
    expected = table["Exp W (Actual)"].str.extract(r"^([\d.]+)")[0].astype(float)
    assert expected.max() <= 2.0 + 1e-9, table


@pytest.mark.parametrize("over, count", [(2, 1), (14, 1)])
def test_the_draft_recap_lists_each_season_once(monkeypatch, over, count):
    from fantasy.config import UPCOMING_SEASON
    from fantasy.league import matchups
    from fantasy.site import draft_current, draft_recap

    monkeypatch.setattr(matchups, "weeks_over", lambda year: over)
    monkeypatch.setattr(draft_current, "view", lambda: "")
    monkeypatch.setattr(draft_recap, "_season_view", lambda s: "")
    html = draft_recap.body()
    assert html.count(f">{UPCOMING_SEASON}<") == count, html[:2000]
