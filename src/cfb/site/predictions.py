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
from cfb.config import DATA_DIR, SEASON, WEB_DIR     # noqa: E402
from cfb.site import write_page                      # noqa: E402
from gordstats import charts, palette                # noqa: E402

_SECTION = "cfb-predictions"
ACCENT = palette.BLUE
INK = palette.INK
MUTED = palette.MUTED
GRIDLINE = palette.GRIDLINE

_CSS = ("""<style>
.pred-note{color:#475569;font-size:14px;line-height:1.55}

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
.pred-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));
  gap:14px;margin:6px 0 28px}
.pg{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:12px 14px 11px;
  box-shadow:0 1px 2px rgba(15,23,42,.05)}
.pg-when{font-size:11.5px;color:#64748b;display:flex;justify-content:space-between;
  gap:10px;margin-bottom:9px;white-space:nowrap;overflow:hidden}
.pg-when .pg-tv{color:#0f172a;font-weight:600}
.pg-row{display:flex;align-items:center;gap:9px;padding:4px 0}
.pg-row.pg-win .pg-name{font-weight:700;color:#0f172a}
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
    return (f"<div class='pg-row{' pg-win' if winning else ''}'>"
            f"<img src='{logo}' alt='' loading='lazy'>"
            f"<span class='pg-name'>{badge}{name}</span>"
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
    return ("<article class='pg'>" + when
            + _side(game, "away", not home_wins, away_score)
            + _side(game, "home", home_wins, home_score)
            + f"<div class='pg-bar'><span style='width:{prob * 100:.0f}%'></span></div>"
            + "<div class='pg-line'>" + ours + market
            + f"<span>O/U {game['pred_total']:.0f}</span>"
            + f"<span>{prob:.0%}</span></div></article>")


def _cards(games: pd.DataFrame) -> str:
    return ("<div class='pred-grid'>"
            + "".join(_card(g) for _, g in games.iterrows()) + "</div>")


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
    if games.empty:
        return (_CSS + "<p class='pred-note'>No games scheduled in the next week. "
                "Predictions return when the season does.</p>" + _method(games))

    games = _with_market(games)
    week = int(games["week"].iloc[0])
    matched = games["market_spread"].notna().sum()

    intro = (f"<p class='pred-note'>Every FBS game kicking off in the next seven days, "
             f"{len(games)} of them. Each card carries the score this model expects, "
             f"each team's rating &mdash; points better than an average FBS side "
             f"&mdash; and the book's line beside ours. The bar is the favourite's "
             f"chance of winning, taken from the margin and the spread of this model's "
             f"own errors: not a second model, and not a promise.</p>")

    parts = [_CSS, f"<h2>Week {week}</h2>", intro, _tiles(games), _cards(games)]
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
