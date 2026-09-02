"""
The real college football schedule (docs/cfb/schedule/).

Every FBS game of the season (cfb.espn.schedule), one tab per week. Inside a
tab, games still to play come first (grouped by day) and finished ones sink
into a Final section below, so mid-week the top of the page is what's next,
not what already happened.

Each game is a row: the stacked scorebox (away over home, ESPN logos, AP
ranks, the winner in bold, a conference tag underneath), kickoff and TV,
then everything the site and the market think about it -

  - the GordStats line: spread, projected total, and for games still to play
    the projected score (cfb.predict, one fit as of build time; for finished
    games the line that was on record before kickoff, from cfb.results);
  - the DraftKings line: spread, total and moneyline (cfb.gameinfo, frozen at
    kickoff, with cfb.odds as the fallback for the spread and total);
  - ESPN's FPI win chance beside ours, each naming its own favourite, and on
    a finished game each marked with whether that favourite won;
  - the forecast where ESPN has one (about ten days out): condition,
    temperature, chance of rain, gusts.

The controls sort a week by anything on the row - closest spread, highest
total, ESPN's matchup quality, biggest home underdog, worst weather, where
the model and the book disagree most, upset chance - and cut it down with
filters that stack: ranked teams, conference or non-conference games, the
Power 4, home underdogs, toss-ups, bad weather, upset watch, still to play,
one conference, or a team name. Sorting by anything but kickoff flattens the
day groups into one ranked list; the URL hash carries the state so a view
can be shared. On a phone the rows become stacked cards, one labelled line
per figure, with empty figures dropped.

The tab that opens first is the current week, computed at build time - the
page is rebuilt daily, so "current" stays current.

    python -m cfb.site.schedule     # rebuild the page
"""
import json
from datetime import datetime, timezone
from functools import lru_cache
from html import escape

import numpy as np
import pandas as pd

from cfb import espn, gameinfo, predict, results
from cfb import odds as odds_mod
from cfb.config import LEAGUE_TZ, SEASON, WEB_DIR
from cfb.site import write_page
from cfb.site.teams import LOGO, team_slug

POWER4 = {"ACC", "Big 12", "Big Ten", "SEC"}
TOSS_UP = 3.0             # a spread this small is a coin flip for the badge
UPSET_WATCH = 0.35        # an underdog somebody gives this much is worth a look

