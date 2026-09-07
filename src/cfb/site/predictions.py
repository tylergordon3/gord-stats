"""
Predicted scores for this week's games (docs/cfb/predictions/).

Every FBS game in the next seven days, with a predicted score, a win
probability and the market's line beside ours. The model is `cfb.ratings`;
what it is worth is `cfb.backtest`, and the honest answer is on the page
rather than buried in a repository: it lands within a point of the closing
spread without ever seeing one, and it has no betting edge whatsoever.

That second half is not modesty, it is the measurement. Across six held-out
seasons the games where this model disagreed with the line by three points or
more went 48% against the spread -- worse than a coin flip, and well under the
52.4% that standard juice requires. Its error grows with the size of the
disagreement while the market's does not. So the market column is here as the
better number, not as something to bet into.

    python -m cfb.site.predictions
"""
import json
from html import escape
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                      # noqa: E402
import numpy as np                                   # noqa: E402
import pandas as pd                                  # noqa: E402

from cfb import odds as odds_mod                     # noqa: E402
from cfb import predict                              # noqa: E402
from cfb import results                              # noqa: E402
from cfb.config import DATA_DIR, SEASON, WEB_DIR     # noqa: E402
from cfb.site import teams as teams_page              # noqa: E402
from cfb.site import write_page                      # noqa: E402
from gordstats import charts, favorites, palette     # noqa: E402

_SECTION = "cfb-predictions"
ACCENT = palette.BLUE
INK = palette.INK
MUTED = palette.MUTED
GRIDLINE = palette.GRIDLINE

