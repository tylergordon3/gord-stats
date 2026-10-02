"""A number kept before kickoff survives the live tick's checkout.

The Pi's live ticks commit once an hour and start each run from
`git checkout -- docs data`. A projection kept at 12:50 for a 1:00 kickoff
lived only in the working tree; the 1:00 tick rolled the file back, and after
kickoff the number can never be kept again. gordstats.pregame keeps an
untracked copy on the Pi (GS_PREGAME_SIDECAR, exported by deploy/publish.sh),
reads it over the tracked file, and writes the merged numbers back so the
next commit records them.
"""
import json
import subprocess
from pathlib import Path

import pandas as pd

from gordstats import pregame

ROOT = Path(__file__).parent.parent


def _week(states, proj):
    return pd.DataFrame({"proj_week": proj, "state": states}, index=["a", "b"])


def test_a_kept_number_outlives_the_checkout_and_reaches_the_tracked_file(tmp_path, monkeypatch):
    monkeypatch.setenv(pregame.SIDECAR_ENV, "1")
    path = tmp_path / "data" / "fantasy" / "gs_proj" / "2026" / "week_05.json"
    side = pregame.sidecar(path)
    assert side == tmp_path / "data" / "fantasy" / "gs_proj_live" / "2026" / "week_05.json"

    # 12:40: the last commit holds a's 10.0.
    pregame.freeze_at(path, _week(["pre", "pre"], [10.0, 7.0]))
    committed = path.read_text()
    # 12:50: a's number moves to 12.5 - kept in the tree and in the copy.
    pregame.freeze_at(path, _week(["pre", "pre"], [12.5, 7.0]))
    assert json.loads(side.read_text())["a"] == 12.5
    # 1:00: the tick's checkout rolls the tracked file back...
    path.write_text(committed)
    # ...and a has kicked off. The page still says 12.5 going in,
    wk = pregame.freeze_at(path, _week(["in", "pre"], [99.0, 7.0]))
    assert wk.loc["a", "proj_week"] == 12.5 and bool(wk.loc["a", "pregame"])
    # and the tracked file has 12.5 again, for the hourly commit to record.
    assert json.loads(path.read_text())["a"] == 12.5
    assert pregame.load(path) == {"a": 12.5, "b": 7.0}


def test_without_the_switch_only_the_tracked_file_exists(tmp_path, monkeypatch):
    monkeypatch.delenv(pregame.SIDECAR_ENV, raising=False)
    path = tmp_path / "gs_proj" / "2026" / "week_05.json"
    assert pregame.sidecar(path) is None
    pregame.freeze_at(path, _week(["pre", "pre"], [10.0, 7.0]))
    assert json.loads(path.read_text()) == {"a": 10.0, "b": 7.0}
    assert not (tmp_path / "gs_proj_live").exists()


def test_the_chances_are_kept_the_same_way(tmp_path, monkeypatch):
    monkeypatch.setenv(pregame.SIDECAR_ENV, "1")
    path = tmp_path / "gs_proj" / "2026" / "week_05.json"
    wk = _week(["pre", "pre"], [10.0, 7.0]).assign(p_play=[0.6, 1.0])
    pregame.freeze_at(path, wk)
    play = pregame.chances_path(path)
    committed = play.read_text()
    pregame.freeze_at(path, wk.assign(p_play=[0.9, 1.0]))
    play.write_text(committed)                                  # the checkout
    got = pregame.freeze_at(path, wk.assign(state=["post", "pre"], p_play=[0.0, 1.0]))
    assert got.loc["a", "p_play"] == 0.9
    assert json.loads(play.read_text())["a"] == 0.9


def test_the_pi_switches_it_on_and_git_ignores_the_copies():
    publish = (ROOT / "deploy" / "publish.sh").read_text()
    assert "export GS_PREGAME_SIDECAR=1" in publish
    for script in ("pi-live.sh", "pi-deploy.sh"):
        text = (ROOT / "deploy" / script).read_text()
        # publish.sh is sourced before main runs, so every Python step sees it.
        assert text.index("source \"$(dirname \"${BASH_SOURCE[0]}\")/publish.sh\"") < text.rindex("main \"$@\"")
    for path in ("data/fantasy/gs_proj_live/2026/week_05.json",
                 "data/cfb/gs_proj_live/2026/week_05_play.json"):
        out = subprocess.run(["git", "check-ignore", "-q", "--no-index", path],
                             cwd=ROOT, capture_output=True)
        assert out.returncode == 0, f"{path} is not ignored"