_CSS = """<style>
.sc-intro{color:#475569;font-size:14px;line-height:1.55}
table.cfb-sched{width:100%;border-collapse:collapse;font-size:14px}
table.cfb-sched th{background:#eef2f7;color:#334155;padding:7px 10px;text-align:left;
  font-size:12px;text-transform:uppercase;letter-spacing:.03em;white-space:nowrap;
  border:1px solid #e2e8f0}
table.cfb-sched td{padding:6px 10px;border:1px solid #eef2f7;color:#0f172a;background:#fff;
  vertical-align:top}
table.cfb-sched tbody tr.g:nth-child(even) td{background:#f8fafc}
table.cfb-sched .rk{font-weight:700;color:#8a6d00;font-size:11.5px}
table.cfb-sched td.venue{color:#4a5a68;font-size:13px;max-width:200px;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
/* Identity leads and stays put while the numbers scroll; every cell carries
   an opaque background in both themes so nothing bleeds through. */
table.cfb-sched th:first-child,table.cfb-sched td.mu{position:sticky;left:0;z-index:1}
/* Day and section headers live inside the table so a sort can hide them and
   a filter can drop an emptied day. */
table.cfb-sched tr.hdr td{background:#f1f5f9;color:#475569;font-weight:700;
  font-size:13px;padding:8px 10px;border-color:#e2e8f0}
table.cfb-sched tr.hdr.sec td{background:#e2e8f0;color:#334155;font-size:11.5px;
  text-transform:uppercase;letter-spacing:.06em;padding:6px 10px}
/* The stacked scorebox: away over home, logos, ranks, the winner in bold. */
.sc-mu{display:flex;flex-direction:column;gap:3px;min-width:190px}
.sc-row{display:flex;align-items:center;gap:8px}
/* The Slate remote theme frames every <img>; reset or each logo becomes a
   boxed figure and the row grows. */
table.cfb-sched .sc-row img{width:20px;height:20px;object-fit:contain;flex:none;
  border:none;padding:0;box-shadow:none;background:none;border-radius:0;margin:0}
.sc-name{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  color:#334155;font-size:14px}
.sc-name a{color:inherit;text-decoration:none}
.sc-name a:hover{text-decoration:underline}
.sc-joiner{color:#94a3b8;font-size:12px}
.sc-pts{min-width:24px;text-align:right;font-variant-numeric:tabular-nums;
  font-size:15px;font-weight:600;color:#94a3b8}
.sc-row.sc-win .sc-name{font-weight:700;color:#0f172a}
.sc-row.sc-win .sc-pts{color:#0f172a;font-weight:700}
.sc-meta{margin-top:4px;font-size:11.5px;color:#64748b;display:flex;flex-wrap:wrap;
  gap:4px 6px;align-items:center}
.tag{display:inline-block;padding:1px 6px;border-radius:999px;font-size:10.5px;
  font-weight:700;letter-spacing:.03em;text-transform:uppercase;line-height:1.5}
.tag-dog{background:#fef3c7;color:#92400e}
.tag-toss{background:#dbeafe;color:#1e40af}
.tag-upset{background:#fee2e2;color:#991b1b}
.tag-wx{background:#e0e7ff;color:#3730a3}
/* Kick: time over TV. */
td.t{white-space:nowrap;color:#4a5a68}
.t-tv{display:block;font-size:12px;color:#64748b;margin-top:2px}
.t-live{color:#0a7d33;font-weight:700}
.t-day{display:none;color:#94a3b8}
table.cfb-sched.sorted .t-day{display:inline}
/* Line cells: the favourite and spread, then the small print. */
td.ln,td.fpi,td.wx{white-space:nowrap;font-variant-numeric:tabular-nums}
.ln b,.fpi b{color:#0f172a;font-weight:700}
.pct{color:#334155;font-weight:600;margin-left:6px}
.sub{font-size:12px;color:#64748b;margin-top:2px}
.bar{height:5px;width:64px;border-radius:3px;background:#eef2f7;overflow:hidden;margin-top:4px}
.bar i{display:block;height:100%;background:#3b82f6}
.mk{font-weight:700;margin-left:4px}
.mk.hit{color:#15803d}
.mk.miss{color:#b91c1c}
.wx-main{font-size:13.5px}
tr.g.wx-bad td.wx .wx-main{color:#3730a3;font-weight:600}
td.na{color:#94a3b8}
.wk-note{font-size:13px;color:#4a5a68;margin:4px 0 10px}
.sc-controls{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:10px 0 4px}
.sc-controls .lbl{font-weight:800;font-size:.72rem;text-transform:uppercase;
  letter-spacing:.04em;color:#475569}
.sc-select,.sc-search{font-size:13.5px;padding:6px 10px;border:1px solid #cbd5e1;
  border-radius:8px;background:#fff;color:#0f172a}
.sc-search{min-width:150px}
.sc-chips{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:4px 0 8px}
.sc-chips button{padding:5px 12px;cursor:pointer;border:1px solid #e2e8f0;background:#fff;
  border-radius:999px;font-size:13px;font-weight:600;color:#334155;
  box-shadow:0 1px 2px rgba(15,23,42,.04)}
.sc-chips button:hover{background:#f1f5f9}
.sc-chips button.active{background:#A34F0A;color:#fff;border-color:#8A420A;font-weight:700}
.sc-chips button.clear{border-style:dashed;color:#64748b;font-weight:500}
.sc-legend{margin:8px 0 14px;font-size:13px;color:#475569}
.sc-legend summary{cursor:pointer;font-weight:600;color:#334155}
.sc-legend ul{margin:6px 0 0 18px;padding:0}
.sc-legend li{margin:3px 0}
tr.g.hide,tr.hdr.hide{display:none}
/* On a phone the table becomes a stack of cards: matchup on top, then one
   labelled line per figure, empty figures dropped. Same rows, same data
   attributes, so sorting and filtering are untouched. */
@media (max-width:700px){
  #cfb-weeks .table-scroll{border:none;box-shadow:none;border-radius:0;overflow:visible;
    background:transparent}
  table.cfb-sched{border:none;background:transparent}
  table.cfb-sched,table.cfb-sched tbody,table.cfb-sched tr,table.cfb-sched td{display:block}
  table.cfb-sched thead{display:none}
  table.cfb-sched tr.g{border:1px solid #e2e8f0;border-radius:10px;margin:8px 0;
    padding:8px 10px 7px;background:#fff}
  table.cfb-sched tr.g td,table.cfb-sched tbody tr.g:nth-child(even) td{border:none;
    padding:2px 0;background:transparent}
  table.cfb-sched td.mu{position:static;padding-bottom:6px;border-bottom:1px solid #eef2f7;
    margin-bottom:4px}
  .sc-mu{min-width:0}
  table.cfb-sched td.d{display:grid;grid-template-columns:78px 1fr;gap:6px;
    font-size:13px;white-space:normal;max-width:none}
  table.cfb-sched td.d::before{content:attr(data-l);font-size:10.5px;text-transform:uppercase;
    letter-spacing:.04em;color:#94a3b8;font-weight:700;padding-top:2px}
  table.cfb-sched td.na,table.cfb-sched td.venue{display:none}
  .t-tv{display:inline;margin:0 0 0 6px}
  .t-day{display:inline}
  .bar{display:none}
  .sub{display:inline;margin-left:6px}
  table.cfb-sched tr.hdr{margin:14px 0 2px}
  table.cfb-sched tr.hdr td{border:none;border-radius:8px}
}
@media (prefers-color-scheme: dark){
  .sc-intro{color:#aab7c9}
  table.cfb-sched th{background:#223052;color:#dde5ef;border-color:#2b3852}
  table.cfb-sched td{background:#16203a;border-color:#2b3852;color:#dde5ef}
  table.cfb-sched tbody tr.g:nth-child(even) td{background:#1b2540}
  table.cfb-sched tr.hdr td{background:#223052;color:#dde5ef;border-color:#2b3852}
  table.cfb-sched tr.hdr.sec td{background:#2b3852;color:#dde5ef}
  table.cfb-sched td.t,table.cfb-sched td.venue,.t-tv{color:#aab7c9}
  table.cfb-sched .rk{color:#f2cc60}
  .sc-name{color:#c3cfdd}
  .sc-joiner,.sc-pts{color:#7f8ea3}
  .sc-row.sc-win .sc-name,.sc-row.sc-win .sc-pts{color:#ffffff}
  .sc-meta{color:#8fa0b8}
  .tag-dog{background:#4a3208;color:#fcd34d}
  .tag-toss{background:#1e3a8a;color:#bfdbfe}
  .tag-upset{background:#7f1d1d;color:#fecaca}
  .tag-wx{background:#312e81;color:#c7d2fe}
  .t-live{color:#4ade80}
  .ln b,.fpi b{color:#f1f5f9}
  .pct{color:#dde5ef}
  .sub{color:#8fa0b8}
  .bar{background:#223052}
  .mk.hit{color:#4ade80}
  .mk.miss{color:#f87171}
  tr.g.wx-bad td.wx .wx-main{color:#c7d2fe}
  td.na{color:#7f8ea3}
  .wk-note{color:#aab7c9}
  .sc-controls .lbl{color:#aab7c9}
  .sc-select,.sc-search{background:#16203a;border-color:#2b3852;color:#dde5ef}
  .sc-chips button{background:#16203a;border-color:#2b3852;color:#dde5ef;box-shadow:none}
  .sc-chips button:hover{background:#223052}
  .sc-chips button.active{background:#A34F0A;color:#fff;border-color:#8A420A}
  .sc-chips button.clear{color:#aab7c9}
  .sc-legend{color:#aab7c9}
  .sc-legend summary{color:#dde5ef}
  @media (max-width:700px){
    table.cfb-sched tr.g{border-color:#2b3852;background:#16203a}
    table.cfb-sched td.mu{border-color:#2b3852}
    table.cfb-sched td.d::before{color:#7f8ea3}
  }
}
</style>"""

