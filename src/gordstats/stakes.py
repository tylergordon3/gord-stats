"""
What this week's games are worth: each team's playoff odds with a win and with
a loss, and the game of the week - the matchup with the most playoff odds on it.

Both leagues' season simulations split their runs on the next week's head to
head (fantasy.league.power.simulate, cfb.league_sim.simulate): the same runs,
counted by whether the team won that game. The gap between the two is the
game's swing. A matchup's worth is how far its result is expected to move the
two teams' odds: 2p(1-p) times the two swings added up, p being the chance
one side wins - so a big swing on a game that could go either way leads, and
a lopsided game whose upset would be huge does not (Mike Locksley 98% to beat
I Stand With Diggs had the biggest raw swing of CFB week 5). The power
pages show every team's (table()); the matchups pages open the week with the
biggest (callout()), read from the file the power build leaves beside it
(write() / read()), since the two pages are built separately.

    {"week": 4, "teams": {"9": {"name": "George", "opp": "7", "now": 0.888,
                                "win": 0.935, "loss": 0.811, "wp": 0.624}, ...}}

Only for a week not yet played: the power model can count a week a day or two
after Sleeper finishes it (it waits for nflverse), and in that gap the "next"
week is one already over, so the caller passes nothing and nothing is shown.
"""
import json
from html import escape
from pathlib import Path

CSS = """<style>
.gw{border:1px solid #e2e8f0;border-left:4px solid var(--accent,#C2410C);border-radius:10px;
  background:#fff;padding:10px 14px;margin:0 0 14px}
.gw-lb{font-size:11px;font-weight:800;letter-spacing:.05em;text-transform:uppercase;
  color:var(--accent,#C2410C)}
.gw-t{font-size:16px;font-weight:800;color:#0f172a;margin:2px 0 3px}
.gw p{margin:0;font-size:13.5px;color:#334155;line-height:1.5}
.gw p a{white-space:nowrap}
.gw-t a{white-space:normal;overflow-wrap:anywhere}
table.stk{width:100%;border-collapse:collapse;font-size:14px}
table.stk th{font-size:11.5px;text-transform:uppercase;letter-spacing:.03em;color:#334155;
  background:#eef2f7;padding:6px 8px;border-bottom:1px solid #e2e8f0;text-align:center;
  white-space:nowrap}
table.stk td{padding:6px 8px;border-bottom:1px solid #eef2f7;text-align:center;white-space:nowrap}
table.stk td.t{text-align:left;font-weight:700}
table.stk td.sw{font-weight:800}
@media (max-width:600px){
  table.stk th{font-size:12px}
  table.stk td.t{max-width:130px;overflow:hidden;text-overflow:ellipsis}
}
table.stk tr.gw-row td{background:#fff7ed}
@media (prefers-color-scheme: dark){
  .gw{background:#16203a;border-color:#2b3852;border-left-color:var(--accent,#C2410C)}
  .gw-lb{color:#fdba74}
  .gw-t{color:#f1f5f9}
  .gw p{color:#c3cfdd}
  table.stk th{color:#dde5ef;background:#223052;border-color:#2b3852}
  table.stk td{border-color:#2b3852}
  table.stk tr.gw-row td{background:#3b2a1a}
}
</style>"""


def pct(p) -> str:
    return "—" if p is None else f"{round(100 * float(p))}%"


def teams_from(frame, key_col: str, name_col: str) -> dict:
    """The simulation's columns as write() wants them, from a table carrying
    `opponent`, `win_prob`, `playoff_if_win`, `playoff_if_loss` and the
    current `now` odds column already named `playoff_odds` or `playoffs`."""
    if "playoff_if_win" not in frame:
        return {}
    now_col = "playoff_odds" if "playoff_odds" in frame else "playoffs"
    out, dropped = {}, set()
    for _, r in frame.iterrows():
        nums = [r.get(c) for c in (now_col, "playoff_if_win", "playoff_if_loss", "win_prob")]
        # A game so lopsided one side never lost it in any run has no "with a
        # loss" for that side (and no "with a win" for the other): NaN, which
        # the table's round() raised on and took the power build down. Both
        # sides of such a game are left out - the pair, not half of it.
        if any(v is None or v != v for v in nums):                      # NaN
            dropped.update({str(r[key_col]), str(r.get("opponent"))})
            continue
        out[str(r[key_col])] = {"name": str(r[name_col]), "opp": str(r["opponent"]),
                                "now": round(float(r[now_col]), 4),
                                "win": round(float(r["playoff_if_win"]), 4),
                                "loss": round(float(r["playoff_if_loss"]), 4),
                                "wp": round(float(r["win_prob"]), 4)}
    return {k: t for k, t in out.items() if k not in dropped}


