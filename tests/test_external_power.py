"""
The outside power-ranking column.

The column comes off a third-party endpoint, so the thing worth testing is not
that the fetch works — it will stop working one day without asking us — but
that every way it can fail leaves the page standing. These run offline.
"""
import json

import pytest

from fantasy.league import external


@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    """Point the module at a throwaway snapshot and never let it hit the wire."""
    path = tmp_path / "external.json"
    monkeypatch.setattr(external, "snapshot_path", lambda year=2026: path)
    return path


def _write(path, **over):
    body = {"source": "FantasyPros", "short": "FP", "label": "League Analyzer",
            "url": "https://example.invalid", "league_key": "nfl~abc", "season": 2026,
            "captured": "2026-08-28",
            "teams": [{"team": "A", "team_id": 3, "rank": 1, "score": 100, "vorp": 111.0},
                      {"team": "B", "team_id": 2, "rank": 2, "score": 79, "vorp": 87.8}]}
    body.update(over)
    path.write_text(json.dumps(body), encoding="utf-8")


def test_reads_a_snapshot_without_touching_the_network(snapshot):
    _write(snapshot)
    frame = external.load(2026, live=False)
    assert list(frame["roster_id"]) == [3, 2]
    assert list(frame["ext_rank"]) == [1, 2]
    assert frame.attrs["short"] == "FP"


def test_missing_snapshot_is_a_missing_column(snapshot):
    assert external.load(2026, live=False).empty


def test_malformed_snapshot_is_a_missing_column(snapshot):
    snapshot.write_text("{not json", encoding="utf-8")
    assert external.load(2026, live=False).empty


def test_a_snapshot_from_another_season_is_ignored(snapshot):
    """Last year's ratings against this year's rosters would be silent nonsense."""
    _write(snapshot, season=2025)
    assert external.load(2026, live=False).empty


def test_a_failed_fetch_falls_back_to_the_last_good_copy(snapshot, monkeypatch):
    _write(snapshot)
    def boom(*a, **k):
        raise external.requests.RequestException("upstream down")
    monkeypatch.setattr(external, "fetch", boom)

    frame = external.load(2026, live=True)
    assert list(frame["ext_rank"]) == [1, 2]
    assert frame.attrs["captured"] == "2026-08-28"
    assert json.loads(snapshot.read_text())["captured"] == "2026-08-28"


def test_a_fetch_rewrites_the_snapshot(snapshot, monkeypatch):
    _write(snapshot)
    fresh = [{"team": "B", "team_id": 2, "rank": 1, "score": 100, "vorp": 104.0},
             {"team": "A", "team_id": 3, "rank": 2, "score": 88, "vorp": 91.5}]
    monkeypatch.setattr(external, "fetch", lambda key, league_id=None: fresh)

    frame = external.load(2026, live=True)
    assert list(frame["roster_id"]) == [2, 3]
    assert json.loads(snapshot.read_text())["teams"] == fresh


def test_the_displayed_score_is_vorp_rescaled_to_the_leader(monkeypatch):
    """Verified against a hand-copy of the rendered table: all ten rows exact."""
    standings = [{"teamName": "A", "teamId": 3, "rank": 1, "vorpPerc": 111.01},
                 {"teamName": "B", "teamId": 2, "rank": 2, "vorpPerc": 108.25},
                 {"teamName": "C", "teamId": 8, "rank": 3, "vorpPerc": 87.80}]

    # The fetch goes through the retrying helper, which owns its own session -
    # so the stub replaces the helper rather than requests.get, which it no
    # longer calls.
    monkeypatch.setattr(external.sleeper_retry, "get_json",
                        lambda *a, **k: {"standings": standings})
    # The audit reads rosters, not names, since 2026-09-25 - see below.
    monkeypatch.setattr(external, "_sleeper_rosters", lambda league_id: {})
    rows = external.fetch("nfl~abc", league_id="x")
    assert [r["score"] for r in rows] == [100, 98, 79]


def test_names_fold_across_encoders():
    """Curly quotes survive Sleeper but not FantasyPros; folding must not care."""
    assert external._key("Brooklyn “Nine”-9") == external._key('Brooklyn "Nine"-9')
    assert external._key("Lotta Cox (Balls Too)") == external._key("lotta  cox balls too")


