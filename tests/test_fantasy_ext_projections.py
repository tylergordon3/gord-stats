"""ESPN and FantasyPros weekly projections: parsing, matching, consensus."""
import pandas as pd

from fantasy.league import ext_projections as ext


def test_espn_parse_keeps_only_the_weeks_projection():
    payload = {"players": [
        {"player": {"id": 4429795, "fullName": "Jahmyr Gibbs", "proTeamId": 8,
                    "defaultPositionId": 2, "stats": [
                        {"statSourceId": 0, "statSplitTypeId": 1, "scoringPeriodId": 18,
                         "seasonId": 2025, "appliedTotal": 20.3},
                        {"statSourceId": 1, "statSplitTypeId": 1, "scoringPeriodId": 1,
                         "seasonId": 2026, "appliedTotal": 21.7}]}},
        {"player": {"id": -16034, "fullName": "Texans D/ST", "proTeamId": 34,
                    "defaultPositionId": 16, "stats": [
                        {"statSourceId": 1, "statSplitTypeId": 1, "scoringPeriodId": 1,
                         "seasonId": 2026, "appliedTotal": 5.2}]}},
        {"player": {"id": 1, "fullName": "Nobody", "proTeamId": 1, "defaultPositionId": 3,
                    "stats": []}},
    ]}
    rows = ext.parse_espn(payload, week=1, year=2026)
    assert rows == [
        {"espn_id": "4429795", "name": "Jahmyr Gibbs", "pos": "RB", "team": "DET", "pts": 21.7},
        {"espn_id": "-16034", "name": "Texans D/ST", "pos": "DEF", "team": "HOU", "pts": 5.2},
    ]


FP_HTML = """<script>
var ecrData = {"week": "1", "players": [
 {"player_id": 22968, "player_name": "Jahmyr Gibbs", "player_team_id": "DET",
  "player_position_id": "RB", "rank_ecr": 1, "start_sit_grade": "A+", "r2p_pts": "21.6"},
 {"player_id": 8140, "player_name": "Jacksonville Jaguars", "player_team_id": "JAC",
  "player_position_id": "DST", "rank_ecr": 3, "start_sit_grade": "A", "r2p_pts": "7.4"},
 {"player_id": 1, "player_name": "Unprojected Guy", "player_team_id": "KC",
  "player_position_id": "RB", "rank_ecr": 90, "start_sit_grade": "", "r2p_pts": ""}
]};
</script>"""


def test_fantasypros_parse_reads_the_embedded_consensus():
    rb = ext.parse_fantasypros(FP_HTML, "RB")
    assert rb[0] == {"name": "Jahmyr Gibbs", "pos": "RB", "team": "DET", "pts": 21.6,
                     "ecr": 1, "grade": "A+"}
    # Ranked but unprojected is not a projection.
    assert [r["name"] for r in rb] == ["Jahmyr Gibbs", "Jacksonville Jaguars"]
    # A defense resolves its franchise name to Sleeper's team code.
    dst = ext.parse_fantasypros(FP_HTML, "DEF")
    assert dst[1]["team"] == "JAX" and dst[1]["pts"] == 7.4
    assert ext.parse_fantasypros("<html>no data</html>", "RB") == []


def test_matching_prefers_espn_id_then_name_and_position_then_team_code():
    reg = pd.DataFrame({
        "sleeper_id": ["9221", "1234", "5678"], "espn_id": ["4429795", None, None],
        "full_name": ["Jahmyr Gibbs", "Amon-Ra St. Brown", "Amon-Ra St. Brown"],
        "position": ["RB", "WR", "TE"],
    })
    lk = ext.Lookup(reg)
    rows = [{"espn_id": "4429795", "name": "J. Gibbs", "pos": "RB", "team": "DET", "pts": 21.7},
            {"name": "Amon-Ra St Brown", "pos": "WR", "team": "DET", "pts": 18.8},
            {"name": "Texans D/ST", "pos": "DEF", "team": "HOU", "pts": 5.2},
            {"name": "Unknown Guy", "pos": "QB", "team": "KC", "pts": 30.0}]
    got = ext.to_sleeper(rows, lk)
    assert got == {"9221": 21.7, "1234": 18.8, "HOU": 5.2}
    assert ext.to_sleeper(rows, lk, only={"HOU"}) == {"HOU": 5.2}


def test_consensus_averages_whatever_sources_have_the_player():
    c = ext.consensus({"a": 10.0, "b": 8.0}, {"a": 14.0}, {})
    assert c == {"a": 12.0, "b": 8.0}
