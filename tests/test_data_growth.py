"""The Pi commits data/ after every run, so a file rewritten whole every run is
stored whole in git every run. On 2026-10-02 .git was growing ~8 MB a day,
most of it four whole-season files rewritten many times a day: the NFL and CFB
prediction archives, the CFB odds archive and the ESPN game summaries.

The archives are now one file per capture day (cfb.partitions) or per ESPN
week (cfb.gameinfo), so a run rewrites only what it captured, and the two
caches that could be refetched (box scores, usage) left git altogether.
These pin the rules that make that safe: the split loses nothing, says exactly
what the single file said, and leaves a closed day's file byte-for-byte alone.
"""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cfb import partitions
from gordstats import stable

ROOT = Path(__file__).resolve().parents[1]


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _single_file(old, fresh, key):
    """How the archives were kept until 2026-10-02 (cfb.results.capture):
    one file, an unchanged same-day capture keeping the row already there,
    otherwise the newest row per key per day."""
    if old is not None:
        fresh = pd.concat([old, stable.drop_repeats(old, fresh, key)], ignore_index=True)
    fresh = fresh.assign(day=fresh["captured"].str[:10])
    fresh = fresh.drop_duplicates(subset=key + ["day"], keep="last")
    return fresh.drop(columns="day").reset_index(drop=True)


def _run(stamp, margins, spread=-3.0):
    return pd.DataFrame({"captured": stamp, "game_id": [str(g) for g in range(len(margins))],
                         "pred_margin": margins, "market_spread": spread})


def _runs():
    """Four days of captures: same-day repeats that change nothing, some that
    move one game, a game that drops off the board and comes back."""
    rng = np.random.default_rng(7)
    base = rng.normal(0, 7, 6).round(3)
    out = []
    for day in ("2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01"):
        for hour in ("05", "11", "17", "23"):
            margins = base.copy()
            if hour in ("17", "23"):
                margins[int(hour) % 6] += 1.5           # one game moves
            frame = _run(f"{day}T{hour}:30:00+00:00", margins)
            if day == "2026-09-30" and hour == "11":
                frame = frame[frame["game_id"] != "2"]  # off the board for a run
            out.append(frame)
        base = base + rng.normal(0, 0.5, 6).round(3)
    return out


def test_day_files_say_what_the_single_file_said(tmp_path):
    legacy = tmp_path / "2026.parquet"
    single = None
    for fresh in _runs():
        single = _single_file(single, fresh, ["game_id"])
        got = partitions.record(legacy, fresh, ["game_id"])
    pd.testing.assert_frame_equal(got, single)
    assert [p.name for p in partitions.day_files(legacy)] == [
        "2026-09-28.parquet", "2026-09-29.parquet", "2026-09-30.parquet", "2026-10-01.parquet"]
    assert not legacy.exists()


def test_a_closed_day_is_never_rewritten(tmp_path):
    legacy = tmp_path / "2026.parquet"
    runs = _runs()
    for fresh in runs[:8]:                                   # two days
        partitions.record(legacy, fresh, ["game_id"])
    first = partitions.directory(legacy) / "2026-09-28.parquet"
    before, mtime = _digest(first), first.stat().st_mtime_ns
    for fresh in runs[8:]:
        partitions.record(legacy, fresh, ["game_id"])
    assert _digest(first) == before
    # Not even touched: only the day being captured is opened for writing.
    assert first.stat().st_mtime_ns == mtime


def test_an_unchanged_rerun_leaves_the_day_file_alone(tmp_path):
    legacy = tmp_path / "2026.parquet"
    partitions.record(legacy, _run("2026-10-01T05:00:00+00:00", [3.0, -7.0]), ["game_id"])
    path = partitions.directory(legacy) / "2026-10-01.parquet"
    before = _digest(path)
    partitions.record(legacy, _run("2026-10-01T11:00:00+00:00", [3.0000001, -7.0]), ["game_id"])
    assert _digest(path) == before
    assert list(partitions.read(legacy, ["game_id"])["captured"].str[11:16]) == ["05:00", "05:00"]


