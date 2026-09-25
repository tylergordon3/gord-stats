"""
NFL predictions (docs/nfl/index.html): a score, a spread and a win
probability for every game of the season, the college predictions page for
the other league.

One card per game, a week at a time, the week being played open: this
site's line beside the book's, the projected score, and once a game is
final the score and whether the call was right. Above the cards, the
season's record so far; below them, the ratings the model runs on and how it
did on six held-out seasons before it was allowed to say anything here.

    python -m nfl.site.predictions
"""
import json
from html import escape

import numpy as np
import pandas as pd

from cfb.site.predictions import _CSS, _fmt_spread
from gordstats import scorecard
from gordstats import matchup_page as ui
from gordstats.frontmatter import add_front_matter
from nfl import predict, results
from nfl.config import DATA_DIR, SEASON, TZ, WEB_DIR

LOGO = "https://a.espncdn.com/i/teamlogos/nfl/500/{abbr}.png"
EDGE = 3.0                      # points from the book before a lean is worth naming
BREAK_EVEN = 0.524

_EXTRA_CSS = """<style>
.pg-final{font-size:11.5px;font-weight:700;padding:1px 7px;border-radius:8px;margin-left:6px}
.pg-final.ok{background:#dcfce7;color:#166534}
.pg-final.no{background:#fee2e2;color:#991b1b}
.pg-final.push{background:#e2e8f0;color:#475569}
.pg-actual{font-size:12px;color:#64748b;margin-left:6px;font-variant-numeric:tabular-nums}
.pg-lean{color:#b45309;font-weight:700}
table.cfb-pred td.rt-name{text-align:left;font-weight:600;white-space:nowrap}
table.cfb-pred td.rt-name img{width:22px;height:22px;vertical-align:-6px;margin:0 8px 0 0;
  border:0;padding:0;box-shadow:none;background:none}
.rt-bar{display:inline-block;width:60px;height:7px;border-radius:4px;background:#eef2f7;
  vertical-align:middle;margin-left:8px;overflow:hidden;position:relative}
.rt-bar i{position:absolute;top:0;height:100%;background:#2a78d6}
.rt-bar i.neg{background:#dc2626}
@media (prefers-color-scheme: dark){
  .pg-final.ok{background:#14532d;color:#bbf7d0}.pg-final.no{background:#5f1d1d;color:#fecaca}
  .pg-final.push{background:#2b3852;color:#cbd5e1}
  .pg-actual{color:#aab7c9}.pg-lean{color:#ffb457}.rt-bar{background:#2b3852}
}
</style>"""


