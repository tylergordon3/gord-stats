"""
/pickem/: the reader pick'em contest - this week's slate with the reader's
picks and confidence points, the weekly and season leaderboards (with the
GordStats entry), and past weeks. The slate and its rules are
gordstats.pickem's; the picks, names and scores are functions/api/pickem.js's.
The browser half is docs/assets/js/gs-pickem.js.

The page is a shell over /api/pickem, but it carries the current week's slate
(as published this run) so the games draw before the API answers, and every
part holds its height from the first paint (the 2026-10-02 layout-shift
work): the slate's box is reserved at CARD pixels a game, the player bar and
the leaderboard are fixed or reserved, and the tabs hide what is not shown.
Confidence is a <select> per game listing the values, the ones on other open
games marked "swap" (choosing one trades the two), the ones on locked games
disabled - a thumb's control, no dragging.

Home carries a small static card (home_card), placed by
cbb.render.render_home after Tweets of the week, Sep 1 to Feb 15.

    python -m gordstats.pickem_page
"""
from __future__ import annotations

import json
from datetime import date
from html import escape

from gordstats import how, js_assets, paths
from gordstats.frontmatter import add_front_matter
from gordstats.jsonio import script_json

OUT = paths.DOCS / "pickem" / "index.html"
SEASON_FILE = paths.DOCS / "pickem" / "season.json"
URL = "/pickem/"
TITLE = "Pick'em"
# One game card and the gap under it, in pixels: .pk-g's height + margin in
# CSS below. The slate's box is reserved at this per game.
CARD = 148
EMPTY = 168

CONFIG = {
    "api": "/api/pickem",
    "card": CARD,
    "login": "/api/auth/login?next=%2Fpickem%2F",
}

