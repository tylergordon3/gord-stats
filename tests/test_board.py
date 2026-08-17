"""
ADP board invariants.

Covers three failures that shipped: movers appearing in both lists, a new
source showing a header with no data under it, and the page dying on a cached
parquet written before a column existed.

Also guards the kicker/defense exclusion, which has two halves that are easy to
get wrong separately: the rows have to go, and the pick numbers have to stay.
"""

import pandas as pd
import pytest

from fantasy.league import adp_board
from fantasy.site import upcoming


def _frame(moves):
    """Minimal board frame with a Move column."""
    col = adp_board.WINDOWS["last"]["move"]
    return pd.DataFrame({
        "player": [f"P{i}" for i in range(len(moves))],
        col: moves,
    })


def test_movers_split_by_direction_not_just_sort(monkeypatch):
    """The bug: with fewer movers than n, head() returned the same rows to both
    lists, so one player was a riser AND a faller — and _mover_items renders
    abs(move) with a fixed arrow, so the faller pointed up."""
    monkeypatch.setattr(adp_board, "board", lambda *a, **k: _frame([3.0, -2.0, 0.0]))
    risers, fallers = adp_board.movers(2026, n=8, min_move=0.5)

    assert list(risers["player"]) == ["P0"]
    assert list(fallers["player"]) == ["P1"]
    assert not set(risers["player"]) & set(fallers["player"])


def test_movers_ignore_moves_under_the_threshold(monkeypatch):
    monkeypatch.setattr(adp_board, "board", lambda *a, **k: _frame([0.2, -0.1]))
    risers, fallers = adp_board.movers(2026, n=8, min_move=0.5)
    assert risers.empty and fallers.empty


def test_every_source_reaches_the_table():
    """The bug: _FIELDS listed the site columns by name, so a source added to
    SOURCES got a header (built from SOURCES) with no column behind it."""
    for source in adp_board.SOURCES:
        assert source in upcoming._FIELDS, f"{source} is in SOURCES but not in the table"


def test_table_column_indices_line_up():
    """The JS addresses row cells by index; a mismatch silently shifts a column."""
    for source in adp_board.SOURCES:
        assert upcoming._FIELDS.index(source) >= 0
    for key in ("Avg", "Spread", "Ovr", "Pick", "PosRk"):
        assert key in upcoming._FIELDS
    for spec in adp_board.WINDOWS.values():
        assert spec["move"] in upcoming._FIELDS


def test_spread_needs_several_sites_not_all_of_them():
    """Yahoo's board is shorter than the others; requiring every site would cut
    the comparable window down to Yahoo's depth."""
    assert adp_board.SPREAD_MIN_SITES >= 2
    assert adp_board.SPREAD_MIN_SITES <= len(adp_board.SOURCES)


def test_cached_board_missing_a_source_is_treated_as_stale(tmp_path, monkeypatch):
    """The bug: board() served a parquet written before a column existed, and
    every consumer selects sources by name, so the homepage died on KeyError
    until the cache aged out."""
    cache = tmp_path / "board_2026.parquet"
    stale = pd.DataFrame({"merge_name": ["x"], "Avg": [1.0]})
    for col in list(adp_board.SOURCES)[:-1]:          # every source but one
        stale[col] = [1.0]
    stale.to_parquet(cache, index=False)

    monkeypatch.setattr(adp_board, "_cache_path", lambda year: cache)
    monkeypatch.setattr(adp_board, "_seed_history", lambda year: None)

    refetched = {"called": False}

    def _fake_fetch(year):
        refetched["called"] = True
        df = stale.copy()
        df[list(adp_board.SOURCES)[-1]] = [1.0]
        return df

    monkeypatch.setattr(adp_board, "_fetch_board", _fake_fetch)
    monkeypatch.setattr(adp_board, "_with_movement", lambda df, year: df)
    monkeypatch.setattr(adp_board, "_write_snapshot", lambda df, year: None)

    adp_board.board(2026)
    assert refetched["called"], "a cache missing a SOURCES column must be refetched"


