import subprocess
from pathlib import Path
import re
from cbb import paths
# -----------------------------
# Config (AUTO-LOCAL)
# -----------------------------
BASE_DIR = Path(__file__).parent   # 👈 analysis/
NOTEBOOK_DIR = BASE_DIR
OUTPUT_DIR = paths.DOCS / "_includes"

LAYOUT = "default"

# -----------------------------
def convert_notebook(nb_path: Path, temp_path: Path):
    subprocess.run([
        "jupyter", "nbconvert",
        "--to", "html",
        "--no-input",
        "--no-prompt",
        "--template", "lab",
        str(nb_path),
        "--output", temp_path.stem,
        "--output-dir", str(temp_path.parent)
    ], check=True)


def extract_body(html: str) -> str:
    match = re.search(r"<body.*?>(.*)</body>", html, re.DOTALL)
    return match.group(1) if match else html


def clean_html(html: str) -> str:
    # remove require.js
    html = re.sub(r'<script src=".*?require.*?"></script>', '', html)

    # keep ONLY pandas table styles
    styles = re.findall(r'<style.*?>.*?</style>', html, flags=re.DOTALL)
    table_styles = [s for s in styles if '#T_' in s]  # pandas tables use #T_

    # remove all styles
    html = re.sub(r'<style.*?>.*?</style>', '', html, flags=re.DOTALL)

    # add back only table styles
    html = "\n".join(table_styles) + "\n" + html

    return html.strip()


def generate_title(nb_path: Path) -> str:
    return nb_path.stem.replace("_", " ").replace("-", " ").title()


def wrap_content(content: str) -> str:
    return f"""
<div class="notebook-content">
{content}
</div>
"""


def add_front_matter(content: str, title: str) -> str:
    return f"""---
layout: {LAYOUT}
title: {title}
---

{content}
"""


# -----------------------------
def main():
    notebooks = list(NOTEBOOK_DIR.glob("*.ipynb"))

    if not notebooks:
        print("No notebooks found in analysis/")
        return

    for nb in notebooks:
        print(f"Processing: {nb.name}")

        temp_path = OUTPUT_DIR / f"__temp_{nb.stem}.html"
        final_path = OUTPUT_DIR / f"{nb.stem}.html"

        # 1. Convert
        convert_notebook(nb, temp_path)

        # 2. Read + process
        raw_html = temp_path.read_text(encoding="utf-8")
        body = extract_body(raw_html)
        cleaned = clean_html(body)
        wrapped = wrap_content(cleaned)

        # 3. Add front matter
        #title = generate_title(nb)
        #final_html = add_front_matter(wrapped, title)

        # 4. Save (overwrite existing)
        final_path.write_text(wrapped, encoding="utf-8")

        # 5. Cleanup
        temp_path.unlink()

        print(f"Updated: {final_path.name}")


if __name__ == "__main__":
    main()