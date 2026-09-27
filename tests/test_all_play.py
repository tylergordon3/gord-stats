"""All-play standings sort by wins as a number. They were sorted as the text
pulled out of "17-1", and "8" sorts above "17", so an 8-10 team led the table.
"""
import json


def test_all_play_standings_sort_by_wins_as_numbers(tmp_path, monkeypatch):
    from fantasy.site import schedule

    # Ten teams, two weeks. "hi" outscores everyone both weeks (18-0); "lo"
    # beats only one team a week (2-16). Anything alphabetical or textual would
    # put "lo"'s leading digit ahead of "hi"'s.
    rows = []
    for week in (1, 2):
        rows.append({"week": week, "team_name": "hi", "points": 200.0})
        rows.append({"week": week, "team_name": "lo", "points": 60.0})
        rows.append({"week": week, "team_name": "floor", "points": 50.0})
        for i in range(7):
            rows.append({"week": week, "team_name": f"mid{i}", "points": 100.0 + i})
    (tmp_path / "9999.json").write_text(json.dumps(rows))
    monkeypatch.setattr(schedule, "SEASON_DIR", tmp_path)

    table = schedule.all_play("9999").data
    assert list(table["Team"])[0] == "hi"
    assert list(table["Total"])[0] == "18-0"
    assert list(table["Team"])[-1] == "floor"
