"""The home page's Top 25: the AP poll's say on a team it does not rank.

Ours and FPI rank all of FBS; the AP stops at 25. A team outside the poll was
compared on the other two lists alone, so Penn State - 15th to FPI, 17th to
us, 28th by AP votes - went unmarked beside teams we and FPI both rank that
were. The poll now places a team by its votes, and one with none below them
all. A team the three lists have within a couple of places (Notre Dame at
1/2/3) is still left alone: MARK_GAP.
"""
import re

from cfb.site import homecards, power


def _team(name, ap, gs, fpi):
    return {"name": name, "logo": None, "ap": ap, "gs": gs, "fpi": fpi}


def _cells(html: str) -> dict:
    return {(name, rank): (mark.strip(), title) for rank, row in enumerate(
        html.split("<tbody>")[1].split("</tr>")[:3], 1)
        for mark, title, name in re.findall(
            r"<td class='hc-tc([^']*)'[^>]*title=\"([^\"]*)\">.*?<span class='hc-tm'>([^<]*)</span>",
            row)}


def test_a_team_outside_the_poll_is_compared_at_its_place_in_the_votes(monkeypatch):
    teams = {
        "1": _team("Notre Dame", 3, 1, 2),
        "2": _team("Georgia", 1, 3, 1),
        "3": _team("Texas", 2, 7, 3),
        "4": _team("Penn State", 28, 2, 4),      # 28th by votes
        "5": _team("Wisconsin", 26, 9, 9),
    }
    monkeypatch.setattr(homecards, "_rankings", lambda: (teams, True))
    cells = _cells(homecards.top25_html(limit=3))
    assert cells[("Penn State", 2)][0] == "hc-hi", "28th by votes against 2nd to us"
    assert "AP unranked (28th by votes)" in cells[("Penn State", 2)][1]
    assert cells[("Notre Dame", 1)][0] == "" and cells[("Notre Dame", 3)][0] == "", \
        "1st, 2nd and 3rd is agreement"
    assert cells[("Texas", 2)][0] == "hc-hi" and cells[("Texas", 3)][0] == ""


def test_a_team_without_a_vote_sits_below_every_team_with_one(monkeypatch):
    teams = {
        "1": _team("Georgia", 1, 1, 1),
        "2": _team("Ohio State", 2, 2, 2),
        "3": _team("Alabama", 3, 4, 4),
        "4": _team("Texas A&M", None, 3, 3),    # no votes at all
        "5": _team("Wisconsin", 26, 30, 30),
    }
    monkeypatch.setattr(homecards, "_rankings", lambda: (teams, True))
    cells = _cells(homecards.top25_html(limit=3))
    # Floored at 27, below Wisconsin's 26th: 3rd to us and FPI is a disagreement.
    assert cells[("Texas A&amp;M", 3)][0] == "hc-hi"


def test_the_poll_places_others_receiving_votes_by_points(tmp_path, monkeypatch):
    poll = {"name": "AP Top 25", "season": {"year": 2026}, "occurrence": {"displayValue": "Week 5"},
            "ranks": [{"current": i, "team": {"id": str(i)}} for i in range(1, 26)],
            "others": [{"current": 0, "points": 98, "team": {"id": "213"}},
                       {"current": 0, "points": 102, "team": {"id": "275"}},
                       {"current": 0, "points": 98, "team": {"id": "154"}},
                       {"current": 0, "points": 1, "team": {"id": "77"}}]}
    (tmp_path / "ap.json").write_text(__import__("json").dumps({"rankings": [poll]}))
    monkeypatch.setattr(power, "DATA_DIR", tmp_path)
    ranks, season, _label = power.ap_poll(refresh=False, others=True)
    assert [ranks[t] for t in ("275", "213", "154", "77")] == [26, 27, 27, 29]
    assert len(power.ap_poll(refresh=False)[0]) == 25, "the power page still gets the 25"