_CSS = ("""<style>
.pred-note{color:#475569;font-size:14px;line-height:1.55}
.pred-scroll{overflow-x:auto}
/* A pick that was never live - no book total on record - reads as absent
   rather than as a loss. */
table.cfb-pred td.pred-na{color:#94a3b8}
table.cfb-pred td.pred-ou{white-space:nowrap;font-variant-numeric:tabular-nums}
table.cfb-pred{width:100%;border-collapse:collapse;font-size:14px}
table.cfb-pred th{background:#eef2f7;color:#334155;padding:7px 10px;text-align:center;
  font-size:12px;text-transform:uppercase;letter-spacing:.03em;white-space:nowrap;
  border:1px solid #e2e8f0}
table.cfb-pred td{padding:6px 10px;border:1px solid #eef2f7;color:#0f172a;background:#fff;
  text-align:center;white-space:nowrap}
table.cfb-pred td.pred-match{text-align:left;font-weight:600}
table.cfb-pred tbody tr:nth-child(even) td{background:#f8fafc}

/* Headline numbers. Four things worth knowing before reading 40 rows. */
.pred-tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
  gap:12px;margin:18px 0 26px}
.pred-tile{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:12px 14px}
.pred-tile .t-label{font-size:11px;text-transform:uppercase;letter-spacing:.05em;
  color:#64748b;font-weight:600}
.pred-tile .t-value{font-size:23px;font-weight:700;color:#0f172a;line-height:1.25;
  margin-top:3px}
.pred-tile .t-sub{font-size:12px;color:#64748b;margin-top:2px}

/* One card per game. */
/* min(330px,100%) so a narrow phone shrinks the card instead of scrolling
   the whole page sideways. */
.pred-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(330px,100%),1fr));
  gap:14px;margin:6px 0 28px}
.pg{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:12px 14px 11px;
  box-shadow:0 1px 2px rgba(15,23,42,.05)}
.pg-when{font-size:11.5px;color:#64748b;display:flex;justify-content:space-between;
  gap:10px;margin-bottom:9px;white-space:nowrap;overflow:hidden}
/* The flex container clips; the ellipsis has to live on the child that
   actually overflows (venue), never the TV badge. */
.pg-when>span:first-child{min-width:0;overflow:hidden;text-overflow:ellipsis}
.pg-when .pg-tv{color:#0f172a;font-weight:600}
.pg-row{display:flex;align-items:center;gap:9px;padding:4px 0}
.pg-row.pg-win .pg-name{font-weight:700;color:#0f172a}
.pg-row .pg-name a{color:inherit;text-decoration:none}
.pg-row .pg-name a:hover{text-decoration:underline}
.pg-row .pg-name{flex:1;color:#475569;font-size:14.5px;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.pg-rank{color:#64748b;font-size:11.5px;font-weight:700;margin-right:3px}
.pg-rating{color:#94a3b8;font-size:11.5px;font-variant-numeric:tabular-nums;
  min-width:44px;text-align:right}
.pg-score{font-size:19px;font-weight:700;color:#0f172a;min-width:32px;text-align:right;
  font-variant-numeric:tabular-nums}
.pg-row:not(.pg-win) .pg-score{color:#94a3b8;font-weight:600}
/* The Slate remote theme frames every <img> - border, padding, shadow, margins.
   Reset it here or every logo becomes a boxed figure and the row grows. */
.pg-row img,.pred-chart img{border:none;padding:0;box-shadow:none;background:none;
  border-radius:0;margin:0}
.pg-row img{width:26px;height:26px;object-fit:contain;flex:none}
.pg-bar{height:6px;border-radius:3px;background:#eef2f7;overflow:hidden;margin:9px 0 6px}
.pg-bar span{display:block;height:100%;background:{accent}}
.pg-line{display:flex;justify-content:space-between;gap:8px;font-size:12px;
  color:#475569;font-variant-numeric:tabular-nums}
.pg-line b{color:#0f172a}
.pred-chart img{margin:12px 0}
.pred-chart{max-width:640px}

/* Rate tiles. A record read as a fraction hides its own size -- 28/69 and
   15/30 look alike and are not -- so the percentage is the value and the bar
   underneath is what makes 88% and 41% look as different as they are. */
.pred-tiles.pred-tiles-wide{grid-template-columns:repeat(auto-fit,minmax(min(220px,100%),1fr))}

/* The record, at the top of the page. Two numbers, and both of them are simply
   right or wrong -- no averages, nothing to convert in your head. They were
   four screens down under a heading most readers never reached. */
.pred-record{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));
  gap:14px;margin:14px 0 10px}
.rec-cell{background:#fff;border:1px solid #e2e8f0;border-radius:12px;
  padding:15px 18px 16px;box-shadow:0 1px 2px rgba(15,23,42,.05)}
.rec-label{font-size:12px;text-transform:uppercase;letter-spacing:.05em;
  color:#64748b;font-weight:700}
/* Proportional figures, not tabular: at this size tabular-nums leaves a gap
   inside 88% wide enough to read as two numbers. */
.rec-value{font-size:46px;font-weight:800;color:#0f172a;line-height:1.05;margin:5px 0 1px}
.rec-sub{font-size:13.5px;color:#475569}
.rec-meter{position:relative;height:9px;border-radius:5px;background:#dbe7f7;margin-top:13px}
.rec-meter>i{display:block;height:100%;border-radius:5px;background:{accent}}
.rec-note{font-size:11.5px;color:#64748b;margin-top:8px}
.rec-more{font-size:13px;margin:0 0 4px}
.pred-tile .t-meter{position:relative;height:7px;border-radius:4px;background:#dbe7f7;
  margin-top:10px}
.pred-tile .t-meter>i{display:block;height:100%;border-radius:4px;background:{accent}}
/* Break-even drawn on the bar rather than left to the caption: the whole point
   of the spread record is where it sits against that line. */
.t-mark{position:absolute;top:-3px;bottom:-3px;width:2px;background:#334155}
.pred-tile .t-note{font-size:11px;color:#64748b;margin-top:6px}
.pred-tile .t-cmp{margin-top:10px;display:grid;gap:5px}
.pred-tile .c-row{display:flex;align-items:center;gap:8px;font-size:11px;color:#64748b;
  font-variant-numeric:tabular-nums}
.pred-tile .c-lab{min-width:30px}
.pred-tile .c-bar{flex:1;height:6px;border-radius:3px;background:#eef2f7}
.pred-tile .c-bar>i{display:block;height:100%;border-radius:3px;background:{accent}}
.pred-tile .c-row.c-book .c-bar>i{background:#94a3b8}

/* One block per week, so the log can hold every game without the page being
   one endless table. The newest week is open; the rest are a click away. */
.pred-week{border:1px solid #e2e8f0;border-radius:12px;background:#fff;margin:0 0 12px}
.pred-week>summary{cursor:pointer;list-style:none;padding:11px 14px;display:flex;
  flex-wrap:wrap;align-items:center;gap:8px 12px}
.pred-week>summary::-webkit-details-marker{display:none}
.pred-week>summary::before{content:"▸";color:#94a3b8;font-size:11px;flex:none}
.pred-week[open]>summary::before{content:"▾"}
.pw-name{font-weight:700;color:#0f172a;font-size:15px}
.pw-chips{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-left:auto}
.pw-chip{font-size:11.5px;color:#475569;background:#f1f5f9;border-radius:999px;
  padding:3px 9px;font-variant-numeric:tabular-nums;white-space:nowrap}
.pw-chip b{color:#0f172a}
.pw-body{padding:0 12px 12px}

/* The upcoming board when the seven-day window straddles two weeks. */
.pred-weekhead{font-size:15px;font-weight:700;color:#0f172a;margin:18px 0 8px;
  display:flex;align-items:baseline;gap:9px}
.pred-weekhead span{font-size:12px;font-weight:600;color:#64748b}

/* Results table: two header rows, so margin and total read as two families of
   four columns rather than eight columns in a row. */
table.cfb-pred th.grp{border-bottom:none;letter-spacing:.08em}
table.cfb-pred .col-sep{border-left:2px solid #cbd5e1}
table.cfb-pred td.pred-match .pm-final{display:block;font-size:12px;font-weight:600;
  color:#64748b;font-variant-numeric:tabular-nums;margin-top:1px}
@media (prefers-color-scheme: dark){
  .pred-note{color:#aab7c9}
  table.cfb-pred th{background:#223052;color:#dde5ef;border-color:#2b3852}
  table.cfb-pred td{background:#16203a;border-color:#2b3852;color:#dde5ef}
  table.cfb-pred tbody tr:nth-child(even) td{background:#1b2540}
  .pred-tile{background:#16203a;border-color:#2b3852}
  .pred-tile .t-label,.pred-tile .t-sub{color:#aab7c9}
  .pred-tile .t-value{color:#f1f5f9}
  .pg{background:#16203a;border-color:#2b3852;box-shadow:none}
  .pg-when{color:#8fa0b8}
  .pg-when .pg-tv{color:#dde5ef}
  .pg-row .pg-name{color:#c3cfdd}
  .pg-row.pg-win .pg-name{color:#ffffff}
  .pg-rank{color:#dde5ef}
  .pg-rating{color:#7f8ea3}
  .pg-score{color:#f1f5f9}
  .pg-row:not(.pg-win) .pg-score{color:#7f8ea3}
  .pg-bar{background:#223052}
  .pg-line{color:#aab7c9}
  .pg-line b{color:#f1f5f9}
  .pred-tile .t-meter{background:#24406b}
  .t-mark{background:#dde5ef}
  .rec-cell{background:#16203a;border-color:#2b3852;box-shadow:none}
  .rec-label,.rec-note{color:#aab7c9}
  .rec-value{color:#f1f5f9}
  .rec-sub{color:#c3cfdd}
  .rec-meter{background:#24406b}
  .pred-tile .t-note{color:#aab7c9}
  .pred-tile .c-row{color:#aab7c9}
  .pred-tile .c-bar{background:#223052}
  .pred-week{background:#16203a;border-color:#2b3852}
  .pred-week>summary::before{color:#7f8ea3}
  .pw-name{color:#f1f5f9}
  .pw-chip{background:#223052;color:#c3cfdd}
  .pw-chip b{color:#ffffff}
  .pred-weekhead{color:#f1f5f9}
  .pred-weekhead span{color:#aab7c9}
  table.cfb-pred .col-sep{border-left-color:#3f5075}
  table.cfb-pred td.pred-match .pm-final{color:#8fa0b8}
}
</style>""").replace("{accent}", ACCENT)