def test_the_split_is_lossless_and_removes_the_single_file(tmp_path):
    legacy = tmp_path / "2026.parquet"
    single = None
    for fresh in _runs():
        single = _single_file(single, fresh, ["game_id"])
    single.to_parquet(legacy, index=False)
    # Before the split, the single file is the archive.
    pd.testing.assert_frame_equal(partitions.read(legacy, ["game_id"]), single)
    assert partitions.migrate(legacy, ["game_id"])
    assert not legacy.exists()
    pd.testing.assert_frame_equal(partitions.read(legacy, ["game_id"]), single)
    assert not partitions.migrate(legacy, ["game_id"])        # nothing left to do


def test_a_newer_single_file_beside_the_days_is_merged_not_lost(tmp_path):
    """The rebase case: day files split from an older copy, then origin's newer
    single file kept beside them. Reading sees the newer file's rows, and the
    next capture folds it in exactly."""
    legacy = tmp_path / "2026.parquet"
    runs = _runs()
    older = newer = None
    for i, fresh in enumerate(runs):
        newer = _single_file(newer, fresh, ["game_id"])
        if i == 9:
            older = newer
    older.to_parquet(legacy, index=False)
    partitions.migrate(legacy, ["game_id"])
    newer.to_parquet(legacy, index=False)
    pd.testing.assert_frame_equal(partitions.read(legacy, ["game_id"]), newer)
    got = partitions.record(legacy, runs[-1], ["game_id"])     # an unchanged rerun
    assert not legacy.exists()
    pd.testing.assert_frame_equal(got, newer)


def test_the_real_archives_keep_their_shape(tmp_path, monkeypatch):
    """cfb.results / nfl.results / cfb.odds read through the day files and
    still accept a single file written the old way (as the tests do)."""
    from cfb import odds, results
    from nfl import results as nfl_results
    monkeypatch.setattr(odds, "ODDS_DIR", tmp_path / "odds")
    monkeypatch.setattr(results, "PRED_DIR", tmp_path / "cfb")
    monkeypatch.setattr(nfl_results, "PRED_DIR", tmp_path / "nfl")
    for mod in (results, nfl_results):
        assert mod.on_record(2026).empty
    assert odds.latest(2026).empty and odds.history(2026).empty
    line = {"season": 2026, "week": 5, "home_id": "1", "away_id": "2", "spread": -3.5,
            "total": 51.5}
    partitions.record(odds.season_path(2026),
                      pd.DataFrame([{**line, "captured": "2026-10-01T05:00:00+00:00"}]),
                      odds.ARCHIVE_KEY)
    partitions.record(odds.season_path(2026),
                      pd.DataFrame([{**line, "spread": -4.5, "captured": "2026-10-02T05:00:00+00:00"}]),
                      odds.ARCHIVE_KEY)
    assert odds.latest(2026)["spread"].tolist() == [-4.5]
    assert odds.history(2026)["spread"].tolist() == [-3.5, -4.5]


def test_parquet_bytes_depend_only_on_the_data(tmp_path):
    """A frame written twice is the same file twice (no clock in the
    metadata), and an identical rewrite is skipped outright."""
    frame = pd.DataFrame({"a": ["x", "y"], "b": [1.5, np.nan]})
    one, two = tmp_path / "one.parquet", tmp_path / "two.parquet"
    frame.to_parquet(one, index=False)
    frame.copy().to_parquet(two, index=False)
    assert _digest(one) == _digest(two)
    assert not partitions.write_parquet(frame, one)
    assert partitions.write_parquet(frame.assign(b=[1.5, 2.0]), one)
    assert not list(tmp_path.glob("*.partial"))


def test_a_torn_day_file_does_not_stop_the_next_capture(tmp_path):
    legacy = tmp_path / "2026.parquet"
    folder = partitions.directory(legacy)
    folder.mkdir()
    (folder / "2026-10-01.parquet").write_bytes(b"PAR1 not really")
    got = partitions.record(legacy, _run("2026-10-01T05:00:00+00:00", [1.0]), ["game_id"])
    assert got["pred_margin"].tolist() == [1.0]


