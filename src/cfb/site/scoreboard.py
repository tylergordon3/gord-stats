"""
The live CFB scoreboard (docs/cfb/scoreboard/).

One card per game of the current week, in three sections - Live, Upcoming,
Final - grouped by day. A card carries everything known about the matchup:
logos, AP ranks, records, model ratings, and a labelled lines block - the
GordStats line (spread, projected total, win probability) over the book's
official line, named for the book that posted it. Upcoming cards show the
projected score where the score will go; live and final cards show the real
score with the projection kept in the lines block for the comparison.

Filters: a conference dropdown (either team counts) and a ranked-only
toggle, both client-side. #conf=SEC in the URL preselects a conference.

Server-side this is a snapshot - rebuilt daily and by the Pi's live tick
(cfb.live) while games are on. The page then keeps itself current: a script
polls ESPN's scoreboard through our Pages Function proxy
(functions/api/cfb-scores.js - ESPN strips CORS for browsers) every ~30s
during games, updating scores, clock, possession, down & distance and last
play, and moving cards between sections as games kick off and finish. No JS
still gets the build-time snapshot.

    python -m cfb.site.scoreboard       # rebuild the page
"""
import json
from datetime import datetime, timezone
from html import escape
from zoneinfo import ZoneInfo

import pandas as pd

from cfb import espn, predict
from cfb import odds as odds_mod
from cfb.config import DATA_DIR, SEASON, WEB_DIR
from cfb.site import write_page
from cfb.site.schedule import _current_week
from cfb.site.teams import LOGO, team_slug

ET = ZoneInfo("America/New_York")

_CSS = """<style>
.sb-note{color:#475569;font-size:14px;line-height:1.55}
.sb-controls{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:10px 0 4px}
.sb-select{font-size:13.5px;padding:6px 10px;border:1px solid #cbd5e1;border-radius:8px;
  background:#fff;color:#0f172a}
.sb-sec{margin:24px 0 2px;font-size:13px;text-transform:uppercase;
  letter-spacing:.06em;color:#64748b}
.sb-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));
  gap:14px;margin:10px 0 8px}
.sb-day{grid-column:1/-1;font-size:14px;font-weight:700;color:#334155;
  margin:6px 0 -4px}
.sb-card{background:#fff;border:1px solid #e2e8f0;border-radius:12px;
  padding:12px 14px 11px;box-shadow:0 1px 2px rgba(15,23,42,.05)}
.sb-hide{display:none}
.sb-top{font-size:12px;color:#64748b;display:flex;justify-content:space-between;
  gap:10px;margin-bottom:9px;white-space:nowrap;overflow:hidden}
.sb-top .sb-tv{color:#0f172a;font-weight:600}
.sb-card[data-state="in"] .sb-status{color:#0a7d33;font-weight:700}
.sb-row{display:flex;align-items:center;gap:9px;padding:4px 0}
.sb-row img{width:26px;height:26px;object-fit:contain;flex:none;
  border:none;padding:0;box-shadow:none;background:none;border-radius:0;margin:0}
.sb-name{flex:1;color:#475569;font-size:15px;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.sb-name a{color:inherit;text-decoration:none}
.sb-name a:hover{text-decoration:underline}
.sb-rank{color:#64748b;font-size:11.5px;font-weight:700;margin-right:3px}
.sb-rec{color:#94a3b8;font-size:11.5px;font-variant-numeric:tabular-nums}
.sb-rating{color:#94a3b8;font-size:11.5px;font-variant-numeric:tabular-nums;
  min-width:38px;text-align:right}
.sb-pts{font-size:19px;font-weight:700;color:#0f172a;min-width:32px;text-align:right;
  font-variant-numeric:tabular-nums}
.sb-pts.sb-proj{color:#94a3b8;font-weight:600;font-style:italic}
.sb-row.sb-win .sb-name{font-weight:700;color:#0f172a}
.sb-row.sb-ball .sb-name::after{content:" \\1F3C8";font-size:11px}
.sb-live{display:none;border-top:1px dashed #e2e8f0;margin-top:7px;padding-top:7px}
.sb-card[data-state="in"] .sb-live{display:block}
.sb-sit{font-size:12.5px;font-weight:600;color:#0f172a}
.sb-play{font-size:12px;color:#64748b;margin-top:2px;overflow:hidden;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.sb-bar{height:6px;border-radius:3px;background:#eef2f7;overflow:hidden;margin:9px 0 4px}
.sb-bar span{display:block;height:100%;background:#3b82f6}
.sb-card:not([data-state="pre"]) .sb-bar{display:none}
/* The lines block: our numbers over the book's official line, labelled. */
.sb-lines{margin-top:7px;border-top:1px solid #eef2f7;padding-top:6px}
.sb-line{display:grid;grid-template-columns:76px 1fr 64px 76px;gap:6px;
  font-size:12.5px;color:#0f172a;font-variant-numeric:tabular-nums;
  align-items:baseline;padding:1px 0}
.sb-lab{font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;
  color:#94a3b8;font-weight:700}
.sb-sp{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sb-ou{color:#475569}
.sb-x{color:#475569;text-align:right;overflow:hidden;white-space:nowrap}
.sb-card[data-state="pre"] .sb-live-only{display:none}
.sb-card:not([data-state="pre"]) .sb-pre-only{display:none}
.sb-venue{font-size:11.5px;color:#94a3b8;margin-top:6px;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis}
@media (prefers-color-scheme: dark){
  .sb-note{color:#aab7c9}
  .sb-select{background:#16203a;border-color:#2b3852;color:#dde5ef}
  .sb-sec{color:#aab7c9}
  .sb-day{color:#dde5ef}
  .sb-card{background:#16203a;border-color:#2b3852;box-shadow:none}
  .sb-top{color:#8fa0b8}
  .sb-top .sb-tv{color:#dde5ef}
  .sb-card[data-state="in"] .sb-status{color:#4ade80}
  .sb-name{color:#c3cfdd}
  .sb-rank,.sb-sit{color:#dde5ef}
  .sb-rec,.sb-rating,.sb-pts.sb-proj,.sb-venue{color:#7f8ea3}
  .sb-pts{color:#f1f5f9}
  .sb-row.sb-win .sb-name{color:#ffffff}
  .sb-live,.sb-lines{border-color:#2b3852}
  .sb-play{color:#8fa0b8}
  .sb-bar{background:#223052}
  .sb-line{color:#f1f5f9}
  .sb-lab{color:#7f8ea3}
  .sb-ou,.sb-x{color:#aab7c9}
}
</style>"""