def _validation() -> dict:
    path = DATA_DIR / "model_validation.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _with_market(games: pd.DataFrame) -> pd.DataFrame:
    """Attach the latest captured book line to each game, where there is one."""
    board = odds_mod.latest(SEASON)
    if board.empty or "home_id" not in games.columns:
        games["market_spread"] = np.nan
        games["market_total"] = np.nan
        return games
    board = board.rename(columns={"spread": "market_spread", "total": "market_total"})
    return games.merge(board[["home_id", "away_id", "market_spread", "market_total"]],
                       on=["home_id", "away_id"], how="left")


ET = ZoneInfo("America/New_York")
LOGO = "https://a.espncdn.com/i/teamlogos/ncaa/500/{team_id}.png"


def _fmt_spread(value) -> str:
    if pd.isna(value):
        return "&mdash;"
    return "PK" if abs(value) < 0.25 else f"{value:+.1f}"


def _scores(game) -> tuple:
    """Projected scores as whole points, never a tie.

    Rounding two numbers 0.3 apart lands them on the same integer, and the card
    then shows a 30-30 draw next to a line calling one side the favourite.
    College football has not drawn a game since overtime arrived in 1996, so the
    favourite is nudged clear rather than shown level.
    """
    home, away = round(game["pred_home"]), round(game["pred_away"])
    if home == away:
        if game["pred_margin"] >= 0:
            home += 1
        else:
            away += 1
    return int(home), int(away)