# --- the ESPN game summaries, one file per week ------------------------------

def _entry(captured, spread):
    return {"spread": spread, "kickoff": "2026-10-03T16:00Z", "captured": captured}


@pytest.fixture
def gameinfo(tmp_path, monkeypatch):
    from cfb import gameinfo as mod
    monkeypatch.setattr(mod, "DATA_DIR", tmp_path)
    return mod


def test_game_summaries_rewrite_only_the_week_that_changed(gameinfo):
    weeks = {"1": 5, "2": 5, "3": 6}
    cache = {"1": _entry("2026-09-30T10:00:00+00:00", -3.0),
             "2": _entry("2026-09-30T10:00:00+00:00", 7.0),
             "3": _entry("2026-09-30T10:00:00+00:00", 1.5)}
    assert len(gameinfo.save(cache, 2026, weeks)) == 2
    week5 = gameinfo.week_dir(2026) / "week_05.json"
    before = _digest(week5)
    cache["3"] = _entry("2026-10-01T10:00:00+00:00", 2.5)
    assert gameinfo.save(cache, 2026, weeks) == [gameinfo.week_dir(2026) / "week_06.json"]
    assert _digest(week5) == before
    assert gameinfo.load(2026) == cache
    assert gameinfo.save(dict(reversed(list(cache.items()))), 2026, weeks) == []


def test_a_rescheduled_game_moves_week(gameinfo):
    cache = {"1": _entry("2026-09-30T10:00:00+00:00", -3.0),
             "2": _entry("2026-09-30T10:00:00+00:00", 7.0)}
    gameinfo.save(cache, 2026, {"1": 5, "2": 5})
    gameinfo.save(cache, 2026, {"1": 5, "2": 9})
    files = {p.name: json.loads(p.read_text()) for p in gameinfo.week_dir(2026).iterdir()}
    assert set(files["week_05.json"]) == {"1"} and set(files["week_09.json"]) == {"2"}
    gameinfo.save(cache, 2026, {"1": 9, "2": 9})
    assert [p.name for p in gameinfo.week_dir(2026).iterdir()] == ["week_09.json"]


def test_the_single_summary_file_is_split_and_merged(gameinfo):
    old = {"1": _entry("2026-09-30T10:00:00+00:00", -3.0),
           "2": _entry("2026-09-30T10:00:00+00:00", 7.0)}
    legacy = gameinfo.cache_path(2026)
    legacy.write_text(json.dumps(old, indent=0))
    assert gameinfo.load(2026) == old                       # read before the split
    gameinfo.save(gameinfo.load(2026), 2026, {"1": 5, "2": 6})
    assert not legacy.exists() and gameinfo.load(2026) == old
    # A newer single file kept beside the weeks (a rebase): its later capture wins.
    newer = dict(old, **{"2": _entry("2026-10-01T10:00:00+00:00", 6.5)})
    legacy.write_text(json.dumps(newer, indent=0))
    assert gameinfo.load(2026) == newer
    gameinfo.save(gameinfo.load(2026), 2026, {"1": 5, "2": 6})
    assert not legacy.exists() and gameinfo.load(2026) == newer


# --- caches that left git ----------------------------------------------------

def test_refetchable_caches_live_where_git_ignores_them():
    from cfb import boxscores, usage
    ignore = (ROOT / ".gitignore").read_text().splitlines()
    assert "data/cfb/cache/" in ignore and "*.partial" in ignore
    for mod in (boxscores, usage):
        rel = mod.path(2026).relative_to(ROOT)
        assert str(rel).startswith("data/cfb/cache/"), rel


@pytest.mark.parametrize("name", ["boxscores", "usage"])
def test_a_missing_or_torn_cache_reads_empty(tmp_path, monkeypatch, name):
    import importlib
    mod = importlib.import_module(f"cfb.{name}")
    path = tmp_path / "cache" / f"{name}_2026.parquet"
    monkeypatch.setattr(mod, "path", lambda season=None: path)
    assert mod.load(2026).empty
    path.parent.mkdir()
    path.write_bytes(b"PAR1 torn")
    assert mod.load(2026).empty
