"""
The chance a player plays, where a reader sets a lineup: the NFL matchups
page (GS column, the blend, the pills) and the team dashboard (the planner's
projection, the pills, the late-swap warning).

A listed player's week is his projection if he plays times the chance he
does - discounted once: every source prices him as if he plays, so the blend
of them is multiplied, not each one. Once his game is on and Sleeper has him
in it, the chance is spent and the whole projection is what is left.
"""
import json
import re

import pandas as pd

from fantasy import pregame
from fantasy.league import availability as av
from fantasy.site import matchups as page
from fantasy.site import roster
from gordstats import contrast
from gordstats import matchup_page as ui

Q75 = {"p": 0.75, "n": 1267, "status": "Questionable", "practice": "Limited", "role": "lead"}
D01 = {"p": 0.012, "n": 220, "status": "Doubtful", "practice": "DNP", "role": "lead"}


# --------------------------------------------------------------------------- #
# The pills
# --------------------------------------------------------------------------- #

def test_the_pill_says_the_chance_and_where_it_comes_from():
    html = page.avail_badges({"avail": Q75})
    assert '<span class="mu-play good"' not in html and 'class="mu-play fair"' in html
    assert ">plays 75%</span>" in html
    assert 'title="Questionable, limited in practice before the final report' in html


def test_a_tiny_chance_is_escaped():
    """"plays <5%" went out raw once: a bare < in the page."""
    html = page.avail_badges({"avail": D01})
    assert ">plays &lt;5%</span>" in html and "plays <5%" not in html


def test_return_date_pill_and_nothing_for_a_player_ruled_out():
    out = {"p": 0.0, "n": 0, "status": "IR", "practice": None, "role": "lead"}
    assert page.avail_badges({"avail": out}) == ""
    assert page.avail_badges({"avail": out, "back": "back ~Nov 1"}) == \
        '<span class="mu-back">back ~Nov 1</span>'
    assert page.avail_badges({}) == ""


def test_the_pills_read_in_both_themes():
    pairs = {}
    for css, theme in ((ui.PLAY_CSS, "light"), (ui.PLAY_DARK, "dark")):
        for cls, bg, fg in re.findall(r"\.mu-(play\.\w+|back)\{background:(#\w+);color:(#\w+)", css):
            pairs[(theme, cls)] = contrast.ratio(fg, bg)
    assert len(pairs) == 8, pairs
    assert all(r >= contrast.AA_NORMAL for r in pairs.values()), pairs
    assert ui.PLAY_CSS in ui.CSS and ui.PLAY_DARK in ui.CSS


# --------------------------------------------------------------------------- #
# The matchups page
# --------------------------------------------------------------------------- #

SLOTS = ["QB", "WR", "BN"]
QB, Q, BN = "4984", "6794", "8000"           # Sleeper ids; "q" would read as a defence


def _side_data(state="pre", stats=None, pts=None):
    data = {"week": 4, "year": 2026, "games": [],
            "projections": {
                QB: {"name": "Quarter Back", "pos": "QB", "team": "KC", "injury": "", "pts": 20.0},
                Q: {"name": "Ques Tionable", "pos": "WR", "team": "SF", "injury": "Questionable",
                      "pts": 16.0},
                BN: {"name": "Bench Guy", "pos": "WR", "team": "SF", "injury": "", "pts": 9.0}},
            "external": {}, "stats": stats or {}, "teams": {}}
    side = {"roster_id": 1, "starters": [QB, Q], "players": [QB, Q, BN],
            "players_points": pts or {}, "points": sum((pts or {}).values())}
    g = {"game_id": "9", "state": state, "home": True, "opp": "DEN", "elapsed": 0.5 if state == "in" else 0.0}
    wk = av.apply(pd.DataFrame({"proj_week": [20.0, 16.0, 9.0], "state": [state] * 3},
                               index=pd.Index([QB, Q, BN], name="sleeper_id")),
                  {Q: Q75})
    ctx = {"slots": SLOTS, "board": {}, "registry": {}, "wk": wk,
           "by_team": {"KC": {**g, "game_id": "8"}, "SF": g},
           "avail": {Q: Q75}, "back": {}, "sd": {}}
    return side, data, ctx


def test_gs_and_the_blend_are_the_projection_times_the_chance():
    side, data, ctx = _side_data()
    html, gs_total, *_, parts = page.roster_table(side, {}, data, ctx, final=False)
    # GS: 16 if he plays x 0.75 = 12; the blend of GS and Sleeper (16, 16) x 0.75.
    assert parts["proj"][Q] == 12.0 and gs_total == 32.0
    assert parts["hproj"][Q] == 12.0, "discounted once, not once per source"
    row = re.search(rf'<tr class="starter[^"]*" data-pid="{Q}".*?</tr>', html).group(0)
    assert 'data-proj="12.0"' in row and 'data-hproj="12.0"' in row
    assert ">plays 75%</span>" in row
    # Plays-or-not widens his week: p*sd^2 + p(1-p)*mu^2 over a 2-point floor's 9.6.
    sd = float(re.search(r'data-sd="([\d.]+)"', row).group(1))
    assert sd > ui.spread_for(None, 16.0)
    pair = page.pair_view({"key": "1", "parts": parts}, {"key": "2", "parts": parts}, ctx)
    assert '<span class="mu-pav"><span class="mu-play' in pair, "phones get the pill on its own line"