CSS = """<style>
.pk{--pk-ink:#0f172a;--pk-text:#1e293b;--pk-line:#e2e8f0;--pk-card:#fff;--pk-act:#1f6fd0;
  --pk-act-ink:#fff;--pk-on:#e8f0fe;--pk-chip:#f1f5f9;--pk-good:#15803d;--pk-bad:#b91c1c;
  --pk-gs:#7c3aed;max-width:680px;margin:0 auto}
.pk .pk-intro{margin:0 0 10px;font-size:14.5px;line-height:1.45;color:var(--pk-text)}
.pk-week{display:flex;align-items:center;gap:8px;height:52px}
.pk-week button{flex:0 0 44px;height:44px;border-radius:999px;border:1px solid var(--pk-line);
  background:transparent;color:var(--pk-ink);font-size:22px;line-height:1;cursor:pointer}
.pk-week button:disabled{opacity:.35;cursor:default}
.pk-wk{flex:1 1 auto;min-width:0;text-align:center;line-height:1.25}
.pk-wk b{display:block;font-size:17px;color:var(--pk-ink)}
.pk-wk span{display:block;font-size:12.5px;color:var(--gs-muted,#5d6b7e);white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis}
.pk-tabs{display:flex;gap:4px;margin:6px 0 10px;border-bottom:1px solid var(--pk-line)}
.pk-tabs button{flex:1 1 0;min-width:0;height:44px;border:0;border-bottom:3px solid transparent;
  background:transparent;color:var(--gs-muted,#5d6b7e);font:inherit;font-size:14.5px;
  font-weight:700;cursor:pointer;white-space:nowrap}
.pk-tabs button[aria-selected=true]{color:var(--pk-ink);border-bottom-color:var(--pk-act)}
/* The player bar is one height in every state: signed out, choosing a name,
   playing - so nothing under it moves when the account answers. */
.pk-player{box-sizing:border-box;height:112px;overflow:hidden;display:flex;flex-direction:column;
  justify-content:center;gap:6px;padding:8px 12px;margin:0 0 10px;border:1px solid var(--pk-line);
  border-radius:12px;background:var(--pk-chip);color:var(--pk-text);font-size:14px;line-height:1.35}
.pk-player p{margin:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pk-player .pk-row{display:flex;align-items:center;gap:8px;min-height:40px}
.pk-player .pk-who{min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pk-player .pk-msg{min-height:18px;font-size:13px;color:var(--gs-muted,#5d6b7e)}
.pk-player .pk-msg.err{color:var(--pk-bad)}
.pk-player .pk-msg.ok{color:var(--pk-good)}
.pk-btn{box-sizing:border-box;display:inline-flex;align-items:center;justify-content:center;
  min-height:40px;padding:0 16px;border-radius:999px;border:1px solid var(--pk-act);
  background:var(--pk-act);color:var(--pk-act-ink);font:inherit;font-size:14px;font-weight:800;
  text-decoration:none;cursor:pointer;white-space:nowrap}
.pk-btn.ghost{background:transparent;color:var(--pk-act)}
.pk-link{border:0;background:none;padding:0 4px;min-height:40px;color:var(--pk-act);font:inherit;
  font-weight:700;cursor:pointer}
/* The theme gives every form a gray box and 20px of padding. */
.pk .pk-form{display:flex;gap:8px;margin:0;padding:0;background:none;min-width:0}
/* 16px: iOS zooms into a smaller field it focuses. */
.pk .pk-form input{flex:1 1 auto;min-width:0;box-sizing:border-box;height:40px;font:inherit;
  font-size:16px;padding:0 10px;border:1px solid #cbd5e1;border-radius:8px;
  background:var(--pk-card);color:var(--pk-ink)}
.pk-games{position:relative}
.pk-g{box-sizing:border-box;height:140px;margin:0 0 8px;padding:8px 10px;display:flex;
  flex-direction:column;gap:6px;border:1px solid var(--pk-line);border-radius:12px;
  background:var(--pk-card)}
.pk-g.ghost{background:var(--pk-chip);border-color:transparent}
.pk-meta{display:flex;align-items:center;gap:6px;height:20px;font-size:12.5px;
  color:var(--gs-muted,#5d6b7e);white-space:nowrap;overflow:hidden}
.pk-meta .pk-when{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis}
.pk-sp{flex:0 0 auto;font-size:11px;font-weight:800;line-height:18px;padding:0 6px;
  border-radius:999px;background:var(--pk-chip);color:var(--pk-text)}
.pk-sp.cfb{background:#fff1e6;color:#9a3412}
.pk-sp.nfl{background:#e8f0fe;color:#1e40af}
.pk-st{flex:0 0 auto;font-weight:800;color:var(--pk-text)}
.pk-st.live{color:var(--pk-bad)}
.pk-teams{display:flex;gap:8px;height:52px}
.pk-team{flex:1 1 0;min-width:0;display:flex;align-items:center;gap:8px;box-sizing:border-box;
  height:52px;padding:0 8px;border:2px solid var(--pk-line);border-radius:10px;
  background:transparent;color:var(--pk-ink);font:inherit;text-align:left;cursor:pointer}
.pk-team img{flex:0 0 28px;width:28px;height:28px}
.pk-team .pk-tn{flex:1 1 auto;min-width:0;font-size:14px;font-weight:700;line-height:1.2;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pk-team .pk-tn small{display:block;font-size:11.5px;font-weight:600;color:var(--gs-muted,#5d6b7e)}
.pk-team .pk-sc{flex:0 0 auto;font-size:16px;font-weight:800}
.pk-team.on{border-color:var(--pk-act);background:var(--pk-on)}
.pk-team.won .pk-sc{color:var(--pk-good)}
.pk-team[aria-disabled=true]{cursor:default}
.pk-ctl{display:flex;align-items:center;gap:8px;height:40px;font-size:13px}
.pk-ctl select{flex:0 0 auto;box-sizing:border-box;height:40px;min-width:104px;max-width:150px;
  font:inherit;font-size:16px;padding:0 6px;border:1px solid #cbd5e1;border-radius:8px;
  background:var(--pk-card);color:var(--pk-ink)}
.pk-ctl select:disabled{opacity:.7}
.pk-mark{flex:0 0 auto;font-weight:800}
.pk-mark.good{color:var(--pk-good)}
.pk-mark.bad{color:var(--pk-bad)}
.pk-model{flex:1 1 auto;min-width:0;text-align:right;color:var(--gs-muted,#5d6b7e);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pk-model b{color:var(--pk-gs)}
.pk-empty{box-sizing:border-box;height:160px;display:flex;align-items:center;justify-content:center;
  text-align:center;padding:16px;border:1px dashed #cbd5e1;border-radius:12px;color:var(--pk-text)}
.pk-which{display:flex;gap:6px;margin:0 0 8px}
.pk-which button{min-height:40px;padding:0 14px;border-radius:999px;border:1px solid var(--pk-line);
  background:transparent;color:var(--pk-ink);font:inherit;font-size:13.5px;font-weight:700;
  cursor:pointer}
.pk-which button[aria-pressed=true]{background:var(--pk-act);border-color:var(--pk-act);
  color:var(--pk-act-ink)}
.pk-board{min-height:440px}
.pk .pk-tbl{width:100%;border-collapse:collapse;font-size:14px}
.pk .pk-tbl th,.pk .pk-tbl td{border:0;border-bottom:1px solid var(--pk-line);padding:0 6px;
  height:40px;text-align:right;white-space:nowrap}
.pk .pk-tbl th{font-size:12px;color:var(--gs-muted,#5d6b7e);height:34px}
.pk .pk-tbl .nm{text-align:left;width:100%;max-width:0;overflow:hidden;text-overflow:ellipsis}
.pk .pk-tbl tr.gs .nm{color:var(--pk-gs);font-weight:800}
.pk .pk-tbl tr.me td{background:var(--pk-on);font-weight:800}
.pk-badge{font-size:11px;font-weight:800;padding:0 6px;margin-left:6px;border-radius:999px;
  background:var(--pk-chip);color:var(--pk-gs)}
.pk-past{list-style:none;margin:0;padding:0}
.pk-past li{margin:0 0 8px}
.pk-past button{box-sizing:border-box;width:100%;min-height:64px;padding:8px 12px;text-align:left;
  border:1px solid var(--pk-line);border-radius:12px;background:var(--pk-card);color:var(--pk-text);
  font:inherit;font-size:13.5px;line-height:1.4;cursor:pointer}
.pk-past b{color:var(--pk-ink);font-size:14.5px}
@media (prefers-color-scheme: dark){
  .pk{--pk-ink:#f1f5f9;--pk-text:#dde5ef;--pk-line:#2b3852;--pk-card:#16203a;--pk-act:#7cb4ff;
    --pk-act-ink:#0b1220;--pk-on:#1d3157;--pk-chip:#1d2840;--pk-good:#6ee7b7;--pk-bad:#ff9b91;
    --pk-gs:#c4b5fd}
  .pk-sp.cfb{background:#3b2410;color:#fdba74}
  .pk-sp.nfl{background:#172554;color:#93c5fd}
  .pk .pk-form input,.pk-ctl select{border-color:#3b4a66}
  .pk-empty{border-color:#3b4a66}
}
</style>"""


