"""Data files are rewritten only when something in them changed
(gordstats.stable) - a parquet rewrite is stored whole in git every time."""
import hashlib

import numpy as np
import pandas as pd

from gordstats import stable


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_reordered_but_identical_table_is_not_rewritten(tmp_path):
    path = tmp_path / "usage.parquet"
    frame = pd.DataFrame({"week": [1, 1, 2], "game_id": ["a", "b", "c"],
                          "player": ["x", "y", "z"], "carries": [3.0, np.nan, 7.0]})
    assert stable.write_parquet(frame, path, sort_by=["week", "game_id"])
    before = _digest(path)
    shuffled = frame.sample(frac=1, random_state=4).reset_index(drop=True)
    assert not stable.write_parquet(shuffled, path, sort_by=["week", "game_id"])
    assert _digest(path) == before
    changed = frame.assign(carries=[3.0, 1.0, 7.0])
    assert stable.write_parquet(changed, path, sort_by=["week", "game_id"])


def test_an_unchanged_same_day_capture_is_not_a_new_one():
    old = pd.DataFrame({"captured": ["2026-09-28T09:00:00+00:00"] * 2, "game_id": ["1", "2"],
                        "pred_margin": [3.1234567, -7.0], "market_spread": [np.nan, -6.5]})
    fresh = pd.DataFrame({"captured": ["2026-09-28T15:00:00+00:00"] * 2 + ["2026-09-29T09:00:00+00:00"],
                          "game_id": ["1", "2", "1"],
                          "pred_margin": [3.1234569, -7.5, 3.1234567],
                          "market_spread": [np.nan, -6.5, np.nan]})
    kept = stable.drop_repeats(old, fresh, ["game_id"])
    # Game 1's wobble in the seventh decimal is not news; game 2 moved; a new
    # day is always a new capture.
    assert list(zip(kept["game_id"], kept["captured"].str[:10])) == [
        ("2", "2026-09-28"), ("1", "2026-09-29")]