def _confs() -> dict:
    """ESPN team id -> conference short name, from the cached FPI pull.

    FPI covers exactly the FBS, which is exactly who the filter is for; FCS
    visitors map to nothing and their games ride on the FBS side's badge.
    The Sun Belt's East/West halves fold together - nobody filters by
    division - and ESPN's "FBS Indep." reads better as "Independent".
    """
    path = DATA_DIR / f"fpi_{SEASON}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out = {}
    for entry in data.get("teams", []):
        team = entry.get("team") or {}
        conf = (team.get("group") or {}).get("shortName")
        if not conf or team.get("id") is None:
            continue
        if conf.startswith("Sun Belt"):
            conf = "Sun Belt"
        elif conf == "FBS Indep.":
            conf = "Independent"
        out[str(team["id"])] = conf
    return out


def _records(week: int) -> dict:
    """Event id -> {'home': '2-0', 'away': '1-1'} from the live feed."""
    try:
        data = espn._get({"groups": espn._FBS, "week": week, "dates": SEASON,
                          "seasontype": 2, "limit": 500})
    except Exception:
        return {}
    out = {}
    for event in data.get("events", []):
        comps = event.get("competitions") or [{}]
        sides = {}
        for c in comps[0].get("competitors", []):
            recs = c.get("records") or []
            total = next((r.get("summary") for r in recs
                          if r.get("type") == "total"), None)
            if total:
                sides[c.get("homeAway")] = total
        if sides:
            out[str(event.get("id"))] = sides
    return out


def _fav_line(spread, home: str, away: str) -> str:
    """A home-convention spread as text: 'Ohio State -3.5', 'PK', or em-dash."""
    if spread is None or pd.isna(spread):
        return "&mdash;"
    if abs(spread) < 0.25:
        return "PK"
    fav = home if spread < 0 else away
    return f"{escape(fav)} {-abs(spread):.1f}"


