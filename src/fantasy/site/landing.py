"""
Section landing pages: link to each week's file in a docs/ section folder
(ported from py/html_builder.generate_landing).
"""
import os
import re

from src.site.frontmatter import add_front_matter


def generate_landing(folder: str, file: str, title: str):
    """Build <folder>/<file>.html linking to every week<N>_<file>.html, newest first."""
    week_files = [f for f in os.listdir(folder)
                  if f.startswith("week") and f.endswith(f"_{file}.html")]

    def week_num(name):
        m = re.search(fr"week(\d+)_{file}.html", name)
        return int(m.group(1)) if m else 0

    week_files.sort(key=week_num, reverse=True)

    body = ""
    if title == "Best Ball":
        body += "<p>Outcomes if every lineup had max points possible for a given week.</p>\n"
        body += '<p><a href="bestball.html">Standings</a></p>\n'
    for f in week_files:
        body += f'<p><a href="{f}">{f.split("_")[0].capitalize()}</a></p>\n'

    out = os.path.join(folder, file) + ".html"
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(add_front_matter(body, title))
    print(f"Wrote landing page -> {out}")