def _validation() -> dict:
    try:
        return json.loads((DATA_DIR / "model_validation.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _scores(game) -> tuple:
    home, away = round(game["pred_home"]), round(game["pred_away"])
    if home == away:                                   # the favourite is nudged clear
        if game["pred_margin"] >= 0:
            home += 1
        else:
            away += 1
    return int(home), int(away)


def _side(game, side: str, winning: bool, score: int, actual=None) -> str:
    logo = LOGO.format(abbr=escape(str(game[f"{side}_abbr"]).lower()))
    rating = game.get(f"{side}_rating")
    record = game.get(f"{side}_record") or ""
    return (f"<div class='pg-row{' pg-win' if winning else ''}'>"
            f"<img src='{logo}' alt='' loading='lazy'>"
            f"<span class='pg-name'>{escape(str(game[side]))}"
            + (f" <span class='pg-rank'>{escape(str(record))}</span>" if record else "")
            + "</span>"
            f"<span class='pg-rating'>{'' if pd.isna(rating) else f'{rating:+.1f}'}</span>"
            + (f"<span class='pg-actual'>proj {score}</span>"
               f"<span class='pg-score'>{int(actual)}</span>" if actual is not None
               else f"<span class='pg-score'>{score}</span>") + "</div>")


def _card(game, record: dict) -> str:
    """One game. Before kickoff the model's number; after it, the final and
    whether the prediction on record (results.on_record) called it."""
    played = bool(game["played"])
    rec = record.get(str(game["game_id"]))
    # What the page shows for a finished game is what was on record before
    # kickoff, never a refit that knows the score.
    margin = rec["pred_margin"] if rec is not None else game["pred_margin"]
    total = rec["pred_total"] if rec is not None else game["pred_total"]
    prob = rec["home_win_prob"] if rec is not None else game["home_win_prob"]
    book = rec["market_spread"] if rec is not None else game.get("book_spread")
    book_total = rec["market_total"] if rec is not None else game.get("book_total")
    home_wins = margin > 0
    favourite = game["home"] if home_wins else game["away"]
    prob = prob if home_wins else 1 - prob
    # ESPN quotes the home line; the card quotes our favourite's, so the two
    # numbers read side by side ("Packers -3.9 · book -3.5").
    if book is not None and not pd.isna(book) and not home_wins:
        book = -book

    kick = game["date"].tz_convert(TZ)
    where = "neutral site" if game.get("neutral") else escape(str(game.get("place") or ""))
    tv = escape(str(game.get("tv") or "").split(",")[0])
    when = (f"<div class='pg-when'><span>{kick:%a %-d %b, %-I:%M %p} ET"
            + (f" &middot; {where}" if where else "") + "</span>"
            + (f"<span class='pg-tv'>{tv}</span>" if tv else "") + "</div>")

    home_score, away_score = _scores({"pred_home": (total + margin) / 2,
                                      "pred_away": (total - margin) / 2, "pred_margin": margin})
    if played:
        actual = game["home_score"] - game["away_score"]
        if rec is None:
            verdict = "<span class='pg-final push'>no call on record</span>"
        elif actual == 0:
            verdict = "<span class='pg-final push'>tie</span>"
        else:
            ok = (margin > 0) == (actual > 0)
            verdict = f"<span class='pg-final {'ok' if ok else 'no'}'>{'&#10003; right' if ok else '&#10007; wrong'}</span>"
        rows = (_side(game, "away", game["away_score"] > game["home_score"], away_score,
                      game["away_score"])
                + _side(game, "home", game["home_score"] > game["away_score"], home_score,
                        game["home_score"]))
        bar = ""
        line = (f"<div class='pg-line'><span>called <b>{escape(str(favourite))} "
                f"{-abs(margin):.1f}</b>{verdict}</span>"
                f"<span>final {int(game['home_score'] + game['away_score'])}, "
                f"O/U {total:.0f}</span></div>")
    else:
        rows = _side(game, "away", not home_wins, away_score) + _side(game, "home", home_wins, home_score)
        bar = f"<div class='pg-bar'><span style='width:{prob * 100:.0f}%'></span></div>"
        lean = ""
        if book is not None and not pd.isna(book):
            # Both in the favourite's terms now: our margin for him against
            # the book's. Positive means we like him more than the book does.
            diff = abs(margin) - (-book)
            if abs(diff) >= EDGE:
                other = game["away"] if home_wins else game["home"]
                side = favourite if diff > 0 else other
                lean = f" <span class='pg-lean'>lean {escape(str(side))}</span>"
        # The total gets the same treatment as the spread: where we are a field
        # goal or more off the book's number, say which side that is. Without it
        # the over/under record at the top of the page counts games the cards
        # never showed a call on.
        ou_lean = ""
        if book_total is not None and not pd.isna(book_total):
            ou_diff = total - book_total
            if abs(ou_diff) >= EDGE:
                ou_lean = (f" <span class='pg-lean'>lean "
                           f"{'over' if ou_diff > 0 else 'under'}</span>")
        line = (f"<div class='pg-line'><span><b>{escape(str(favourite))} {-abs(margin):.1f}</b>"
                + ("" if book is None or pd.isna(book) else f" &middot; book {_fmt_spread(book)}")
                + lean + "</span>"
                f"<span>O/U {total:.0f}"
                + ("" if book_total is None or pd.isna(book_total) else f" ({book_total:g})")
                + ou_lean + f" &middot; {prob:.0%}</span></div>")
    return f"<article class='pg'>{when}{rows}{bar}{line}</article>"


def _week_label(block: pd.DataFrame) -> str:
    st, wk = int(block["seasontype"].iloc[0]), int(block["week"].iloc[0])
    if st == 3:
        return {1: "Wild Card", 2: "Divisional", 3: "Conference", 5: "Super Bowl"}.get(wk, f"Playoffs {wk}")
    return f"Week {wk}"


def _week_key(block) -> str:
    return f"{int(block['week'].iloc[0]) + (18 if int(block['seasontype'].iloc[0]) == 3 else 0)}"


def _record_band(scored: pd.DataFrame) -> str:
    """The same four calls the college page leads with."""
    if scored.empty:
        return ("<p class='pred-note'>No finished game has a prediction on record yet; the "
                "record starts with the first kickoff after this page went up.</p>")
    return scorecard.band(results.summary(scored), break_even=BREAK_EVEN)


def _closeness(scored: pd.DataFrame) -> str:
    """How close the misses were, against the book on the same games. This is
    the averages half of the record - it used to sit in the band up top, where
    a points figure had to be read in the same glance as three percentages."""
    if scored.empty:
        return ""
    got = results.summary(scored)
    book = (f"{got['market_margin_mae']:.1f} pts" if got.get("market_margin_mae")
            else "&mdash;")
    tiles = [
        ("Our average miss", f"{got['margin_mae']:.1f} pts", f"the book: {book}"),
        ("On the total", f"{got['total_mae']:.1f} pts", "average miss on the points scored"),
    ]
    return ("<h2>How close it was</h2>"
            "<div class='pred-tiles pred-tiles-wide'>" + "".join(
                f"<div class='pred-tile'><div class='t-label'>{label}</div>"
                f"<div class='t-value'>{value}</div><div class='t-sub'>{sub}</div></div>"
                for label, value, sub in tiles) + "</div>")


def _ratings_table(model, names: dict, schedule: pd.DataFrame) -> str:
    table = model.table()
    table = table[table["team"].isin(names)]
    # Points for and against an average opponent on a neutral field, out of
    # the same two numbers the cards use.
    base = model.total_base / 2
    table["off"] = base + (table["pace"] + table["rating"]) / 2
    table["dfn"] = base + (table["pace"] - table["rating"]) / 2
    records = {}
    for side in ("home", "away"):
        for tid, rec in zip(schedule[f"{side}_id"], schedule[f"{side}_record"]):
            if rec:
                records[str(tid)] = rec
    span = max(abs(table["rating"].min()), abs(table["rating"].max()), 1e-9)
    rows = []
    for n, r in enumerate(table.itertuples(index=False), 1):
        name, abbr = names[r.team]
        width = abs(r.rating) / span * 50
        bar = (f"<span class='rt-bar'><i class='{'neg' if r.rating < 0 else ''}' style='"
               + (f"left:{50 - width:.0f}%;width:{width:.0f}%" if r.rating < 0
                  else f"left:50%;width:{width:.0f}%") + "'></i></span>")
        rows.append(f"<tr><td>{n}</td><td class='rt-name'>"
                    f"<img src='{LOGO.format(abbr=escape(abbr.lower()))}' alt=''>{escape(name)}"
                    f"</td><td>{escape(records.get(r.team, ''))}</td>"
                    f"<td>{r.rating:+.1f}{bar}</td><td>{r.off:.1f}</td><td>{r.dfn:.1f}</td></tr>")
    head = ("<tr><th>#</th><th>Team</th><th>Record</th>"
            "<th title='Points better than an average team on a neutral field'>Rating</th>"
            "<th title='Points scored against an average defence'>Off</th>"
            "<th title='Points allowed to an average offence'>Def</th></tr>")
    return (f"<div class='pred-scroll'><table class='cfb-pred'><thead>{head}</thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>")


def _method(model, valid: dict) -> str:
    overall = valid.get("overall") or {}
    hp = valid.get("hyperparameters") or {}
    return (
        "<h2>How it Works</h2>"
        "<p class='pred-note'>The same model as the <a href='/cfb/predictions/'>college "
        "page</a>: one strength number per team plus home field "
        f"(<b>{model.hfa:.1f}</b> points), fitted by ridge regression to every game since "
        f"2014, with older games fading on a {hp.get('half_life_days', 180):.0f}-day "
        "half-life. Margin and total are modelled separately; the scores and the win "
        "probability fall out of them.</p>"
        + (f"<p class='pred-note'><b>Before this page existed</b> it was scored "
           f"walk-forward on {overall.get('games', 0)} games: margin RMSE "
           f"<b>{overall.get('margin_rmse', 0):.2f}</b>, winners "
           f"<b>{overall.get('winner_accuracy', 0):.1%}</b>. The closing line runs about "
           "13.3 and 66-67% over the same years - there are no injuries, no weather and "
           "no quarterback news in this model, and the book has all three. Where the two "
           "differ by a field goal the card says <i>lean</i>.</p>"
           if overall else ""))


def body() -> str:
    frame, model, names = predict.season()
    record = {str(r["game_id"]): r for _, r in results.on_record(SEASON).iterrows()}
    scored = results.scored(SEASON)
    week, seasontype = predict.current_week(frame)
    valid = _validation()

    blocks = [(key, block) for key, block in frame.groupby(["seasontype", "week"], sort=True)]
    views, weeks, labels = {}, [], {}
    for (st, wk), block in blocks:
        key = _week_key(block)
        weeks.append(key)
        labels[key] = _week_label(block)
        views[key] = ("<div class='pred-grid'>"
                      + "".join(_card(g, record) for _, g in block.sort_values("date").iterrows())
                      + "</div>")
    current = _week_key(frame[(frame["week"] == week) & (frame["seasontype"] == seasontype)])
    switch = ui.week_switch(weeks, current, views)
    for key, label in labels.items():
        if not label.startswith("Week"):
            switch = switch.replace(f'id="wk-tab-{key}">{key}</button>',
                                    f'id="wk-tab-{key}">{escape(label)}</button>')
    return (
        _CSS + _EXTRA_CSS
        # The subtitle under the title already says what the page is; saying it
        # again in the first line of the body is the Top 25 card's old problem.
        + "<h2>Season scorecard</h2>" + _record_band(scored)
        + f"<h2>{escape(labels[current])}</h2>"
        + switch
        + "<h2>Ratings</h2>"
        "<p class='pred-note'>Points better than an average team on a neutral field; "
        "Off and Def are what the model expects a team to score and allow against an "
        "average opponent.</p>"
        + _ratings_table(model, names, frame)
        + _closeness(scored)
        + _method(model, valid))


def generate():
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    out = WEB_DIR / "index.html"
    out.write_text(add_front_matter(body(), f"NFL Predictions {SEASON}",
                                    "Every game, with the book's line beside ours"),
                   encoding="utf-8")
    print(f"Wrote NFL Predictions -> {out}")


if __name__ == "__main__":
    generate()
