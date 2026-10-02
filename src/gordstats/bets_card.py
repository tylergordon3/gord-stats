"""
The week's bets card on the homepage, for any sport with a model and a book:
one spread bet and a short parlay, taken from the model's widest
disagreements with the book and frozen for the week the morning of its first
kickoff, then graded once the games are played - legs won and lost, what the
bets as offered would have paid, and how the numbers taken compare with where
the lines closed (gordstats.bet_record).

Written for the college card (cfb.site.homecards) and shared with the NFL's
(nfl.site.homecards) when the owner asked for every football feature in both
sections. A sport brings what only it knows:

    its games     the week's unplayed games with our number beside the
                  book's - game_id, home, away, date, spread (the home line,
                  favourite negative), total, pred_margin (home), pred_total;
                  with_edges() adds the disagreements
    its gates     edge_min, edge_max: the smallest disagreement worth pricing,
                  and the largest worth believing - past it the gap is a
                  modelling artefact or news the model cannot see
    its finals    {game id: (home margin, total)} for games with a result
    its closes    {game id: (home spread, total)}, the book's last line before
                  kickoff, for games that have kicked off

and this does the rest: the picks, the lock, the grading and the card. The
card is plain HTML with its own <style> block, written by each section as an
include (docs/_includes/<sport>_bets.html) that the homepage places.

The picks are frozen to data/<sport>/best_bets/{season}_wkNN.json the first
time a build runs after LOCK_HOUR on the day of the week's first kickoff.
Before that the card shows what it would take and says when it locks; after
it the file on disk is the card, whatever the model later thinks.
"""
import json
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

import pandas as pd

from gordstats import bet_record, share_button

ET = ZoneInfo("America/New_York")

# The picks are frozen from this hour on the day of the week's first kickoff -
# "Thursday morning" for a normal week, and the right morning for the weeks
# that open on a Tuesday (college) or a Saturday (the NFL's playoffs).
LOCK_HOUR = 9
PARLAY_LEGS = 3

# The card's colours as variables on .hc, so the college Top 25 table (which
# shares them) and both sports' bets cards read as one family on the home page.
VARS_CSS = """.hc{--hc-line:#e5e7eb;--hc-ink:#0f172a;--hc-mute:#64748b;--hc-soft:#f8fafc;
  --hc-up:#15803d;--hc-down:#b91c1c;--hc-accent:#2a78d6;--hc-flag:#d08700;
  --hc-rank:#475569;--hc-disc:transparent;
  --hc-hi-bg:rgba(21,128,61,.10);--hc-lo-bg:rgba(185,28,28,.09);
  --hc-focus:rgba(42,120,214,.14)}
@media (prefers-color-scheme:dark){
  .hc{--hc-line:#2b3852;--hc-ink:#e3eaf4;--hc-mute:#aab7c9;--hc-soft:#1b2540;
    --hc-up:#6ee7b7;--hc-down:#ff9b91;--hc-accent:#6aa9f0;--hc-flag:#e0a92a;
    --hc-rank:#cbd5e1;--hc-disc:#e8edf4;
    --hc-hi-bg:rgba(110,231,183,.13);--hc-lo-bg:rgba(255,155,145,.13);
    --hc-focus:rgba(106,169,240,.20)}
}
.hc .hc-note{font-size:12px;color:var(--hc-mute);margin:8px 0 0;line-height:1.5}
"""

