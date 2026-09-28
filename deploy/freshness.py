"""
Is the live site still being refreshed? Run every two hours by
.github/workflows/freshness.yml.

Every publish writes status.json into the site (deploy/publish.sh): when it
went out, and when the daily run last got through. The daily timer fires four
times a day, so a site whose daily half is more than STALE_HOURS old has
missed two runs in a row - the Pi is down, its timer stopped, or every run is
failing before it publishes. Nobody was told when that happened; the site just
sat still until somebody noticed a Saturday's scores were missing.

Stale, or not answering: one open issue (GitHub emails the owner), found again
by its title marker rather than opened twice. Fresh: that issue is closed with
the time it recovered. Failed sections alone do not alert - the daily run
publishes through them, and CBB fails on purpose every run until its sources
publish in November.

Read from the pages.dev address: www.gordstats.com puts a bot challenge in
front of anything that looks like a script.

    python deploy/freshness.py            # needs GITHUB_TOKEN and GITHUB_REPOSITORY
"""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

STATUS_URL = "https://gordstats-cbb.pages.dev/status.json"
STALE_HOURS = 13
MARKER = "[freshness]"
API = "https://api.github.com"


def _when(text):
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def verdict(status: dict | None, now: datetime) -> tuple:
    """(stale, one line saying why). `status` is status.json, or None when
    the site did not answer."""
    if status is None:
        return True, "the site did not answer (status.json unreachable)"
    daily = _when(status.get("daily")) or _when(status.get("published"))
    if daily is None:
        return True, "status.json carries no usable time"
    hours = (now - daily).total_seconds() / 3600
    rc = status.get("daily_sections_rc")
    tail = " - some sections failed in that run" if rc not in (0, None) else ""
    if hours > STALE_HOURS:
        return True, (f"the daily refresh last published {daily:%Y-%m-%d %H:%M} UTC, "
                      f"{hours:.0f} hours ago{tail}")
    return False, f"daily refresh {hours:.1f} hours ago{tail}"


def fetch_status(url: str = STATUS_URL):
    try:
        with urllib.request.urlopen(urllib.request.Request(
                url, headers={"User-Agent": "gordstats-freshness", "Cache-Control": "no-cache"}),
                timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, ValueError, TimeoutError):
        return None


def _github(method: str, path: str, token: str, body: dict = None):
    req = urllib.request.Request(
        f"{API}{path}", method=method, data=json.dumps(body).encode() if body else None,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "User-Agent": "gordstats-freshness"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8") or "null")


def main() -> int:
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    now = datetime.now(timezone.utc)
    stale, why = verdict(fetch_status(), now)
    print(("STALE: " if stale else "fresh: ") + why)
    if not token or not repo:
        return 1 if stale else 0
    open_issues = [i for i in _github("GET", f"/repos/{repo}/issues?state=open&per_page=100", token)
                   if MARKER in i.get("title", "") and "pull_request" not in i]
    if stale and not open_issues:
        _github("POST", f"/repos/{repo}/issues", token, {
            "title": f"{MARKER} gordstats.com has stopped refreshing",
            "body": (f"Checked {now:%Y-%m-%d %H:%M} UTC: {why}.\n\n"
                     "The daily timer on the Pi fires at 05:30, 11:30, 17:30 and 23:30 ET. "
                     "Look at `journalctl _SYSTEMD_USER_UNIT=gordstats-daily.service` on the Pi, "
                     "or run `pi deploy`. This issue closes itself once the site is fresh again.")})
        print("opened an issue")
    elif not stale:
        for issue in open_issues:
            _github("POST", f"/repos/{repo}/issues/{issue['number']}/comments", token,
                    {"body": f"Fresh again at {now:%Y-%m-%d %H:%M} UTC: {why}."})
            _github("PATCH", f"/repos/{repo}/issues/{issue['number']}", token, {"state": "closed"})
            print(f"closed #{issue['number']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