def _row(g, side: str, records: dict) -> str:
    name = str(getattr(g, side))
    tid = escape(str(getattr(g, f"{side}_id")))
    rank = getattr(g, f"{side}_rank")
    badge = "" if pd.isna(rank) else f'<span class="sb-rank">#{int(rank)}</span>'
    rec = records.get(str(g.game_id), {}).get(side, "")
    rec_tag = f'<span class="sb-rec">{escape(rec)}</span>' if rec else ""
    rating = getattr(g, f"{side}_rating")
    rating_txt = "" if pd.isna(rating) else f"{rating:+.1f}"
    slug = team_slug(name)
    a, a_close = ((f'<a href="/cfb/teams/{slug}/">', "</a>")
                  if (WEB_DIR / "teams" / slug / "index.html").exists() else ("", ""))

    score = getattr(g, f"{side}_score")
    other = getattr(g, "home_score" if side == "away" else "away_score")
    pred = getattr(g, f"pred_{side}")
    if g.state in ("in", "post") and not pd.isna(score):
        pts, proj = f"{score:.0f}", ""
        won = g.state == "post" and score > other
    else:
        pts, proj = ("" if pd.isna(pred) else f"{pred:.0f}"), " sb-proj"
        won = False
    return (f'<div class="sb-row{" sb-win" if won else ""}" data-tid="{tid}">'
            f'{a}<img src="{LOGO.format(team_id=tid)}" alt="" loading="lazy">{a_close}'
            f'<span class="sb-name">{badge}{a}{escape(name)}{a_close} {rec_tag}</span>'
            f'<span class="sb-rating" title="GordStats rating">{rating_txt}</span>'
            f'<span class="sb-pts{proj}">{pts}</span></div>')


def _lines(g) -> str:
    """The labelled lines block: GordStats over the book's official line."""
    ours = _fav_line(g.gs_spread, g.home, g.away)
    our_ou = "&mdash;" if pd.isna(g.pred_total) else f"O/U {g.pred_total:.0f}"
    prob = g.home_win_prob if not pd.isna(g.home_win_prob) else None
    fav_prob = "" if prob is None else f"{max(prob, 1 - prob):.0%}"
    proj = ("" if pd.isna(g.pred_away)
            else f"proj {g.pred_away:.0f}&ndash;{g.pred_home:.0f}")

    book_name = str(g.book) if isinstance(g.book, str) and g.book else "Book"
    book_sp = _fav_line(g.book_spread, g.home, g.away)
    book_ou = "&mdash;" if pd.isna(g.book_total) else f"O/U {g.book_total:g}"

    return (
        '<div class="sb-lines">'
        '<div class="sb-line"><span class="sb-lab">GordStats</span>'
        f'<span class="sb-sp">{ours}</span><span class="sb-ou">{our_ou}</span>'
        f'<span class="sb-x"><span class="sb-pre-only">{fav_prob}</span>'
        f'<span class="sb-live-only">{proj}</span></span></div>'
        f'<div class="sb-line"><span class="sb-lab">{escape(book_name)}</span>'
        f'<span class="sb-sp">{book_sp}</span><span class="sb-ou">{book_ou}</span>'
        '<span class="sb-x"></span></div>'
        "</div>")


def _card(g, records: dict, confs: dict) -> str:
    kick = g.local
    if g.state == "post":
        status = g.detail if "Final" in (g.detail or "") else "Final"
    elif g.state == "in":
        status = g.detail or "Live"
    else:
        status = f"{kick:%a %-I:%M %p} ET"
    tv = escape(str(g.tv or "").split(",")[0])

    prob = g.home_win_prob if not pd.isna(g.home_win_prob) else None
    bar = ("" if prob is None else
           f'<div class="sb-bar"><span style="width:{prob * 100:.0f}%"></span></div>')

    venue = escape(str(g.venue or "")) + (f" &mdash; {escape(str(g.place))}" if g.place else "")
    ranked = not (pd.isna(g.home_rank) and pd.isna(g.away_rank))
    conf = "|".join(sorted({c for c in (confs.get(str(g.away_id)),
                                        confs.get(str(g.home_id))) if c}))
    return (f'<article class="sb-card{"" if ranked else " sb-unranked"}" '
            f'id="sb-{escape(str(g.game_id))}" data-state="{g.state}" '
            f'data-kick="{escape(str(g.date_utc))}" data-conf="{escape(conf)}">'
            f'<div class="sb-top"><span class="sb-status">{status}</span>'
            + (f'<span class="sb-tv">{tv}</span>' if tv else "") + "</div>"
            + _row(g, "away", records) + _row(g, "home", records)
            + '<div class="sb-live"><div class="sb-sit"></div>'
              '<div class="sb-play"></div></div>'
            + bar + _lines(g)
            + f'<div class="sb-venue">{venue}</div></article>')


def _grid(games: pd.DataFrame, records: dict, confs: dict,
          dividers: bool) -> str:
    """Cards in kickoff order, with a full-width day header where the
    (Eastern) day turns over. Headers carry data-kick so cards the page
    moves later still slot in kickoff order around them."""
    out, last_day = [], None
    for g in games.itertuples():
        if dividers and g.local.date() != last_day:
            last_day = g.local.date()
            out.append(f'<div class="sb-day" data-kick="{escape(str(g.date_utc))}">'
                       f"{g.local:%A, %B %-d}</div>")
        out.append(_card(g, records, confs))
    return "".join(out)


