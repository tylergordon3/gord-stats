"""What a search engine is told: robots.txt and the sitemap template (docs/).

Nothing crawled the site before 2026-09-28 - Cloudflare's bot challenge stood
in front of every page - so these are new and nothing else would notice them
breaking.
"""
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / "docs"


def test_robots_points_at_the_sitemap_and_keeps_out_the_signed_in_pages():
    robots = (DOCS / "robots.txt").read_text()
    assert "Sitemap: https://www.gordstats.com/sitemap.xml" in robots
    for path in ("/api/", "/profile/", "/fantasy/sync/"):
        assert f"Disallow: {path}" in robots
    assert "Disallow: /\n" not in robots, "the whole site stays open"


def test_the_sitemap_lists_pages_and_skips_what_robots_closes():
    sitemap = (DOCS / "sitemap.xml").read_text()
    assert sitemap.startswith("---\n") and "layout: null" in sitemap, "Jekyll must render it"
    assert "site.pages" in sitemap and "absolute_url" in sitemap
    for path in ("/404.html", "/profile/", "/fantasy/sync/"):
        assert path in sitemap