BETS_CSS = """/* --- The week's bets ------------------------------------------------------
   These classes went out unstyled, so the card rendered as the site theme's
   default list - which is what "it is just a list" meant. The pick is the
   headline, so it is set big; everything explaining it is small and muted. */
.hc-bet{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(240px,1fr))}
.hc-pick{border:1px solid var(--hc-line);border-radius:10px;padding:11px 13px;
  background:var(--hc-soft);min-width:0}
.hc-kind{font-size:11px;font-weight:800;text-transform:uppercase;
  letter-spacing:.07em;color:var(--hc-accent);margin:0 0 6px}
.hc-call{font-size:19px;font-weight:800;color:var(--hc-ink);line-height:1.2;
  font-variant-numeric:tabular-nums;display:flex;align-items:center;gap:7px;
  flex-wrap:wrap}
.hc .hc-sub{font-size:12px;color:var(--hc-mute);line-height:1.45;margin-top:3px}
/* Legs are rows, not bullets: three picks stacked with a rule between them
   read as three picks. A disc in front of each read as prose. */
.hc .hc-legs{list-style:none;margin:0;padding:0}
.hc .hc-legs li{margin:0;padding:7px 0;border-top:1px solid var(--hc-line);
  font-size:15px;font-weight:700;color:var(--hc-ink);
  font-variant-numeric:tabular-nums}
.hc .hc-legs li:first-child{border-top:0;padding-top:0}
.hc .hc-legs li:last-child{padding-bottom:0}
.hc-res{font-size:11px;font-weight:800;padding:1px 6px;border-radius:999px;
  text-transform:uppercase;letter-spacing:.04em;vertical-align:middle}
.hc-res.win{color:var(--hc-up);background:var(--hc-hi-bg)}
.hc-res.loss{color:var(--hc-down);background:var(--hc-lo-bg)}
.hc-res.push{color:var(--hc-mute);background:var(--hc-focus)}
/* When it was worked out, and how long it stands. Its own line above the
   record so neither has to be hunted for in a paragraph. */
.hc-when-row{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 12px;
  margin:11px 0 0;font-size:11px;text-transform:uppercase;letter-spacing:.04em;
  color:var(--hc-mute)}
.hc-lock{font-weight:800;color:var(--hc-flag)}
.hc-lock.hc-locked{color:var(--hc-mute)}
.hc-rec{font-size:13px;color:var(--hc-ink);margin:7px 0 0;line-height:1.45}
.hc .hc-up{color:var(--hc-up);font-weight:700}
.hc .hc-down{color:var(--hc-down);font-weight:700}
.hc-rec .hc-dis{color:var(--hc-mute)}
@media (max-width:560px){
  .hc-bet{grid-template-columns:1fr;gap:8px}
  .hc-call{font-size:17px}
  .hc .hc-legs li{font-size:14px}
}
"""

CSS = "<style>\n" + VARS_CSS + BETS_CSS + "</style>"

LOCK_JS = """{% raw %}<script>
(function(){
  // Counts the provisional card down to its lock. Server-rendered text is
  // already correct ("Locks Thu 9 AM ET"), so this only sharpens it while the
  // page is open and never leaves it blank if the date will not parse. The
  // home page carries a card per sport and one clock ticks them all; a card
  // parsed after the clock started asks it for a tick of its own.
  if(window.__hcLockTick){ window.__hcLockTick(); return; }
  window.__hcLockTick=tick;
  function tick(){
    var els=document.querySelectorAll('.hc-lock[data-lock]');
    for(var i=0;i<els.length;i++){
      var at=Date.parse(els[i].dataset.lock);
      if(isNaN(at)) continue;
      var left=at-Date.now();
      if(left<=0){
        els[i].textContent='Locking now';
        els[i].removeAttribute('data-lock');
        continue;
      }
      var m=Math.floor(left/60000), h=Math.floor(m/60), d=Math.floor(h/24);
      els[i].textContent='Locks in '+(d?d+'d '+(h%24)+'h':h?h+'h '+(m%60)+'m':m+'m');
    }
  }
  tick();
  setInterval(tick, 60000);
})();
</script>{% endraw %}"""


# --------------------------------------------------------------------------- #
# Picking
# --------------------------------------------------------------------------- #

def with_edges(games: pd.DataFrame) -> pd.DataFrame:
    """`games` with the book's line in the model's terms and the two
    disagreements: `edge` (points of home margin; positive likes the home
    side) and `ou_edge` (points; positive likes the over)."""
    games = games.copy()
    # Numbers whatever came in: a week with no line on any game (every spread
    # None) arrives as an object column, and `-games["spread"]` raised on it
    # and took the NFL card down. No line is NaN, and NaN is no pick.
    for col in ("spread", "total", "pred_margin", "pred_total"):
        games[col] = pd.to_numeric(games[col], errors="coerce").astype(float)
    # The book prices the home side; the model talks in home margin.
    games["market_margin"] = -games["spread"]
    games["edge"] = games["pred_margin"] - games["market_margin"]
    games["ou_edge"] = games["pred_total"] - games["total"]
    return games


def spread_pick(game) -> dict:
    """The side the model wants, and the number it is laying or taking.

    Both numbers are quoted from that side's own point of view - a pick on the
    underdog reading "we make it +29, the book +56" is two different sign
    conventions in one sentence. `model` and `market_margin` are margins (the
    side wins by); the card writes them as lines (as_line).
    """
    home = game["edge"] > 0
    side, other = (game["home"], game["away"]) if home else (game["away"], game["home"])
    flip = 1 if home else -1
    return {"kind": "spread", "game_id": str(game["game_id"]),
            "team": str(side), "opponent": str(other), "home": bool(home),
            "line": round(float(game["spread"] * flip), 1),
            "market_margin": round(float(game["market_margin"] * flip), 1),
            "model": round(float(game["pred_margin"] * flip), 1),
            "edge": round(float(abs(game["edge"])), 1),
            "kickoff": pd.Timestamp(game["date"]).isoformat()}


