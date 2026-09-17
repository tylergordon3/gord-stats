"""
The two CFB graphics on the homepage (docs/_includes/cfb_top25.html and
cfb_bets.html).

The homepage is written by cbb.render.render_home, which has no business
importing the football model, so this follows the pattern cfb.site.countdown
set: the CFB build writes an include, and the homepage includes it. Both are
plain HTML with their own <style> block, so nothing has to be added to the
site theme for one card.

  Top 25    the three rankings side by side - ours, the AP poll and ESPN's
            FPI - ordered by where they agree, so the rows that disagree are
            the point of the table rather than a footnote.
  Best bets one spread bet and a short parlay, taken from the model's widest
            disagreements with the book and frozen for the week the morning
            of its first kickoff. What that is worth is printed on the card:
            see the note below.

    python -m cfb.site.homecards
"""
from datetime import datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

import pandas as pd

from cfb import espn, games as games_mod, predict, results
from cfb import odds as odds_mod
from cfb.config import DATA_DIR, SEASON
from cfb.site import power, teams as teams_page
from gordstats import paths

ET = ZoneInfo("America/New_York")
TOP25_OUT = paths.DOCS / "_includes" / "cfb_top25.html"
BETS_OUT = paths.DOCS / "_includes" / "cfb_bets.html"
BETS_DIR = DATA_DIR / "best_bets"
LOGO = "https://a.espncdn.com/i/teamlogos/ncaa/500/{team_id}.png"

# The picks are frozen from this hour on the day of the week's first kickoff -
# "Thursday morning" for a normal week, and the right morning for the weeks
# that open on a Tuesday. Before it the card shows what it would take and says
# so; after it the file on disk is the card, whatever the model later thinks.
LOCK_HOUR = 9

# A disagreement worth pricing, in points. Same gate as the predictions page's
# scored record (cfb.results.BET_MIN), so the record printed on this card is
# the record of exactly these picks.
EDGE_MIN = results.BET_MIN
# And the widest worth believing. Every FBS team has its own rating; the whole
# of the FCS shares one bucket, so a game against it is priced by a number that
# was never fitted to that opponent - which is how a first cut of this card
# came back holding four 30-point disagreements, all of them cupcakes. Those
# games are dropped outright, and a disagreement bigger than this on a real
# matchup is treated as a modelling artefact rather than a bet.
EDGE_MAX = 10
PARLAY_LEGS = 3

