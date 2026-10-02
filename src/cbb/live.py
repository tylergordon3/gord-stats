"""
The live tick's college basketball gate: pushes the day's scoreboard to the
cbb-live-scores Worker that /men/ and /women/ poll.

    python -m cbb.live      # exit 0 pushed, 3 nothing to do (or a feed or
                            # the Worker unreachable), else failed

Nothing scheduled this before: the scoreboard was pushed by hand from a laptop
in 2025-26, so from tipoff the pages would have had no data at all.

Nothing here touches the site. The scoreboard pages read the Worker, not a
rebuilt page, so pi-live.sh runs this apart from the gates that ask for a build.

Both leagues go in one payload, {generated, leagues: {men, women}, meta}: the
Worker stores one KV key and live.js reads `data.leagues[league]`. The script
this replaces pushed each league on its own - the women's over the men's - in
a shape live.js never read.
"""
import os
import sys
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
# Tip-offs run from late morning to near midnight Eastern, and the last games
# finish by half past one. Outside that a tick only spends requests.
OPEN, CLOSE = time(11, 0), time(1, 30)
# pi-live's timer; live.js shows it as the refresh rate.
TICK_SECONDS = 600


def in_hours(now: datetime) -> bool:
    t = now.time()
    return t >= OPEN or t <= CLOSE


def payload(leagues: dict) -> dict:
    return {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "leagues": leagues, "meta": {"poll_interval_sec": TICK_SECONDS}}


def main() -> int:
    from cbb.render.render_home import CBB_SEASON_END, CBB_TIPOFF

    now = datetime.now(ET)
    if not CBB_TIPOFF <= now.date() <= CBB_SEASON_END:
        print("  cbb: outside the season, nothing to push")
        return 3
    if not in_hours(now):
        print("  cbb: outside playing hours")
        return 3
    if not os.getenv("INGEST_KEY"):
        print("  cbb: INGEST_KEY is not set - the scoreboard is not being pushed")
        return 3

    import requests

    from cbb import live_scraper, push_scores

    # A feed or Worker that is down is a skipped tick (3), like every other
    # gate: an HTTP error used to escape as exit 1, which pi-live.sh mailed
    # every ten minutes - ~87 mails a day through an outage. What the far end
    # refuses (an INGEST_KEY the Worker rejects, a payload it will not take,
    # a feed URL that has moved) is ours to fix, so it still fails the gate,
    # and pi-live.sh's tick_trouble mails once an hour while it lasts.
    try:
        leagues = {k: live_scraper.get_current_live_dataset(k)["games"]
                   for k in ("men", "women")}
    except requests.RequestException as exc:
        if refused(exc):
            raise
        print(f"  cbb: scoreboard feed unreachable ({exc}), skipping")
        return 3
    # The lines first, and never at the push's expense: they exist nowhere else.
    try:
        from cbb import lines
        lines.record(leagues)
    except Exception as exc:                            # noqa: BLE001
        print(f"  ! cbb: betting lines not recorded ({exc})")
    try:
        push_scores.push(payload(leagues))
    except requests.RequestException as exc:
        if refused(exc):
            raise
        print(f"  cbb: the scoreboard Worker is unreachable ({exc}), skipping")
        return 3
    print(f"  cbb: pushed {len(leagues['men'])} men's and {len(leagues['women'])} "
          "women's games")
    return 0


def refused(exc: Exception) -> bool:
    """A 4xx other than a timeout or rate limit: the other end answered and
    said no, which waiting will not fix."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return status is not None and 400 <= status < 500 and status not in (408, 429)


if __name__ == "__main__":
    sys.exit(main())
