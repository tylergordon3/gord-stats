"""What's new: Home's card and /changelog/, from gordstats.changelog.ENTRIES."""
import inspect
import re
from datetime import date
from pathlib import Path

from gordstats import changelog

DOCS = Path(__file__).parent.parent / "docs"


def test_entries_are_dated_newest_first_and_say_one_thing():
    days = [date.fromisoformat(e[0]) for e in changelog.ENTRIES]
    assert days == sorted(days, reverse=True), "add new entries at the top"
    for day, title, text, link in changelog.ENTRIES:
        assert title and text and len(title) <= 60, title
        assert link is None or link.startswith("/"), link


def test_every_link_is_a_page_the_site_builds():
    """A link to a page that is not there is a dead end on Home."""
    for *_, link in changelog.ENTRIES:
        if link and link != "/":
            src = Path(__file__).parent.parent / "src"
            # A generator writes docs/<path>/index.html: its path is named in src/.
            path = link.strip("/")
            assert any(path in p.read_text(encoding="utf-8", errors="ignore")
                       for p in src.rglob("*.py")), f"nothing builds {link}"


def test_home_shows_the_latest_few_and_links_the_rest():
    card = changelog.home_card()
    assert card.count("<li>") == changelog.HOME_SHOWN
    assert "href='/changelog/'" in card
    first = changelog.ENTRIES[0][1]
    assert first.replace("'", "&#x27;") in card
    # Home places it.
    from cbb.render import render_home
    assert "changelog.home_card()" in inspect.getsource(render_home.render_home)


def test_the_page_lists_every_entry_under_its_day():
    html = changelog.body()
    assert html.count("<li>") == len(changelog.ENTRIES)
    assert html.count("class='cl-day'") == len({e[0] for e in changelog.ENTRIES})
    assert "October 2, 2026" in html


def test_text_is_escaped(monkeypatch):
    monkeypatch.setattr(changelog, "ENTRIES",
                        [("2026-10-02", "<b>x</b>", "{% raw %}<script>", "/x/'y")])
    card = changelog.home_card()
    assert "<script>" not in card and "&lt;script&gt;" in card
    assert "href='/x/&#x27;y'" in card


def test_the_page_is_built_with_the_others():
    from gordstats import daily
    assert "changelog.generate()" in inspect.getsource(daily)
    assert not re.search(r"{%|{{", changelog.CSS)
