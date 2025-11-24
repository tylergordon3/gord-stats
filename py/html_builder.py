import os

def add_front_matter(html, title):
    fm = f"""---
layout: default
title: {title}
---
"""
    header = f'<h1>{title}</h1>'
    new_html = fm + header + html
    return new_html.lstrip()