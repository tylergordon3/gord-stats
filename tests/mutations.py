"""
Prove the test suite still catches the bugs it claims to.

    .venv/bin/python tests/mutations.py     # from the repo root

Reintroduces each failure that actually shipped during the 2026-08 rewrite and
asserts the corresponding test fails. A test that passes either way is theatre,
and three of these did exactly that on the first run:

  * the colormap check asserted >= 3.0, and the brightness-threshold version it
    replaced scored 3.12 — so it passed with the bug in place;
  * the dark-mode audit sliced the stylesheet at the *first* dark block, so
    every rule defined after it went unchecked;
  * the lang test captured `lang="([^"]*)"`, which stops at the quote inside
    the Liquid and matched the broken form quite happily.

This is not run by pytest — it edits tracked files and restores them, so it is
a deliberate, manual check to run after touching the suite.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(".").resolve()

# (label, file, find, replace, test that must fail)
MUTATIONS = [
    ("movers sorted but not filtered",
     "src/fantasy/league/adp_board.py",
     'risers = moved[moved[col] > 0].sort_values(col, ascending=False).head(n)\n'
     '    fallers = moved[moved[col] < 0].sort_values(col).head(n)',
     'risers = moved.sort_values(col, ascending=False).head(n)\n'
     '    fallers = moved.sort_values(col).head(n)',
     "test_movers_split_by_direction_not_just_sort"),

    ("table columns hardcoded instead of derived from SOURCES",
     "src/fantasy/site/upcoming.py",
     '_FIELDS = (["player", "pos", "team"] + list(SOURCES) + ["Avg"]',
     '_FIELDS = (["player", "pos", "team", "ESPN", "FFC"] + ["Avg"]',
     "test_every_source_reaches_the_table"),

    ("stale board cache served despite a missing source column",
     "src/fantasy/league/adp_board.py",
     'if not set(SOURCES).difference(cached.columns):\n            return _ensure_ranks(_blank_movement(cached))',
     'if True:\n            return _ensure_ranks(_blank_movement(cached))',
     "test_cached_board_missing_a_source_is_treated_as_stale"),

    ("text colour picked by a brightness threshold",
     "src/gordstats/contrast.py",
     'return "#ffffff" if ratio(WHITE, background) > ratio(BLACK, background) else "#000000"',
     'r, g, b = parse(background)\n'
     '    return "#ffffff" if (0.299 * r + 0.587 * g + 0.114 * b) / 255 < 0.5 else "#000000"',
     "test_best_text_on_beats_a_brightness_threshold"),

    ("light surface with no dark counterpart",
     "docs/assets/css/custom.css",
     "  details.section {\n    background: #1b2540;",
     "  details.section {\n    /* removed */",
     "test_every_light_surface_has_a_dark_counterpart"),

    ("light-only muted text",
     "docs/assets/css/custom.css",
     "  .sub-nav a {\n    color: #aab7c9 !important;",
     "  .sub-nav a {\n    font-weight: 600;",
     "test_light_only_text_colours_are_not_invisible_on_dark"),

    ("nav href rewriting restored in the layout",
     "docs/_layouts/default.html",
     "  <script>",
     "  <script>\n    /**\n     * LEAGUE-AWARE NAV REWRITE\n     */",
     "test_no_script_rewrites_nav_hrefs"),

    ("dynamic import of the old package name",
     "src/fantasy/rebuild.py",
     'importlib.import_module(f"fantasy.site.{module}")',
     'importlib.import_module(f"src.site.{module}")',
     "test_no_dynamic_imports_of_the_old_package_name"),

    ("broken lang attribute",
     "docs/_layouts/default.html",
     "<html lang=\"{{ site.lang | default: 'en-US' }}\">",
     '<html lang="{{ site.lang | default: " en-US" }}">',
     "test_lang_attribute_is_a_valid_tag"),

    ("nav link pointing at a page that does not exist",
     "docs/_data/nav.yml",
     "    url: /fantasy/adp/",
     "    url: /fantasy/adp-gone/",
     "test_nav_links_point_at_real_pages"),
]


def run_pytest(node=None):
    cmd = [".venv/bin/python", "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider"]
    if node:
        cmd += ["-k", node]
    r = subprocess.run(cmd, capture_output=True, text=True, env={"MPLBACKEND": "Agg", "PATH": "/usr/bin:/bin"})
    return r.returncode, r.stdout


failures = []
for label, rel, find, replace, node in MUTATIONS:
    path = ROOT / rel
    original = path.read_text()
    if find not in original:
        failures.append(f"SETUP  {label}: anchor not found in {rel}")
        continue
    path.write_text(original.replace(find, replace, 1))
    try:
        code, out = run_pytest(node)
        caught = code != 0
        print(f"  {'CAUGHT ' if caught else 'MISSED '} {label}")
        if not caught:
            failures.append(f"{label} -> {node} still passed")
    finally:
        path.write_text(original)

print()
if failures:
    print("PROBLEMS:")
    for f in failures:
        print("  " + f)
    sys.exit(1)
print(f"all {len(MUTATIONS)} reintroduced bugs were caught")
