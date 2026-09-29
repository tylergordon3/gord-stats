"""
A page's own link-preview card (gordstats.share_card): the right size, a name
that changes with the picture, older cards of the same page cleared, and a
failure that costs the card rather than the page.
"""
from PIL import Image

from gordstats import share_card
from gordstats.frontmatter import add_front_matter

GAMES = [("Team A \U0001F3C8", 142.36, 98.1, "Team B"), ("Team C", 101.0, 124.5, "Team D")]


def _card(tmp_path, monkeypatch, slug="nfl-recap-w3", rows=GAMES):
    monkeypatch.setattr(share_card, "OUT_DIR", tmp_path)
    return share_card.games(slug, "NFL Fantasy", "Week 3 Recap", "The League", rows)


def test_a_card_is_a_wide_png_named_for_what_it_shows(tmp_path, monkeypatch):
    card = _card(tmp_path, monkeypatch)
    name = card["path"].rsplit("/", 1)[1]
    assert card["path"].startswith("/assets/images/share/nfl-recap-w3-")
    assert (card["width"], card["height"]) == (1200, 630)
    with Image.open(tmp_path / name) as im:
        assert im.size == (1200, 630)
    assert (tmp_path / name).stat().st_size < 60_000          # a chat downloads it
    # the same picture keeps its name; a different one gets a new one
    assert _card(tmp_path, monkeypatch)["path"] == card["path"]
    other = _card(tmp_path, monkeypatch, rows=GAMES[:1])
    assert other["path"] != card["path"]


def test_a_new_card_clears_that_pages_older_ones_only(tmp_path, monkeypatch):
    week1 = _card(tmp_path, monkeypatch, slug="nfl-recap-w1")
    week10 = _card(tmp_path, monkeypatch, slug="nfl-recap-w10")
    _card(tmp_path, monkeypatch, slug="nfl-recap-w1", rows=GAMES[:1])
    left = sorted(p.name for p in tmp_path.glob("*.png"))
    assert len(left) == 2
    assert week10["path"].rsplit("/", 1)[1] in left            # w1 is not a prefix of w10
    assert week1["path"].rsplit("/", 1)[1] not in left


def test_text_the_font_cannot_draw_is_dropped_and_long_names_cut():
    assert share_card.clean("Team A \U0001F3C8\U0001F4AA  win") == "Team A win"
    from PIL import ImageDraw
    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    cut = share_card.fit(d, "Too B1G Too Strong Too Fast", share_card.font(34, True), 200)
    assert cut.endswith("…") and d.textlength(cut, font=share_card.font(34, True)) <= 200


def test_a_week_is_live_only_once_somebody_has_scored(tmp_path, monkeypatch):
    monkeypatch.setattr(share_card, "OUT_DIR", tmp_path)
    pairs = [("A", 0.0, 120.5, "B", 0.0, 99.0)]
    pre = share_card.matchups("cfb-matchups", "CFB", 5, pairs, started=True, final=False)
    assert "matchups and projections" in pre["alt"]              # Yahoo's "started" week
    pairs = [("A", 12.0, 120.5, "B", 0.0, 99.0)]
    live = share_card.matchups("cfb-matchups", "CFB", 5, pairs, started=True, final=False)
    assert "live scores" in live["alt"]
    done = share_card.matchups("cfb-matchups", "CFB", 5, pairs, started=True, final=True)
    assert "final scores" in done["alt"]


def test_a_card_that_cannot_be_drawn_costs_the_card_not_the_page(tmp_path, monkeypatch):
    monkeypatch.setattr(share_card, "OUT_DIR", tmp_path)
    assert share_card.games("x", "k", "t", "s", None) is None
    assert share_card.ranked("x", "k", "t", "s", [("1",)]) is None


def test_front_matter_carries_the_card():
    page = add_front_matter("<p>x</p>", "Week 3 Recap", image={
        "path": "/assets/images/share/a.png", "width": 1200, "height": 630,
        "alt": 'Team "C": 150'})
    assert ('image: {"path": "/assets/images/share/a.png", "width": 1200, "height": 630, '
            '"alt": "Team \\"C\\": 150"}\n') in page
    assert "image:" not in add_front_matter("<p>x</p>", "T")
