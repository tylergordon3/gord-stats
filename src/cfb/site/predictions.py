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

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                      # noqa: E402
import numpy as np                                   # noqa: E402
import pandas as pd                                  # noqa: E402

from cfb import odds as odds_mod                     # noqa: E402
from cfb import predict                              # noqa: E402
from cfb.config import DATA_DIR, SEASON, WEB_DIR     # noqa: E402
from cfb.site import write_page                      # noqa: E402
from gordstats import charts                         # noqa: E402

_SECTION = "cfb-predictions"
ACCENT = "#2a78d6"
INK = "#0b0b0b"
MUTED = "#94a3b8"
GRIDLINE = "#e2e8f0"

_CSS = """<style>
table.cfb-pred{width:100%;border-collapse:collapse;font-size:14px}
table.cfb-pred th{background:#eef2f7;color:#334155;padding:7px 10px;text-align:center;
  font-size:12px;text-transform:uppercase;letter-spacing:.03em;white-space:nowrap;
  border:1px solid #e2e8f0}
table.cfb-pred td{padding:6px 10px;border:1px solid #eef2f7;color:#0f172a;background:#fff;
  text-align:center;white-space:nowrap}
table.cfb-pred td.pred-match{text-align:left;font-weight:600}
table.cfb-pred tbody tr:nth-child(even) td{background:#f8fafc}
table.cfb-pred td.pred-fav{font-weight:700}
.pred-note{color:#475569;font-size:14px}
.pred-scroll{overflow-x:auto}
/* The Slate remote theme frames every <img>; charts here are not figures. */
.pred-chart img{border:none;padding:0;box-shadow:none;background:none;margin:12px 0}
</style>"""


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


def _fmt_spread(value) -> str:
    if pd.isna(value):
        return "&mdash;"
    return "PK" if abs(value) < 0.25 else f"{value:+.1f}"


def _table(games: pd.DataFrame) -> str:
    rows = []
    for _, g in games.iterrows():
        favourite = g["home"] if g["pred_margin"] > 0 else g["away"]
        prob = g["home_win_prob"] if g["pred_margin"] > 0 else 1 - g["home_win_prob"]
        rows.append(
            "<tr>"
            f"<td>{g['date']:%a %-d %b, %-I:%M%p} UTC</td>"
            f"<td class='pred-match'>{g['away']} at {g['home']}</td>"
            f"<td>{g['pred_away']:.0f} &ndash; {g['pred_home']:.0f}</td>"
            f"<td class='pred-fav'>{favourite} {_fmt_spread(-abs(g['pred_margin']))}</td>"
            f"<td>{_fmt_spread(g['market_spread'])}</td>"
            f"<td>{g['pred_total']:.0f}</td>"
            f"<td>{prob:.0%}</td>"
            "</tr>")
    head = ("<tr><th>Kickoff</th><th>Game</th><th>Score</th><th>Our line</th>"
            "<th>Market</th><th>Total</th><th>Confidence</th></tr>")
    return ("<div class='pred-scroll'><table class='cfb-pred'>"
            f"<thead>{head}</thead><tbody>{''.join(rows)}</tbody></table></div>")


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
    closest = games.reindex(games["pred_margin"].abs().sort_values().index).iloc[0]
    matched = games["market_spread"].notna().sum()

    intro = (f"<p class='pred-note'>Every FBS game kicking off in the next seven days, "
             f"{len(games)} of them, with the score this model expects and the book's "
             f"line beside it. The closest game on the board is "
             f"<strong>{closest['away']} at {closest['home']}</strong>, which it "
             f"separates by {abs(closest['pred_margin']):.1f} points. "
             f"<strong>Confidence</strong> is the chance the favourite wins, taken from "
             f"the margin and the spread of this model's own errors &mdash; not a "
             f"second model, and not a promise.</p>")

    parts = [_CSS, f"<h2>Week {week}</h2>", intro, _table(games)]
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