_CSS = """<style>
.hc{--hc-line:#e5e7eb;--hc-ink:#0f172a;--hc-mute:#64748b;--hc-soft:#f8fafc;
  --hc-up:#15803d;--hc-down:#b91c1c;--hc-accent:#2a78d6}
@media (prefers-color-scheme:dark){
  .hc{--hc-line:#2b3852;--hc-ink:#e3eaf4;--hc-mute:#aab7c9;--hc-soft:#1b2540;
    --hc-up:#6ee7b7;--hc-down:#ff9b91;--hc-accent:#3987e5}
}
.hc table{width:100%;border-collapse:collapse;font-size:13px;margin:0}
/* The site theme paints every th a dark bar; these are column labels inside a
   card, not a header band, so the background is reset here. */
.hc th{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--hc-mute);
  font-weight:700;padding:4px 6px;text-align:center;background:transparent;
  border:0;border-bottom:1px solid var(--hc-line)}
.hc th:first-child{text-align:left}
.hc td{padding:4px 6px;text-align:center;color:var(--hc-ink);
  border-bottom:1px solid var(--hc-line);white-space:nowrap}
.hc tr:nth-child(even) td{background:var(--hc-soft)}
.hc td.hc-team{text-align:left;font-weight:600;width:99%}
.hc td.hc-team img{width:18px;height:18px;object-fit:contain;vertical-align:middle;
  margin:0 7px 0 0;border:none;padding:0;box-shadow:none;background:none;border-radius:0}
.hc .hc-rk{display:inline-block;min-width:18px;text-align:right;color:var(--hc-mute);
  font-size:11px;margin-right:6px}
.hc .hc-none{color:var(--hc-mute)}
/* A row the three sources disagree about, which is the reason to look. */
.hc tr.hc-split td{background:#fdf6e3}
@media (prefers-color-scheme:dark){.hc tr.hc-split td{background:#33301a}}
.hc .hc-note{font-size:12px;color:var(--hc-mute);margin:8px 0 0;line-height:1.5}
.hc .hc-scroll{overflow-x:auto}
/* Bets */
.hc-bet{display:flex;flex-wrap:wrap;gap:10px;margin:0 0 4px}
.hc-pick{flex:1 1 220px;border:1px solid var(--hc-line);border-radius:10px;padding:9px 11px}
.hc-pick .hc-kind{font-size:10px;text-transform:uppercase;letter-spacing:.06em;
  color:var(--hc-mute);font-weight:700}
.hc-pick .hc-call{font-size:16px;font-weight:700;color:var(--hc-ink);margin:2px 0 1px}
.hc-pick .hc-sub{font-size:12px;color:var(--hc-mute)}
.hc-legs{list-style:none;margin:4px 0 0;padding:0}
.hc-legs li{font-size:13px;color:var(--hc-ink);padding:3px 0;border-bottom:1px solid var(--hc-line)}
.hc-legs li:last-child{border-bottom:0}
.hc-legs .hc-sub{color:var(--hc-mute);font-size:12px}
.hc-res{font-weight:700;margin-left:6px}
.hc-res.win{color:var(--hc-up)}
.hc-res.loss{color:var(--hc-down)}
.hc-res.push{color:var(--hc-mute)}
.hc-stamp{font-size:11px;color:var(--hc-mute);text-transform:uppercase;letter-spacing:.04em}
</style>"""


# --------------------------------------------------------------------------- #
# Top 25: ours, the AP poll, ESPN's FPI
# --------------------------------------------------------------------------- #

def _rankings() -> tuple:
    """({espn id: {name, logo, gs, ap, fpi}}, whether the AP poll is live)."""
    rows = power._rows(power.fpi())
    ap_ranks, ap_season, _label = power.ap_poll()
    show_ap = bool(ap_ranks) and ap_season == SEASON

    teams = {}
    for i, t in enumerate(rows, 1):
        teams[t["id"]] = {"name": t["school"] or t["name"], "logo": t["logo"],
                          "fpi": i, "ap": None, "gs": None}
    frame, model, names = predict.season()
    for _, r in teams_page._standings(frame, model, names).iterrows():
        team = teams.setdefault(str(r["team"]), {"name": str(r["name"]), "logo": None,
                                                 "fpi": None, "ap": None, "gs": None})
        team["gs"] = int(r["rank"])
    if show_ap:
        for team_id, rank in ap_ranks.items():
            teams.setdefault(team_id, {"name": team_id, "logo": None, "fpi": None,
                                       "ap": None, "gs": None})["ap"] = int(rank)
    return teams, show_ap


def _cell(rank) -> str:
    return f"<span class='hc-none'>&mdash;</span>" if rank is None else f"{rank}"


