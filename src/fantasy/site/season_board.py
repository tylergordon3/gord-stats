"""
The projection board the browser needs to rank a reader's own league.

/fantasy/power/ ranks this site's league by simulating its season ten thousand
times. Doing the same for a reader's league has to happen in the browser, since
the rosters and the rules only exist at Sleeper — but the numbers each player is
simulated from cannot. They come out of `fantasy.projections`: five seasons of
weekly scoring, a ridge model per position, anchored to the market's ADP. None
of that is going in a phone.

It does not have to. What the simulation actually consumes is six numbers per
player, and those six are the same for every league in the country. So the
model runs here, as it always has, and publishes its answer:

    docs/fantasy/season-board.json
    {"year": 2026, "week": 3,
     "fields": ["pos","bye","mu","sd","mu_se","avail","rec","out"],
     "pos": ["QB","RB","WR","TE","K","DEF"],
     "board": {"9221": [1, 6, 23.9, 13.65, 3.6, 0.85, 4.3, 0], ...}}

About 1,200 players, 47 KB, 12 KB over the wire — smaller than the player index
the same pages already fetch.

Two of the eight fields are not in the board the site's own page uses, and both
exist because a reader's league is not this one:

`rec` — projected receptions a week. `mu` is PPR, because this league plays
PPR. The only difference between Sleeper's three scoring bases is what a catch
is worth, so half-PPR is `mu - rec/2` and standard is `mu - rec`, exactly,
without re-running a model per basis.

The first source is Sleeper's own weekly projections, which price every player
under all three bases at once: the gap between the PPR and standard figures
*is* his projected receptions. But Sleeper does not project a player who is
hurt or on a bye, and those are exactly the players a half-PPR league is about
to be told the wrong number for - the first pass here gave a receiver who
catches six a week the league-wide median of 1.8. So the fallback is his own
catch rate, from the weekly file, most recent season first. Only a player with
no projection and no history at all takes the positional median, and by then he
is a deep-bench flier whose scoring basis decides nothing.

`out` — weeks a player is held out from the next one, from Sleeper's live
injury designation through `power.FORCED_OUT`. The site's own page reads this
off the matchups archive, but that archive only holds this league's rostered
players, and a reader's league has different ones. So it is taken from
Sleeper's player table instead, which knows about everybody.

The board is published *after* `projections.current_form`, so a reader's league
is simulated from the same in-season numbers as the page next to it rather than
from preseason ones.

    python -m fantasy.site.season_board
"""
import json
import statistics

import pandas as pd

from fantasy import paths, projections
from fantasy.config import UPCOMING_YEAR

OUT = paths.WEB_FANTASY_DIR / "season-board.json"
# Sleeper's designations go stale the moment the fetch fails, so the last good
# copy is kept: an out-of-date injury is a better input than no injury at all.
INJURY_CACHE = paths.DATA_DIR / "players" / "injury_status.json"

POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"]
FIELDS = ["pos", "bye", "mu", "sd", "mu_se", "avail", "rec", "out"]