def _side(game, side: str, winning: bool, score: int) -> str:
    """One team's row inside a card: badge, rank, name, rating, projected score."""
    name = escape(str(game[side]))
    rank = game.get(f"{side}_rank")
    badge = "" if pd.isna(rank) else f"<span class='pg-rank'>#{int(rank)}</span>"
    rating = game.get(f"{side}_rating")
    rating_txt = "" if pd.isna(rating) else f"{rating:+.1f}"
    logo = LOGO.format(team_id=escape(str(game[f"{side}_id"])))
    # Only FBS teams get a page; an FCS visitor is pooled and has no rating to
    # show, so it gets a badge and no link rather than a link to nothing. Team
    # pages are built before this one -- see cfb.build.PAGES -- so the file is
    # already on disk when this asks.
    slug = teams_page.team_slug(str(game[side]))
    linked = (WEB_DIR / "teams" / slug / "index.html").exists()
    open_a = f"<a href='/cfb/teams/{slug}/'>" if linked else ""
    close_a = "</a>" if linked else ""
    return (f"<div class='pg-row{' pg-win' if winning else ''}'>"
            f"{open_a}<img src='{logo}' alt='' loading='lazy'>{close_a}"
            f"<span class='pg-name'>{badge}{open_a}{name}{close_a}</span>"
            f"<span class='pg-rating'>{rating_txt}</span>"
            f"<span class='pg-score'>{score}</span></div>")


def _card(game) -> str:
    home_wins = game["pred_margin"] > 0
    favourite = game["home"] if home_wins else game["away"]
    prob = game["home_win_prob"] if home_wins else 1 - game["home_win_prob"]

    kick = game["date"].astimezone(ET)
    where = "neutral site" if game.get("neutral") else escape(str(game.get("place") or ""))
    tv = escape(str(game.get("tv") or "").split(",")[0])
    when = (f"<div class='pg-when'><span>{kick:%a %-d %b, %-I:%M %p} ET"
            + (f" &middot; {where}" if where else "") + "</span>"
            + (f"<span class='pg-tv'>{tv}</span>" if tv else "") + "</div>")

    ours = f"<b>{escape(str(favourite))} {-abs(game['pred_margin']):.1f}</b>"
    market = ("" if pd.isna(game.get("market_spread"))
              else f"<span>book {_fmt_spread(game['market_spread'])}</span>")
    home_score, away_score = _scores(game)
    return (f"<article class='pg'{favorites.many_attr('cfb', (game.get('home_id'), game.get('away_id')))}>"
            + when
            + _side(game, "away", not home_wins, away_score)
            + _side(game, "home", home_wins, home_score)
            + f"<div class='pg-bar'><span style='width:{prob * 100:.0f}%'></span></div>"
            + "<div class='pg-line'>" + ours + market
            + f"<span>O/U {game['pred_total']:.0f}</span>"
            + f"<span>{prob:.0%}</span></div></article>")


def _grid(games: pd.DataFrame) -> str:
    return ("<div class='pred-grid'>"
            + "".join(_card(g) for _, g in games.iterrows()) + "</div>")


def _weeks(games: pd.DataFrame) -> list:
    return sorted(int(w) for w in games["week"].dropna().unique())


def _week_label(games: pd.DataFrame) -> str:
    """What to call the board.

    The window is seven days, not a week, so from Tuesday on it holds the tail
    of one week and the front of the next. Naming it after the first game's week
    -- which is what this did -- left week two's games filed under a "Week 1"
    heading for half of every week.
    """
    weeks = _weeks(games)
    if not weeks:
        return "This week"
    if len(weeks) == 1:
        return f"Week {weeks[0]}"
    return f"Weeks {weeks[0]}&ndash;{weeks[-1]}"


def _cards(games: pd.DataFrame) -> str:
    weeks = _weeks(games)
    if len(weeks) < 2:
        return _grid(games)
    out = []
    for week in weeks:
        block = games[games["week"] == week]
        out.append(f"<h3 class='pred-weekhead'>Week {week}"
                   f"<span>{len(block)} games</span></h3>")
        out.append(_grid(block))
    return "".join(out)


def _tiles(games: pd.DataFrame) -> str:
    """The four numbers worth having before reading forty cards."""
    closest = games.reindex(games["pred_margin"].abs().sort_values().index).iloc[0]
    biggest = games.reindex(games["pred_margin"].abs().sort_values(ascending=False).index).iloc[0]
    big_fav = biggest["home"] if biggest["pred_margin"] > 0 else biggest["away"]
    ranked = games[(games["home_rank"].notna()) | (games["away_rank"].notna())]

    priced = games.dropna(subset=["market_spread"])
    agree = ((-priced["pred_margin"]) - priced["market_spread"]).abs().mean() \
        if len(priced) else float("nan")

    tiles = [
        ("Games", f"{len(games)}", f"{len(ranked)} with a ranked team"),
        ("Closest call",
         f"{abs(closest['pred_margin']):.1f} pts",
         escape(f"{closest['away']} at {closest['home']}")),
        ("Biggest mismatch",
         f"{abs(biggest['pred_margin']):.0f} pts",
         escape(f"{big_fav} over "
                f"{biggest['away'] if biggest['pred_margin'] > 0 else biggest['home']}")),
        ("Distance from the book",
         "&mdash;" if pd.isna(agree) else f"{agree:.1f} pts",
         f"average across {len(priced)} priced games"),
    ]
    return ("<div class='pred-tiles'>" + "".join(
        f"<div class='pred-tile'><div class='t-label'>{label}</div>"
        f"<div class='t-value'>{value}</div><div class='t-sub'>{sub}</div></div>"
        for label, value, sub in tiles) + "</div>")