def _weeks(index: dict | None) -> list:
    """The week list the page starts with (the API's adds winners and scores)."""
    return [{"w": w["w"], "label": w["label"], "sub": w.get("sub", ""), "n": w.get("n", 0),
             "done": bool(w.get("done"))} for w in (index or {}).get("weeks", [])]


def body(index: dict | None, slate: dict | None) -> str:
    """The page: the current week's slate drawn from `slate`, the rest from
    the API once it answers."""
    games = len((slate or {}).get("games") or [])
    reserve = games * CARD if games else EMPTY
    week = (slate or {}).get("label") or "Pick'em"
    sub = (slate or {}).get("sub") or ("The first slate opens with the NFL season."
                                      if not slate else "")
    seed = {"season": (index or {}).get("season"), "current": (index or {}).get("current"),
            "week": (slate or {}).get("week"), "weeks": _weeks(index), "slate": slate}
    return (
        CSS
        + '<div class="pk" id="pk">'
        + '<p class="pk-intro">Pick the winner of every NFL game and the week\'s ten biggest '
          'college games, rank them by how sure you are, and try to beat the GordStats model. '
        + how.button("pickem") + "</p>"
        + '<div class="pk-week"><button type="button" class="pk-prev" aria-label="Previous week" '
          'disabled>&lsaquo;</button><div class="pk-wk" aria-live="polite">'
          f'<b class="pk-wk-t">{escape(week)}</b><span class="pk-wk-s">{escape(sub)}</span></div>'
          '<button type="button" class="pk-next" aria-label="Next week" disabled>&rsaquo;</button>'
          "</div>"
        + '<div class="pk-tabs" role="tablist" aria-label="Pick\'em">'
          '<button type="button" role="tab" id="pk-t-picks" aria-controls="pk-p-picks" '
          'aria-selected="true">Picks</button>'
          '<button type="button" role="tab" id="pk-t-board" aria-controls="pk-p-board" '
          'aria-selected="false" tabindex="-1">Leaderboard</button>'
          '<button type="button" role="tab" id="pk-t-past" aria-controls="pk-p-past" '
          'aria-selected="false" tabindex="-1">Past weeks</button></div>'
        + '<section id="pk-p-picks" role="tabpanel" aria-labelledby="pk-t-picks">'
          '<div class="pk-player" aria-live="polite"><p>Sign in to make your picks.</p>'
          '<div class="pk-row"><a class="pk-btn" href="' + escape(CONFIG["login"]) + '">Sign in '
          'to play</a></div><p class="pk-msg"></p></div>'
          f'<div class="pk-games" aria-busy="true" style="min-height:{reserve}px"></div>'
          "</section>"
        + '<section id="pk-p-board" role="tabpanel" aria-labelledby="pk-t-board" hidden>'
          '<div class="pk-which" role="group" aria-label="Which leaderboard">'
          '<button type="button" data-b="week" aria-pressed="true">This week</button>'
          '<button type="button" data-b="season" aria-pressed="false">Season</button></div>'
          '<div class="pk-board" aria-busy="true"></div></section>'
        + '<section id="pk-p-past" role="tabpanel" aria-labelledby="pk-t-past" hidden>'
          '<ol class="pk-past" aria-busy="true"></ol></section>'
        + "</div>"
        + f'<script type="application/json" id="pk-data">{script_json(seed)}</script>'
        + js_assets.tag("gs-pickem.js", {"pickem": CONFIG})
        + how.JS_TAG)