def injury_status() -> dict:
    """{sleeper_id: designation} for every player Sleeper knows about.

    Every league's players, not this one's - which is the whole reason this
    does not reuse `power.injury_designations`.
    """
    try:
        from sleeper_wrapper import Players

        raw = Players().get_all_players(sport="nfl") or {}
        out = {str(pid): p.get("injury_status") for pid, p in raw.items()
               if p.get("injury_status")}
        if out:
            INJURY_CACHE.parent.mkdir(parents=True, exist_ok=True)
            INJURY_CACHE.write_text(json.dumps(out, separators=(",", ":")),
                                    encoding="utf-8")
            return out
    except Exception as exc:                                # noqa: BLE001
        print(f"  ! injury designations unavailable ({exc}); using the last copy")

    if INJURY_CACHE.exists():
        try:
            return json.loads(INJURY_CACHE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


#: How far back a catch rate is worth reading when Sleeper has no projection.
REC_HISTORY_SEASONS = 2


def _projected_receptions() -> dict:
    """{sleeper_id: receptions a week}, from Sleeper's own three bases.

    Sleeper scores every player under PPR, half-PPR and standard, and the
    difference between the outer two is the catches those points came from.
    """
    path = paths.WEB_FANTASY_DIR / "week-projections.json"
    if not path.exists():
        return {}
    try:
        week = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    rec = {}
    for pid, row in (week.get("proj") or {}).items():
        if len(row) >= 3:
            rec[str(pid)] = round(max(float(row[0]) - float(row[2]), 0.0), 2)
    return rec


def _historical_receptions(year: int) -> dict:
    """{sleeper_id: receptions a game}, most recent season a player has one.

    Games he appeared in, not games the season had: a receiver who missed half
    the year still catches what he catches when he plays, and the simulation
    handles the missing weeks itself.
    """
    from fantasy.league import weekly_points

    out = {}
    for season in range(year, year - REC_HISTORY_SEASONS, -1):
        path = weekly_points.path(season)
        if not path.exists():
            continue
        try:
            frame = pd.read_parquet(path, columns=["sleeper_id", "receptions"])
        except (OSError, ValueError, KeyError):
            continue
        frame = frame.dropna(subset=["sleeper_id"])
        if frame.empty:
            continue
        rate = frame.groupby("sleeper_id")["receptions"].mean()
        for pid, value in rate.items():
            key = str(pid)
            # An earlier season only fills a gap; it never overwrites a newer one.
            if key not in out and pd.notna(value):
                out[key] = round(max(float(value), 0.0), 2)
    return out


def receptions_per_week(year: int = UPCOMING_YEAR) -> tuple:
    """(projected, historical) catch rates, best source first."""
    return _projected_receptions(), _historical_receptions(year)


#: Positions whose projection contains catches. A quarterback does occasionally
#: catch one - three on this board have a non-zero rate in the weekly file, from
#: throwbacks and trick plays - and subtracting it in a standard league would be
#: arithmetically right and predictively worthless. Sleeper prices them the same
#: under all three bases for the same reason.
CATCH_POSITIONS = ("RB", "WR", "TE")


def _catch_rate(pid: str, pos: str, mu: float, projected: dict, past: dict,
                median: dict) -> float:
    """What a catch is worth to this player, best source first.

    Capped at his own projection, which is not a fudge but arithmetic: `mu` is
    PPR points a week and a catch is worth a point before any yards, so a catch
    rate above it describes a player who does not exist. It happens when the
    two numbers come from different times - a fringe receiver projected for a
    point and a half a week, carrying the catch rate of the season he played a
    real role. Left alone, a standard league would project him below zero.
    """
    if pos not in CATCH_POSITIONS:
        return 0.0
    if pid in projected:
        rate = projected[pid]
    elif pid in past:
        rate = past[pid]
    else:
        rate = median.get(pos, 0.0)
    return round(min(rate, max(float(mu), 0.0)), 2)


#: How much of a normal week's player rows the newest week must have before its
#: form is believed. A Thursday night game is about a tenth of a slate.
FULL_WEEK_SHARE = 0.9


def absorbed_weeks(year: int = UPCOMING_YEAR) -> int:
    """Weeks whose form the board can safely take, which is complete ones only.

    `projections.completed_weeks` answers with the highest week present in the
    weekly file, and on a Thursday that is a week with one game in it. Blending
    a week like that into every player's form marks everyone who has not played
    yet as having had a terrible one, and a reader's league would then be
    ranked off numbers the page beside it disagrees with - which is the one
    thing a second implementation must not do.

    The built page avoids this by taking the lesser of nflverse and the weeks
    its own league has fully scored. There is no league here, so the NFL's own
    calendar is the test: a week is over once Sleeper's display week has moved
    past it (the same rule the pages use). Only if Sleeper will not answer does
    the week's own size decide - and that test rejected finished bye weeks,
    whose four to six missing teams read as a week part played (the audit).
    """
    from fantasy.league import matchups, weekly_points

    weeks = projections.completed_weeks(year)
    over = matchups.weeks_over(year)
    if over is not None:
        return min(weeks, over)
    if weeks < 2:
        return weeks
    path = weekly_points.path(year)
    if not path.exists():
        return weeks
    try:
        counts = pd.read_parquet(path, columns=["week"]).groupby("week").size()
    except (OSError, ValueError, KeyError):
        return weeks
    earlier = counts[counts.index < weeks]
    if earlier.empty or counts.get(weeks, 0) >= FULL_WEEK_SHARE * earlier.median():
        return weeks
    print(f"  week {weeks} is only part played ({int(counts.get(weeks, 0))} of "
          f"~{int(earlier.median())} players); the board stops at {weeks - 1}")
    return weeks - 1


def build(year: int = UPCOMING_YEAR) -> dict:
    """The published board, as the browser reads it."""
    from fantasy.league.power import FORCED_OUT

    board = projections.load(year)
    weeks = absorbed_weeks(year)
    board = projections.current_form(board, year, through_week=weeks)
    board = projections.with_sleeper(board, year, through_week=weeks)
    rec, past = receptions_per_week(year)
    injuries = injury_status()

    # A position's median catch rate, for the players Sleeper is not projecting
    # this week - deep bench, and the ones a bye or an injury has taken off the
    # board entirely.
    by_position = {}
    for row in board.itertuples():
        value = rec.get(str(row.sleeper_id))
        if value is not None:
            by_position.setdefault(row.pos, []).append(value)
    median = {pos: round(statistics.median(values), 2)
              for pos, values in by_position.items() if values}

    out = {}
    for row in board.itertuples():
        pid = str(row.sleeper_id)
        if row.pos not in POSITIONS or pd.isna(row.mu):
            continue
        out[pid] = [
            POSITIONS.index(row.pos),
            int(row.bye),
            round(float(row.mu), 2),
            round(float(row.sd), 2),
            round(float(row.mu_se), 2),
            round(float(row.avail), 3),
            _catch_rate(pid, row.pos, row.mu, rec, past, median),
            FORCED_OUT.get(injuries.get(pid, ""), 0),
        ]
    return {"year": int(year), "week": int(weeks),
            "fields": FIELDS, "pos": POSITIONS, "board": out}


def generate(year: int = UPCOMING_YEAR) -> None:
    try:
        payload = build(year)
    except Exception as exc:                                # noqa: BLE001
        print(f"  ! season board not rebuilt ({exc}); keeping the last copy")
        return
    if not payload["board"]:
        print("  ! season board came out empty; keeping the last copy")
        return
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    held = sum(1 for v in payload["board"].values() if v[-1])
    print(f"Wrote season board ({len(payload['board'])} players, {held} held out) "
          f"-> {OUT}")


if __name__ == "__main__":
    generate()
