"""
The CFB game clock (docs/_data/cfb_countdown.json).

The homepage CFB card used to count down to the draft via the static
_data/countdowns.yml entry; once the draft passed, that card rendered
nothing. This writes what the clock should show *now*, recomputed on every
build from the ESPN schedule:

    games in progress    -> a "games are on" notice instead of a clock
    games later          -> a countdown to the next kickoff (which is the
                            start of the next week's slate once a week is
                            done - ESPN's week windows don't overlap)
    season over          -> nothing

_includes/cfb_countdown.html renders the result. Between builds the page
covers itself: countdown.js flips an expired clock to the `expired` text,
and the include shows that same text when the target has already passed at
Jekyll build time.

    python -m cfb.site.countdown        # rewrite the JSON
"""
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from cfb import espn
from gordstats import paths

ET = ZoneInfo("America/New_York")
OUT = paths.DOCS / "_data" / "cfb_countdown.json"


def payload(df: pd.DataFrame, now: datetime) -> dict:
    kicks = pd.to_datetime(df["date_utc"], utc=True)

    live = df["state"] == "in"
    if live.any():
        week = int(df.loc[live, "week"].min())
        n = int(live.sum())
        return {"mode": "notice",
                "eyebrow": f"CFB WEEK {week} · GAMEDAY",
                "title": f"{n} game{'s' if n != 1 else ''} on right now"}

    # assign before filtering: .assign on an already-empty selection aligns
    # the full-length series back in and resurrects rows as all-NaN.
    upcoming = df.assign(kick=kicks)[(df["state"] == "pre") & (kicks > now)]
    if upcoming.empty:
        return {"mode": "off"}

    nxt = upcoming.sort_values("kick").iloc[0]
    week = int(nxt["week"])
    kick_et = nxt["kick"].tz_convert(ET)
    now_et = now.astimezone(ET)
    when = f"{kick_et:%-I:%M %p} ET"
    if kick_et.date() == now_et.date():
        # Kickoff is today: same clock, but say so, and count from the first
        # *remaining* game rather than pretending the day hasn't started.
        played_today = bool(((df["state"] == "post")
                             & (kicks.dt.tz_convert(ET).dt.date == now_et.date())).any())
        eyebrow = f"CFB WEEK {week} · GAMEDAY"
        title = f"{'Next' if played_today else 'First'} kickoff {when}"
    else:
        eyebrow = f"CFB WEEK {week}"
        title = f"{kick_et:%A, %B %-d} · {when}"
    return {"mode": "countdown", "eyebrow": eyebrow, "title": title,
            "target": nxt["kick"].strftime("%Y-%m-%dT%H:%M:%SZ"),
            "expired": f"Kickoff — Week {week} is on.",
            "note": "Kickoff in Eastern Time; the clock runs on yours."}


def generate():
    out = payload(espn.schedule(), datetime.now(timezone.utc))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote CFB game clock ({out['mode']}) -> {OUT}")


if __name__ == "__main__":
    generate()