def top25_html(limit: int = 25) -> str:
    teams, show_ap = _rankings()
    sources = ["gs", "fpi"] + (["ap"] if show_ap else [])

    def ranked(team) -> list:
        # Outside a poll's top 25 is not a rank; the AP simply stops at 25, so
        # a team the poll never named is ordered on the sources that do name it.
        return [team[s] for s in sources if team[s] is not None and
                (s != "ap" or team[s] <= 25)]

    rows = []
    for team_id, team in teams.items():
        seen = ranked(team)
        # In somebody's top 25 - one source liking a team enough is the whole
        # reason a disagreement row exists.
        if not seen or min(seen) > limit:
            continue
        rows.append((sum(seen) / len(seen), max(seen) - min(seen), team_id, team))
    rows.sort(key=lambda r: r[0])
    rows = rows[:limit]

    body = []
    for i, (_avg, spread, team_id, team) in enumerate(rows, 1):
        logo = (f"<img src='{LOGO.format(team_id=escape(str(team_id)))}' alt='' "
                f"loading='lazy'>")
        cells = "".join(f"<td>{_cell(team[s])}</td>" for s in ("gs", "ap", "fpi")
                        if s != "ap" or show_ap)
        body.append(f"<tr{' class=hc-split' if spread >= 8 else ''}>"
                    f"<td class='hc-team'><span class='hc-rk'>{i}</span>{logo}"
                    f"{escape(str(team['name']))}</td>{cells}</tr>")

    head = ("<tr><th>Team</th><th>GS</th>" + ("<th>AP</th>" if show_ap else "")
            + "<th>FPI</th></tr>")
    # The row the three sources argue about hardest, named in words - a table
    # of numbers does not say "look here" on its own.
    argued = max(rows, key=lambda r: r[1]) if rows else None
    note = ("<strong>GS</strong> is this site's rating, <strong>FPI</strong> ESPN's"
            + (", <strong>AP</strong> the poll" if show_ap else "")
            + ". Ordered by where they agree; highlighted where they are eight or "
            "more places apart.")
    if argued and argued[1] >= 8:
        team = argued[3]
        ranks = ", ".join(f"{s.upper() if s != 'gs' else 'GS'} {team[s]}"
                          for s in ("gs", "ap", "fpi")
                          if team[s] is not None and (s != "ap" or show_ap))
        note = (f"Widest disagreement: <strong>{escape(str(team['name']))}</strong> "
                f"({ranks}). ") + note
    return (_CSS + "<div class='hc'><div class='hc-scroll'><table>"
            f"<thead>{head}</thead><tbody>{''.join(body)}</tbody></table></div>"
            f"<p class='hc-note'>{note}</p></div>")


# --------------------------------------------------------------------------- #
# Best bets, frozen for the week
# --------------------------------------------------------------------------- #

def _current_week(now: datetime) -> tuple:
    """(week number, first kickoff) for the week the card is about: the one
    being played, or the next one to start."""
    spans = espn.week_spans()
    for number, start, end in spans:
        if now < end:
            return number, start
    return (spans[-1][0], spans[-1][1]) if spans else (None, None)


def _candidates(week: int) -> pd.DataFrame:
    """This week's games with both our number and the book's, widest first."""
    frame, _model, _names = predict.season()
    games = frame[(frame["week"] == week) & (~frame["played"])].copy()
    # FBS on both sides. The FCS pool is one shared rating, and the schools the
    # model does rate individually but ESPN does not cover (Sacramento St, N
    # Dakota St) are fitted on a handful of games against each other - either
    # way the number is not one to bet. espn.conferences() is exactly the FBS.
    fbs = set(espn.conferences())
    both = (games["home_id"].astype(str).isin(fbs) & games["away_id"].astype(str).isin(fbs)
            & (games["home_team"] != games_mod.FCS) & (games["away_team"] != games_mod.FCS))
    games = games[both].copy()
    board = odds_mod.latest(SEASON)
    if games.empty or board.empty:
        return pd.DataFrame()
    games = games.merge(board[["home_id", "away_id", "spread", "total"]],
                        on=["home_id", "away_id"], how="left")
    # The book prices the home side; the model talks in home margin.
    games["market_margin"] = -games["spread"]
    games["edge"] = games["pred_margin"] - games["market_margin"]
    games["ou_edge"] = games["pred_total"] - games["total"]
    return games