def home_card(today: date | None = None) -> str:
    """Home's small Pick'em card, during the NFL season (Sep 1 - Feb 15).
    Static: nothing loads, so nothing moves."""
    today = today or date.today()
    if not (today >= date(today.year, 9, 1) or today <= date(today.year, 2, 15)):
        return ""
    return ("<section class='home-card pk-home'><div class='home-card-head'><h2>Pick'em</h2>"
            f"<a class='home-card-link' href='{URL}'>Make your picks &rarr;</a></div>"
            "<p>Pick this week's NFL games and the ten biggest college games, rank them by "
            "confidence, and see if you can beat the GordStats model.</p></section>")


def _published() -> tuple[dict | None, dict | None]:
    """The season file and the current week's slate as published this run."""
    try:
        index = json.loads(SEASON_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None
    cur = index.get("current")
    if not cur:
        return index, None
    path = SEASON_FILE.parent / str(index["season"]) / f"week_{int(cur):02d}.json"
    try:
        return index, json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return index, None


def generate() -> None:
    """Write /pickem/ from the files gordstats.pickem published this run."""
    index, slate = _published()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(add_front_matter(
        body(index, slate), TITLE,
        "Pick the winners, rank them by confidence, beat the model", updated=False,
        description="A free weekly college football and NFL pick'em: pick every winner, rank "
                    "your picks by confidence and see if you can beat the GordStats model."),
        encoding="utf-8")
    print(f"Wrote pick'em -> {OUT}")


if __name__ == "__main__":
    generate()
