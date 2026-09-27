"""The CFB board stops moving at the draft for anything that grades the draft
or adds the season on top itself.

After the draft Yahoo's rank order becomes season-to-date form - #1 flipped
from Jeremiah Smith to Nate Sheppard on 2026-09-24 - so draft review graded
Arch Manning (pick 14) as a 367-place reach, and league power added the season
to a board that already held it.
"""
import pandas as pd
import pytest
import requests


@pytest.fixture
def offline(monkeypatch):
    def blocked(*a, **k):
        raise RuntimeError("network blocked in tests")
    monkeypatch.setattr(requests, "get", blocked)
    monkeypatch.setattr(requests.Session, "request", blocked)


def test_the_frozen_value_board_never_reads_the_drifting_one(monkeypatch, offline):
    from cfb import projections, yahoo

    monkeypatch.setattr(yahoo, "board", lambda **k: (_ for _ in ()).throw(
        AssertionError("the in-season board was priced")))
    board = projections.value_board(frozen=True)
    manning = board[board["player"].str.contains("Arch Manning")]
    assert not manning.empty and int(manning["value_rank"].iloc[0]) <= 30


def test_board_snapshots_stop_once_the_draft_has_happened(tmp_path, monkeypatch):
    from cfb import yahoo

    monkeypatch.setattr(yahoo, "DATA_DIR", tmp_path)
    monkeypatch.setattr(yahoo, "_fetch_board", lambda: pd.DataFrame({"player": ["x"]}))
    monkeypatch.setattr(yahoo, "_drafted", lambda: True)
    yahoo.board(refresh=True)
    assert not (tmp_path / "adp_history").exists()

    monkeypatch.setattr(yahoo, "_drafted", lambda: False)
    yahoo.board(refresh=True)
    assert len(list((tmp_path / "adp_history").glob("*.parquet"))) == 1
