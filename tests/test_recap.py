"""The weekly recap and lineup accuracy (gordstats.recap, with the two
leagues' adapters fantasy.site.recap and cfb.site.recap)."""
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from gordstats import recap
from gordstats.recap import Player, Side, Team, Week

ROOT = Path(__file__).resolve().parents[1]
FLEX = {"FLEX": ("RB", "WR", "TE")}


def _side(key, points, starters, bench, best, proj=None):
    return Side(key, points, [Player(*p) for p in starters], [Player(*p) for p in bench],
                set(best), proj)


def _week(**kw):
    """Four teams, two games. A beats B narrowly while B's bench would have
    won it; C crushes D; A and C set perfect lineups."""
    sides = {
        "A": _side("A", 100, [("a1", "Q A", "QB", 60, "QB"), ("a2", "R A", "RB", 40, "FLEX")],
                   [("a3", "W A", "WR", 10)], {"a1", "a2"}, proj=90),
        "B": _side("B", 95, [("b1", "Q B", "QB", 55, "QB"), ("b2", "R B", "RB", 40, "FLEX")],
                   [("b3", "Big Bench", "WR", 30), ("b4", "Spare QB", "QB", 70)],
                   {"b4", "b2"}, proj=120),
        "C": _side("C", 150, [("c1", "Q C", "QB", 80, "QB"), ("c2", "R C", "RB", 70, "FLEX")],
                   [], {"c1", "c2"}, proj=100),
        "D": _side("D", 50, [("d1", "Q D", "QB", 30, "QB"), ("d2", "R D", "RB", 20, "FLEX")],
                   [("d3", "Pickup", "WR", 25)], {"d1", "d3"}, proj=80),
    }
    base = dict(number=3, teams={k: Team(f"Team {k}") for k in sides},
                games=[("A", "B"), ("C", "D")], sides=sides, median=True, flex=FLEX,
                pickups=[recap.Pickup("D", sides["D"].bench[0], False),
                         recap.Pickup("C", sides["C"].starters[1], True)],
                power={"A": (3, 1), "B": (1, 3), "C": (2, 2), "D": (4, 4)})
    base.update(kw)
    return Week(**base)


def _awards(week):
    return {a.label: a for a in recap.awards(week)}


def test_lineup_accuracy_is_points_started_over_the_best_possible():
    w = _week()
    b = w.sides["B"]
    assert (b.started, b.max, b.left) == (95, 110, 15)
    assert round(b.pct, 4) == round(95 / 110, 4)
    assert w.sides["A"].pct == 1.0 and w.sides["A"].left == 0
    # A lineup the rules cannot beat is never "better than the best".
    odd = _side("X", 50, [("x1", "Out of position", "K", 50, "QB")], [], set())
    assert odd.max == 50 and odd.pct == 1.0


def test_the_costliest_call_only_pairs_players_who_could_swap():
    w = _week()
    benched, started = recap.swap(w.sides["B"], FLEX)
    # The spare QB (70) belonged in the QB slot. Big Bench (a WR, 30) is not in
    # the best lineup at all, and a QB could never have taken the FLEX.
    assert (benched.name, started.name) == ("Spare QB", "Q B")


def test_the_awards():
    a = _awards(_week())
    assert a["High score"].key == "C" and "Led by Q C, 80" in a["High score"].detail
    assert a["Low score"].key == "D"
    assert a["Blowout"].key == "C" and a["Blowout"].stat == "by 100"
    assert a["Nail-biter"].key == "A" and a["Nail-biter"].stat == "by 5"
    assert a["Luckiest win"].key == "A" and "1 team scored more" in a["Luckiest win"].detail
    assert a["Toughest loss"].key == "B" and "beaten 1 of the other 3" in a["Toughest loss"].detail
    # B lost by 5 with 110 on its best lineup against A's 100.
    cost = a["Cost them the game"]
    assert cost.key == "B" and cost.stat == "lost by 5"
    assert "Started Q B (55) over Spare QB (70)" in cost.detail
    # A and C both perfect: the tie goes to the bigger score, the other is named.
    assert a["Best lineup"].key == "C" and a["Best lineup"].stat == "100.0%"
    assert "so did Team A" in a["Best lineup"].detail
    assert a["Most left on the bench"].key == "B" and a["Most left on the bench"].stat == "15"
    assert a["Beat the projection"].key == "C" and a["Beat the projection"].stat == "+50"
    assert a["Missed the projection"].key == "D"
    assert a["Player of the week"].detail == "Q C, QB"
    assert a["Bench star"].detail.startswith("Spare QB, QB")
    # A pickup who sat is not the pickup of the week.
    assert a["Pickup of the week"].key == "C"
    assert a["Power riser"].key == "A" and a["Power riser"].stat == "up 2"
    assert a["Power faller"].key == "B" and "3rd" in a["Power faller"].detail


