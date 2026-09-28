"""Only players this league can roster: the Power 4 and Notre Dame.

Yahoo's college game draws its pool from those conferences and one
independent, so every list built from a Yahoo feed (the board, free agents,
waivers) already holds nobody else. The usage page is built from CFBD's box
scores, which cover all of FBS - it listed Sun Belt and MAC backs nobody here
can add.
"""
from cfb.config import league_school


def test_the_power_four_and_notre_dame_are_in():
    for school, conf in (("Iowa", "Big Ten"), ("Clemson", "ACC"), ("Baylor", "Big 12"),
                         ("Alabama", "SEC"), ("Notre Dame", "Independent")):
        assert league_school(school, conf), school


def test_everyone_else_is_out():
    for school, conf in (("App State", "Sun Belt"), ("Boise State", "Mountain West"),
                         ("UConn", "Independent"), ("Toledo", "Mid-American"),
                         ("Oregon State", "Pac-12"), ("Somewhere", "")):
        assert not league_school(school, conf), school


def test_the_usage_page_applies_it():
    import inspect
    from cfb.site import usage
    assert "league_school(" in inspect.getsource(usage.body)
