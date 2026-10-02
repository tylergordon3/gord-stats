"""
Shared bits for the tests that drive headless Chromium.

GitHub's runners are slower than the PC or the Pi: a Chromium asked to quit
can take more than the ten seconds the tests used to give it, and the wait
then failed a test that had passed (2026-10-01, test_auth_session). A browser
that will not go is killed instead.

Every launch also gets a profile of its own. They all used to share
Chromium's default profile, and a dying instance still holding its
SingletonLock made the next launch hand over to it and exit - "Chromium did
not come up", in 2 of 25 CI runs (the 2026-10-02 audit).
"""
import atexit
import shutil
import subprocess
import tempfile
from pathlib import Path

# The snap Chromium on the PC gets a private /tmp and cannot see hidden
# directories in $HOME, so a profile made with tempfile's defaults would be
# created inside the snap's own /tmp, out of reach of the cleanup below. Its
# common directory is visible to both sides.
_SNAP_COMMON = Path.home() / "snap" / "chromium" / "common"
_profiles = set()


def launch(chrome: str, port: int, *args: str) -> subprocess.Popen:
    """Headless Chromium on DevTools port `port`, in a fresh profile that
    reap() deletes."""
    base = _SNAP_COMMON if _SNAP_COMMON.is_dir() else None
    profile = tempfile.mkdtemp(prefix="gs-test-chromium-", dir=base)
    _profiles.add(profile)
    proc = subprocess.Popen(
        [chrome, "--headless=new", "--no-sandbox", "--disable-gpu",
         f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
         *args, f"--remote-debugging-port={port}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    proc.profile_dir = profile
    return proc


def reap(proc, timeout: float = 10) -> None:
    """Wait for a terminated browser to exit; kill it if it will not. Then
    delete the profile launch() gave it."""
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            pass
    profile = getattr(proc, "profile_dir", None)
    if profile:
        shutil.rmtree(profile, ignore_errors=True)
        _profiles.discard(profile)


@atexit.register
def _sweep() -> None:
    """Profiles of browsers that were terminated without a reap()."""
    for profile in list(_profiles):
        shutil.rmtree(profile, ignore_errors=True)
