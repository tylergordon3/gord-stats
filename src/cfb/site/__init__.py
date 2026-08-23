"""Page builders for the college football section (docs/cfb/)."""

from gordstats.frontmatter import add_front_matter


def write_page(path, title: str, body: str, subtitle: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(add_front_matter(body, title, subtitle), encoding="utf-8")
    print(f"Wrote {title} -> {path}")
