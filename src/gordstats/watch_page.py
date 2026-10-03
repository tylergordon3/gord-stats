"""
The watch guide, for any sport: the day cut into kickoff windows, each ranked
by a watch score, with the reader's own teams and fantasy players and the live
state of the games added in the browser.

A reader on a game day has one question the schedule answers only after some
sorting: what should be on right now, and what after it. This is the page for
it, shared by the three sports (the pattern of gordstats.matchup_page): each
sport's adapter builds the day's games in one shape and says how its live
scores are read, and everything else - the windows, the ranking, the cards,
the reader's part, the live queue - lives here once.

    cfb.site.watch      /cfb/watch/   ESPN matchup quality, Yahoo rosters, stars
    nfl.site.watch      /nfl/watch/   ESPN matchup quality, Sleeper rosters and
                                      the reader's opponent this week
    cbb.render.render_watch  /cbb/watch/  built in the browser from the live
                                      scoreboard feed, men's and women's

A game, as the adapters build it (JSON, short keys - a Saturday is 60 of them):

    id, day (ET date), slot, ko (kickoff, UTC), tk (time known), tv, note,
    n (neutral), state, hw (our home win chance), sp (book spread, home),
    score (the watch score), tags, fav ('h' / 'a' / None, the pregame favourite)
    h / a: id, nm, lg (logo URL), rk (rank), rec (record), sc (score),
           pr (our projected points), k (the key rosters use for the team)

Rosters, when the sport has a fantasy league here: {key: {n: team name,
p: [[player, pos, team key, starting]], opp: this week's opponent's key}}.

The watch score starts from ESPN's matchup quality (0-100: how good the teams
are and how close it should be) where the sport has one, nudged for the
things it misses; the reader's part (+100 for a starred team, up to +20 for
their fantasy players, +12 for their opponent's) and the live part (a close
game late, overtime, an underdog ahead in the second half) are added in the
browser, where they are known.
"""
import json
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

import pandas as pd

from gordstats import how, js_assets, share_button
from gordstats.jsonio import script_json

ET = ZoneInfo("America/New_York")
TBA = ("tba", "Time TBA")
TOSS_UP = 3.0             # a line this small is a coin flip (cfb.site.schedule's badge)
UPSET_WATCH = 0.35        # an underdog somebody gives this much is worth a look


# A kickoff before this Eastern hour belongs to the night before: Hawaii's
# 12:30 AM football and the Pacific's late tips are the end of a day, not the
# start of the next one's early window.
NIGHT_ENDS = 4


def slot(kick: pd.Timestamp, slots: list, time_known: bool = True) -> str:
    """The window a kickoff falls in: `slots` is [(key, label, starts before
    this Eastern hour)], the last one open-ended."""
    if not time_known:
        return TBA[0]
    t = pd.Timestamp(kick).tz_convert(ET)
    hour = t.hour + t.minute / 60
    if hour < NIGHT_ENDS:
        return slots[-1][0]
    return next(key for key, _label, before in slots if hour < before)


def game_day(kick: pd.Timestamp, time_known: bool = True) -> str:
    """The Eastern date a game is on the guide's day tabs, the small hours
    counted to the night before (NIGHT_ENDS) - only when the time is a real
    one. ESPN files a game with no kickoff time yet at midnight Eastern of its
    day, and rolled back, every untimed Saturday game sat on Friday's tab."""
    t = pd.Timestamp(kick).tz_convert(ET)
    if time_known and t.hour < NIGHT_ENDS:
        t -= pd.Timedelta(days=1)
    return t.strftime("%Y-%m-%d")


def slot_hours(slots: list) -> list:
    """[key, label, "2-6 ET"] for the windows, in order, TBA last."""
    def h(x):
        hh, mm = int(x), int(round((x % 1) * 60))
        return f"{(hh - 1) % 12 + 1}{':%02d' % mm if mm else ''}"
    out, start = [], None
    for key, label, before in slots:
        span = (f"before {h(before)} ET" if start is None else
                f"from {h(start)} ET" if before > 24 else f"{h(start)}-{h(before)} ET")
        out.append([key, label, span])
        start = before
    return out + [[TBA[0], TBA[1], ""]]