def total_pick(game) -> dict:
    over = game["ou_edge"] > 0
    return {"kind": "total", "game_id": str(game["game_id"]),
            "team": f"{game['away']} at {game['home']}", "opponent": "",
            "side": "Over" if over else "Under", "line": round(float(game["total"]), 1),
            "model": round(float(game["pred_total"]), 1),
            "edge": round(float(abs(game["ou_edge"])), 1),
            "kickoff": pd.Timestamp(game["date"]).isoformat()}


def pick_week(games: pd.DataFrame, week: int, edge_min: float, edge_max: float,
              legs: int = PARLAY_LEGS) -> dict:
    """The card's picks for a week from its candidate games (with_edges), as
    they would be taken right now: the widest spread disagreement inside the
    gates as the single, the next `legs` widest calls - spreads or totals -
    as the parlay."""
    out = {"week": week, "single": None, "parlay": []}
    if games.empty:
        return out
    spreads = games.dropna(subset=["spread", "edge"])
    spreads = spreads[spreads["edge"].abs().between(edge_min, edge_max)].sort_values(
        "edge", key=lambda s: s.abs(), ascending=False)
    totals = games.dropna(subset=["total", "ou_edge"])
    totals = totals[totals["ou_edge"].abs().between(edge_min, edge_max)].sort_values(
        "ou_edge", key=lambda s: s.abs(), ascending=False)

    picks = [spread_pick(g) for _, g in spreads.iterrows()]
    if picks:
        out["single"] = picks[0]
    # The parlay is the next-best calls, and deliberately not the single again:
    # one bet repeated inside a parlay is one opinion priced twice.
    rest = picks[1:] + [total_pick(g) for _, g in totals.iterrows()]
    rest.sort(key=lambda p: -p["edge"])
    out["parlay"] = rest[:legs]
    return out


# --------------------------------------------------------------------------- #
# The lock
# --------------------------------------------------------------------------- #

def lock_path(bets_dir, season: int, week: int):
    return bets_dir / f"{season}_wk{int(week):02d}.json"


def locked_picks(path, pick, first_kick: datetime, now: datetime,
                 lock_hour: int = LOCK_HOUR) -> tuple:
    """(picks, locked at, whether they are frozen).

    Frozen from `lock_hour` on the day of the week's first kickoff: the file is
    written once and then read, so a card published on Saturday says what it
    said on Thursday even if the ratings have moved since. `pick` is called
    for the picks only when there is no file yet - the model is not asked
    about a week it has already answered for. `first_kick` and `now` are
    both naive (the machine's clock, which is Eastern on the Pi) or both
    aware.
    """
    if path.exists():
        saved = json.loads(path.read_text(encoding="utf-8"))
        return saved, datetime.fromisoformat(saved["locked"]), True
    picks = pick()
    lock_at = first_kick.replace(hour=lock_hour, minute=0, second=0, microsecond=0)
    if now < lock_at or not picks["single"]:
        return picks, lock_at, False
    picks["locked"] = now.isoformat(timespec="seconds")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(picks, indent=1), encoding="utf-8")
    return picks, now, True


def saved_weeks(bets_dir, season: int) -> list:
    """Every week of the season whose picks were locked, in order."""
    return [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(bets_dir.glob(f"{season}_wk*.json"))]


def legs(weeks: list) -> list:
    """Every pick of those weeks, singles and parlay legs alike."""
    return [p for w in weeks
            for p in ([w["single"]] if w.get("single") else []) + w.get("parlay", [])]


# --------------------------------------------------------------------------- #
# Grading
# --------------------------------------------------------------------------- #

# A sport's finals carry this for a game called off - cancelled, or postponed
# out of the week - rather than leaving it out: left out, a locked pick on it
# waited for a result that never came and the week never settled.
VOID = (None, None)


def grade(pick: dict, finals: dict):
    """True, False, None (push) or "" for a game that has not finished. A
    game called off (VOID) is a push, as a book voids the bet."""
    got = finals.get(pick["game_id"])
    if got is None:
        return ""
    margin, total = got
    if margin is None or pd.isna(margin):
        return None
    if pick["kind"] == "spread":
        # The pick's own margin: the side it took, against the line it took.
        mine = margin if pick["home"] else -margin
        cover = mine + pick["line"]
        return None if abs(cover) < 1e-9 else cover > 0
    diff = total - pick["line"]
    return None if abs(diff) < 1e-9 else (diff > 0) == (pick["side"] == "Over")


