"""
Shared bits for the tests that drive headless Chromium.

GitHub's runners are slower than the PC or the Pi: a Chromium asked to quit
can take more than the ten seconds the tests used to give it, and the wait
then failed a test that had passed (2026-10-01, test_auth_session). A browser
that will not go is killed instead.
"""
import subprocess


def reap(proc, timeout: float = 10) -> None:
    """Wait for a terminated browser to exit; kill it if it will not."""
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            pass