def test_awards_with_nobody_to_give_them_to_are_left_out():
    w = _week(pickups=[], power={})
    w.sides["A"].proj = None          # one side without an honest projection
    labels = set(_awards(w))
    assert not labels & {"Beat the projection", "Missed the projection",
                         "Pickup of the week", "Power riser", "Power faller"}


def test_headline_is_the_preview_line():
    assert recap.headline(_week()) == (
        "Week 3: Team C top-scored with 150, Team B left 15 on the bench and "
        "1 team was beaten by their own bench.")


def test_season_accuracy_weights_big_weeks_more():
    w1, w2 = _week(), _week(number=4)
    w2.sides["A"] = _side("A", 10, [("a1", "Q A", "QB", 10, "QB")],
                          [("a4", "Q2", "QB", 90)], {"a4"})
    rows = {r["key"]: r for r in recap.season([w1, w2])}
    a = rows["A"]
    assert (a["started"], a["max"], a["left"], a["perfect"], a["weeks"]) == (110, 190, 80, 1, 2)
    assert round(a["pct"], 4) == round(110 / 190, 4)   # not the mean of 100% and 11%
    assert recap.season([w1, w2])[0]["key"] == "C"


def test_the_page():
    w = _week()
    html = recap.page(w, [_week(number=1), w], "/fantasy/recap/")
    assert '<a href="/fantasy/recap/week-1/">1</a>' in html and "<span>3</span>" in html
    assert html.count('class="rc-game"') == 2 and html.count('class="rc-award') >= 10
    assert 'class="rc-med w"' in html, "median results shown in a median league"
    assert "<th>Wk 3</th>" in html and 'class="pf"' in html


def test_the_teaser_follows_the_newest_week_and_clears(tmp_path):
    assert recap.teaser(tmp_path, "/cfb/recap/") == ""
    recap.write_latest(tmp_path, _week())
    t = recap.teaser(tmp_path, "/cfb/recap/")
    assert 'href="/cfb/recap/week-3/"' in t and "Week 3 recap" in t
    assert "Team C top-scored" in t and "Week 3:" not in t.split("rc-teaser")[-1]
    recap.write_latest(tmp_path, None)
    assert recap.teaser(tmp_path, "/cfb/recap/") == "", "a new season points at nothing"


def test_a_page_can_carry_its_own_preview_line():
    from gordstats.frontmatter import add_front_matter
    page = add_front_matter("<p>x</p>", "Week 3 Recap", description='Team "C’s" 150: a & b')
    assert 'description: "Team \\"C\\u2019s\\" 150: a & b"\n---' in page


# --------------------------------------------------------------------------- #
# The NFL league, off the committed Sleeper archive
# --------------------------------------------------------------------------- #

SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "K", "DEF",
         "BN", "BN", "BN", "BN", "BN"]


def _nfl_week(n, adds=None, ranks=None):
    from fantasy.site import matchups as mu
    from fantasy.site import recap as nfl
    d = json.loads((ROOT / "data/fantasy/matchups/2026" / f"week_{n:02d}.json").read_text())
    cards = {str(p): mu.player_card(str(p), d, {}, {})
             for m in d["matchups"] for s in m["sides"] for p in s["players"]}
    adds = adds if adds is not None else pd.DataFrame(columns=["week", "pid", "roster_id"])
    return nfl.build_week(d, SLOTS, cards, {}, adds, ranks or {})


def test_nfl_max_points_match_sleepers_own():
    """Sleeper's potential points (roster settings ppts) after weeks 1-2,
    read from the league on 2026-09-28: the best lineup here is the same
    lineup Sleeper counts, to the hundredth, for all ten teams."""
    sleeper = {"1": 324.78, "2": 298.14, "3": 298.28, "4": 276.7, "5": 370.64,
               "6": 255.86, "7": 280.74, "8": 265.78, "9": 367.88, "10": 258.74}
    ours = {}
    for n in (1, 2):
        for k, s in _nfl_week(n).sides.items():
            ours[k] = round(ours.get(k, 0) + s.max, 2)
    assert ours == sleeper