def close_of(pick: dict, closes: dict):
    """The closing line from the pick's side: the picked team's spread, or
    the total."""
    got = closes.get(str(pick["game_id"]))
    if not got:
        return None
    spread, total = got
    if pick["kind"] == "spread":
        return spread if pick["home"] else -spread
    return total


def close_html(pick: dict, closes: dict) -> str:
    """"Closed -18.5 · beat it by 1.0" under a pick whose game has started."""
    close = close_of(pick, closes)
    gain = bet_record.clv(pick, close)
    if gain is None:
        return ""
    shown = f"{close:+.1f}" if pick["kind"] == "spread" else f"{close:.1f}"
    if gain > 0:
        verdict = f"<span class='hc-up'>beat it by {gain:.1f}</span>"
    elif gain < 0:
        verdict = f"<span class='hc-down'>{-gain:.1f} worse</span>"
    else:
        verdict = "the same number"
    return f"<div class='hc-sub'>Closed {shown} &middot; {verdict}</div>"


def mark(state) -> str:
    if state == "":
        return ""
    if state is None:
        return "<span class='hc-res push'>push</span>"
    return ("<span class='hc-res win'>&check;</span>" if state
            else "<span class='hc-res loss'>&times;</span>")


def season_record(weeks: list, finals: dict, closes: dict) -> str:
    """How every locked pick of the season has done: the picks graded on the
    results, what the bets as offered would have paid (a unit on each week's
    single and a unit on its parlay, at -110), and how the numbers taken
    compare with where the lines closed (gordstats.bet_record)."""
    wins = losses = pushes = 0
    paid, settled = 0.0, 0
    for w in weeks:
        if w.get("single"):
            state = grade(w["single"], finals)
            if state not in ("", None):
                paid += bet_record.units(int(state), int(not state))
            settled += state != ""
        if w.get("parlay"):
            got = bet_record.parlay_units(grade(p, finals) for p in w["parlay"])
            if got is not None:
                paid, settled = paid + got, settled + 1
    every = legs(weeks)
    for pick in every:
        state = grade(pick, finals)
        if state == "":
            continue
        if state is None:
            pushes += 1
        else:
            wins, losses = wins + int(state), losses + int(not state)
    if not (wins + losses + pushes):
        return ""
    gains = [g for g in (bet_record.clv(p, close_of(p, closes)) for p in every) if g is not None]
    out = (f"Locked picks this season: <strong>{wins}-{losses}"
           + (f"-{pushes}" if pushes else "") + "</strong>")
    if settled:
        sign = "+" if paid >= 0 else "&minus;"
        out += (f", <strong title='A unit on each week&#39;s single and one on its parlay, "
                f"at -110'>{sign}{abs(paid):.1f} units</strong>")
    if gains:
        better, worse = sum(g > 0 for g in gains), sum(g < 0 for g in gains)
        out += (f"; against the closing line, <strong>{better} better</strong>, "
                f"<strong>{worse} worse</strong>")
        if len(gains) - better - worse:
            out += f", {len(gains) - better - worse} the same"
    return out + "."


# --------------------------------------------------------------------------- #
# The card
# --------------------------------------------------------------------------- #

def as_line(margin: float) -> str:
    """A side's winning margin written as a sportsbook line, the favourite
    negative: we have them winning by 14.9 -> -14.9 (the card read "+14.9"
    beside a call of "-6.0", two conventions in one sentence)."""
    line = -float(margin)
    return "pk" if abs(line) < 0.05 else f"{line:+.1f}"


def leg_html(pick: dict, finals: dict, closes: dict = None) -> str:
    if pick["kind"] == "spread":
        call = f"{escape(pick['team'])} {pick['line']:+.1f}"
        sub = (f"vs {escape(pick['opponent'])} &middot; we have them "
               f"{as_line(pick['model'])}, the book {as_line(pick['market_margin'])}")
    else:
        call = f"{pick['side']} {pick['line']:.1f}"
        sub = f"{escape(pick['team'])} &middot; we make it {pick['model']:.1f}"
    return (f"<li>{call}{mark(grade(pick, finals))}"
            f"<div class='hc-sub'>{sub}</div>{close_html(pick, closes or {})}</li>")


def note(text: str) -> str:
    """The card when there is nothing to bet: one muted line."""
    return CSS + f"<div class='hc'><p class='hc-note'>{text}</p></div>"