def judge(quality, spread, probs, margin=None, nudges=(), toss_up: float = TOSS_UP,
          span: float = 28.0) -> tuple:
    """(watch score, tags, pregame favourite 'h' / 'a' / None).

    `quality` is ESPN's matchup quality (0-100) or None; `spread` the book's
    home line (our `margin`, home points, stands in when there is none);
    `probs` the home win chances there are (ours, ESPN's). `nudges` are
    (tag, applies) pairs - a Top 25 matchup, playoff stakes - and each that
    applies is tagged and closes a quarter of the gap to 100, so the score
    stays on the 0-100 scale. With no quality the closeness of the game stands
    in, at half weight."""
    if spread is None and margin is not None:
        spread = -margin
    fav = None if spread is None or abs(spread) <= 0.25 else ("h" if spread < 0 else "a")
    probs = [p for p in probs if p is not None]
    dog = None
    if probs and fav:
        dog = max((p if fav == "a" else 1 - p) for p in probs)
    elif probs:
        dog = max(min(p, 1 - p) for p in probs)
    tags = [tag for tag, on in nudges if on and tag]
    if spread is not None and abs(spread) <= toss_up:
        tags.insert(1 if tags and tags[0] == "Top 25 matchup" else 0, "Toss-up")
    elif dog is not None and dog >= UPSET_WATCH:
        tags.insert(1 if tags and tags[0] == "Top 25 matchup" else 0, "Upset watch")
    if quality is None:
        quality = 50 * max(0.0, 1 - abs(spread) / span) if spread is not None else 20.0
    lifted = sum(1 for _tag, on in nudges if on)
    return round(quality + (100 - quality) * 0.25 * lifted, 1), tags, fav


def best_day(games: list, today: str) -> str:
    """The day the guide opens on: today if there are games today, otherwise
    the biggest day coming (on a Wednesday, Saturday rather than Thursday's
    two games). The browser makes the same choice (JS)."""
    days = {}
    for g in games:
        if g["day"] >= today:
            days[g["day"]] = days.get(g["day"], 0) + 1
    if not days:
        return ""
    return today if today in days else min(days, key=lambda d: (-days[d], d))


def teaser(games: list, now: datetime = None, n: int = 3) -> str:
    """The day's best few, for a section's home page: the guide's own ranking
    without the reader's part, which only the guide itself can add."""
    now = now or datetime.now(ET)
    today = now.astimezone(ET).strftime("%Y-%m-%d")
    day = best_day(games, today)
    todo = sorted((g for g in games if g["day"] == day and g["state"] != "post"),
                  key=lambda g: -g["score"])[:n]
    if not todo:
        return ""
    when = "Today" if day == today else datetime.strptime(day, "%Y-%m-%d").strftime("%A")

    def team(t):
        return (f"{'<span class=wt-rk>' + str(int(t['rk'])) + '</span> ' if t.get('rk') else ''}"
                f"{escape(t['nm'])}")
    rows = "".join(
        f"<li><span class='wt-g'>{team(g['a'])} <span class='wt-at'>{'vs' if g['n'] else 'at'}</span> "
        f"{team(g['h'])}</span><span class='wt-w'>"
        + (pd.Timestamp(g["ko"]).tz_convert(ET).strftime("%-I:%M %p ET") if g["tk"] else "TBA")
        + (f" &middot; {escape(g['tv'])}" if g["tv"] else "")
        + f" &middot; <b>Watch {min(100, round(g['score']))}</b></span></li>"
        for g in todo)
    return ("<style>.wt{list-style:none;margin:0;padding:0}.wt li{padding:8px 0;"
            "border-top:1px solid var(--gs-line,#e2e8f0);display:flex;flex-direction:column;gap:2px}"
            ".wt li:first-child{border-top:0}.wt-g{font-weight:700;font-size:15px}"
            ".wt-at{font-weight:500;color:var(--gs-muted,#5d6b7e);font-size:13px}"
            ".wt-rk{font-size:12px;color:var(--gs-muted,#5d6b7e)}"
            ".wt-w{font-size:13px;color:var(--gs-muted,#5d6b7e)}"
            "@media (prefers-color-scheme: dark){.wt li{border-color:#2b3852}}</style>"
            f"<p class='wt-day'><b>{when}</b>, best first:</p><ul class='wt'>{rows}</ul>")