def test_nfl_week_pickups_and_power():
    adds = pd.DataFrame([{"week": 1, "pid": "PIT", "roster_id": "1"},
                         {"week": 1, "pid": "9999999", "roster_id": "1"},   # not his
                         {"week": 2, "pid": "PIT", "roster_id": "1"}])
    w = _nfl_week(1, adds, {0: {str(i): i for i in range(1, 11)},
                            1: {str(i): 11 - i for i in range(1, 11)}})
    assert [(p.key, p.player.name, p.started) for p in w.pickups] == [("1", "PIT D/ST", True)]
    assert w.power["1"] == (1, 10) and w.power["10"] == (10, 1)
    assert len(w.games) == 5 and w.median
    # Injured reserve is nobody's bench.
    assert all(p.slot == "" for s in w.sides.values() for p in s.bench)


# --------------------------------------------------------------------------- #
# The college league, off a Yahoo-shaped week
# --------------------------------------------------------------------------- #

def test_cfb_week(tmp_path, monkeypatch):
    from cfb.site import recap as cfbr
    lg = {"uses_median_score": True,
          "roster": [{"position": "QB", "count": 1}, {"position": "W/R/T", "count": 1},
                     {"position": "BN", "count": 2}, {"position": "IL", "count": 1}],
          "teams": [{"team_key": "t1", "name": "Alpha", "logo": "a.png"},
                    {"team_key": "t2", "name": "Beta", "logo": "b.png"}]}

    def p(i, name, pos, slot, pts):
        return {"yahoo_id": i, "player": name, "pos": pos, "slot": slot, "points": pts}
    d = {"week": 4, "week_start": "2026-09-20", "week_end": "2026-09-26",
         "matchups": [{"teams": [{"team_key": "t1", "points": 50}, {"team_key": "t2", "points": 40}]}],
         "rosters": {"t1": [p("1", "QB One", "QB", "QB", 30), p("2", "WR One", "WR", "W/R/T", 20),
                            p("3", "RB Bench", "RB", "BN", 25), p("4", "Hurt", "WR", "IL", 40)],
                     "t2": [p("5", "QB Two", "QB", "QB", 25), p("6", "TE Two", "TE", "W/R/T", 15),
                            p("7", "Added", "RB", "BN", 5)]}}
    thu = datetime(2026, 9, 24, 12).timestamp()
    tx = [{"status": "successful", "timestamp": thu,
           "players": [{"player": "Added", "type": "add", "destination": "Beta"},
                       {"player": "Dropped", "type": "drop", "destination": None}]},
          {"status": "successful", "timestamp": datetime(2026, 9, 30).timestamp(),
           "players": [{"player": "QB One", "type": "add", "destination": "Alpha"}]}]
    w = cfbr.build_week(d, lg, {"1": 20, "2": 15, "5": 20, "6": 10}, tx, {})
    a, b = w.sides["t1"], w.sides["t2"]
    assert (a.started, a.max) == (50, 55), "the RB belonged in the W/R/T; the IL player never did"
    assert a.proj == 35 and b.proj == 30
    assert [s.name for s in a.bench] == ["RB Bench"]
    assert [(k.key, k.player.name, k.started) for k in w.pickups] == [("t2", "Added", False)]
    assert w.teams["t1"].avatar == "a.png" and w.games == [("t1", "t2")]

    hist = tmp_path / "hist"
    hist.mkdir()
    for stamp, ranks in (("20260922-120000", "t1,2\nt2,1\n"),      # before Thursday
                         ("20260925-120000", "t1,1\nt2,2\n"),      # mid-week: ignored
                         ("20260927-120000", "t1,1\nt2,2\n"),      # after Saturday
                         ("20261002-120000", "t1,2\nt2,1\n")):     # next week's games
        (hist / f"{stamp}.csv").write_text("key,rank\n" + ranks)
    monkeypatch.setattr(cfbr, "HISTORY_DIR", hist)
    assert cfbr._power("2026-09-20", "2026-09-26") == {"t1": (2, 1), "t2": (1, 2)}


def test_the_recap_is_built_and_found():
    from cfb import build
    from fantasy import rebuild
    keys = [k for k, *_ in rebuild.PAGES]
    assert keys.index("recap") < keys.index("matchups") < keys.index("homepage")
    assert build.PAGES.index("recap") < build.PAGES.index("league")
    nav = (ROOT / "docs/_data/nav.yml").read_text()
    assert 'covers: "/fantasy/recap/"' in nav and 'covers: "/cfb/recap/"' in nav
    assert "page.url contains '/cfb/recap/'" in (ROOT / "docs/_includes/nav.html").read_text()
