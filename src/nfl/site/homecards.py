"""
The NFL's graphic on the homepage: the week's bets
(docs/_includes/nfl_bets.html), the college card's twin on the same engine
(gordstats.bets_card). One spread bet and a short parlay from the model's
widest disagreements with the book, frozen the morning of the week's first
game - Thursday for a normal week, the Saturday of a playoff round - and
graded in units and against the closing line.

What is the NFL's own:

  the week      nfl.site.schedule's week keys and names, the playoff rounds
                after week 18 (the file for the Wild Card round is wk19)
  the gates     EDGE_MIN and EDGE_MAX below, and why they are what they are
  the finals    the season's played games, from the same fit the picks use
  the close     the prediction archive's last look before kickoff
                (nfl.results.on_record) - the line the predictions page
                grades its own record on

It has to build after nfl.results.capture, which the section's build runs
before any page: a game that kicked off since the last run then has its
closing line on record.

    python -m nfl.site.homecards
"""
from datetime import datetime, timedelta

import pandas as pd

from cfb.results import BET_MIN
from gordstats import bets_card, paths
from gordstats.frontmatter import literal
from nfl import games as games_mod, predict, results
from nfl.config import DATA_DIR, SEASON, TZ
from nfl.site.schedule import week_key, week_label

BETS_OUT = paths.DOCS / "_includes" / "nfl_bets.html"
BETS_DIR = DATA_DIR / "best_bets"
# A game is called over this long after kickoff; the card moves on to the
# next week once the last one is.
GAME_HOURS = 4

# A disagreement worth pricing, in points: the gate the predictions page puts
# on a lean and its record against the spread (cfb.results.BET_MIN, which
# nfl.results grades with), so the record on this card is the record of
# exactly these picks. The NFL model disagrees with the book far less than
# the college one - on the 2026 archive's 256 lines the median gap is 1.8
# points, the college model's 4.0 - but a field goal is still the NFL's first
# key number, and 29% of spreads and 19% of totals clear it: a single in every
# week of the archive, and the full single and three-leg parlay in 15 of 17.
EDGE_MIN = BET_MIN
# And the widest worth believing. The college cap (10) is about the FCS and
# never binds here - the widest NFL gap on record is 8.4. What a wide NFL gap
# mostly is instead is news the model cannot see: it has no injuries and no
# quarterbacks, and the book has both. On the archive, a gap of 3-4 points
# had the line move 2+ points away from us since its first look 4% of the
# time; at 4-6 about a third of the time, and past 6, 5 times in 13 -
# Jets-Bears in week 4 is 6.2 because the line went from Bears -8.5 to -3.5
# while the model sat at 9.7. Six is the archive's 95th percentile: it rules
# out one game a week at most, the one likeliest to be a quarterback.
EDGE_MAX = 6.0
PARLAY_LEGS = bets_card.PARLAY_LEGS
LOCK_HOUR = bets_card.LOCK_HOUR


def _season() -> pd.DataFrame:
    frame, _model, _names = predict.season()
    return frame


def _keys(frame: pd.DataFrame) -> pd.Series:
    return pd.Series([week_key(w, s) for w, s in zip(frame["week"], frame["seasontype"])],
                     index=frame.index)


def _current_week(frame: pd.DataFrame, now: datetime) -> tuple:
    """(week key, first kickoff in Eastern time) for the week the card is
    about: the one being played, or the next one to start."""
    spans = frame.assign(key=_keys(frame)).groupby("key")["date"].agg(["min", "max"])
    for key, row in spans.sort_index().iterrows():
        if now < (row["max"] + timedelta(hours=GAME_HOURS)).to_pydatetime():
            return int(key), row["min"].tz_convert(TZ).to_pydatetime()
    if spans.empty:
        return None, None
    return int(spans.index[-1]), spans["min"].iloc[-1].tz_convert(TZ).to_pydatetime()


