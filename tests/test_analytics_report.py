"""deploy/analytics.py: the pieces that decide what the report says."""
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "analytics", Path(__file__).parent.parent / "deploy" / "analytics.py")
analytics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analytics)


def test_pages_group_into_their_places_on_the_site():
    s = analytics.section
    assert s("/") == "Home"
    assert s("/fantasy/") == "/fantasy/"
    assert s("/fantasy/matchups/") == "/fantasy/matchups/"
    assert s("/cfb/teams/alabama/") == s("/cfb/teams/ohio-state/") == "/cfb/teams/*"
    assert s("/cfb/game/401858245/") == "/cfb/game/*"
    assert s("/fantasy/recap/week-3/") == "/fantasy/recap/*"
    assert s("/men/conference.html") == "/men/"


def test_an_audit_hour_is_a_burst_and_a_busy_saturday_is_not():
    hourly = {f"2026-10-0{d}T{h:02d}": 20 for d in (1, 2) for h in range(10, 20)}
    hourly["2026-10-02T17"] = 1010          # our own audit, 1 PM ET
    hourly["2026-10-01T23"] = 90            # a busy evening of real readers
    assert analytics.bursts(hourly) == {"2026-10-02T17"}
    assert analytics.bursts({}) == set()


def test_the_quiet_windows_go_around_the_bursts():
    start = datetime(2026, 10, 2, 10, tzinfo=timezone.utc)
    end = datetime(2026, 10, 2, 20, 30, tzinfo=timezone.utc)
    got = analytics.quiet_windows(start, end, {"2026-10-02T17"})
    assert got == [(start, datetime(2026, 10, 2, 17, tzinfo=timezone.utc)),
                   (datetime(2026, 10, 2, 18, tzinfo=timezone.utc), end)]


def test_cloudflare_quantiles_are_microseconds():
    assert analytics.secs(449000) == "0.45s"
    assert analytics.ms(48000) == "48ms"
    assert analytics.secs(-1) == analytics.ms(None) == "-"      # iOS Safari reports none


def test_without_the_token_it_says_where_the_token_lives(monkeypatch, capsys):
    monkeypatch.delenv("CLOUDFLARE_ANALYTICS_TOKEN", raising=False)
    assert analytics.main(["7"]) == 2
    assert "secrets/gord-stats.env" in capsys.readouterr().err
