"""
Games-missed is archived once per finished season, not four times a day.

This step took the fantasy section down in 6 of 29 scheduled runs in the week
to 2026-09-25, and five of those six failed on a season that ended months ago:
it re-fetched every season's draft, rosters and users from Sleeper on every
run, and api.sleeper.app drops the occasional TLS handshake. Retries reduced
the rate; not asking removes it.

These tests run offline - anything that reaches Sleeper here is the bug.
"""
import pytest

from fantasy import archive
from fantasy.config import FORMAL_SEASON, UPCOMING_SEASON
from fantasy.site import draft


@pytest.fixture
def no_network(monkeypatch):
    """Any Sleeper call at all fails the test that made it."""
    def forbidden(*args, **kwargs):
        raise AssertionError("this reached Sleeper")

    monkeypatch.setattr(draft, "_season_rosters", forbidden)
    monkeypatch.setattr(draft, "_season_picks", forbidden)
    monkeypatch.setattr(draft, "_build", forbidden)


def test_the_live_season_is_the_only_unfinished_one():
    live = [s for s in FORMAL_SEASON if not draft.is_finished(s)]
    assert live == [s for s, formal in FORMAL_SEASON.items()
                    if formal == UPCOMING_SEASON]
    assert len(live) == 1, f"expected exactly one season in play, got {live}"


def test_a_finished_season_already_archived_is_skipped(no_network, monkeypatch, capsys):
    monkeypatch.setattr(archive, "has_statistic", lambda season, *stats: True)
    draft.save_games_missed("2324")
    assert "already archived" in capsys.readouterr().out


def test_a_finished_season_not_yet_archived_is_built(monkeypatch):
    """The skip is about not repeating work, not about refusing it."""
    monkeypatch.setattr(archive, "has_statistic", lambda season, *stats: False)
    monkeypatch.setattr(draft, "_build", lambda s, **k: (_ for _ in ()).throw(
        RuntimeError("built")))
    with pytest.raises(RuntimeError, match="built"):
        draft.save_games_missed("2324")


def test_the_season_being_played_is_not_archived_mid_season(monkeypatch):
    """Games missed are out of the whole regular season's window: two weeks in,
    every healthy starter read as having missed eleven games."""
    from fantasy.league import matchups

    live = next(s for s in FORMAL_SEASON if not draft.is_finished(s))
    monkeypatch.setattr(matchups, "weeks_over", lambda year: 2)
    monkeypatch.setattr(draft, "_build", lambda s, **k: (_ for _ in ()).throw(
        AssertionError("a season two weeks old was archived")))
    draft.save_games_missed(live)


def test_the_live_season_is_never_skipped_once_its_regular_season_is_over(monkeypatch):
    """From then until the rollover its rosters and transactions can still move."""
    from fantasy.league import matchups

    live = next(s for s in FORMAL_SEASON if not draft.is_finished(s))
    monkeypatch.setattr(matchups, "weeks_over", lambda year: 14)
    monkeypatch.setattr(archive, "has_statistic", lambda season, *stats: True)
    monkeypatch.setattr(draft, "_build", lambda s, **k: (_ for _ in ()).throw(
        RuntimeError("built")))
    with pytest.raises(RuntimeError, match="built"):
        draft.save_games_missed(live)


def test_force_re_derives_a_finished_season(monkeypatch):
    """For when the calculation changes rather than the data."""
    monkeypatch.setattr(archive, "has_statistic", lambda season, *stats: True)
    monkeypatch.setattr(draft, "_build", lambda s, **k: (_ for _ in ()).throw(
        RuntimeError("built")))
    with pytest.raises(RuntimeError, match="built"):
        draft.save_games_missed("2324", force=True)


def test_both_statistics_must_be_present_to_count_as_done():
    """Half an archive is not an archive - a run that died between the two
    writes must be finished, not skipped."""
    assert draft.GAMES_MISSED_STATS == ("missing_df", "injury_detail_df")
    assert archive.has_statistic("2324", *draft.GAMES_MISSED_STATS)
    assert not archive.has_statistic("2324", "missing_df", "a_statistic_we_never_wrote")


def test_the_two_consumers_share_one_fetch(monkeypatch):
    """`_build` and `_pickup_detail` each used to fetch the league, its users,
    its rosters and its draft picks for themselves - eight calls where four
    would do, for every season on every run."""
    import inspect

    source = inspect.getsource(draft)
    body = source[source.index("def _build("):]
    for direct in ("League(LEAGUE_IDS[", "Drafts(DRAFT_IDS["):
        assert direct not in body, (
            f"{direct} is fetched below the cached helpers; both consumers "
            "must go through _season_rosters / _season_picks")