# The break-even a spread bet has to clear at standard -110 juice. Quoted from
# the backtest record where there is one, so the page never carries two numbers.
BREAK_EVEN = 0.524


def _span(frame: pd.DataFrame) -> str:
    """The dates the archive covers, as one line."""
    first = frame["kickoff"].min().astimezone(ET)
    last = frame["kickoff"].max().astimezone(ET)
    if first.date() == last.date():
        return f"{first:%-d %b}"
    return f"{first:%-d %b} &ndash; {last:%-d %b}"


def _plain_tile(label: str, value: str, sub: str, extra: str = "") -> str:
    return (f"<div class='pred-tile'><div class='t-label'>{label}</div>"
            f"<div class='t-value'>{value}</div>"
            f"<div class='t-sub'>{sub}</div>{extra}</div>")


def _rate_tile(label: str, wins: int, games: int, sub: str,
               benchmark: float | None = None) -> str:
    """A record led by its percentage, with the bar that gives it a size.

    28/69 and 15/30 read alike as fractions and are eleven points apart. The
    percentage is the value, the fraction is the caption, and the meter is what
    makes the difference visible without arithmetic.
    """
    if not games:
        return _plain_tile(label, "&mdash;", sub)
    pct = wins / games
    mark = note = ""
    if benchmark is not None:
        mark = f"<span class='t-mark' style='left:{benchmark * 100:.1f}%'></span>"
        gap = (benchmark - pct) * 100
        note = ("<div class='t-note'>the mark is break-even at "
                f"{benchmark:.1%} &middot; "
                + (f"{abs(gap):.0f} points clear" if gap <= 0
                   else f"{gap:.0f} points under") + "</div>")
    meter = (f"<div class='t-meter'><i style='width:{pct * 100:.0f}%'></i>{mark}</div>"
             f"{note}")
    return _plain_tile(label, f"{pct:.0%}", f"{wins} of {games} {sub}", meter)


def _miss_tile(label: str, ours: float, book: float | None, sub: str) -> str:
    """Our average miss beside the book's on the same games, one shared scale."""
    bars = ""
    if book is not None:
        top = max(ours, book) or 1.0
        bars = ("<div class='t-cmp'>"
                "<div class='c-row'><span class='c-lab'>ours</span>"
                f"<span class='c-bar'><i style='width:{ours / top * 100:.0f}%'></i></span>"
                f"<span>{ours:.1f}</span></div>"
                "<div class='c-row c-book'><span class='c-lab'>book</span>"
                f"<span class='c-bar'><i style='width:{book / top * 100:.0f}%'></i></span>"
                f"<span>{book:.1f}</span></div></div>")
    return _plain_tile(label, f"{ours:.1f} pts", sub, bars)


def _mark(ok) -> str:
    """A tick, a cross, or a dash where the pick was never live."""
    if ok is None or (isinstance(ok, float) and pd.isna(ok)):
        return "<td class='pred-na'>&mdash;</td>"
    glyph = "&#10003;" if ok else "&#10007;"
    colour = teams_page.GOOD if ok else teams_page.BAD
    return f"<td style='color:{colour};font-weight:700'>{glyph}</td>"


