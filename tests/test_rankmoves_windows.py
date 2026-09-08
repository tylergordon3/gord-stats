"""Change-since windows over a snapshot archive (gordstats.rankmoves)."""
from datetime import datetime, timedelta

import pandas as pd

from gordstats import rankmoves


def _write(history_dir, when, ranks: dict, rating: dict = None):
    df = pd.DataFrame({"key": list(ranks), "rank": list(ranks.values())})
    if rating:
        df["rating"] = [rating[k] for k in ranks]
    df.to_csv(history_dir / f"{when:%Y%m%d-%H%M%S}.csv", index=False)


def test_windows_resolve_to_distinct_baselines_only(tmp_path):
    now = datetime(2026, 10, 1, 12)
    _write(tmp_path, now - timedelta(days=40), {"a": 3, "b": 1}, {"a": 1.0, "b": 9.0})
    _write(tmp_path, now - timedelta(days=8), {"a": 2, "b": 1}, {"a": 4.0, "b": 9.0})
    _write(tmp_path, now - timedelta(hours=20), {"a": 2, "b": 1}, {"a": 5.0, "b": 9.0})
    _write(tmp_path, now - timedelta(hours=1), {"a": 1, "b": 2})       # this build: too young
    bases = rankmoves.baselines(tmp_path, now=now)
    # last build = 20h ago; 1d, 3d and 7d all resolve to 8 days ago (one button);
    # 14d and 30d to 40 days ago, which is also the season start (one button).
    assert list(bases) == ["last", "1d", "14d"]
    assert bases["last"]["at"] == now - timedelta(hours=20)
    assert bases["14d"]["at"] == now - timedelta(days=40)


def test_move_and_delta_spans_carry_every_window():
    now = datetime(2026, 10, 1, 12)
    frame_old = pd.DataFrame({"rank": [3], "rating": [1.0]}, index=pd.Index(["a"], name="key"))
    frame_new = pd.DataFrame({"rank": [2]}, index=pd.Index(["a"], name="key"))
    bases = {"last": {"label": "Last build", "at": now, "frame": frame_new},
             "season": {"label": "Season start", "at": now, "frame": frame_old}}
    spans, first = rankmoves.move_spans(bases, "a", 1)
    assert first == 1
    assert "data-win='last' data-v='1' class=on" in spans
    assert "data-win='season' data-v='2'" in spans and "&#9650;2" in spans
    spans, first = rankmoves.delta_spans(bases, "a", 5.5, "rating")
    # The last build has no rating column: no figure, and the first figure
    # found (season start, +4.5) is the one handed back for sorting.
    assert "data-win='last' data-v=''" in spans and first == 4.5
    assert "+4.5" in spans
    # A key the baseline never saw shows nothing, not an error.
    assert rankmoves.move_spans(bases, "zz", 5)[1] is None


def test_window_switch_is_empty_without_an_archive(tmp_path):
    assert rankmoves.window_switch(rankmoves.baselines(tmp_path)) == ""


def test_window_buttons_say_when(tmp_path):
    now = datetime(2026, 10, 1, 12)
    _write(tmp_path, now - timedelta(days=9), {"a": 1})
    _write(tmp_path, now - timedelta(hours=20, minutes=26), {"a": 1})
    html = rankmoves.window_switch(rankmoves.baselines(tmp_path, now=now))
    assert ">Sep 30, 3:34 PM</button>" in html          # the last build, by its clock
    assert "1 day <span class='win-when'>Sep 22</span>" in html   # 1d, 3d, 7d all resolve here


def test_week_windows_take_the_last_snapshot_before_the_next_kickoff(tmp_path):
    now = datetime(2026, 9, 22, 12)
    wk1 = (1, datetime(2026, 8, 29, 12), datetime(2026, 9, 7, 23, 30))
    wk2 = (2, datetime(2026, 9, 10, 20), datetime(2026, 9, 13, 4))
    wk3 = (3, datetime(2026, 9, 17, 19, 30), datetime(2026, 9, 20, 3))
    _write(tmp_path, datetime(2026, 8, 25, 19), {"a": 1})          # preseason
    _write(tmp_path, datetime(2026, 9, 7, 5), {"a": 2})            # week 1 still on
    _write(tmp_path, datetime(2026, 9, 8, 5), {"a": 3})            # after week 1...
    _write(tmp_path, datetime(2026, 9, 10, 5), {"a": 4})           # ...the last before week 2
    _write(tmp_path, datetime(2026, 9, 21, 5), {"a": 5})           # after week 3
    bases = rankmoves.baselines(tmp_path, now=now, weeks=[wk1, wk2, wk3])
    assert bases["w1"]["at"] == datetime(2026, 9, 10, 5)
    assert bases["w1"]["group"] == "week" and bases["w1"]["label"] == "Wk 1"
    assert "w2" not in bases                       # nothing archived between weeks 2 and 3
    # Week 3's baseline is also the last build: both buttons are offered.
    assert bases["w3"]["at"] == bases["last"]["at"] == datetime(2026, 9, 21, 5)
    html = rankmoves.window_switch(bases)
    assert "After week:" in html
    assert 'data-win="w1" title="After Week 1' in html
    assert "Wk 1 <span class='win-when'>Sep 10</span>" in html
