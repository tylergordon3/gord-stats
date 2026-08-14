"""
archive_predictions.py
----------------------
Converts dated bracketology pages (docs/{men,women}/predict_YYYY-MM-DD.html)
into compact JSON so past rankings stay retrievable across seasons without
keeping hundreds of rendered HTML files in the site.

For every prediction page it stores date, last-update stamp, and both tables
(the projected field and the bubble teams) as columns + text rows under:

    docs/assets/data/predictions/{league}/{season}/{date}.json
    docs/assets/data/predictions/manifest.json   (league -> season -> dates)

then deletes the HTML — except each league's most recent page, which stays
as the live Bracketology target. The archive pages (/men/history.html,
/women/history.html) read the manifest and render any stored date
client-side.

Usage:
    python -m cbb.tools.archive_predictions            # archive + delete
    python -m cbb.tools.archive_predictions --dry-run  # report only

Run at season end (or whenever the dailies pile up); it is incremental and
idempotent — already-archived dates are simply rewritten.
"""

import argparse
import json
import re
from io import StringIO
from pathlib import Path

import pandas as pd

from cbb.lib import paths

LEAGUES = {
    "men":   paths.WEB_M_DIR,
    "women": paths.WEB_W_DIR,
}
ARCHIVE_DIR   = paths.ASSETS_DIR / "data" / "predictions"
MANIFEST_FILE = ARCHIVE_DIR / "manifest.json"

PREDICT_RE = re.compile(r"predict_(\d{4}-\d{2}-\d{2})\.html$")


def season_of(date_str: str) -> str:
    """Nov 2025 – Jun 2026 all belong to season '2026'."""
    year, month = int(date_str[:4]), int(date_str[5:7])
    return str(year + 1) if month >= 7 else str(year)


def parse_predict_html(path: Path, date_str: str) -> dict:
    html = path.read_text(encoding="utf-8")

    updated = None
    m = re.search(r"Last Update:\s*([^<]+)<", html)
    if m:
        updated = m.group(1).strip()

    # Headings that precede each table ("First Four Out & Next 4 Out" sits
    # between the two); default titles cover pages without them.
    titles = ["Projected Field", "First Four Out & Next 4 Out"]
    mid = re.search(r"<h[2-4][^>]*>(First Four[^<]*)</h[2-4]>", html)
    if mid:
        titles[1] = mid.group(1).strip()

    tables = []
    for i, df in enumerate(pd.read_html(StringIO(html))):
        df = df.fillna("")
        tables.append({
            "title":   titles[i] if i < len(titles) else f"Table {i + 1}",
            "columns": [str(c) for c in df.columns],
            "rows":    [[str(v) for v in row] for row in df.itertuples(index=False)],
        })

    return {"date": date_str, "updated": updated, "tables": tables}


def load_manifest() -> dict:
    if MANIFEST_FILE.exists():
        with open(MANIFEST_FILE) as f:
            return json.load(f)
    return {}


def archive(dry_run: bool = False) -> None:
    manifest = load_manifest()

    for league, web_dir in LEAGUES.items():
        pages = {}
        for f in web_dir.glob("predict_*.html"):
            m = PREDICT_RE.search(f.name)
            if m:
                pages[m.group(1)] = f
        if not pages:
            continue

        latest = max(pages)
        print(f"{league}: {len(pages)} prediction pages, keeping {latest} as live")

        for date_str, f in sorted(pages.items()):
            season = season_of(date_str)
            out = ARCHIVE_DIR / league / season / f"{date_str}.json"
            if dry_run:
                print(f"  would archive {f.name} -> {out.relative_to(paths.DOCS)}"
                      + ("" if date_str != latest else " (html kept)"))
                continue

            data = parse_predict_html(f, date_str)
            out.parent.mkdir(parents=True, exist_ok=True)
            with open(out, "w", encoding="utf-8") as fh:
                json.dump(data, fh)

            seasons = manifest.setdefault(league, {})
            dates = seasons.setdefault(season, [])
            if date_str not in dates:
                dates.append(date_str)
                dates.sort()

            if date_str != latest:
                f.unlink()

    if not dry_run:
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        with open(MANIFEST_FILE, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=1)
        print(f"Manifest -> {MANIFEST_FILE.relative_to(paths.DOCS)}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Archive dated bracketology pages to JSON and prune the HTML."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would happen without writing/deleting")
    args = parser.parse_args(argv)
    archive(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
