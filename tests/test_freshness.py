"""Publishing: the upload is retried, and a site that stops refreshing opens
an issue (deploy/publish.sh, deploy/freshness.py).

On 2026-09-27 a deploy built fine and then lost its Cloudflare upload to
"fetch failed"; nothing retried it, and nothing would have said so had the
Pi stayed down.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy"))
import freshness  # noqa: E402

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)


def test_a_daily_run_within_two_missed_timers_is_fresh():
    stale, why = freshness.verdict({"daily": "2026-09-28T03:30:00Z", "daily_sections_rc": 4}, NOW)
    assert not stale and "some sections failed" in why, "failed sections alone do not alert"


def test_two_missed_runs_or_no_answer_is_stale():
    assert freshness.verdict({"daily": "2026-09-27T21:30:00Z"}, NOW)[0]
    assert freshness.verdict(None, NOW) == (True, "the site did not answer (status.json unreachable)")
    assert freshness.verdict({"daily": ""}, NOW)[0]


def test_before_any_daily_stamp_the_publish_time_stands_in():
    """The first live tick after this shipped had no daily run to carry."""
    assert not freshness.verdict({"daily": "", "published": "2026-09-28T11:50:00Z"}, NOW)[0]


def _bash(tmp_path, body, fails=0):
    """Run publish.sh's functions in a scratch git repo, with a wrangler that
    fails `fails` times before it succeeds."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    counter = tmp_path / "calls"
    (bin_dir / "wrangler").write_text(
        f"#!/bin/bash\nn=$(( $(cat {counter} 2>/dev/null || echo 0) + 1 ))\necho $n > {counter}\n"
        f"[ $n -gt {fails} ]\n")
    (bin_dir / "wrangler").chmod(0o755)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
                    "--allow-empty", "-m", "x"], cwd=tmp_path, check=True)
    (tmp_path / "docs" / "_site").mkdir(parents=True)
    script = ("set -euo pipefail\nlog() { echo \"LOG $*\"; }\nsleep() { :; }\n"
              f"source {ROOT / 'deploy' / 'publish.sh'}\n{body}\n")
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    out = subprocess.run(["bash", "-c", script], cwd=tmp_path, env=env,
                         capture_output=True, text=True)
    calls = int(counter.read_text()) if counter.exists() else 0
    return out.returncode, calls, out.stderr


def test_a_failed_upload_is_retried(tmp_path):
    rc, calls, err = _bash(tmp_path, "publish proj", fails=2)
    assert rc == 0 and calls == 3 and "attempt 2 of 3" in err


def test_three_failures_fail_the_run(tmp_path):
    rc, calls, err = _bash(tmp_path, "publish proj", fails=5)
    assert rc != 0 and calls == 3 and "failed three times" in err


def test_the_status_file_carries_both_times(tmp_path):
    rc, _calls, _err = _bash(tmp_path, 'write_status "2026-09-28T12:00:00Z" "2026-09-28T09:30:00Z" 4')
    assert rc == 0
    got = json.loads((tmp_path / "docs" / "_site" / "status.json").read_text())
    assert got["published"] == "2026-09-28T12:00:00Z" and got["daily"] == "2026-09-28T09:30:00Z"
    assert got["daily_sections_rc"] == 4 and len(got["commit"]) >= 7


def test_both_deploy_scripts_publish_through_it():
    for name in ("pi-deploy.sh", "pi-live.sh"):
        src = (ROOT / "deploy" / name).read_text()
        assert 'source "$(dirname "${BASH_SOURCE[0]}")/publish.sh"' in src, name
        assert "publish \"$PROJECT\"" in src and "write_status" in src, name
        assert "wrangler pages deploy" not in src, f"{name} uploads around the retry"