# --------------------------------------------------------------------------- #
# The id audit. It exists to catch a transposition; it must not cry wolf.
# --------------------------------------------------------------------------- #

def _grid(by_team: dict) -> dict:
    """An analyzer payload whose grid puts these players on these teamIds."""
    cells = [{"teamId": tid, "name": name}
             for tid, names in by_team.items() for name in names]
    return {"grid": [{"position": "Teams", "cells": []},
                     {"position": "QB", "cells": cells}]}


def _audit_output(monkeypatch, capsys, upstream, sleeper):
    monkeypatch.setattr(external, "_sleeper_rosters", lambda league_id: sleeper)
    external._audit(_grid(upstream), "x")
    return capsys.readouterr().out


def test_the_audit_is_silent_when_only_the_names_have_drifted(monkeypatch, capsys):
    """The false alarm this replaced. Three managers in this league renamed
    their teams; FantasyPros kept the names it last synced, and the old
    name-based check warned about all three on every build - for a join that
    was, on the rosters, exactly right."""
    upstream = {1: ["Josh Allen", "Bijan Robinson"], 2: ["Drake Maye", "Puka Nacua"]}
    sleeper = {1: {external._key(n) for n in ("Josh Allen", "Bijan Robinson")},
               2: {external._key(n) for n in ("Drake Maye", "Puka Nacua")}}
    assert _audit_output(monkeypatch, capsys, upstream, sleeper) == ""


def test_the_audit_still_catches_a_real_transposition(monkeypatch, capsys):
    """Which is the whole reason it exists: a swapped pair would read as a
    disagreement between two models rather than as a bug."""
    upstream = {1: ["Josh Allen", "Bijan Robinson"], 2: ["Drake Maye", "Puka Nacua"]}
    sleeper = {2: {external._key(n) for n in ("Josh Allen", "Bijan Robinson")},
               1: {external._key(n) for n in ("Drake Maye", "Puka Nacua")}}
    out = _audit_output(monkeypatch, capsys, upstream, sleeper)
    assert "teamId 1 looks like Sleeper roster 2" in out
    assert "teamId 2 looks like Sleeper roster 1" in out


def test_an_unrecognised_roster_is_not_reported_as_drift(monkeypatch, capsys):
    """A stale player table means names we cannot fold, not ids we cannot
    trust. Warning then would be noise on a build that is fine."""
    upstream = {1: ["Somebody Unknown"], 2: ["Another Stranger"]}
    sleeper = {1: {external._key("Josh Allen")}, 2: {external._key("Drake Maye")}}
    assert _audit_output(monkeypatch, capsys, upstream, sleeper) == ""


def test_the_audit_never_gates_a_build(monkeypatch, capsys):
    """It is a nicety. A failure inside it must not reach the caller."""
    def boom(league_id):
        raise ValueError("no rosters")

    monkeypatch.setattr(external, "_sleeper_rosters", boom)
    external._audit(_grid({1: ["Josh Allen"]}), "x")      # must not raise
    assert capsys.readouterr().out == ""


def test_the_upstream_roster_comes_off_the_grid_not_the_standings():
    """`standings` names teams; only the grid says which players are on them,
    and the players are what an id actually means."""
    payload = _grid({1: ["Josh Allen"], 2: ["Drake Maye"]})
    assert external._upstream_rosters(payload) == {
        1: {external._key("Josh Allen")}, 2: {external._key("Drake Maye")}}


def test_a_rosters_response_of_the_wrong_shape_is_nothing_to_check(monkeypatch):
    """Sleeper answers a league it does not know with something that is not a
    list. The audit must treat that as no information, not raise inside a
    build it has no business failing."""
    monkeypatch.setattr(external, "_player_names",
                        lambda: {"1": "Josh Allen"})
    monkeypatch.setattr(external.sleeper_retry, "get_json",
                        lambda *a, **k: {"error": "not found"})
    assert external._sleeper_rosters("x") == {}

    monkeypatch.setattr(external.sleeper_retry, "get_json",
                        lambda *a, **k: ["nonsense", {"roster_id": 1, "players": ["1"]}])
    assert external._sleeper_rosters("x") == {1: {external._key("Josh Allen")}}