def test_once_he_is_playing_the_chance_is_spent():
    side, data, ctx = _side_data(state="in", stats={Q: {"gp": 1.0, "rec": 2}}, pts={Q: 6.0})
    html, *_, parts = page.roster_table(side, {}, data, ctx, final=False)
    row = re.search(rf'<tr class="starter[^"]*" data-pid="{Q}".*?</tr>', html).group(0)
    assert parts["proj"][Q] == 12.0, "the GS column stays the number he had going in"
    assert 'data-proj="16.0"' in row and parts["hproj"][Q] == 16.0
    assert "mu-play" not in row, "no pill once his game has started"


def test_a_game_on_without_him_in_it_keeps_the_chance():
    side, data, ctx = _side_data(state="in")
    *_, parts = page.roster_table(side, {}, data, ctx, final=False)
    assert parts["hproj"][Q] == 12.0


def test_gs_week_freezes_the_expected_points(tmp_path, monkeypatch):
    monkeypatch.setattr(pregame, "ARCHIVE", tmp_path)
    board = pd.DataFrame({"sleeper_id": ["a", "b"], "team": ["KC", "KC"], "pos": ["WR", "WR"],
                          "mu": [16.0, 10.0]})
    games = [{"game_id": "1", "date": "2026-10-04T17:00Z", "home": "KC", "away": "SF",
              "home_score": None, "away_score": None, "home_implied": 24.0,
              "away_implied": 24.0, "state": "pre", "detail": ""}]
    wk = page.gs_week({"week": 4, "year": 2026, "games": games}, board,
                      chances={"a": {"p": 0.5}, "b": {"p": 0.0}})
    assert wk.loc["a", "proj_full"] == 16.0 and wk.loc["a", "proj_week"] == 8.0
    assert wk.loc["b", "proj_week"] == 0.0
    assert json.loads(pregame.path(4).read_text()) == {"a": 8.0, "b": 0.0}


def test_disagreements_compare_like_with_like():
    """The sources price a Questionable player as playing; ours, discounted,
    used to read as a disagreement about the player."""
    data = {"projections": {"q": {"name": "Q", "pos": "WR", "team": "SF", "pts": 16.0}},
            "external": {"espn": {"q": 16.5}}, "teams": {"1": {"name": "A"}},
            "matchups": [{"sides": [{"roster_id": 1, "starters": ["q"], "players": ["q"]}]}]}
    wk = pd.DataFrame({"proj_week": [8.0], "p_play": [0.5]}, index=["q"])
    rows = page.disagreements(data, {"wk": wk, "board": {}, "registry": {}})
    assert rows[0]["gs"] == 16.0 and rows[0]["nearest"] == 0.0


# --------------------------------------------------------------------------- #
# The team dashboard
# --------------------------------------------------------------------------- #

def _week(state="pre", stats=None, pts=None):
    wkd = roster.Week.__new__(roster.Week)
    wkd.wk = av.apply(pd.DataFrame({"proj_week": [16.0, 10.0]}, index=["q", "h"]), {"q": Q75})
    wkd.chances = {"q": Q75}
    wkd.by_team = {"SF": {"game_id": "9", "state": state, "home": True, "opp": "DEN"}}
    wkd.sleeper_all = {"q": 18.0, "h": 10.0}
    wkd.sources = {"sleeper": {}, "espn": {"q": 14.0}}
    wkd.data = {"stats": stats or {}}
    wkd.pts = pts or {}
    wkd.backs = {"ir": "back ~Nov 1"}
    wkd.dvp, wkd.dvp_ranks, wkd.weather = pd.DataFrame(), {}, {}
    return wkd


def test_the_planner_reads_the_blend_times_the_chance():
    wkd = _week()
    assert wkd.if_plays("q", "SF") == 16.0                      # (16 + 18 + 14) / 3
    assert wkd.blend("q", "SF") == 12.0
    assert wkd.gs("q", "SF") == 12.0 and wkd.gs("q", "SF", "proj_full") == 16.0
    assert wkd.blend("h", "SF") == 10.0
    assert wkd.blend("q", "BYE") == 0.0
    playing = _week(state="in", stats={"q": {"gp": 1.0}})
    assert playing.blend("q", "SF") == 16.0


def test_team_cells_carry_the_pills():
    wkd = _week()
    card = roster.with_avail(wkd, "q", {"name": "Ques Tionable", "pos": "WR", "team": "SF",
                                        "injury": "Questionable"})
    assert card["avail"] is Q75
    cell = roster.player_cell(card)
    assert "<span class='rd-inj'" in cell and ">plays 75%</span>" in cell
    info = roster.card_info(wkd, card, 12.0)
    assert info["extra"].startswith("<div class='rd-c-sub rd-c-av'><span class=\"mu-play")
    assert roster._if_plays_title(wkd, "q", card) == \
        " title='16.0 if he plays, times the 75% chance he does'"
    ir = roster.with_avail(wkd, "ir", {"name": "Hurt", "pos": "WR", "team": "SF", "injury": "IR"})
    assert "back ~Nov 1" in roster.player_cell(ir)
    started = roster.with_avail(_week(state="in"), "q", {"name": "Q", "pos": "WR", "team": "SF",
                                                         "injury": "Questionable"})
    assert "avail" not in started, "no pill once his game has started"


def test_a_player_on_the_official_report_sleeper_has_not_tagged_shows_the_tag():
    wkd = _week()
    card = roster.with_avail(wkd, "q", {"name": "Q", "pos": "WR", "team": "SF", "injury": ""})
    assert card["injury"] == "Questionable"


def test_the_page_includes_the_pill_styles():
    import inspect
    body = inspect.getsource(roster.body)
    assert "ui.PLAY_CSS" in body and "ui.PLAY_DARK" in body
    # The theme's img{max-width:100%} let the logo count for nothing in the
    # column's width, and the widest player cell's pill spilled into the next.
    assert "td.rd-p img{max-width:none}" in body