_LEGEND = """<details class="sc-legend"><summary>What the columns and tags mean</summary>
<ul>
<li><b>GordStats</b> &mdash; this site's <a href="/cfb/predictions/">model</a>: the favourite
and spread, its win chance, the projected total and (for games still to play) the projected
score. A finished game shows the line that was on record before kickoff, never one refit
afterwards, and &#10003; or &#10007; says whether the pick won.</li>
<li><b>DraftKings</b> &mdash; the book's spread, total and moneyline as ESPN carries them,
captured before kickoff and frozen there. Games more than a week or so out usually have no
line yet.</li>
<li><b>FPI</b> &mdash; ESPN's Football Power Index projection: its favourite and that team's
win chance, marked &#10003; or &#10007; once the game is over.</li>
<li><b>Weather</b> &mdash; ESPN's AccuWeather forecast for kickoff, which appears about ten
days out: conditions, temperature, chance of rain, gusts. <i>Bad weather</i> means rain,
storms or snow, a 50%+ chance of rain, gusts of 25+ mph, or a kickoff at or below
freezing.</li>
<li><b>Tags</b> &mdash; <i>Home dog</i>: the home team is the underdog on the book's line
(the model's, if there is no book line yet). <i>Toss-up</i>: the spread is three points or
fewer. <i>Upset</i>: the favourite lost. <i>Upset watch</i> in the filters: the model or
FPI gives the underdog at least a 35% chance, or the two disagree on who is favoured.</li>
<li><b>Sorting</b> by anything other than kickoff turns the week into one ranked list;
games without the figure being sorted on fall to the bottom. <i>Matchup quality</i> is
ESPN's 0&ndash;100 measure of how competitive and consequential a game projects to be.</li>
</ul></details>"""


@lru_cache(maxsize=1)
def _team_pages() -> frozenset:
    """Slugs with a built team page - the only names worth linking.

    cfb.build runs teams before schedule, so on a full build every FBS page is
    on disk by now; FCS visitors have no page and stay plain text.
    """
    d = WEB_DIR / "teams"
    return frozenset(p.name for p in d.iterdir() if p.is_dir()) if d.exists() else frozenset()


def _abandoned(g) -> bool:
    """Cancelled/postponed games arrive as state=post with hollow 0-0 scores."""
    return any(w in (g.detail or "") for w in ("Cancel", "Postpon"))


def _v(x):
    """A scalar, or None where pandas or JSON left a hole."""
    if x is None:
        return None
    try:
        return None if pd.isna(x) else x
    except (TypeError, ValueError):
        return x


# ---------------------------------------------------------------------------
# Assembling one frame with everything a row needs.

def _model_lines(sched: pd.DataFrame) -> pd.DataFrame:
    """game_id -> gs_margin, gs_total, gs_wp, gs_home, gs_away.

    Games still to play get one fit as of now, the same fit the team pages
    run on. Finished games get the last prediction archived before their
    kickoff, or nothing: a line produced after the result is not a line.
    """
    cols = ["game_id", "gs_margin", "gs_total", "gs_wp", "gs_home", "gs_away"]
    frames = []
    try:
        season, _, _ = predict.season()
    except Exception as exc:                 # no history yet, or a fit that failed
        print(f"  ! model lines unavailable ({exc})")
        season = pd.DataFrame()
    done = set(sched.loc[sched["state"] == "post", "game_id"].astype(str))
    # The fit for a pending game, the archive for a finished one - by source,
    # not by membership: the archive also holds this week's games, captured
    # before kickoff, and a pending game must still show today's fit.
    if not season.empty:
        pending = season[~season["game_id"].astype(str).isin(done)]
        frames.append(pd.DataFrame({
            "game_id": pending["game_id"].astype(str),
            "gs_margin": pending["pred_margin"], "gs_total": pending["pred_total"],
            "gs_wp": pending["home_win_prob"],
            "gs_home": pending["pred_home"], "gs_away": pending["pred_away"]}))
    record = results.on_record()
    if not record.empty:
        finished = record[record["game_id"].astype(str).isin(done)]
        frames.append(pd.DataFrame({
            "game_id": finished["game_id"].astype(str),
            "gs_margin": finished["pred_margin"], "gs_total": finished["pred_total"],
            "gs_wp": finished["home_win_prob"],
            "gs_home": np.nan, "gs_away": np.nan}))
    if not frames:
        return pd.DataFrame(columns=cols)
    out = pd.concat(frames, ignore_index=True)
    return out.drop_duplicates("game_id", keep="last")[cols]


