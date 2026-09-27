"""
Jekyll front-matter helpers for generated pages.

Every section writes plain HTML fragments; Jekyll needs front matter and the
page needs its own <h1>, so both get prepended here. Shared so the sections
can't drift into producing subtly different page headers.
"""


def add_front_matter(html: str, title: str, subtitle: str | None = None) -> str:
    """Prepend Jekyll front matter and an <h1> title to a page body.

    `subtitle` renders as a small muted line under the title — used for things
    like the date stamp on a bracketology page. It was an <h3>: 21px bold on a
    phone under a 24px title it mostly restated, so it read as a second
    heading rather than a caption (`.page-sub` in custom.css).
    """
    fm = f"""---
layout: default
title: {title}
---
"""
    header = f"<h1>{title}</h1>"
    if subtitle:
        header += f"<p class='page-sub'>{subtitle}</p>"
    return (fm + header + html).lstrip()
