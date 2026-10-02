"""Regressions from the 2026-10-02 whole-site audit."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd


# --------------------------------------------------------------------------- #
# The CFB predictions card quotes the book on the same side as ours
# --------------------------------------------------------------------------- #

def _game(pred_margin, market_spread):
    return pd.Series({
        "home": "North Carolina", "away": "Notre Dame", "home_id": 153, "away_id": 87,
        "pred_margin": pred_margin, "home_win_prob": 0.08 if pred_margin < 0 else 0.92,
        "market_spread": market_spread, "pred_total": 55.0, "neutral": False,
        "date": datetime(2026, 10, 3, 15, 30, tzinfo=ZoneInfo("America/New_York")),
        "time_valid": True, "game_id": None, "place": "Chapel Hill, NC", "tv": "ABC",
        "completed": False})


def test_an_away_favourite_reads_the_books_line_for_the_same_team(monkeypatch):
    from cfb.site import predictions
    monkeypatch.setattr(predictions, "_scores", lambda g: (None, None))
    # The home line is +21.5 (UNC): the book has Notre Dame -21.5, as we do -20.9.
    html = predictions._card(_game(-20.9, 21.5))
    assert "Notre Dame -20.9" in html and "book -21.5" in html
    # A home favourite is quoted as it stands.
    html = predictions._card(_game(7.2, -6.5))
    assert "North Carolina -7.2" in html and "book -6.5" in html


# --------------------------------------------------------------------------- #
# Names chosen by league members are text, in the WNBA includes too
# --------------------------------------------------------------------------- #

def test_wnba_fantasy_team_names_are_escaped():
    from wnba import wnba_pickups
    evil = "<img src=x onerror=alert(1)>"
    html = wnba_pickups.drop_recommendations_html({evil: []})
    assert "<img src=x" not in html and "&lt;img src=x" in html


def test_generated_includes_are_literal_to_jekyll():
    """A team or player name holding {% or {{ must not run as Liquid (or fail
    the build): every include the generators write goes through literal()."""
    import inspect
    from cfb.site import homecards as cfb_home
    from nfl.site import homecards as nfl_home
    from wnba import wnba_remaining
    assert "TOP25_OUT.write_text(literal(" in inspect.getsource(cfb_home)
    assert "BETS_OUT.write_text(literal(" in inspect.getsource(cfb_home)
    assert "BETS_OUT.write_text(literal(" in inspect.getsource(nfl_home)
    src = inspect.getsource(wnba_remaining)
    assert 'f.write(literal("\\n\\n".join(scoreboard_parts)))' in src
    assert 'f.write(literal("\\n\\n".join(dashboard_parts)))' in src


# --------------------------------------------------------------------------- #
# JSON inside <script> cannot end or bend the element
# --------------------------------------------------------------------------- #

def test_script_json_neutralises_markup_and_round_trips():
    from gordstats.jsonio import script_json
    data = {"team": "<!--<script>", "end": "</script>", "amp": "A&M"}
    out = script_json(data, separators=(",", ":"))
    assert "<" not in out and ">" not in out and "&" not in out
    assert json.loads(out) == data
