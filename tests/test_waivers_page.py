"""The season being played gets the live waivers view - Waiver Watch and the
move-by-move log - whether or not it has been added to LEAGUE_IDS.

The page used to hand a season in LEAGUE_IDS to data_manager, which the
scheduled preset never runs: from the 2026-09-25 rollover the log stopped at
that day and both sections vanished from the page.
"""


def test_the_live_season_keeps_its_waiver_watch_after_the_rollover(tmp_path, monkeypatch):
    from fantasy import paths
    from fantasy.config import LEAGUE_IDS
    from fantasy.site import transactions

    assert transactions.CURRENT in LEAGUE_IDS, "the rollover this guards has happened"
    pulled = []
    monkeypatch.setattr(paths, "WEB_TRANSACTIONS", tmp_path / "index.html")
    monkeypatch.setattr(transactions, "_refresh_current", lambda: pulled.append(1) or True)
    monkeypatch.setattr(transactions, "waiver_watch", lambda: "<div id='ww-stub'></div>")
    monkeypatch.setattr(transactions, "_player_names", lambda: {})

    transactions.generate()
    html = (tmp_path / "index.html").read_text()
    assert pulled, "the live season's log was not refreshed"
    assert "ww-stub" in html and "Waiver Log" in html
