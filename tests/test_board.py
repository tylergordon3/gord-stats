"""
ADP board invariants.

Covers three failures that shipped: movers appearing in both lists, a new
source showing a header with no data under it, and the page dying on a cached
parquet written before a column existed.
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