def _js(week: int) -> str:
    url = f"/api/cfb-scores?week={week}&dates={SEASON}"
    return """<script>
(function () {
  "use strict";
  var URL = %s;
  var timer = null;
  var board = document.getElementById("sb-board");
  var confSel = document.getElementById("sb-conf");
  var rankedBtn = document.getElementById("sb-ranked");
  var rankedOn = false;

  function visible(card) {
    if (rankedOn && card.classList.contains("sb-unranked")) return false;
    var conf = confSel.value;
    if (conf &&
        (card.getAttribute("data-conf") || "").split("|").indexOf(conf) < 0) {
      return false;
    }
    return true;
  }

  /* Re-decide every card, then hide day headers whose group emptied and
     sections with nothing left to show. */
  function applyFilters() {
    board.querySelectorAll(".sb-card").forEach(function (c) {
      c.classList.toggle("sb-hide", !visible(c));
    });
    ["in", "pre", "post"].forEach(function (s) {
      var grid = document.getElementById("sb-grid-" + s);
      var any = false, day = null, dayHas = false;
      Array.prototype.forEach.call(grid.children, function (el) {
        if (el.classList.contains("sb-day")) {
          if (day) day.classList.toggle("sb-hide", !dayHas);
          day = el; dayHas = false;
        } else if (!el.classList.contains("sb-hide")) {
          dayHas = true; any = true;
        }
      });
      if (day) day.classList.toggle("sb-hide", !dayHas);
      document.getElementById("sb-sec-" + s).style.display = any ? "" : "none";
    });
  }

  function move(card, state) {
    var grid = document.getElementById("sb-grid-" + state);
    var kick = card.getAttribute("data-kick"), before = null;
    Array.prototype.forEach.call(grid.children, function (el) {
      if (!before && el.getAttribute("data-kick") > kick) before = el;
    });
    grid.insertBefore(card, before);
  }

  function apply(ev) {
    var card = document.getElementById("sb-" + ev.id);
    if (!card) return null;
    var comp = (ev.competitions || [])[0] || {};
    var st = ev.status || comp.status || {};
    var state = (st.type || {}).state || "pre";
    var sit = comp.situation || {};

    (comp.competitors || []).forEach(function (c) {
      var row = card.querySelector('.sb-row[data-tid="' + c.team.id + '"]');
      if (!row) return;
      if (state !== "pre") {
        var pts = row.querySelector(".sb-pts");
        pts.textContent = c.score;
        pts.classList.remove("sb-proj");
      }
      var recs = c.records || [];
      for (var i = 0; i < recs.length; i++) {
        if (recs[i].type === "total" && recs[i].summary) {
          var el = row.querySelector(".sb-rec");
          if (el) el.textContent = recs[i].summary;
          break;
        }
      }
      row.classList.toggle("sb-ball",
        state === "in" && sit.possession === c.team.id);
    });

    if (state !== "pre") {
      card.querySelector(".sb-status").textContent =
        (st.type || {}).shortDetail || (state === "post" ? "Final" : "Live");
    }
    if (state === "post") {
      var cs = comp.competitors || [];
      if (cs.length === 2 && +cs[0].score !== +cs[1].score) {
        var w = +cs[0].score > +cs[1].score ? cs[0] : cs[1];
        var wr = card.querySelector('.sb-row[data-tid="' + w.team.id + '"]');
        if (wr) wr.classList.add("sb-win");
      }
    }
    if (state === "in") {
      card.querySelector(".sb-sit").textContent =
        [sit.downDistanceText, sit.possessionText]
          .filter(Boolean).join(" \\u00b7 ");
      card.querySelector(".sb-play").textContent = (sit.lastPlay || {}).text || "";
    }
    if (card.getAttribute("data-state") !== state) {
      card.setAttribute("data-state", state);
      move(card, state);
    }
    return { state: state, kick: ev.date };
  }

  function poll() {
    fetch(URL).then(function (r) { return r.json(); }).then(function (data) {
      var live = false, next = null, now = Date.now();
      (data.events || []).forEach(function (ev) {
        var r = apply(ev);
        if (!r) return;
        if (r.state === "in") live = true;
        else if (r.state === "pre") {
          var t = new Date(r.kick).getTime();
          if (t > now && (next === null || t < next)) next = t;
        }
      });
      applyFilters();
      // 30s while anything is live; 90s in the half hour before a kickoff;
      // otherwise sleep until just before the next one (checking at most
      // every 30 min in case the slate changes). Nothing left: stop.
      var delay;
      if (live) delay = 30e3;
      else if (next !== null && next - now < 45 * 60e3) delay = 90e3;
      else if (next !== null) delay = Math.min(next - now - 40 * 60e3, 30 * 60e3);
      else return;
      timer = setTimeout(poll, Math.max(delay, 30e3));
    }).catch(function () { timer = setTimeout(poll, 120e3); });
  }

  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) { clearTimeout(timer); poll(); }
  });
  rankedBtn.addEventListener("click", function () {
    rankedOn = !rankedOn;
    rankedBtn.classList.toggle("active", rankedOn);
    applyFilters();
  });
  confSel.addEventListener("change", function () {
    history.replaceState(null, "",
      confSel.value ? "#conf=" + encodeURIComponent(confSel.value)
                    : location.pathname);
    applyFilters();
  });
  var m = /^#conf=(.+)$/.exec(decodeURIComponent(location.hash));
  if (m) {
    for (var i = 0; i < confSel.options.length; i++) {
      if (confSel.options[i].value === m[1]) { confSel.value = m[1]; break; }
    }
    applyFilters();
  }
  poll();
})();
</script>""" % json.dumps(url)