def games(teams: dict) -> list:
    """[(key a, key b, worth)] once each, the most expected to move first."""
    seen, out = set(), []
    for k, t in teams.items():
        o = t.get("opp")
        if o not in teams or (o, k) in seen:
            continue
        seen.add((k, o))
        p = t["wp"]
        swing = (t["win"] - t["loss"]) + (teams[o]["win"] - teams[o]["loss"])
        out.append((k, o, 2 * p * (1 - p) * swing))
    return sorted(out, key=lambda g: -g[2])


def _side(t: dict, name: str) -> str:
    return (f"<b>{escape(name)}</b> {pct(t['win'])} with a win, {pct(t['loss'])} with a "
            f"loss")


def callout(week: int, teams: dict, names: dict = None, anchor: str = "",
            more: str = "") -> str:
    """The game of the week, for the top of a matchups page. `names` maps a
    key to the name that page uses (team names there, managers on NFL power)."""
    ranked = games(teams)
    if not ranked:
        return ""
    a, b, _ = ranked[0]
    names = names or {}
    na, nb = names.get(a) or teams[a]["name"], names.get(b) or teams[b]["name"]
    title = f"{escape(na)} vs {escape(nb)}"
    if anchor:
        title = f"<a href='#{escape(anchor, quote=True)}'>{title}</a>"
    return (CSS + "<div class='gw'><div class='gw-lb'>Game of the week " + f"{week}</div>"
            f"<div class='gw-t'>{title}</div>"
            f"<p>The game expected to move the playoff race most. {_side(teams[a], na)}; "
            f"{_side(teams[b], nb)}.{(' ' + more) if more else ''}</p></div>")


def table(week: int, teams: dict) -> str:
    """Every team's stakes this week, the biggest swing first, the game of the
    week's two rows marked."""
    ranked = games(teams)
    if not ranked:
        return ""
    gw = {ranked[0][0], ranked[0][1]}
    rows = sorted(teams.items(), key=lambda kv: -(kv[1]["win"] - kv[1]["loss"]))
    body = "".join(
        f"<tr{' class=gw-row' if k in gw else ''}><td class='t'>{escape(t['name'])}</td>"
        f"<td class='sw'>{round(100 * (t['win'] - t['loss']))}</td>"
        f"<td>{pct(t['win'])}</td><td>{pct(t['loss'])}</td><td>{pct(t['now'])}</td>"
        f"<td>{pct(t['wp'])}</td>"
        f"<td>{escape(teams[t['opp']]['name']) if t['opp'] in teams else ''}</td></tr>"
        for k, t in rows)
    a, b, _ = ranked[0]
    # How stakes and the game of the week are worked out is the
    # fantasy-stakes explainer (gordstats.how), opened from the chip on the
    # section's heading; the lead says only what the table is.
    lead = (f"<p>Each team's playoff odds with a win and with a loss in week {week}. Game of "
            f"the week, highlighted: {escape(teams[a]['name'])} vs "
            f"{escape(teams[b]['name'])}.</p>")
    return (CSS + lead + "<div class='table-scroll'><table class='stk'><thead><tr>"
            "<th>Team</th><th title='Playoff odds with a win minus with a loss, in percentage "
            "points'>Swing</th><th>With a win</th><th>With a loss</th>"
            "<th>Playoffs now</th><th>Win chance</th><th>Plays</th></tr></thead>"
            f"<tbody>{body}</tbody></table></div>")


def write(path: Path, week: int | None, teams: dict) -> None:
    """Leave this week's stakes for the matchups page; clear them when there
    is no week to show."""
    path = Path(path)
    if not week or not teams:
        if path.exists():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"week": int(week), "teams": teams}, separators=(",", ":")),
                    encoding="utf-8")


def read(path: Path, week: int) -> dict:
    """The stakes left for `week`, or {} if there are none for it."""
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if int(d.get("week") or 0) != int(week):
        return {}
    return d.get("teams") or {}