def no_bet(edge_min: float, edge_max: float = None, games: pd.DataFrame = None) -> str:
    """The card for a week with no single to name. Given the week's
    candidates (with_edges), it says why, truthfully: "agree on every game"
    was printed for an NFL week whose totals were 4 points off the book's
    (the card names a parlay only beside a single) and for one whose only
    wide spread was past `edge_max`."""
    text = (f"The model and the book agree to within {edge_min:.0f} points on every "
            "game this week, so there is no bet to name.")
    if games is None:
        return note(text)
    spreads = games["edge"].abs() if "edge" in games else pd.Series(dtype=float)
    totals = games["ou_edge"].abs() if "ou_edge" in games else pd.Series(dtype=float)
    if not (spreads.notna().any() or totals.notna().any()):
        # Every game under way, a playoff round whose teams are not set, or
        # no line up yet: there is nothing to compare, agreed or not.
        text = ("No game still to play this week has both our number and the book's, "
                "so there is no bet to name.")
    else:
        wide_spread = bool((spreads >= edge_min).any())
        if wide_spread and edge_max is not None:
            text = (f"No spread this week is between {edge_min:.0f} and {edge_max:.0f} points "
                    "off the book's - closer is agreement, further is likelier news the model "
                    "cannot see - so there is no bet to name.")
        elif wide_spread or bool((totals >= edge_min).any()):
            text = (f"The model and the book agree to within {edge_min:.0f} points on every "
                    "spread this week, so there is no bet to name.")
    return note(text)


def _instant(when: datetime) -> str:
    """An ISO instant for the countdown. A naive time is the machine's clock,
    which is Eastern where the card is built; the reader may not be."""
    return (when.replace(tzinfo=ET) if when.tzinfo is None else when).isoformat()


def card_html(picks: dict, label: str, now: datetime, when: datetime, frozen: bool,
              finals: dict, closes: dict, record: str, href: str,
              sport: str = "") -> str:
    """The card for a week with a single to name. `label` is the week's name
    ("Week 5", "Wild Card"), `record` the season_record line, `href` the page
    with the full record, and `sport` a prefix for the Share line ("NFL ")."""
    single = picks["single"]
    body = [f"<div class='hc-bet'><div class='hc-pick'>"
            f"<div class='hc-kind'>Single bet</div>"
            f"<div class='hc-call'>{escape(single['team'])} {single['line']:+.1f}"
            f"{mark(grade(single, finals))}</div>"
            f"<div class='hc-sub'>vs {escape(single['opponent'])} &middot; we have them "
            f"{as_line(single['model'])}, the book {as_line(single['market_margin'])}</div>"
            f"{close_html(single, closes)}</div>"]
    if picks["parlay"]:
        rows = "".join(leg_html(p, finals, closes) for p in picks["parlay"])
        body.append(f"<div class='hc-pick'><div class='hc-kind'>"
                    f"{len(picks['parlay'])}-leg parlay</div>"
                    f"<ul class='hc-legs'>{rows}</ul></div>")
    body.append("</div>")

    # Two short lines instead of a paragraph: when the call was made and how
    # long it stands, then the record. The backtest caveat that used to live
    # here (these picks hit 48% ATS, under the 52.4% juice needs) was four
    # lines of small print nobody read on a phone; it belongs with the rest of
    # the record, one tap away on the predictions page.
    if frozen:
        timing = (f"<span>Generated {when:%a %-d %b, %-I:%M %p ET}</span>"
                  f"<span class='hc-lock hc-locked'>Locked</span>")
    else:
        # Emitted as an instant, not a wall clock: the reader may not be
        # Eastern.
        timing = (f"<span>Generated {now:%a %-d %b, %-I:%M %p ET}</span>"
                  f"<span class='hc-lock' data-lock='{_instant(when)}'>"
                  f"Locks {when:%a %-I %p ET}</span>")
    foot = (f"<div class='hc-when-row'><span>{escape(label)}</span>{timing}</div>"
            f"<p class='hc-rec'>{record} <span class='hc-dis'>Not gambling "
            f"advice.</span> <a href='{href}'>Full record</a>.</p>")
    # The bet, as the sender would have typed it; the home page it links to
    # carries this card.
    line = (f"GordStats' {sport}{label} bet: {single['team']} {single['line']:+.1f} "
            f"vs {single['opponent']}")
    if picks["parlay"]:
        line += f", plus a {len(picks['parlay'])}-leg parlay"
    # The countdown after the card, not before it: ahead of the card its first
    # tick found no lock to count down to, and the text sat unsharpened for
    # the first minute on the page.
    return (CSS + "<div class='hc'>" + "".join(body)
            + foot + share_button.row("/", line) + "</div>" + LOCK_JS)
