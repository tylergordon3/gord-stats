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

    class Response:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"standings": standings}

    monkeypatch.setattr(external.requests, "get", lambda *a, **k: Response())
    monkeypatch.setattr(external, "team_names", lambda league_id: {})
    rows = external.fetch("nfl~abc", league_id="x")
    assert [r["score"] for r in rows] == [100, 98, 79]


def test_team_names_fold_across_encoders():
    """Curly quotes survive Sleeper but not FantasyPros; the audit must not care."""
    assert external._key("Brooklyn “Nine”-9") == external._key('Brooklyn "Nine"-9')
    assert external._key("Lotta Cox (Balls Too)") == external._key("lotta  cox balls too")