def _frame() -> pd.DataFrame:
    df = espn.schedule().copy()
    df["game_id"] = df["game_id"].astype(str)
    df["local"] = pd.to_datetime(df["date_utc"], utc=True).dt.tz_convert(str(LEAGUE_TZ))
    for col in ("home_conf_id", "away_conf_id"):
        if col not in df.columns:
            df[col] = ""

    df = df.merge(_model_lines(df), on="game_id", how="left")

    board = odds_mod.latest(SEASON)
    if not board.empty:
        board = board.rename(columns={"spread": "bd_spread", "total": "bd_total",
                                      "book": "bd_book"})
        df = df.merge(board[["home_id", "away_id", "bd_spread", "bd_total", "bd_book"]],
                      on=["home_id", "away_id"], how="left")
    for col in ("bd_spread", "bd_total", "bd_book", "gs_margin", "gs_total", "gs_wp",
                "gs_home", "gs_away"):
        if col not in df.columns:
            df[col] = np.nan

    info = gameinfo.load(SEASON)
    confs = espn.conferences()
    rows = []
    for g in df.itertuples():
        e = info.get(g.game_id) or {}
        final = g.state == "post"
        # The summary's line is fresher than the daily odds archive while a
        # game is pending; once it is over the archive's last capture is the
        # closing line and the frozen summary entry only backs it up.
        first, second = ((_v(g.bd_spread), _v(g.bd_total)), (e.get("spread"), e.get("total")))
        if not final:
            first, second = second, first
        dk_spread = first[0] if first[0] is not None else second[0]
        dk_total = first[1] if first[1] is not None else second[1]
        rows.append({
            "dk_spread": dk_spread, "dk_total": dk_total,
            "dk_book": e.get("book") or _v(g.bd_book) or "DraftKings",
            "ml_home": e.get("ml_home"), "ml_away": e.get("ml_away"),
            "fpi_wp": e.get("espn_home_wp"),
            "mq": e.get("mq"),
            "weather": e.get("weather"),
            "home_conf": confs.get(str(g.home_id), ""),
            "away_conf": confs.get(str(g.away_id), ""),
        })
    extra = pd.DataFrame(rows, index=df.index)
    return pd.concat([df, extra], axis=1)


# ---------------------------------------------------------------------------
# Rendering.

def _side_row(g, side: str) -> str:
    """One team's line in the scorebox: logo, rank, linked name, score."""
    name = str(getattr(g, side))
    rank = getattr(g, f"{side}_rank")
    badge = "" if pd.isna(rank) else f'<span class="rk">#{int(rank)}</span> '
    joiner = ("" if side == "away"
              else f'<span class="sc-joiner">{"vs" if g.neutral else "at"}</span> ')
    slug = team_slug(name)
    a, a_close = ((f'<a href="/cfb/teams/{slug}/">', "</a>")
                  if slug in _team_pages() else ("", ""))
    logo = LOGO.format(team_id=escape(str(getattr(g, f"{side}_id"))))

    score = getattr(g, f"{side}_score")
    other = getattr(g, "home_score" if side == "away" else "away_score")
    scored = g.state in ("in", "post") and not pd.isna(score) and not _abandoned(g)
    won = g.state == "post" and scored and score > other
    pts = f'<span class="sc-pts">{score:.0f}</span>' if scored else ""
    return (f'<div class="sc-row{" sc-win" if won else ""}">'
            f'{a}<img src="{logo}" alt="" loading="lazy">{a_close}'
            f'<span class="sc-name">{joiner}{badge}{a}{escape(name)}{a_close}</span>'
            f"{pts}</div>")


def _conf_text(g) -> str:
    home, away = g.home_conf, g.away_conf
    if home and away:
        return f"{home} game" if home == away else f"{away} vs {home}"
    if home or away:
        return f"{away or home} vs FCS"
    return ""


def _kick_cell(g) -> str:
    """Kickoff (or the clock, or Final) over the network, with the weekday
    for sorted views, where the day headers are hidden."""
    local = g.local
    day = f'<span class="t-day">{local.strftime("%a")} </span>'
    if _abandoned(g):
        when = day + escape(str(g.detail))
    elif g.state == "post":
        when = day + (g.detail if "Final" in (g.detail or "") else "Final")
    elif g.state == "in":
        when = f'<span class="t-live">{escape(str(g.detail or "Live"))}</span>'
    else:
        when = day + local.strftime("%-I:%M %p")
    tv = f'<span class="t-tv">{escape(str(g.tv))}</span>' if g.tv else ""
    return f'<td class="t d" data-l="Kick"><div class="c">{when}{tv}</div></td>'


def _fav(g, margin) -> tuple:
    """(favourite name, favourite abbreviation, home favoured?) for a home margin."""
    home = margin >= 0
    return ((g.home, g.home_abbr, True) if home else (g.away, g.away_abbr, False))


