"""
Jekyll front-matter helpers for generated pages.
"""


def add_front_matter(html: str, title: str, subnav: str | None = None) -> str:
    """Prepend Jekyll front matter and an <h1> title to a page body."""
    if subnav:
        fm = f"""---
layout: default
title: {title}
subnav_id: {subnav}
---
"""
    else:
        fm = f"""---
layout: default
title: {title}
---
"""
    return (fm + f"<h1>{title}</h1>" + html).lstrip()
