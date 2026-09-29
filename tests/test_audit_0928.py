"""Fixes from the 2026-09-28 audit: security (names that were HTML or Liquid,
the API on stale deployments, the visit counter's write budget) and college
basketball's first night (unknown teams, last season's data, the lines)."""
import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# Liquid: a page body is literal to Jekyll but for the tags a generator marks
# --------------------------------------------------------------------------- #

def test_a_team_name_cannot_run_liquid_or_end_the_raw_wrapping():
    from gordstats.frontmatter import add_front_matter, liquid
    hostile = "{%x%} {{ site.time }} {% endraw %}{%- endraw -%}<b>"
    page = add_front_matter(
        f"<p>{hostile}</p>{{% raw %}}<script>var a={{b:1}};</script>{{% endraw %}}"
        + liquid("{% include cfb_countdown.html %}") + "<i>after</i>", "Title")
    body = page.split("---\n", 2)[2]
    # One raw block before the include, one after, and nothing else Liquid can see.
    assert body.startswith("{% raw %}<h1>Title</h1><p>{%x%} {{ site.time }} <b></p>")
    assert body.count("{% raw %}") == 2 and body.count("{% endraw %}") == 2
    assert "{% endraw %}{% include cfb_countdown.html %}{% raw %}<i>after</i>{% endraw %}" in body
    assert "<script>var a={b:1};</script>" in body, "the scripts' own guards come out"


def test_only_this_run_can_mark_a_tag():
    from gordstats import frontmatter
    # A marker someone typed into a name ahead of time is just text.
    forged = "deadbeefdeadbeef:{% include evil.html %}:deadbeefdeadbeef"
    out = frontmatter.literal(forged)
    assert out.startswith("{% raw %}") and out.endswith("{% endraw %}")


def test_every_intended_liquid_tag_is_marked():
    """An include or relative_url written bare into a body wrapped by
    add_front_matter would now print as text. The two home pages that write
    their own front matter (no member-supplied text) are the exceptions."""
    import re
    bare = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        if path.name in ("render_home.py", "frontmatter.py", "pipeline.py"):
            continue
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if re.search(r"\{%-? *include|\| *relative_url", line) and "liquid(" not in line \
                    and not line.lstrip().startswith("#") and "Liquid `relative_url`" not in line:
                bare.append(f"{path.relative_to(ROOT)}:{n}")
    assert not bare, bare


def test_yahoo_team_names_are_escaped_on_the_league_page():
    from cfb.site import league
    lg = {"teams": [{"name": "<img src=x onerror=alert(1)>", "rank": 1, "wins": 1, "losses": 0,
                     "manager": "", "logo": 'x" onload="alert(1)', "points_for": 1}],
          "num_playoff_teams": 6}
    html = league.standings_section(lg)
    assert "<img src=x" not in html and "&lt;img src=x" in html
    assert 'onload="alert' not in html


# --------------------------------------------------------------------------- #
# The API answers on www only; the visit counter can't eat the write budget
# --------------------------------------------------------------------------- #

def test_the_api_refuses_every_host_but_the_sites_own():
    mw = (ROOT / "functions/api/_middleware.js").read_text()
    assert '"www.gordstats.com"' in mw and "pages.dev" not in mw.split("const HOSTS")[1].split(";")[0]
    assert "status: 404" in mw and "context.next()" in mw


def test_the_visit_counter_keys_on_the_address_and_stops_at_its_cap():
    js = (ROOT / "functions/api/visits.js").read_text()
    record = js.split("async function record")[1].split("async function bump")[0]
    assert "user-agent" not in record, "the caller chooses the user agent"
    assert "DAILY_CAP" in record and "const DAILY_CAP = 250" in js


def test_pages_carry_security_headers():
    headers = (ROOT / "docs/_headers").read_text()
    assert "Strict-Transport-Security: max-age=31536000" in headers
    assert "frame-ancestors 'none'" in headers
    assert '"_headers"' in (ROOT / "docs/_config.yml").read_text(), "Jekyll must copy it"


# --------------------------------------------------------------------------- #
# College basketball, opening night
# --------------------------------------------------------------------------- #

MASTER = pd.DataFrame({"team": ["Maryland", "Duke"], "index": [0, 1],
                       "names": [["Maryland", "UMD", "MD"], ["Duke", "DUKE"]],
                       "short": ["UMD", "Duke"]})


