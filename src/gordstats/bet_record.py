"""
The honest half of a bet record: what the bets would have paid, and whether
the market came round to them.

A win-loss record is mostly luck for a long time. Against the spread a
bettor with a real edge wins 55% of the time where a coin wins 50%, and it
takes several hundred bets before the two records reliably come apart - the
home bets card makes four a week. What separates them sooner is the closing
line: the book's last number before kickoff is the best estimate there is of
a game, so a bet taken at a better number than the close was a good bet
whatever the score, and one taken at a worse number was not. That is the
figure bettors are judged on, and it is the one printed here beside the
record.

Two uses:

    units(wins, losses)            straight bets at -110, in units staked
    parlay_units(states)           one parlay, a unit at -110 a leg
    clv(pick, close)               points better (+) or worse (-) than the close

    moves(archive)                 the predictions pages: each call the model
    summary(moves(archive))        made on the early-week line, and whether
                                   the line then moved toward it by kickoff

`moves` reads a predictions archive (cfb.results / nfl.results - one row per
game per day it was captured, the book's line beside ours). A game's opening
call is its first capture inside the week before kickoff, if the two differed
there by `bet_min` points or more; its close is the last capture before
kickoff. The model's own number is left where it was at the open - the
question is whether the market moved to meet a number already on record.
"""
import numpy as np
import pandas as pd

PRICE = -110
WIN = 100 / -PRICE            # what a unit wins at -110
BET_MIN = 3                   # the gate cfb.results.BET_MIN puts on a bet
WINDOW = pd.Timedelta(days=7)


def units(wins: int, losses: int) -> float:
    """Straight bets, a unit each at -110; a push returns the stake."""
    return wins * WIN - losses


def parlay_units(states) -> float | None:
    """One parlay, a unit staked. `states` is each leg: True, False, None for a
    push, "" for not yet played. A lost leg settles it at once; a pushed leg
    drops out, as a book would price it; None while it is still live."""
    states = list(states)
    if any(s is False for s in states):
        return -1.0
    if any(s == "" for s in states):
        return None
    won = sum(1 for s in states if s is True)
    return (1 + WIN) ** won - 1 if won else 0.0


def clv(pick: dict, close) -> float | None:
    """How much better the number taken was than the closing one, in points,
    from the pick's side: laying 17.5 on a game that closed at 18.5 is +1.0,
    taking +10 on one that closed at +10.5 is -0.5. `close` is the closing
    line from the same side - the spread for the team picked, or the total."""
    if close is None or pd.isna(close):
        return None
    if pick["kind"] == "spread":
        return round(float(pick["line"]) - float(close), 1)
    return round((float(close) - float(pick["line"])) * (1 if pick["side"] == "Over" else -1), 1)


def moves(archive: pd.DataFrame, bet_min: float = BET_MIN,
          now: pd.Timestamp = None) -> pd.DataFrame:
    """One row per call the model made on the early-week line, for games
    already kicked off: kind, the lean at the open (points, signed toward the
    side it liked), the open and close lines, and `clv`, how far the line
    moved toward that side by kickoff."""
    cols = ["game_id", "kind", "lean", "open", "close", "clv"]
    if archive is None or archive.empty:
        return pd.DataFrame(columns=cols)
    now = now if now is not None else pd.Timestamp.now(tz="UTC")
    a = archive.copy()
    a["captured_at"] = pd.to_datetime(a["captured"], utc=True, format="ISO8601")
    a["kickoff"] = pd.to_datetime(a["kickoff"], utc=True)
    a = a[(a["captured_at"] < a["kickoff"]) & (a["kickoff"] <= now)
          & (a["kickoff"] - a["captured_at"] <= WINDOW)].sort_values("captured_at")
    out = []
    for kind, ours, book, sign in (("spread", "pred_margin", "market_spread", -1),
                                   ("total", "pred_total", "market_total", 1)):
        priced = a.dropna(subset=[ours, book])
        if priced.empty:
            continue
        # Both lines in the model's terms: home margin for a spread (the book
        # quotes the home side's line, so a -7 is +7 of margin), points for a
        # total. A positive lean likes the home side, or the over.
        # The first look of the week, and only if it was a call then: taking
        # the first capture where the gap reached `bet_min` instead would
        # pick games whose line had just moved away from us, and lines that
        # wander tend to wander back - the record would flatter itself.
        opened = priced.drop_duplicates("game_id", keep="first")
        opened = opened[(opened[ours] - sign * opened[book]).abs() >= bet_min]
        closed = priced.drop_duplicates("game_id", keep="last").set_index("game_id")
        for r in opened.itertuples(index=False):
            last = closed.loc[r.game_id]
            if last["captured_at"] <= r.captured_at:      # one look at the line: no move to judge
                continue
            side = 1 if getattr(r, ours) - sign * getattr(r, book) > 0 else -1
            moved = sign * (float(last[book]) - float(getattr(r, book)))
            out.append({"game_id": r.game_id, "kind": kind,
                        "lean": round(abs(getattr(r, ours) - sign * getattr(r, book)), 1),
                        "open": float(getattr(r, book)), "close": float(last[book]),
                        "clv": round(side * moved, 1)})
    return pd.DataFrame(out, columns=cols)


def summary(frame: pd.DataFrame) -> dict:
    """{calls, moved, our_way, against, avg} over a `moves` frame; `avg` is
    the closing-line value a call, in points, the unmoved lines included."""
    if frame is None or frame.empty:
        return {"calls": 0, "moved": 0, "our_way": 0, "against": 0, "avg": None}
    v = frame["clv"].astype(float)
    return {"calls": int(len(v)), "moved": int((v != 0).sum()),
            "our_way": int((v > 0).sum()), "against": int((v < 0).sum()),
            "avg": float(np.round(v.mean(), 2))}
