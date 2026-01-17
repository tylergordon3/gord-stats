def add_front_matter(html, title, opt_date=None):
    fm = f"""---
layout: default
title: {title}
---
"""
    header = f'<h1>{title}</h1>'
    if opt_date:
        header += f'<h2>{opt_date}</h2>'
    new_html = fm + header + html
    return new_html.lstrip()