def test_only_division_i_teams_are_looked_up():
    from cbb.live_scraper import resolve_team
    assert resolve_team({"abbreviation": "MD", "division": "NCAA Division I"}, MASTER)[1] == "Maryland"
    # theScore's UMD is Michigan-Dearborn (NAIA), not the list's Maryland alias.
    idx, name, _ = resolve_team({"abbreviation": "UMD", "medium_name": "Michigan-Dearborn",
                                 "division": "National Association of Intercollegiate Athletic"},
                                MASTER)
    assert (idx, name) == (None, "Michigan-Dearborn")
    # A Division I school the list does not know yet keeps its own name.
    assert resolve_team({"abbreviation": "UWF", "medium_name": "West Florida",
                         "division": "NCAA Division I"}, MASTER)[:2] == (None, "West Florida")
    assert resolve_team({"abbreviation": "DUKE", "division": "NCAA Division I Women"},
                        MASTER)[1] == "Duke"
    assert resolve_team({"abbreviation": "X", "division": "NCAA Division II"}, MASTER)[0] is None


def test_an_unknown_team_is_a_blank_not_a_dead_scoreboard(monkeypatch):
    from cbb import live_scraper
    monkeypatch.setattr(live_scraper.season, "get_last_x", lambda g, t, x: "")
    g = {"home_team": {"abbreviation": "DUKE", "division": "NCAA Division I"},
         "away_team": {"abbreviation": "LYN", "medium_name": "Lynchburg",
                       "division": "NCAA Division III"},
         "game_date": "Sun, 01 Nov 2026 19:00:00 -0500", "status": "pre_game"}
    net = {"rows": [["3", "Duke"]]}
    out = live_scraper.format_event(g, {}, MASTER, None, net, None, None, "M")
    assert out["away_team"] == "Lynchburg" and out["net_away"] is None
    assert out["net_home"] == "3" and out["wab_home"] is None, "no Torvik yet is a blank"


def test_last_seasons_files_are_not_this_seasons(tmp_path):
    from cbb import utils
    for name in ("2026-03-15.json", "2026-05-24.json", "notes.json"):
        (tmp_path / name).write_text("{}")
    assert utils.latest_this_season(tmp_path, date(2026, 11, 1)) is None
    (tmp_path / "2026-11-02.json").write_text("{}")
    assert utils.latest_this_season(tmp_path, date(2026, 11, 3)).name == "2026-11-02.json"
    assert utils.latest_this_season(tmp_path, date(2026, 4, 1)).name == "2026-05-24.json"


def test_bpi_waits_for_its_own_season(monkeypatch):
    from cbb.scrape import bpi, net

    class R:
        def json(self):
            return {"pagination": {"pages": 1}, "teams": [],
                    "requestedSeason": {"year": 2026}, "currentSeason": {"year": 2027}}
    monkeypatch.setattr(bpi.requests, "get", lambda *a, **k: R())
    with pytest.raises(net.NotReleased, match="BPI not out for 2027"):
        bpi.main()
    monkeypatch.setattr(bpi, "get_today_bpi", lambda: None)
    assert bpi.get_conf_records() == {}


def test_tipoff_is_the_first_game():
    from cbb.render.render_home import CBB_TIPOFF
    assert CBB_TIPOFF == date(2026, 11, 1), "Notre Dame-Villanova in Rome, Sunday Nov 1"


def test_the_closing_line_and_the_final_are_kept(tmp_path, monkeypatch):
    from cbb import lines
    monkeypatch.setattr(lines, "LIVE_DIR", tmp_path / "live")
    monkeypatch.setattr(lines, "RECORD_DIR", tmp_path / "record")
    g = {"date": "2026-11-03", "home_team": "Duke", "away_team": "Kansas",
         "status": "pre_game", "spread_close": "DUKE -3", "total_close": 150.5}
    lines.record({"men": {"9": g}}, season=2027)
    lines.record({"men": {"9": dict(g, spread_close="DUKE -4.5")}}, season=2027)
    lines.record({"men": {"9": dict(g, status="in_progress", spread_close="DUKE -1")}},
                 season=2027)
    lines.record({"men": {"9": dict(g, status="final", home_score=80, away_score=71,
                                    spread_close=None)}}, season=2027)
    assert lines.publish(2027) == 1
    row = json.loads((tmp_path / "record" / "2027.json").read_text())["men:9"]
    assert row["spread"] == "DUKE -4.5", "the last line before tipoff, not an in-game one"
    assert (row["total"], row["home_score"], row["away_score"], row["final"]) == (150.5, 80, 71, True)
    before = (tmp_path / "record" / "2027.json").stat().st_mtime_ns
    lines.publish(2027)
    assert (tmp_path / "record" / "2027.json").stat().st_mtime_ns == before, "unchanged, unwritten"


