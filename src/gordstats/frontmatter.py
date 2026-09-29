"""
Jekyll front-matter helpers for generated pages.

Every section writes plain HTML fragments; Jekyll needs front matter and the
page needs its own <h1>, so both get prepended here. Shared so the sections
can't drift into producing subtly different page headers.

A page body is also made literal to Jekyll here. Jekyll runs Liquid over every
page, and the bodies carry text nobody here wrote - team names a league member
chose, league names, provider data - which html.escape leaves alone: a team
named `{%x%}` failed the whole build (no publish that day), and a name built
from Liquid tags could reassemble a <script> after escaping (found by the
2026-09-28 audit). So the body is wrapped in {% raw %}, and only the tags a
generator means Jekyll to run - an include, a relative_url - pass through,
each marked with liquid().
"""
import json
import re
import secrets

# A fresh token per process: a marker cannot be written into a team name ahead
# of time, so nothing but liquid() can open a hole in the raw wrapping.
_TOKEN = secrets.token_hex(8)
_OPEN, _CLOSE = f"{_TOKEN}:", f":{_TOKEN}"
_MARKED = re.compile(re.escape(_OPEN) + "(.*?)" + re.escape(_CLOSE), re.S)
# Liquid's own pattern for the tags that begin and end a raw block.
_RAW_TAG = re.compile(r"\{%-?\s*(?:end)?raw\s*-?%\}")


def liquid(tag: str) -> str:
    """A Liquid tag Jekyll is meant to run inside a generated page body."""
    return f"{_OPEN}{tag}{_CLOSE}"


def literal(body: str) -> str:
    """`body` with nothing for Liquid to run but the tags liquid() marked.

    The {% raw %} guards the sections put around their scripts come out first
    (the whole body is raw now), and so does any raw or endraw tag inside a
    name - which is what would otherwise end the wrapping early.
    """
    out = []
    for i, part in enumerate(_MARKED.split(_RAW_TAG.sub("", body))):
        if i % 2:
            out.append(part)
        elif part:
            out.append("{% raw %}" + part + "{% endraw %}")
    return "".join(out)


def add_front_matter(html: str, title: str, subtitle: str | None = None,
                     description: str | None = None, image: dict | None = None) -> str:
    """Prepend Jekyll front matter and an <h1> title to a page body.

    `subtitle` renders as a small muted line under the title — used for things
    like the date stamp on a bracketology page. It was an <h3>: 21px bold on a
    phone under a 24px title it mostly restated, so it read as a second
    heading rather than a caption (`.page-sub` in custom.css).

    `description` is the page's own line in search results and link previews
    (jekyll-seo-tag); without one it is the site's. Written as a JSON string,
    which YAML reads as a double-quoted scalar whatever the text holds.

    `image` is the page's own link-preview card (gordstats.share_card: path,
    width, height, alt); without one it is the site's. JSON again, which YAML
    reads as a flow mapping.
    """
    desc = f"description: {json.dumps(description)}\n" if description else ""
    if image:
        desc += f"image: {json.dumps(image)}\n"
    fm = f"""---
layout: default
title: {title}
{desc}---
"""
    header = f"<h1>{title}</h1>"
    if subtitle:
        header += f"<p class='page-sub'>{subtitle}</p>"
    return fm + literal((header + html).lstrip())