def _result_rows(frame: pd.DataFrame) -> str:
    rows = []
    for _, g in frame.iterrows():
        ou_said = ("&mdash;" if pd.isna(g["market_total"])
                   else f"{'O' if g['ou_edge'] > 0 else 'U'} {g['market_total']:.1f}")
        rows.append(
            f"<tr><td class='pred-match'>{escape(str(g['away']))} at "
            f"{escape(str(g['home']))}"
            f"<span class='pm-final'>{int(g['away_score'])}"
            f"&ndash;{int(g['home_score'])}</span></td>"
            f"<td>{g['pred_margin']:+.1f}</td>"
            f"<td>{g['actual_margin']:+.0f}</td>"
            f"<td>{abs(g['margin_error']):.1f}</td>"
            + _mark(bool(g["correct"]))
            + f"<td class='col-sep'>{g['pred_total']:.0f}</td>"
            f"<td>{g['actual_total']:.0f}</td>"
            f"<td class='pred-ou'>{ou_said}</td>"
            + _mark(g["ou_correct"]) + "</tr>")
    return ("<div class='pred-scroll'><table class='cfb-pred'><thead>"
            "<tr><th rowspan='2'>Game</th><th class='grp' colspan='4'>Margin</th>"
            "<th class='grp col-sep' colspan='4'>Total</th></tr>"
            "<tr><th>Ours</th><th>It was</th><th>Miss</th><th>Call</th>"
            "<th class='col-sep'>Ours</th><th>It was</th><th>Our O/U</th><th>Call</th>"
            f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div>")


def _week_block(frame: pd.DataFrame, label: str, is_open: bool) -> str:
    """One week of scored games, with its own record on the header.

    Collapsed by default past the newest week: the log only grows, and a season
    of it is three thousand pixels of table nobody scrolled to.
    """
    stat = results.summary(frame)
    chips = [f"<span class='pw-chip'>{stat['games']} games</span>",
             f"<span class='pw-chip'><b>{stat['winner_accuracy']:.0%}</b> winners "
             f"({stat['correct']}/{stat['games']})</span>",
             f"<span class='pw-chip'><b>{stat['margin_mae']:.1f}</b> pt miss</span>"]
    if stat["ats_games"]:
        chips.append(f"<span class='pw-chip'><b>"
                     f"{stat['ats_wins'] / stat['ats_games']:.0%}</b> ATS "
                     f"({stat['ats_wins']}/{stat['ats_games']})</span>")
    if stat["ou_games"]:
        chips.append(f"<span class='pw-chip'><b>"
                     f"{stat['ou_wins'] / stat['ou_games']:.0%}</b> O/U "
                     f"({stat['ou_wins']}/{stat['ou_games']})</span>")
    # Newest first inside the week, matching the order of the weeks themselves.
    ordered = frame.sort_values("kickoff", ascending=False)
    return (f"<details class='pred-week'{' open' if is_open else ''}>"
            f"<summary><span class='pw-name'>{label}</span>"
            f"<span class='pw-chips'>{''.join(chips)}</span></summary>"
            f"<div class='pw-body'>{_result_rows(ordered)}</div></details>")


def _record_cell(label: str, wins: int, games: int, sub: str,
                 benchmark: float | None = None) -> str:
    pct = wins / games
    mark = note = ""
    if benchmark is not None:
        mark = f"<span class='t-mark' style='left:{benchmark * 100:.1f}%'></span>"
        gap = (benchmark - pct) * 100
        note = ("<div class='rec-note'>the mark is break-even at "
                f"{benchmark:.1%} &middot; "
                + (f"{abs(gap):.0f} points clear" if gap <= 0
                   else f"{gap:.0f} points under") + "</div>")
    return (f"<div class='rec-cell'><div class='rec-label'>{label}</div>"
            f"<div class='rec-value'>{pct:.0%}</div>"
            f"<div class='rec-sub'>{wins} of {games} {sub}</div>"
            f"<div class='rec-meter'><i style='width:{pct * 100:.0f}%'></i>{mark}</div>"
            f"{note}</div>")


def _record_band(frame: pd.DataFrame) -> str:
    """Right or wrong, at the top of the page.

    Everything else here measures how far off the model was, which is the
    interesting question only once you already trust it. These two need no
    conversion: the winner was called or it was not, and the total went over
    the book's number or it did not.

    The over/under figure here is deliberately the ungated one - every game the
    book priced, however small our disagreement. The three-point version is a
    claim about bets worth placing and belongs with the rest of the analysis
    further down; up here the question is only whether we were right.
    """
    if frame.empty:
        return ""
    stat = results.summary(frame)
    cells = [_record_cell("Winners called right", stat["correct"], stat["games"],
                          "games")]
    if stat["ou_all_games"]:
        cells.append(_record_cell("Over/under called right", stat["ou_all_wins"],
                                  stat["ou_all_games"], "games the book priced"))
    return ("<p class='pred-note'>Every prediction below is archived before "
            "kickoff and scored against the result. Here is how that has gone "
            f"across {stat['games']} finished game"
            f"{'s' if stat['games'] != 1 else ''}, {_span(frame)}.</p>"
            "<div class='pred-record'>" + "".join(cells) + "</div>"
            "<p class='pred-note rec-more'><a href='#how-it-has-gone'>How close the "
            "scores were, the spread and total records against the book, and every "
            "game week by week &rarr;</a></p>")


def _results_section(frame: pd.DataFrame) -> str:
    """How the published predictions have actually done, in detail.

    Everything else on this page is a claim about seasons nobody watched. This
    is the only part a reader can check, so it is scored on predictions that
    were on record before kickoff and nothing else. The two plain right-or-wrong
    rates are at the top of the page; what is left here is what needs a sentence
    of explanation -- the spread, the average miss, and the game-by-game log.
    """
    if frame.empty:
        return ("<h2 id='how-it-has-gone'>How it has gone</h2>"
                "<p class='pred-note'>Every prediction above is archived with the "
                "moment it was made, and scored only if it was on record before "
                "kickoff. Nothing has finished yet, so there is nothing to report "
                "&mdash; this fills in from the first Saturday and never resets.</p>")

    stat = results.summary(frame)
    ours = stat["margin_mae"]
    book = stat.get("market_margin_mae")
    ours_total = stat["total_mae"]
    book_total = stat.get("market_total_mae")

    tiles = [
        _plain_tile("Games scored", f"{stat['games']}", "predicted before kickoff",
                    f"<div class='t-note'>{_span(frame)}</div>"),
        _rate_tile("Against the spread", stat["ats_wins"], stat["ats_games"],
                   "where we differed by 3+", BREAK_EVEN),
        _rate_tile("Over/under", stat["ou_wins"], stat["ou_games"],
                   "where we differed by 3+", BREAK_EVEN),
        _miss_tile("Margin miss", ours, book, "average, against the final margin"),
        _miss_tile("Total miss", ours_total, book_total,
                   "average, against the points scored"),
    ]
    tile_html = ("<div class='pred-tiles pred-tiles-wide'>" + "".join(tiles) + "</div>")

    filed = frame["week"].fillna(-1).astype(int)
    weeks = sorted(filed.unique(), reverse=True)
    blocks = "".join(
        _week_block(frame[filed == week],
                    f"Week {week}" if week >= 0 else "Unfiled",
                    is_open=(i == 0))
        for i, week in enumerate(weeks))

    verdict = ""
    if book is not None:
        gap = ours - book
        verdict = (f" On these games the book missed by {book:.1f}, so we are "
                   + ("ahead of it by " if gap < 0 else "behind it by ")
                   + f"{abs(gap):.1f} points a game &mdash; on a sample this small "
                   "that is noise, not a trend.")
    ats = ""
    if stat["ats_games"]:
        ats = (f" Where the two disagreed by three points or more, this model has "
               f"been right {stat['ats_wins']} times in {stat['ats_games']} on the "
               f"spread")
        ats += (f" and {stat['ou_wins']} in {stat['ou_games']} on the total."
                if stat["ou_games"] else ".")

    # The over/under record starts empty and it is worth saying why: the book's
    # total was not archived alongside its spread until now, so there is no
    # honest way to score a total pick on a game that has already been played.
    # Without this the column reads as broken rather than as not yet earned.
    ou_note = ""
    if not stat["ou_games"]:
        ou_note = (" The over/under record starts from the next round of games: "
                   "the book's total is archived before kickoff the same way its "
                   "spread is, and that archive only begins now, so there is "
                   "nothing to score it against on games already played.")

    return ("<h2 id='how-it-has-gone'>How it has gone</h2>"
            f"<p class='pred-note'>Scored on the "
            f"{stat['games']} game{'s' if stat['games'] != 1 else ''} that have "
            f"finished since the archive started, using the last prediction made "
            f"before each kickoff. Average miss on the final margin is "
            f"<strong>{ours:.1f} points</strong>. In the <strong>Call</strong> "
            f"column, &#10003; means the pick got the winner right and "
            f"&#10007; means it did not. <strong>Total</strong> is the same "
            f"exercise on the points in the game, and <strong>Our O/U</strong> is "
            f"the side our number took against the book's."
            f"{verdict}{ats}{ou_note}</p>"
            + tile_html
            + "<p class='pred-note'>Every game scored so far, newest week first. "
            "Open a week for the game-by-game log.</p>"
            + blocks)


def _agreement_chart(games: pd.DataFrame) -> str:
    """Our line against the market's, one dot per game.

    The diagonal is agreement. Distance from it is not an edge -- the backtest
    says the disagreements are the model's error, not the market's -- so the
    chart is here to show how closely a model built only from final scores
    tracks a line built from everything else.
    """
    both = games.dropna(subset=["market_spread"])
    if len(both) < 5:
        return ""

    ours, theirs = -both["pred_margin"], both["market_spread"]
    # One shared range across both axes, taken from the games actually on the
    # board rather than centred on zero: nobody is a fifty-point home underdog,
    # and reserving room for it shrinks everything that did happen.
    low = float(min(ours.min(), theirs.min())) - 4
    high = float(max(ours.max(), theirs.max())) + 4

    fig, ax = plt.subplots(figsize=(6.8, 6.4))
    ax.plot([low, high], [low, high], color=MUTED, linewidth=1.2,
            linestyle="--", zorder=1)
    ax.scatter(ours, theirs, s=46, color=ACCENT, edgecolor="white",
               linewidth=1.2, zorder=3)
    ax.set_xlim(low, high)
    ax.set_ylim(low, high)
    ax.set_aspect("equal")            # so agreement really is the 45-degree line
    ax.set_xlabel("our line (negative = home favoured)")
    ax.set_ylabel("the market's line")
    ax.set_title("Where we agree with the book, and where we do not")
    ax.grid(color=GRIDLINE)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    fig.tight_layout()
    return ("<div class='pred-chart'>"
            + charts.save(_SECTION, "agreement",
                          alt="Scatter of our predicted line against the book's line "
                              "for each game, with the line of agreement drawn")
            + "</div>")


def _method(games: pd.DataFrame) -> str:
    record = _validation()
    overall = record.get("overall", {})
    market = record.get("versus_market", {})
    if not overall:
        return ""

    scored = record.get("scored_on", "held-out seasons")
    lines = [
        f"<p class='pred-note'>Every roster of results since 2014 &mdash; "
        f"{record.get('scored_games', 'FBS games')} &mdash; fitted as ridge team "
        f"ratings, one number per team, chosen so the gap between two of them plus "
        f"home field best explains the margins actually played. Margin and total are "
        f"modelled separately and the score is rebuilt from the two, because over "
        f"these seasons they barely correlate. Games decay with a half-life of "
        f"{record.get('hyperparameters', {}).get('half_life_days', 180):.0f} days, so "
        f"in week one the evidence is almost all last season's and by November almost "
        f"all of this one's.</p>",
        f"<p class='pred-note'>Tuned on {record.get('tuned_on', 'earlier seasons')} and "
        f"then scored once on {scored}, predicting each week from only what had "
        f"finished before it: <strong>{overall.get('margin_rmse', 0):.1f}</strong> "
        f"points of margin RMSE against <strong>"
        f"{overall.get('baseline_home_rmse', 0):.1f}</strong> for knowing nothing but "
        f"who is at home, and the winner right "
        f"<strong>{overall.get('winner_accuracy', 0):.0%}</strong> of the time.</p>",
    ]
    if market:
        lines.append(
            f"<p class='pred-note'><strong>It does not beat the market, and it is worth "
            f"saying so plainly.</strong> On the "
            f"{market.get('games', 0):,} games with a closing line it managed "
            f"{market.get('our_margin_rmse', 0):.2f} against the book's "
            f"{market.get('market_margin_rmse', 0):.2f} &mdash; within "
            f"{market.get('gap_rmse', 0):.2f} of a number built from injuries, weather "
            f"and everyone else's money, which is the part worth being pleased about. "
            f"But on the {market.get('ats_sample', 0):,} games where the two disagreed "
            f"by three points or more, this model went "
            f"<strong>{market.get('ats_when_we_disagree_by_3', 0):.1%}</strong> against "
            f"the spread &mdash; under a coin flip, and under the "
            f"{market.get('break_even_at_minus_110', 0.524):.1%} that standard juice "
            f"needs. Its error grows with the size of the disagreement; the market's "
            f"does not. Every point between the two columns above is this model being "
            f"wrong, not the book. Read it as a description of who is strong, and not "
            f"as a tip.</p>")
    lines.append(
        "<p class='pred-note'>It is at its worst on mismatches. Past about 45 points "
        "of predicted margin it has historically said winner 53, loser 3, where the "
        "truth was nearer 51 and 8 &mdash; so the lopsided lines on this page are the "
        "ones to trust least, and a promoted team playing its first FBS season is "
        "rated on the division it just left. Between two established teams, which is "
        "most of the board, it is on much firmer ground.</p>")
    return "<h2>How this is built, and how well it works</h2>" + "".join(lines)


def body() -> str:
    games = predict.week()
    scored = results.scored()
    if games.empty:
        return (_CSS + "<p class='pred-note'>No games scheduled in the next week. "
                "Predictions return when the season does.</p>"
                + _results_section(scored) + _method(games))

    games = _with_market(games)
    weeks = _weeks(games)
    matched = games["market_spread"].notna().sum()

    span = ("" if len(weeks) < 2 else
            f" That window straddles week {weeks[0]} and week {weeks[-1]}, so both "
            f"are below.")
    intro = (f"<p class='pred-note'>Every FBS game kicking off in the next seven days, "
             f"{len(games)} of them.{span} Each card carries the score this model expects, "
             f"each team's rating &mdash; points better than an average FBS side "
             f"&mdash; and the book's line beside ours. The bar is the favourite's "
             f"chance of winning, taken from the margin and the spread of this model's "
             f"own errors: not a second model, and not a promise.</p>")

    parts = [_CSS, _record_band(scored), f"<h2>{_week_label(games)}</h2>", intro,
             _tiles(games), _cards(games), _results_section(scored)]
    if matched >= 5:
        parts.append(_agreement_chart(games))
    parts.append(_method(games))
    return "".join(parts)


def generate() -> None:
    charts.clear(_SECTION)
    write_page(WEB_DIR / "predictions" / "index.html",
               "CFB Predictions", body(),
               subtitle="Predicted scores for this week's college football")


if __name__ == "__main__":
    generate()
