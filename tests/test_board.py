"""
ADP board invariants.

Covers three failures that shipped: movers appearing in both lists, a new
source showing a header with no data under it, and the page dying on a cached
parquet written before a column existed.

Also guards kicker and defense coverage. They were excluded from the board for
a while; the live draft board grades every pick against this table, so a pick it
has no row for is a pick it cannot say anything about.
"""

import pandas as pd
import pytest

from fantasy.league import adp_board
from fantasy.site import draft_live, upcoming


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


def test_board_keeps_kickers_and_defenses(tmp_path, monkeypatch):
    """Both of them survive the whole way to a caller, cache included.

    The exclusion had to be undone in two places — the fetch and the cached
    read — and undoing only the fetch would have kept serving a filtered board
    from the parquet until it aged out twelve hours later.
    """
    served = _serve_cached(monkeypatch, tmp_path, _streamer_board())
    assert set(served["pos"]) == {"WR", "DST", "RB", "K", "TE"}
    assert {"Houston Texans", "Brandon Aubrey"} <= set(served["player"])


def test_kickers_and_defenses_keep_their_pick_numbers(tmp_path, monkeypatch):
    """Ovr is where a player actually goes in a draft where somebody takes the
    kicker, so with nothing dropped the column reads straight through."""
    served = _serve_cached(monkeypatch, tmp_path, _streamer_board())
    assert list(served["Ovr"]) == [1, 2, 3, 4, 5]


def test_position_filters_cover_exactly_what_the_board_holds():
    """Both pages that draw the board filter it by the same set of positions.

    A missing chip hides those rows behind a filter nothing can select, and a
    chip for a position the board does not carry filters the table to nothing.
    The two lists are written out separately, one per page, so this is what
    stops them drifting apart.
    """
    assert set(upcoming.POSITIONS) == {"QB", "RB", "WR", "TE", "K", "DST"}
    assert set(draft_live.POSITIONS) == set(upcoming.POSITIONS)


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