def _games(week: int) -> pd.DataFrame:
    sched = espn.schedule()
    games = sched[sched["week"] == week].copy()
    games["game_id"] = games["game_id"].astype(str)
    games["local"] = (pd.to_datetime(games["date_utc"], utc=True)
                      .dt.tz_convert(ET))

    preds = predict.week(number=week)
    if not preds.empty:
        preds = preds.rename(columns={"spread": "gs_spread"})
        preds["game_id"] = preds["game_id"].astype(str)
        cols = ["game_id", "pred_home", "pred_away", "pred_total",
                "home_win_prob", "gs_spread", "home_rating", "away_rating"]
        games = games.merge(preds[[c for c in cols if c in preds.columns]],
                            on="game_id", how="left")
    for col in ("pred_home", "pred_away", "pred_total", "home_win_prob",
                "gs_spread", "home_rating", "away_rating"):
        if col not in games.columns:
            games[col] = pd.NA

    board = odds_mod.latest(SEASON)
    if not board.empty:
        board = board.rename(columns={"spread": "book_spread", "total": "book_total"})
        games = games.merge(board[["home_id", "away_id", "book_spread",
                                   "book_total", "book"]],
                            on=["home_id", "away_id"], how="left")
    for col in ("book_spread", "book_total", "book"):
        if col not in games.columns:
            games[col] = pd.NA
    return games.sort_values("local")


# Power-conference names first in the dropdown; the rest alphabetical after.
_CONF_LEAD = ["ACC", "Big 12", "Big Ten", "SEC"]


def _conf_options(confs: dict) -> str:
    names = set(confs.values())
    ordered = ([c for c in _CONF_LEAD if c in names]
               + sorted(names - set(_CONF_LEAD)))
    return '<option value="">All conferences</option>' + "".join(
        f'<option value="{escape(c)}">{escape(c)}</option>' for c in ordered)


def body() -> str:
    week = _current_week(espn.schedule())
    games = _games(week)
    records = _records(week)
    confs = _confs()

    grids = {state: _grid(grp, records, confs, dividers=state != "in")
             for state, grp in games.groupby("state")}
    titles = {"in": "Live", "pre": "Upcoming", "post": "Final"}
    sections = "".join(
        f'<section id="sb-sec-{s}"'
        + ("" if grids.get(s) else ' style="display:none"')
        + f'><h2 class="sb-sec">{titles[s]}</h2>'
          f'<div class="sb-grid" id="sb-grid-{s}">{grids.get(s, "")}</div></section>'
        for s in ("in", "pre", "post"))

    built = datetime.now(ET).strftime("%b %-d, %-I:%M %p %Z")
    return (
        _CSS
        + f'<p class="sb-note">Week {week}, every FBS game. Each card shows the '
        '<a href="/cfb/predictions/">GordStats model</a>&rsquo;s line - spread, '
        "total and win probability - over the book&rsquo;s official line "
        "(the latest captured; the model has no edge on it). Live scores "
        f"update in place while games are on. Built {built}.</p>"
        '<div class="sb-controls">'
        f'<select id="sb-conf" class="sb-select">{_conf_options(confs)}</select>'
        '<button id="sb-ranked" class="adp-toggle">Ranked matchups only</button>'
        "</div>"
        f'<div id="sb-board">{sections}</div>'
        + _js(week)
    )


def generate():
    write_page(WEB_DIR / "scoreboard" / "index.html",
               f"CFB Scoreboard {SEASON}", body())


if __name__ == "__main__":
    generate()