# --------------------------------------------------------------------------- #
# Kickers and defenses
# --------------------------------------------------------------------------- #

def _streamer_board():
    """A board with a kicker and a defense in the middle of it."""
    return pd.DataFrame({
        "merge_name": ["a", "hou", "b", "aubrey", "c"],
        "player": ["A", "Houston Texans", "B", "Brandon Aubrey", "C"],
        "pos": ["WR", "DST", "RB", "K", "TE"],
        "Avg": [1.0, 2.0, 3.0, 4.0, 5.0],
        "Ovr": [1, 2, 3, 4, 5],
        **{col: [1.0] * 5 for col in adp_board.SOURCES},
    })


def _serve_cached(monkeypatch, tmp_path, df):
    """Point board() at a fresh parquet holding df, with no network in reach."""
    cache = tmp_path / "board_2026.parquet"
    df.to_parquet(cache, index=False)
    monkeypatch.setattr(adp_board, "_cache_path", lambda year: cache)
    monkeypatch.setattr(adp_board, "_seed_history", lambda year: None)
    monkeypatch.setattr(adp_board, "_fetch_board",
                        lambda year: pytest.fail("cache was fresh; should not refetch"))
    return adp_board.board(2026)


def test_board_leaves_out_kickers_and_defenses(tmp_path, monkeypatch):
    served = _serve_cached(monkeypatch, tmp_path, _streamer_board())
    assert set(served["pos"]) == {"WR", "RB", "TE"}
    assert "Houston Texans" not in set(served["player"])


def test_a_cache_written_before_the_exclusion_is_still_filtered(tmp_path, monkeypatch):
    """The parquet is refetched twice a day at most, so filtering only in
    _fetch_board would have left kickers on the page until it aged out."""
    served = _serve_cached(monkeypatch, tmp_path, _streamer_board())
    assert not served["pos"].isin(adp_board.STREAMER_POS).any()


def test_dropping_streamers_does_not_renumber_the_picks(tmp_path, monkeypatch):
    """Ovr is where a player actually goes in a draft where somebody takes the
    kicker. Renumbering 1..N without them would have moved everyone below the
    first defense up by a pick per row dropped — four rounds by the tail."""
    served = _serve_cached(monkeypatch, tmp_path, _streamer_board())
    assert list(served["Ovr"]) == [1, 3, 5], "a gap in Ovr is the K or DST that went there"


def test_position_filters_cover_exactly_what_the_board_holds():
    """A chip for an excluded position filters the table down to nothing."""
    assert not set(upcoming.POSITIONS) & set(adp_board.STREAMER_POS)
    assert set(upcoming.POSITIONS) == {"QB", "RB", "WR", "TE"}


def test_a_board_without_a_pos_column_survives_the_filter():
    """Caches predating the slot columns have no pos to match on."""
    bare = pd.DataFrame({"merge_name": ["x"], "Avg": [1.0]})
    assert len(adp_board._drop_streamers(bare)) == 1


# --------------------------------------------------------------------------- #
# Scheduled tasks
# --------------------------------------------------------------------------- #

def test_cbb_task_is_registered_and_refuses_to_run_out_of_season():
    """_cbb() used to raise NotImplementedError. Now it is wired, but the feeds
    keep serving last season's numbers in the off-season, so turning `cbb` on
    in September must not republish March's bracket as if it were current."""
    import io
    import contextlib
    from datetime import date, timedelta

    from cbb.render.render_home import CBB_SEASON_END, CBB_TIPOFF
    from gordstats import daily

    assert "cbb" in daily.TASKS

    if CBB_TIPOFF <= date.today() <= CBB_SEASON_END:
        pytest.skip("in season — the guard is not the path under test today")

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        daily.TASKS["cbb"]()
    assert "season" in buf.getvalue().lower(), \
        "out of season, _cbb() must decline rather than rebuild from stale feeds"


def test_every_task_in_the_table_is_callable():
    from gordstats import daily

    for name, fn in daily.TASKS.items():
        assert callable(fn), f"task {name} is not callable"