def _spread_pick(game) -> dict:
    """The side the model wants, and the number it is laying or taking.

    Both numbers are quoted from that side's own point of view - a pick on the
    underdog reading "we make it +29, the book +56" is two different sign
    conventions in one sentence.
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


def _total_pick(game) -> dict:
    over = game["ou_edge"] > 0
    return {"kind": "total", "game_id": str(game["game_id"]),
            "team": f"{game['away']} at {game['home']}", "opponent": "",
            "side": "Over" if over else "Under", "line": round(float(game["total"]), 1),
            "model": round(float(game["pred_total"]), 1),
            "edge": round(float(abs(game["ou_edge"])), 1),
            "kickoff": pd.Timestamp(game["date"]).isoformat()}


def _pick_week(week: int) -> dict:
    """The card's picks for a week, as they would be taken right now."""
    games = _candidates(week)
    out = {"week": week, "single": None, "parlay": []}
    if games.empty:
        return out
    spreads = games.dropna(subset=["spread", "edge"])
    spreads = spreads[spreads["edge"].abs().between(EDGE_MIN, EDGE_MAX)].sort_values(
        "edge", key=lambda s: s.abs(), ascending=False)
    totals = games.dropna(subset=["total", "ou_edge"])
    totals = totals[totals["ou_edge"].abs().between(EDGE_MIN, EDGE_MAX)].sort_values(
        "ou_edge", key=lambda s: s.abs(), ascending=False)

    picks = [_spread_pick(g) for _, g in spreads.iterrows()]
    if picks:
        out["single"] = picks[0]
    # The parlay is the next-best calls, and deliberately not the single again:
    # one bet repeated inside a parlay is one opinion priced twice.
    rest = picks[1:] + [_total_pick(g) for _, g in totals.iterrows()]
    rest.sort(key=lambda p: -p["edge"])
    out["parlay"] = rest[:PARLAY_LEGS]
    return out


def _lock_path(week: int):
    return BETS_DIR / f"{SEASON}_wk{int(week):02d}.json"


def locked_picks(week: int, first_kick: datetime, now: datetime) -> tuple:
    """(picks, locked at, whether they are frozen).

    Frozen from LOCK_HOUR on the day of the week's first kickoff: the file is
    written once and then read, so a card published on Saturday says what it
    said on Thursday even if the ratings have moved since.
    """
    import json
    path = _lock_path(week)
    if path.exists():
        saved = json.loads(path.read_text(encoding="utf-8"))
        return saved, datetime.fromisoformat(saved["locked"]), True
    picks = _pick_week(week)
    lock_at = first_kick.replace(hour=LOCK_HOUR, minute=0, second=0, microsecond=0)
    if now < lock_at or not picks["single"]:
        return picks, lock_at, False
    picks["locked"] = now.isoformat(timespec="seconds")
    BETS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(picks, indent=1), encoding="utf-8")
    return picks, now, True


def _finals() -> dict:
    """{game_id: (home margin, total)} for games with a result."""
    frame, _model, _names = predict.season()
    done = frame[frame["played"]]
    return {str(g["game_id"]): (float(g["home_score"] - g["away_score"]),
                                float(g["home_score"] + g["away_score"]))
            for _, g in done.iterrows()}


def _grade(pick: dict, finals: dict):
    """True, False, None (push) or "" for a game that has not finished."""
    got = finals.get(pick["game_id"])
    if got is None:
        return ""
    margin, total = got
    if pick["kind"] == "spread":
        # The pick's own margin: the side it took, against the line it took.
        mine = margin if pick["home"] else -margin
        cover = mine + pick["line"]
        return None if abs(cover) < 1e-9 else cover > 0
    diff = total - pick["line"]
    return None if abs(diff) < 1e-9 else (diff > 0) == (pick["side"] == "Over")


def _mark(state) -> str:
    if state == "":
        return ""
    if state is None:
        return "<span class='hc-res push'>push</span>"
    return ("<span class='hc-res win'>&check;</span>" if state
            else "<span class='hc-res loss'>&times;</span>")