def write_games(path, data: dict) -> None:
    """A guide's games as JSON beside its page, for the all-sports guide
    (gordstats.watch_all) to merge in the browser."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")


def body(data: dict, adapter_js: str, topic: str, share_url: str, share_text: str) -> str:
    """The page: the host the engine draws into, the "How this works" chip
    for `topic` (the gordstats.how explainer of how the sport's games are
    ranked: "watch-guide", "cbb-watch"), the Share button, the day's games as
    JSON (when the sport builds them here), then the engine and the sport's
    adapter, which starts it. The chip's line is .wg-how: an adapter with no
    games hides it with the Share row."""
    blob = ("" if data is None else
            "<script type='application/json' id='wg-data'>"
            + script_json(data, separators=(",", ":")) + "</script>")
    return (CSS + "<div class='wg'>"
            + "<div id='wg-host'><p class='wg-note'>Loading the day's games&hellip;</p></div>"
            + f"<div class='wg-how'>{how.section_note(topic)}</div>"
            + share_button.row(share_url, share_text) + "</div>"
            + blob + ENGINE_JS_TAG + adapter_js + how.JS_TAG)


CSS = """<style>
.wg{--wg-line:#e2e8f0;--wg-card:#fff;--wg-ink:#0f172a;--wg-mute:#475569;--wg-soft:#64748b;
  --wg-acc:#C2410C;--wg-live:#b3382c;--wg-live-bg:#fff5f4;--wg-chip:#eef2f7;--wg-me:#1d4ed8;
  --wg-on-acc:#fff}
/* --wg-on-acc: text on an accent fill. White on the dark theme's lighter
   orange was 2.26:1 (the day chip, the Watch pill, the Sound badge); near-black
   on it is 7.7:1 (2026-10-02). */
@media (prefers-color-scheme: dark){
  .wg{--wg-line:#2b3852;--wg-card:#16203a;--wg-ink:#f1f5f9;--wg-mute:#c3cfdd;--wg-soft:#aab7c9;
    --wg-acc:#fb923c;--wg-live:#ffb4ab;--wg-live-bg:#3a1f22;--wg-chip:#223052;--wg-me:#93c5fd;
    --wg-on-acc:#1c1917}
}
.wg-days{display:flex;gap:8px;overflow-x:auto;margin:4px 0 10px;padding-bottom:2px}
.wg-days button{flex:none;min-height:40px;padding:0 16px;border-radius:999px;font:inherit;
  font-weight:700;font-size:14px;border:1px solid var(--wg-line);background:var(--wg-card);
  color:var(--wg-ink);cursor:pointer}
.wg-days button[aria-pressed=true]{background:var(--wg-acc);border-color:var(--wg-acc);
  color:var(--wg-on-acc)}
.wg-bar{display:flex;flex-wrap:wrap;align-items:center;gap:6px 12px;margin:0 0 12px;
  font-size:13px;color:var(--wg-mute)}
.wg-bar select{min-height:40px;font:inherit;font-size:14px;border-radius:8px;
  border:1px solid var(--wg-line);background:var(--wg-card);color:var(--wg-ink);padding:0 8px;
  max-width:100%}
.wg h3{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--wg-soft);
  margin:18px 0 8px;display:flex;align-items:baseline;gap:8px}
.wg h3 .wg-n{font-weight:600;letter-spacing:0;text-transform:none}
.wg-list{display:grid;gap:8px}
a.wg-g{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:2px 12px;padding:10px 12px;
  border:1px solid var(--wg-line);border-radius:12px;background:var(--wg-card);color:inherit;
  text-decoration:none}
a.wg-g.top{border-left:4px solid var(--wg-acc);padding-left:10px}
a.wg-g.live{border-color:#fca5a5;background:var(--wg-live-bg)}
a.wg-g.done{opacity:.8}
.wg-t{display:flex;align-items:center;gap:8px;min-width:0;font-size:15.5px;font-weight:700;
  color:var(--wg-ink);line-height:1.5}
.wg-t img{width:24px;height:24px;flex:none;object-fit:contain;border:0;padding:0;margin:0;
  box-shadow:none;background:none}
.wg-t .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.wg-t .rk{font-size:11.5px;font-weight:700;color:var(--wg-soft)}
.wg-t .sc{margin-left:auto;font-variant-numeric:tabular-nums;font-size:16px}
.wg-t.lost{color:var(--wg-mute);font-weight:600}
.wg-t .rec{font-size:12px;font-weight:600;color:var(--wg-soft)}
.wg-when{grid-row:1 / span 2;grid-column:2;text-align:right;font-size:13px;font-weight:700;
  color:var(--wg-ink);white-space:nowrap;align-self:center;line-height:1.35}
.wg-when small{display:block;font-size:12px;font-weight:600;color:var(--wg-soft)}
.wg-when.live{color:var(--wg-live)}
.wg-sub{grid-column:1 / -1;font-size:12.5px;color:var(--wg-mute);line-height:1.45;margin-top:2px}
.wg-sub b{color:var(--wg-ink)}
.wg-tags{grid-column:1 / -1;display:flex;flex-wrap:wrap;gap:5px;margin-top:4px;align-items:center}
.wg-tags span{font-size:11.5px;font-weight:700;padding:2px 8px;border-radius:999px;
  background:var(--wg-chip);color:var(--wg-mute)}
.wg-tags .wg-sc{background:var(--wg-acc);color:var(--wg-on-acc)}
.wg-tags .hot{background:#fee2e2;color:#991b1b}
.wg-tags .mine{background:#dbeafe;color:#1e3a8a}
.wg-me{grid-column:1 / -1;font-size:12.5px;color:var(--wg-me);font-weight:600;margin-top:2px}
.wg-them{grid-column:1 / -1;font-size:12.5px;color:var(--wg-mute);font-weight:600}
.wg-more{margin-top:8px}
.wg-more summary{cursor:pointer;font-weight:700;font-size:14px;color:var(--wg-acc);
  min-height:40px;display:flex;align-items:center}
.wg-note{font-size:13px;color:var(--wg-mute);line-height:1.5;margin:0 0 8px}
.wg-note.wg-empty{font-size:17px;color:var(--wg-ink);margin:8px 0 16px}
/* The quadbox: four games for one screen, a window at a time. The frame is
   the screen, dark in both themes; the best game sits top left with the sound. */
.wg-view{display:inline-flex;border:1px solid var(--wg-line);border-radius:999px;overflow:hidden;
  flex:none}
.wg-view button{min-height:40px;padding:0 14px;border:0;background:var(--wg-card);
  color:var(--wg-mute);font:inherit;font-size:13px;font-weight:700;cursor:pointer}
.wg-view button[aria-pressed=true]{background:var(--wg-ink);color:var(--wg-card)}
.wg-quad{display:grid;grid-template-columns:1fr 1fr;gap:5px;padding:5px;border-radius:14px;
  background:#0b1220}
.wg-q{display:flex;flex-direction:column;gap:3px;min-height:104px;padding:8px 9px;
  border-radius:9px;background:var(--wg-card);color:inherit;text-decoration:none;min-width:0}
.wg-q.audio{box-shadow:inset 0 0 0 2px var(--wg-acc)}
.wg-q.live{background:var(--wg-live-bg)}
.wg-q .ch{display:flex;align-items:center;gap:6px;font-size:14px;font-weight:800;
  color:var(--wg-ink);letter-spacing:.02em;min-width:0}
.wg-q .ch b{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.wg-q .ch .sp{flex:none;font-size:12px;font-weight:800;letter-spacing:.02em;padding:1px 5px;
  border-radius:4px;background:var(--wg-chip);color:var(--wg-mute)}
.wg-q .aud,.wg-q .new{flex:none;font-size:12px;font-weight:800;padding:1px 6px;
  border-radius:999px;letter-spacing:0}
.wg-q .aud{background:var(--wg-acc);color:var(--wg-on-acc);margin-left:auto}
.wg-q .new{background:#dbeafe;color:#1e3a8a}
.wg-q .tm{display:flex;align-items:center;gap:5px;font-size:13.5px;font-weight:700;
  color:var(--wg-ink);min-width:0;line-height:1.35}
.wg-q .tm img{width:18px;height:18px;flex:none;object-fit:contain;border:0;padding:0;margin:0;
  box-shadow:none;background:none}
.wg-q .tm .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.wg-q .tm .rk{font-size:12px;color:var(--wg-soft)}
.wg-q .tm .sc{margin-left:auto;font-variant-numeric:tabular-nums}
.wg-q .st{margin-top:auto;font-size:12px;font-weight:600;color:var(--wg-soft);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.wg-q .st .hot{color:var(--wg-live)}
.wg-bench{font-size:12.5px;color:var(--wg-mute);margin:6px 2px 0;line-height:1.5}
.wg-bench b{color:var(--wg-ink)}
/* A 320px tile is ~124px inside: at 12px the sport badge and "Sound" left
   the channel one letter. The speaker and the tile's accent ring still say
   which one has the sound. */
@media (max-width:360px){
  .wg-q .aud-w{display:none}
}
@media (prefers-color-scheme: dark){
  .wg-t img{background:#e8edf5;border-radius:50%;padding:2px;box-sizing:border-box}
  a.wg-g.live{border-color:#7f1d1d}
  .wg-tags .hot{background:#7f1d1d;color:#fecaca}
  .wg-tags .mine{background:#1e3a8a;color:#dbeafe}
  .wg-quad{background:#000}
  .wg-q .tm img{background:#e8edf5;border-radius:50%;padding:1px;box-sizing:border-box}
  .wg-q .new{background:#1e3a8a;color:#dbeafe}
}
</style>"""


# The engine. A sport's adapter calls GSWatch(data, cfg) - cfg says what only
# the sport knows:
#
#   live(games, D)  -> Promise of {game id: {state, detail, period, home, away,
#                      late, ot, second}} for the games on now (the phase flags
#                      optional: football reads them off the quarter, the
#                      adapter sets them where it cannot)
#   stars()         -> {team key: 1} for the reader's starred teams
#   myKey           the localStorage key of the reader's fantasy team
#   link            where a card goes; a game's own `href` wins
#   hint            a line for a reader with no stars and no team picked
#   close           a margin that counts as close late (football 8, basketball 6)
#   blowout         a second-half margin that drops a game down the order (21)
#   every           milliseconds between live polls (default a minute)
#   quadShared      true where every game can be on at once (NFL Sunday Ticket),
#                   or function(game) deciding it game by game; otherwise a
#                   quadbox never puts two games on one broadcast channel
#   team()          the reader's roster key, in place of the myKey picker - the
#                   all-sports guide (gordstats.watch_all) merges two leagues
#   blowout and close may be a function(game) too, where sports mix
#   quadNote        a line under the quadbox switch
#
# cfg is read each time the guide draws, so an adapter may change its hint or
# empty line between draws (CBB does, per league). It returns {set(D),
# update(D), redraw()}: set swaps in another set of games, update refreshes
# the same ones keeping the reader's day.
# The code is docs/assets/js/gs-watch.js (gordstats.js_assets): ENGINE_JS is it inline,
# for the browser tests; ENGINE_JS_TAG is what the pages carry.
# The night (NIGHT_ENDS) reaches it through GSCFG.
_CFG = {"nightEnds": NIGHT_ENDS}
ENGINE_JS = js_assets.inline("gs-watch.js", _CFG, raw=False)
ENGINE_JS_TAG = js_assets.tag("gs-watch.js", _CFG)
