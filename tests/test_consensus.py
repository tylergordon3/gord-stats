"""
Blending rankings that disagree.

Two things matter here: that averaging happens on ratings rather than ranks,
which is the whole reason the module exists, and that the frozen draft
consensus stays frozen.
"""
import json

import numpy as np
import pandas as pd
import pytest

from fantasy.league import consensus


def test_centring_puts_the_league_average_at_100():
    out = consensus.centred(pd.Series([120.0, 100.0, 80.0]))
    assert out.mean() == pytest.approx(100.0)
    assert out.iloc[0] > out.iloc[1] > out.iloc[2]


def test_sources_are_centred_before_averaging():
    """A source with wider units must not get a louder vote for that reason."""
    ours = pd.Series({1: 110.0, 2: 100.0, 3: 90.0})
    theirs = ours * 1000.0                       # same opinion, different units
    out = consensus.blend({"us": ours, "them": theirs})
    assert out["combined"].tolist() == pytest.approx(consensus.centred(ours).sort_values(
        ascending=False).tolist())


def test_the_blend_keeps_the_size_of_a_disagreement():
    """Averaging ranks would call this a tie; averaging ratings does not."""
    ours = pd.Series({1: 101.0, 2: 100.0, 3: 99.0})
    theirs = pd.Series({1: 130.0, 2: 100.0, 3: 70.0})
    out = consensus.blend({"us": ours, "them": theirs})
    gaps = out["combined"].to_numpy()
    assert gaps[0] - gaps[1] > 5.0               # not the 1-point gap ours alone sees


def test_weights_shift_the_result_toward_the_heavier_source():
    ours = pd.Series({1: 110.0, 2: 90.0})
    theirs = pd.Series({1: 90.0, 2: 110.0})
    even = consensus.blend({"us": ours, "them": theirs})["combined"]
    tilted = consensus.blend({"us": ours, "them": theirs}, {"us": 3.0, "them": 1.0})["combined"]
    assert even[1] == pytest.approx(even[2])     # a dead heat
    assert tilted[1] > tilted[2]                 # ours breaks it


def test_combined_falls_back_to_our_own_number_when_the_source_is_missing():
    table = pd.DataFrame({"roster_id": [1, 2], "power": [110.0, 90.0]})
    out = consensus.combined(table, pd.DataFrame(columns=["roster_id", "ext_vorp"]))
    assert out["combined"].tolist() == pytest.approx([110.0, 90.0])
    assert out["combined_rank"].tolist() == [1, 2]


def test_a_roster_the_source_does_not_carry_keeps_our_rating():
    """One missing team must not drag its own row toward the league mean."""
    table = pd.DataFrame({"roster_id": [1, 2], "power": [110.0, 90.0]})
    ext = pd.DataFrame({"roster_id": [1], "ext_vorp": [110.0]})
    out = consensus.combined(table, ext)
    assert out["combined"].notna().all()


def test_the_frozen_draft_consensus_refuses_to_overwrite_itself(tmp_path, monkeypatch):
    path = tmp_path / "draft_consensus.json"
    path.write_text(json.dumps({"frozen": "2026-08-28", "teams": [{"rank": 1}]}),
                    encoding="utf-8")
    monkeypatch.setattr(consensus, "draft_path", lambda year=2026: path)

    def explode(*a, **k):
        raise AssertionError("freeze() recomputed a frozen consensus")
    monkeypatch.setattr(consensus, "footballers", explode)

    assert consensus.freeze(2026)["frozen"] == "2026-08-28"


def test_a_missing_draft_consensus_is_an_absent_section(tmp_path, monkeypatch):
    monkeypatch.setattr(consensus, "draft_path", lambda year=2026: tmp_path / "nope.json")
    assert consensus.draft(2026) == {}