def _line_text(g, spread) -> str:
    """'Missouri -7.5' from a home-convention spread, or 'Pick'."""
    if abs(spread) < 0.25:
        return "Pick"
    name, _, _ = _fav(g, -spread)
    return f"{escape(str(name))} {-abs(spread):.1f}".replace(".0", "")


def _mark(home_fav: bool, home_won) -> str:
    """A tick or a cross once the game is over: did this favourite win?"""
    if home_won is None:
        return ""
    hit = home_fav == home_won
    return f'<span class="mk {"hit" if hit else "miss"}">{"&#10003;" if hit else "&#10007;"}</span>'


def _gs_cell(g, home_won) -> str:
    margin = _v(g.gs_margin)
    if margin is None:
        return '<td class="ln na d" data-l="GordStats">&mdash;</td>'
    wp = _v(g.gs_wp)
    pct = "" if wp is None else f'<span class="pct">{max(wp, 1 - wp):.0%}</span>'
    line = f"<b>{_line_text(g, -margin)}</b>{pct}{_mark(margin >= 0, home_won)}"
    sub = []
    total = _v(g.gs_total)
    if total is not None:
        sub.append(f"O/U {total:.0f}")
    if g.state != "post" and _v(g.gs_home) is not None:
        sub.append(f"proj {g.gs_away:.0f}&ndash;{g.gs_home:.0f}")
    return (f'<td class="ln d" data-l="GordStats"><div class="c">{line}'
            + (f'<div class="sub">{" &middot; ".join(sub)}</div>' if sub else "")
            + "</div></td>")


def _ml(ml) -> str:
    return f"{ml:+.0f}" if ml is not None else "&mdash;"


def _dk_cell(g) -> str:
    spread, total = _v(g.dk_spread), _v(g.dk_total)
    if spread is None and total is None and _v(g.ml_home) is None:
        return '<td class="ln na d" data-l="DraftKings">&mdash;</td>'
    line = f"<b>{_line_text(g, spread)}</b>" if spread is not None else "<b>&mdash;</b>"
    sub = []
    if total is not None:
        sub.append(f"O/U {total:g}")
    if _v(g.ml_home) is not None or _v(g.ml_away) is not None:
        sub.append(f"ML {escape(str(g.away_abbr))} {_ml(_v(g.ml_away))} "
                   f"&middot; {escape(str(g.home_abbr))} {_ml(_v(g.ml_home))}")
    return (f'<td class="ln d" data-l="DraftKings"><div class="c">{line}'
            + (f'<div class="sub">{" &middot; ".join(sub)}</div>' if sub else "")
            + "</div></td>")


def _fpi_cell(g, home_won) -> str:
    wp = _v(g.fpi_wp)
    if wp is None:
        return '<td class="fpi na d" data-l="FPI">&mdash;</td>'
    _, abbr, home_fav = _fav(g, wp - 0.5)
    p = wp if home_fav else 1 - wp
    return (f'<td class="fpi d" data-l="FPI"><div class="c"><b>{escape(str(abbr))}</b>'
            f'<span class="pct">{p:.0%}</span>{_mark(home_fav, home_won)}'
            f'<div class="bar"><i style="width:{p * 100:.0f}%"></i></div></div></td>')


def _wx_icon(cond) -> str:
    if cond is None:
        return ""
    if cond in gameinfo._SNOW:
        return "&#10052;&#65039;"                    # snowflake
    if cond in gameinfo._STORM:
        return "&#9928;&#65039;"                     # cloud with lightning and rain
    if cond in gameinfo._RAIN:
        return "&#127783;&#65039;"                   # cloud with rain
    if cond in (11, 37):
        return "&#127787;&#65039;"                   # fog
    if cond == 32:
        return "&#128168;"                           # dashing away (wind)
    if cond in (1, 2, 30, 33, 34):
        return "&#9728;&#65039;"                     # sun
    if cond in (3, 4, 5, 35, 36):
        return "&#9925;"                             # sun behind cloud
    return "&#9729;&#65039;"                         # cloud


def _wx_cell(g) -> str:
    wx = g.weather if isinstance(g.weather, dict) else None
    if not wx:
        return '<td class="wx na d" data-l="Weather">&mdash;</td>'
    main = []
    temp = wx.get("temp")
    if temp is not None:
        main.append(f"{temp:.0f}&deg;")
    text = gameinfo.weather_text(wx)
    if text:
        main.append(escape(text))
    sub = []
    if wx.get("precip") is not None and wx["precip"] > 0:
        sub.append(f"rain {wx['precip']:.0f}%")
    if wx.get("gust") is not None and wx["gust"] >= 10:
        sub.append(f"gusts {wx['gust']:.0f} mph")
    return (f'<td class="wx d" data-l="Weather"><div class="c">'
            f'<span class="wx-main">{_wx_icon(wx.get("cond"))} {" ".join(main)}</span>'
            + (f'<div class="sub">{" &middot; ".join(sub)}</div>' if sub else "")
            + "</div></td>")