def _candidates(frame: pd.DataFrame, key: int, now: datetime) -> pd.DataFrame:
    """The week's games still to kick off, with both our number and the
    book's. A playoff game before its teams are known has neither."""
    games = frame[(_keys(frame) == key) & ~frame["played"].astype(bool)
                  & (frame["date"] > pd.Timestamp(now))]
    games = games[~games["home_id"].astype(str).str.startswith("-")
                  & ~games["away_id"].astype(str).str.startswith("-")]
    if games.empty:
        return pd.DataFrame()
    # The schedule's own `total` is points scored (nfl.games._derive); the
    # card's is the book's.
    games = (games.drop(columns=["spread", "total"], errors="ignore")
             .rename(columns={"book_spread": "spread", "book_total": "total"}))
    return bets_card.with_edges(games)


def _lock_path(key: int):
    return bets_card.lock_path(BETS_DIR, SEASON, key)


def locked_picks(frame: pd.DataFrame, key: int, first_kick: datetime,
                 now: datetime) -> tuple:
    """(picks, locked at, whether they are frozen): bets_card.locked_picks on
    this week's file, frozen from LOCK_HOUR Eastern on the day of its first
    game."""
    return bets_card.locked_picks(
        _lock_path(key),
        lambda: bets_card.pick_week(_candidates(frame, key, now), key,
                                    EDGE_MIN, EDGE_MAX, PARLAY_LEGS),
        first_kick, now, LOCK_HOUR)


def _finals(frame: pd.DataFrame) -> dict:
    """{game id: (home margin, total)} for games with a result, and
    bets_card.VOID for a game called off (games_mod.called_off) - a pick on
    it is a push, where it used to wait for a final that never came."""
    done = frame[frame["played"].astype(bool)]
    out = {str(g["game_id"]): (float(g["home_score"] - g["away_score"]),
                               float(g["home_score"] + g["away_score"]))
           for _, g in done.iterrows()}
    for gid in frame.loc[games_mod.called_off(frame) & ~frame["played"].astype(bool), "game_id"]:
        out[str(gid)] = bets_card.VOID
    return out


def _closes(now: datetime) -> dict:
    """{game id: (home spread, total)}, the archive's last line before
    kickoff, for the games that have kicked off. The archive keeps a look a
    day, the last of each run's, so for a Sunday game this is Sunday
    morning's line - near enough the close, and the line the predictions
    page's own record is graded on."""
    record = results.on_record(SEASON)
    if record.empty:
        return {}
    record = record[(record["kickoff"] <= pd.Timestamp(now)) & record["market_spread"].notna()]
    return {str(r["game_id"]): (float(r["market_spread"]),
                                None if pd.isna(r["market_total"]) else float(r["market_total"]))
            for _, r in record.iterrows()}


def _season_record(finals: dict, closes: dict) -> str:
    return bets_card.season_record(bets_card.saved_weeks(BETS_DIR, SEASON), finals, closes)


def bets_html(now: datetime = None, frame: pd.DataFrame = None) -> str:
    now = now or datetime.now(TZ)
    frame = _season() if frame is None else frame
    key, first_kick = _current_week(frame, now)
    if key is None:
        return bets_card.note("No games scheduled.")
    picks, when, frozen = locked_picks(frame, key, first_kick, now)
    if not picks.get("single"):
        # Why there is none, from the week's own numbers: "agree on every
        # game" was printed over totals 4 points off the book's.
        return bets_card.no_bet(EDGE_MIN, EDGE_MAX, _candidates(frame, key, now))
    finals = _finals(frame)
    closes = _closes(now)
    return bets_card.card_html(picks, week_label(key), now, when, frozen, finals, closes,
                               _season_record(finals, closes), "/nfl/", sport="NFL ")


def generate() -> None:
    BETS_OUT.parent.mkdir(parents=True, exist_ok=True)
    BETS_OUT.write_text(literal(bets_html()), encoding="utf-8")
    print(f"Wrote NFL best bets card -> {BETS_OUT}")


if __name__ == "__main__":
    generate()