# --------------------------------------------------------------------------- #
# Numbers that were wrong
# --------------------------------------------------------------------------- #

def _nfl_week_data(states, sleeper_pts):
    return {"games": [{"game_id": "1", "date": "2026-09-13T17:00Z", "home": "KC", "away": "DEN",
                       "state": states[0], "detail": "", "home_score": 0, "away_score": 0,
                       "home_implied": None, "away_implied": None},
                      {"game_id": "2", "date": "2026-09-15T00:15Z", "home": "CHI", "away": "PHI",
                       "state": states[1], "detail": "", "home_score": 0, "away_score": 0,
                       "home_implied": None, "away_implied": None}],
            "projections": {"1": {"pts": sleeper_pts, "team": "KC"},
                            "2": {"pts": sleeper_pts, "team": "PHI"}},
            "external": {"espn": {"1": sleeper_pts, "2": sleeper_pts, "KC": sleeper_pts}}}


def test_outside_projections_stay_as_they_were_at_kickoff():
    from fantasy.league import matchups
    old = _nfl_week_data(("pre", "pre"), 10.0)
    new = _nfl_week_data(("in", "pre"), 2.0)       # KC-DEN is on; CHI-PHI is not
    out = matchups.keep_pregame(old, new)
    assert out["projections"]["1"]["pts"] == 10.0, "KC kicked off: the pregame number stands"
    assert out["projections"]["2"]["pts"] == 2.0, "PHI has not: today's number is the pregame one"
    assert out["external"]["espn"]["1"] == 10.0 and out["external"]["espn"]["KC"] == 10.0
    assert out["external"]["espn"]["2"] == 2.0
    assert matchups.keep_pregame(None, new) is new


def test_a_finished_week_is_read_once_more_for_corrections(tmp_path, monkeypatch):
    from fantasy.league import matchups
    final = _nfl_week_data(("post", "post"), 10.0)
    final["matchups"] = [{"matchup_id": 1, "sides": [{"points": 100.0}, {"points": 90.0}]}]
    final["teams"] = {"1": {"name": "Then", "reserve": []}}
    cache = tmp_path / "week_03.json"
    cache.write_text(json.dumps(final))
    corrected = json.loads(json.dumps(final))
    corrected["matchups"][0]["sides"][0]["points"] = 101.5
    corrected["projections"]["1"]["pts"] = 0.0          # post-game: must not replace kickoff's
    corrected["teams"] = {"1": {"name": "Now", "reserve": ["4034"]}}   # today's IR, not that week's
    calls = []
    monkeypatch.setattr(matchups, "_fetch_week", lambda *a: calls.append(a) or json.loads(json.dumps(corrected)))
    out = matchups._settle(json.loads(cache.read_text()), 3, 2026, "L", cache)
    assert out["settled"] and out["matchups"][0]["sides"][0]["points"] == 101.5
    assert out["projections"]["1"]["pts"] == 10.0
    assert out["teams"] == {"1": {"name": "Then", "reserve": []}}, "the week's own rosters"
    assert matchups._settle(out, 3, 2026, "L", cache) is out and len(calls) == 1, "once"
    # A failed read keeps the archive and tries again later.
    monkeypatch.setattr(matchups, "_fetch_week", lambda *a: (_ for _ in ()).throw(OSError("down")))
    assert matchups._settle(final, 3, 2026, "L", cache) is final


def test_a_game_with_no_kickoff_time_says_so():
    from datetime import datetime, timezone
    from cfb.site import predictions
    game = {"pred_margin": 7.0, "home": "Iowa", "away": "Ohio State", "home_win_prob": 0.7,
            "date": datetime(2026, 10, 17, 4, 0, tzinfo=timezone.utc), "time_valid": False,
            "pred_total": 50.0, "home_id": "2294", "away_id": "194", "neutral": False,
            "pred_home": 28.5, "pred_away": 21.5, "home_rank": float("nan"),
            "away_rank": 2.0, "home_rating": 3.0, "away_rating": 9.0}
    html = predictions._card(pd.Series(game))
    assert "12:00 AM" not in html and "time TBA" in html