def _row(g, idx: int) -> str:
    final = g.state == "post" and not _abandoned(g)
    ranked = not (pd.isna(g.home_rank) and pd.isna(g.away_rank))
    dk_spread, gs_margin = _v(g.dk_spread), _v(g.gs_margin)
    # The book's opinion where there is one, the model's until then, drives
    # the badges; the model and FPI each show their own favourite.
    spread = dk_spread if dk_spread is not None else (
        -gs_margin if gs_margin is not None else None)
    home_won = None
    if final and _v(g.home_score) is not None and _v(g.away_score) is not None:
        home_won = bool(g.home_score > g.away_score)

    known = [wp for wp in (_v(g.gs_wp), _v(g.fpi_wp)) if wp is not None]
    home_dog = spread is not None and spread > 0.25
    toss_up = spread is not None and abs(spread) <= TOSS_UP
    upset = home_won is not None and spread is not None and abs(spread) > 0.25 \
        and (spread < 0) != home_won
    # Upset chance: the consensus underdog's best case between the model and
    # FPI, or what happened. Two that disagree on the favourite make it > 0.5.
    upset_chance = None
    if home_won is not None and spread is not None and abs(spread) > 0.25:
        upset_chance = 1.0 if upset else 0.0
    elif known and spread is not None and abs(spread) > 0.25:
        upset_chance = max((wp if spread > 0 else 1 - wp) for wp in known)
    elif known:
        upset_chance = max(min(wp, 1 - wp) for wp in known)
    wx = g.weather if isinstance(g.weather, dict) else None
    severity = gameinfo.weather_severity(wx)
    gap = (abs(gs_margin - (-dk_spread))
           if gs_margin is not None and dk_spread is not None else None)
    total = _v(g.dk_total) if _v(g.dk_total) is not None else _v(g.gs_total)

    tags = []
    if home_dog:
        tags.append('<span class="tag tag-dog">Home dog</span>')
    if toss_up:
        tags.append('<span class="tag tag-toss">Toss-up</span>')
    if upset:
        tags.append('<span class="tag tag-upset">Upset</span>')
    if severity >= 2:
        tags.append('<span class="tag tag-wx">Weather</span>')
    conf = _conf_text(g)
    meta = ('<div class="sc-meta">' + (f"<span>{escape(conf)}</span>" if conf else "")
            + "".join(tags) + "</div>") if (conf or tags) else ""

    confs = "|".join(sorted({c for c in (g.home_conf, g.away_conf) if c}))
    teams = " ".join(str(x).lower() for x in (g.home, g.away, g.home_abbr, g.away_abbr))

    def attr(name, value, fmt="{:.3f}"):
        return f' data-{name}="{fmt.format(value)}"' if value is not None else ""

    classes = ["g"] + (["wx-bad"] if severity >= 2 else [])
    venue = escape(str(g.venue or "")) + (f" &mdash; {escape(str(g.place))}" if g.place else "")
    return (
        f'<tr class="{" ".join(classes)}" data-i="{idx}" data-state="{g.state}"'
        f' data-final="{int(final)}" data-ranked="{int(ranked)}"'
        f' data-confgame="{int(bool(g.conference_game))}"'
        f' data-p4="{int(bool({g.home_conf, g.away_conf} & POWER4))}"'
        f' data-confs="{escape(confs)}" data-teams="{escape(teams)}"'
        + attr("homedog", spread if home_dog else None, "{:.1f}")
        + attr("spread", abs(spread) if spread is not None else None, "{:.1f}")
        + attr("total", total, "{:.1f}")
        + attr("mq", _v(g.mq), "{:.1f}")
        + attr("wx", severity)
        + attr("gap", gap, "{:.1f}")
        + attr("upset", upset_chance)
        + f' data-tossup="{int(toss_up)}">'
        f'<td class="mu"><div class="sc-mu">{_side_row(g, "away")}{_side_row(g, "home")}'
        f"</div>{meta}</td>"
        + _kick_cell(g) + _gs_cell(g, home_won) + _dk_cell(g) + _fpi_cell(g, home_won)
        + _wx_cell(g)
        + f'<td class="venue">{venue}</td></tr>')


_HEAD = ('<thead><tr><th>Matchup</th><th>Kick (ET)</th><th>GordStats</th>'
         '<th>DraftKings</th><th>FPI</th><th>Weather</th>'
         '<th class="venue">Venue</th></tr></thead>')
_COLS = 7


def _hdr(text: str, idx: int, kind: str) -> str:
    return f'<tr class="hdr {kind}" data-i="{idx}"><td colspan="{_COLS}">{text}</td></tr>'