def _season_record() -> str:
    """How every locked pick of the season has done, graded on the results."""
    import json
    finals = _finals()
    wins = losses = pushes = 0
    for path in sorted(BETS_DIR.glob(f"{SEASON}_wk*.json")):
        saved = json.loads(path.read_text(encoding="utf-8"))
        for pick in ([saved["single"]] if saved.get("single") else []) + saved.get("parlay", []):
            state = _grade(pick, finals)
            if state == "":
                continue
            if state is None:
                pushes += 1
            else:
                wins, losses = wins + int(state), losses + int(not state)
    if not (wins + losses + pushes):
        return ""
    return (f"Locked picks this season: <strong>{wins}-{losses}"
            + (f"-{pushes}" if pushes else "") + "</strong>.")


def _leg_html(pick: dict, finals: dict) -> str:
    if pick["kind"] == "spread":
        call = f"{escape(pick['team'])} {pick['line']:+.1f}"
        sub = (f"vs {escape(pick['opponent'])} &middot; we have them "
               f"{pick['model']:+.1f}, the book {pick['market_margin']:+.1f}")
    else:
        call = f"{pick['side']} {pick['line']:.1f}"
        sub = f"{escape(pick['team'])} &middot; we make it {pick['model']:.1f}"
    return (f"<li>{call}{_mark(_grade(pick, finals))}"
            f"<div class='hc-sub'>{sub}</div></li>")


def bets_html(now: datetime = None) -> str:
    now = now or datetime.now()
    week, first_kick = _current_week(now)
    if week is None:
        return _CSS + "<div class='hc'><p class='hc-note'>No games scheduled.</p></div>"
    picks, when, frozen = locked_picks(week, first_kick, now)
    finals = _finals()

    if not picks.get("single"):
        return (_CSS + "<div class='hc'><p class='hc-note'>The model and the book agree "
                f"to within {EDGE_MIN:.0f} points on every game this week, so there is "
                "no bet to name.</p></div>")

    single = picks["single"]
    stamp = (f"Locked {when:%a %-I:%M %p}" if frozen
             else f"Provisional &middot; locks {when:%a} morning")
    body = [f"<div class='hc-bet'><div class='hc-pick'>"
            f"<div class='hc-kind'>Single bet</div>"
            f"<div class='hc-call'>{escape(single['team'])} {single['line']:+.1f}"
            f"{_mark(_grade(single, finals))}</div>"
            f"<div class='hc-sub'>vs {escape(single['opponent'])} &middot; we have them "
            f"{single['model']:+.1f}, the book {single['market_margin']:+.1f}</div></div>"]
    if picks["parlay"]:
        legs = "".join(_leg_html(p, finals) for p in picks["parlay"])
        body.append(f"<div class='hc-pick'><div class='hc-kind'>"
                    f"{len(picks['parlay'])}-leg parlay</div>"
                    f"<ul class='hc-legs'>{legs}</ul></div>")
    body.append("</div>")

    # The caveat is the honest part of the card, not small print: the backtest
    # says this model does not beat the number it is disagreeing with.
    note = (f"<span class='hc-stamp'>Week {week} &middot; {stamp}</span><br>"
            f"The model's widest disagreements with the DraftKings line "
            f"({EDGE_MIN:.0f}+ points). {_season_record()} Across six held-out seasons "
            f"picks like these went <strong>48% against the spread</strong> - under the "
            f"52.4% that standard juice needs - so read this as what the model thinks, "
            f"not as an edge. <a href='/cfb/predictions/'>The full record</a>.")
    return _CSS + "<div class='hc'>" + "".join(body) + f"<p class='hc-note'>{note}</p></div>"


def generate() -> None:
    TOP25_OUT.parent.mkdir(parents=True, exist_ok=True)
    TOP25_OUT.write_text(top25_html(), encoding="utf-8")
    print(f"Wrote CFB top 25 card -> {TOP25_OUT}")
    BETS_OUT.write_text(bets_html(), encoding="utf-8")
    print(f"Wrote CFB best bets card -> {BETS_OUT}")


if __name__ == "__main__":
    generate()