def _week_table(games: pd.DataFrame) -> str:
    """One table for the week: section and day header rows, then game rows.

    Order is the kickoff order the page opens in - still-to-play days first,
    finished ones under a Final header - and every row carries that position
    so a sort can be undone.
    """
    done = games["state"] == "post"
    split = bool(done.any() and not done.all())
    rows, idx = [], 0

    def days(frame):
        nonlocal idx
        for day, grp in frame.groupby(frame["local"].dt.date, sort=True):
            rows.append(_hdr(pd.Timestamp(day).strftime("%A, %B %-d"), idx, "day"))
            idx += 1
            for g in grp.itertuples():
                rows.append(_row(g, idx))
                idx += 1

    if split:
        rows.append(_hdr("Still to play", idx, "sec")); idx += 1
        days(games[~done])
        rows.append(_hdr("Final", idx, "sec")); idx += 1
        days(games[done])
    else:
        days(games)
    return (f'<div class="table-scroll"><table class="cfb-sched">{_HEAD}'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def _week_view(games: pd.DataFrame) -> str:
    ranked = int((games["home_rank"].notna() | games["away_rank"].notna()).sum())
    return (f'<p class="wk-note"><span class="wk-count">{len(games)} games</span>, '
            f'{ranked} with a ranked team.</p>' + _week_table(games))


def _current_week(df: pd.DataFrame) -> int:
    """The first week with games still to play, else the last week."""
    now = datetime.now(timezone.utc).isoformat()
    pending = df[df["date_utc"] >= now]
    return int(pending["week"].min()) if len(pending) else int(df["week"].max())


_SORTS = [("kick", "Kickoff"), ("spread", "Closest spread"), ("bigspread", "Biggest spread"),
          ("total", "Highest total"), ("lowtotal", "Lowest total"),
          ("mq", "Matchup quality (ESPN)"), ("upset", "Upset chance"),
          ("homedog", "Biggest home underdog"), ("gap", "Model vs book gap"),
          ("wx", "Worst weather")]
_CHIPS = [("ranked", "Ranked"), ("confgame", "Conference games"),
          ("nonconf", "Non-conference"), ("p4", "Power 4"), ("homedog", "Home underdogs"),
          ("tossup", "Toss-ups"), ("wx", "Bad weather"), ("upset", "Upset watch"),
          ("pending", "Still to play")]
_CONF_LEAD = ["ACC", "Big 12", "Big Ten", "SEC"]

_JS = """<script>
(function(){
"use strict";
var UPSET=%(upset)s;
var weeks=document.getElementById('cfb-weeks');
var sortSel=document.getElementById('sc-sort');
var confSel=document.getElementById('sc-conf');
var search=document.getElementById('sc-search');
var chips=Array.prototype.slice.call(document.querySelectorAll('.sc-chips button[data-f]'));
var on={};
var current=%(current)s;

// Sort keys: attribute and direction. Rows lacking the attribute sink to the bottom.
var SORTS={spread:['spread',1],bigspread:['spread',-1],total:['total',-1],
  lowtotal:['total',1],mq:['mq',-1],upset:['upset',-1],homedog:['homedog',-1],
  gap:['gap',-1],wx:['wx',-1]};

function num(row,key){var v=row.getAttribute('data-'+key);return v===null||v===''?null:+v;}

function passes(row){
  if(on.ranked&&row.getAttribute('data-ranked')!=='1')return false;
  if(on.confgame&&row.getAttribute('data-confgame')!=='1')return false;
  if(on.nonconf&&row.getAttribute('data-confgame')!=='0')return false;
  if(on.p4&&row.getAttribute('data-p4')!=='1')return false;
  if(on.homedog&&num(row,'homedog')===null)return false;
  if(on.tossup&&row.getAttribute('data-tossup')!=='1')return false;
  if(on.wx&&!((num(row,'wx')||0)>=2))return false;
  if(on.upset){var u=num(row,'upset');if(u===null||u<UPSET)return false;}
  if(on.pending&&row.getAttribute('data-final')==='1')return false;
  var c=confSel.value;
  if(c&&(row.getAttribute('data-confs')||'').split('|').indexOf(c)<0)return false;
  var q=(search.value||'').trim().toLowerCase();
  if(q&&(row.getAttribute('data-teams')||'').indexOf(q)<0)return false;
  return true;
}

function applyTo(view){
  var tbody=view.querySelector('tbody');if(!tbody)return;
  var rows=Array.prototype.slice.call(tbody.rows);
  var mode=sortSel.value,spec=SORTS[mode];
  rows.sort(function(a,b){
    if(spec){
      var ah=a.classList.contains('hdr'),bh=b.classList.contains('hdr');
      if(ah!==bh)return ah?1:-1;           // headers out of the way (hidden anyway)
      var av=num(a,spec[0]),bv=num(b,spec[0]);
      if(av===null&&bv!==null)return 1;
      if(bv===null&&av!==null)return -1;
      if(av!==null&&bv!==null&&av!==bv)return (av-bv)*spec[1];
    }
    return (+a.getAttribute('data-i'))-(+b.getAttribute('data-i'));
  });
  rows.forEach(function(r){tbody.appendChild(r);});
  tbody.parentNode.classList.toggle('sorted',!!spec);
  // Filters, then headers: a day with nothing left in it goes too.
  var shown=0,total=0,day=null,dayHas=false,sec=null,secHas=false;
  rows.forEach(function(r){
    if(r.classList.contains('hdr')){
      if(day)day.classList.toggle('hide',!!spec||!dayHas);
      if(r.classList.contains('sec')){
        if(sec)sec.classList.toggle('hide',!!spec||!secHas);
        sec=r;secHas=false;
      }
      day=r;dayHas=false;return;
    }
    total++;
    var ok=passes(r);
    r.classList.toggle('hide',!ok);
    if(ok){shown++;dayHas=true;secHas=true;}
  });
  if(day)day.classList.toggle('hide',!!spec||!dayHas);
  if(sec)sec.classList.toggle('hide',!!spec||!secHas);
  var count=view.querySelector('.wk-count');
  if(count)count.textContent=(shown===total?total+' games':shown+' of '+total+' games');
}

function applyAll(){
  Array.prototype.forEach.call(weeks.querySelectorAll('.wk-view'),applyTo);
  writeHash();
}

function writeHash(){
  var parts=['w='+current];
  if(sortSel.value!=='kick')parts.push('sort='+sortSel.value);
  var f=Object.keys(on).filter(function(k){return on[k];});
  if(f.length)parts.push('f='+f.join(','));
  if(confSel.value)parts.push('conf='+encodeURIComponent(confSel.value));
  if(search.value.trim())parts.push('q='+encodeURIComponent(search.value.trim()));
  history.replaceState(null,'','#'+parts.join('&'));
}

function readHash(){
  var h=location.hash.replace(/^#/,'');if(!h)return;
  h.split('&').forEach(function(kv){
    var i=kv.indexOf('='),k=kv.slice(0,i),v=decodeURIComponent(kv.slice(i+1));
    if(k==='w'&&document.getElementById('wk-view-'+v))current=+v;
    else if(k==='sort'&&SORTS[v])sortSel.value=v;
    else if(k==='f')v.split(',').forEach(function(x){on[x]=true;});
    else if(k==='conf'){for(var j=0;j<confSel.options.length;j++)
      if(confSel.options[j].value===v)confSel.value=v;}
    else if(k==='q')search.value=v;
  });
  chips.forEach(function(b){b.classList.toggle('active',!!on[b.getAttribute('data-f')]);});
}

window.show_wk=function(w){
  current=+w;
  Array.prototype.forEach.call(document.querySelectorAll('.wk-view'),function(e){e.style.display='none';});
  document.getElementById('wk-view-'+w).style.display='';
  Array.prototype.forEach.call(document.querySelectorAll('.wk-btn'),function(b){b.classList.remove('active');});
  document.getElementById('wk-tab-'+w).classList.add('active');
  writeHash();
};

chips.forEach(function(b){
  b.addEventListener('click',function(){
    var k=b.getAttribute('data-f');on[k]=!on[k];
    // Conference and non-conference cannot both be on; nor can a filter
    // and its opposite make sense, so the newer one wins.
    if(on[k]&&k==='confgame')on.nonconf=false;
    if(on[k]&&k==='nonconf')on.confgame=false;
    chips.forEach(function(c){c.classList.toggle('active',!!on[c.getAttribute('data-f')]);});
    applyAll();
  });
});
document.getElementById('sc-clear').addEventListener('click',function(){
  on={};chips.forEach(function(c){c.classList.remove('active');});
  sortSel.value='kick';confSel.value='';search.value='';applyAll();
});
sortSel.addEventListener('change',applyAll);
confSel.addEventListener('change',applyAll);
search.addEventListener('input',applyAll);

readHash();
window.show_wk(current);
applyAll();
})();
</script>"""


def _controls(confs: dict) -> str:
    names = set(confs.values())
    ordered = [c for c in _CONF_LEAD if c in names] + sorted(names - set(_CONF_LEAD))
    conf_opts = '<option value="">All conferences</option>' + "".join(
        f'<option value="{escape(c)}">{escape(c)}</option>' for c in ordered)
    sort_opts = "".join(f'<option value="{k}">{v}</option>' for k, v in _SORTS)
    chips = "".join(f'<button type="button" data-f="{k}">{v}</button>' for k, v in _CHIPS)
    return (
        '<div class="sc-controls">'
        '<span class="lbl">Sort</span>'
        f'<select id="sc-sort" class="sc-select" aria-label="Sort games">{sort_opts}</select>'
        f'<select id="sc-conf" class="sc-select" aria-label="Conference">{conf_opts}</select>'
        '<input id="sc-search" class="sc-search" type="search" placeholder="Team&hellip;" '
        'aria-label="Find a team">'
        "</div>"
        f'<div class="sc-chips"><span class="lbl">Show</span>{chips}'
        '<button type="button" id="sc-clear" class="clear">Reset</button></div>')


def _switcher(week_ids: list[int], current: int, views: dict[int, str]) -> str:
    buttons = "".join(
        f'<button class="wk-btn{" active" if w == current else ""}" '
        f"onclick=\"show_wk('{w}')\" id=\"wk-tab-{w}\">{w}</button>"
        for w in week_ids)
    divs = "".join(
        f'<div id="wk-view-{w}" class="wk-view"'
        f'{"" if w == current else " style=\'display:none\'"}>{views[w]}</div>'
        for w in week_ids)
    return (f'<div class="view-switch"><span class="switch-label">Week:</span>{buttons}</div>'
            f'<div id="cfb-weeks">{divs}</div>')


def body() -> str:
    df = _frame()
    week_ids = sorted(int(w) for w in df["week"].unique())
    views = {int(w): _week_view(grp.sort_values("local"))
             for w, grp in df.groupby("week")}
    current = _current_week(df)
    info = gameinfo.load(SEASON)
    lined = sum(1 for e in info.values() if e.get("spread") is not None)
    forecast = sum(1 for e in info.values() if e.get("weather"))

    built = datetime.now(LEAGUE_TZ).strftime("%b %-d, %-I:%M %p %Z")
    intro = (
        f'<p class="sc-intro">Every FBS game of the {SEASON} season, from ESPN &mdash; '
        "kickoffs in Eastern time, TV where it has been announced, scores once games go "
        "final, ranks from the AP top 25. Beside each game: the "
        '<a href="/cfb/predictions/">GordStats</a> line and win chance, the DraftKings '
        "line, ESPN's FPI win chance and the kickoff forecast. "
        f"Right now {lined} upcoming games carry a book line and {forecast} a "
        f"forecast; both fill in as the week approaches. Rebuilt daily (last: {built}).</p>")
    return (_CSS + intro + _LEGEND + _controls(espn.conferences())
            + _switcher(week_ids, current, views)
            + _JS % {"upset": json.dumps(UPSET_WATCH), "current": current})


def generate():
    write_page(WEB_DIR / "schedule" / "index.html", f"CFB Schedule {SEASON}", body())


if __name__ == "__main__":
    generate()
