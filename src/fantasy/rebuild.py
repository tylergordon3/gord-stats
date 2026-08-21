#!/usr/bin/env python3
"""
Interactive rebuild for the fantasy site.

    python -m fantasy.rebuild                       # ask what to do, then do it
    python -m fantasy.rebuild --preset pages --yes   # no prompts (for scripts)

Wraps the two existing entry points so you don't have to remember either:

    fantasy.data_manager   refreshes stored datasets (players, injuries, season files)
    fantasy.site.build     regenerates the HTML pages under docs/fantasy/

Presets cover the usual cases; "Custom" asks about every step. Nothing is fetched
or written until you confirm the plan.
"""
import argparse
import sys
import time
import traceback
from fantasy.config import LEAGUE_IDS, UPCOMING_YEAR

SEASONS = list(LEAGUE_IDS)

# Page jobs. Imports are deferred into the lambdas: matplotlib and jinja2 cost a
# second or two to load, and the menu should appear instantly.
PAGES = [
    ("schedule",     "Schedule Stats",                    lambda: _gen("schedule")),
    ("transactions", "Waivers & Trades",                  lambda: _gen("transactions")),
    ("draft",        "Draft Analytics (board, values, report, DNA)", lambda: _gen("draft_analytics")),
    ("live",         "Live Draft Board",                  lambda: _gen("draft_live")),
    ("power",        "Power Rankings (post-draft)",        lambda: _gen("power")),
    ("homepage",     "Home (countdown + live ADP board)", lambda: _gen("homepage")),
]

DATA_JOBS = [
    ("season",   "League matchup / record files"),
    ("transactions", "Waiver / free-agent / trade log"),
    ("injuries", "Weekly injury reports (slow: scrapes nfl.com)"),
    ("players",  "Cross-source player registry"),
    ("history",  "Year-over-year player table"),
]

PRESETS = {
    "pages":    "Rebuild all pages (use cached ADP)",
    "predraft": "Refresh live ADP board, then rebuild all pages",
    "full":     "Refresh all stored data, then rebuild everything",
    "custom":   "Choose each step",
}


def _gen(module: str):
    """Import fantasy.site.<module> late and run its generate()."""
    import importlib
    importlib.import_module(f"fantasy.site.{module}").generate()


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #

class Abort(Exception):
    """User pressed Ctrl-C / Ctrl-D."""


def _read(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        raise Abort


def ask_choice(question: str, options: dict, default: str) -> str:
    """Numbered single-select. `options` is {key: description}."""
    keys = list(options)
    print(f"\n{question}")
    for i, key in enumerate(keys, 1):
        mark = " (default)" if key == default else ""
        print(f"  {i}. {options[key]}{mark}")
    while True:
        raw = _read(f"Choice [1-{len(keys)}, Enter = default]: ")
        if not raw:
            return default
        if raw.isdigit() and 1 <= int(raw) <= len(keys):
            return keys[int(raw) - 1]
        print("  Enter one of the listed numbers.")


def ask_yes_no(question: str, default: bool) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        raw = _read(f"{question} {suffix}: ").lower()
        if not raw:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  Answer y or n.")


def ask_multi(question: str, items, default_all: bool = True):
    """Multi-select by number ("1,3" or "1 3"), 'a' for all, 'n' for none."""
    print(f"\n{question}")
    for i, (_, label, *_rest) in enumerate(items, 1):
        print(f"  {i}. {label}")
    hint = "Enter = all" if default_all else "Enter = none"
    while True:
        raw = _read(f"Select [numbers, a = all, n = none, {hint}]: ").lower()
        if not raw:
            return list(items) if default_all else []
        if raw in ("a", "all"):
            return list(items)
        if raw in ("n", "none"):
            return []
        picks = [p for p in raw.replace(",", " ").split() if p]
        if all(p.isdigit() and 1 <= int(p) <= len(items) for p in picks) and picks:
            seen = dict.fromkeys(int(p) - 1 for p in picks)   # de-dupe, keep order
            return [items[i] for i in seen]
        print("  Enter numbers from the list, or a / n.")


# --------------------------------------------------------------------------- #
# Plan
# --------------------------------------------------------------------------- #

class Plan:
    def __init__(self):
        self.data_jobs = []       # names for fantasy.data_manager
        self.force_refresh = False
        self.refresh_adp = False
        self.games_missed = False
        self.pages = []           # (slug, label, fn)
        self.seasons = SEASONS

    def describe(self) -> str:
        lines = []
        if self.data_jobs:
            forced = " (forcing re-fetch of cached data)" if self.force_refresh else ""
            lines.append(f"  Refresh data: {', '.join(self.data_jobs)}{forced}")
            lines.append(f"  Seasons: {', '.join(self.seasons)}")
        if self.refresh_adp:
            lines.append(f"  Refetch the live {UPCOMING_YEAR} ADP board from all three sites")
        if self.games_missed:
            lines.append(f"  Re-archive games-missed for: {', '.join(self.seasons)}")
        if self.pages:
            lines.append(f"  Rebuild pages: {', '.join(slug for slug, _, _ in self.pages)}")
        return "\n".join(lines) or "  (nothing selected)"

    def is_empty(self) -> bool:
        return not (self.data_jobs or self.refresh_adp or self.games_missed or self.pages)


def plan_from_preset(preset: str) -> Plan:
    plan = Plan()
    if preset in ("pages", "predraft", "full"):
        plan.pages = list(PAGES)
        plan.games_missed = True
    if preset in ("predraft", "full"):
        plan.refresh_adp = True
    if preset == "full":
        plan.data_jobs = [name for name, _ in DATA_JOBS]
    return plan


def plan_from_prompts() -> Plan:
    plan = Plan()

    if ask_yes_no("\nRefresh stored data first (Sleeper pulls, injury scrapes)?", False):
        chosen = ask_multi("Which datasets?", DATA_JOBS, default_all=True)
        plan.data_jobs = [name for name, _ in chosen]
        if plan.data_jobs:
            plan.force_refresh = ask_yes_no(
                "Force re-fetch of data already cached (slower, hits the network)?", False)

    plan.refresh_adp = ask_yes_no(
        f"\nRefetch the live {UPCOMING_YEAR} ADP board (FantasyPros / ESPN / FFC)?"
        f"{_board_age_hint()}", True)

    pages = ask_multi("\nWhich pages should be rebuilt?", PAGES, default_all=True)
    plan.pages = pages
    if pages:
        plan.games_missed = ask_yes_no(
            "Re-archive per-season games-missed first (the homepage injury section reads it)?",
            any(slug == "homepage" for slug, _, _ in pages))

    if plan.data_jobs or plan.games_missed:
        chosen = ask_multi("\nWhich seasons?", [(s, s) for s in SEASONS], default_all=True)
        plan.seasons = [s for s, _ in chosen] or SEASONS
    return plan


def _board_age_hint() -> str:
    """' (cached copy is 5h old)' - so you know whether a refresh is worth it."""
    try:
        from fantasy.league.adp_board import last_updated
        when = last_updated(UPCOMING_YEAR)
    except Exception:
        return ""
    if not when:
        return " (no cached copy yet)"
    hours = (time.time() - when.timestamp()) / 3600
    age = f"{hours:.0f}h" if hours >= 1 else f"{hours * 60:.0f}m"
    return f" (cached copy is {age} old)"


# --------------------------------------------------------------------------- #
# Run
# --------------------------------------------------------------------------- #

def _step(name: str, fn, results: list):
    """Run one step, time it, and keep going if it fails."""
    print(f"\n--- {name} ---")
    started = time.time()
    try:
        fn()
    except Exception:
        traceback.print_exc()
        results.append((name, "FAILED", time.time() - started))
        return False
    results.append((name, "ok", time.time() - started))
    return True


def run(plan: Plan) -> int:
    results = []

    if plan.data_jobs:
        from fantasy import data_manager
        _step(f"data: {', '.join(plan.data_jobs)}",
              lambda: data_manager.main(seasons=plan.seasons, only=plan.data_jobs,
                                        refresh=plan.force_refresh),
              results)

    if plan.refresh_adp:
        from fantasy.league import adp_board
        _step("live ADP board", lambda: adp_board.board(UPCOMING_YEAR, refresh=True), results)

    if plan.games_missed:
        from fantasy.site import draft
        for season in plan.seasons:
            _step(f"games-missed [{season}]",
                  lambda s=season: draft.save_games_missed(s), results)

    for slug, _, fn in plan.pages:
        _step(f"page: {slug}", fn, results)

    failed = [r for r in results if r[1] == "FAILED"]
    width = max([len(name) for name, _, _ in results] + [30])
    rule = "=" * (width + 18)

    print("\n" + rule)
    for name, status, secs in results:
        flag = "  " if status == "ok" else "! "
        print(f"{flag}{name:<{width}} {status:>7} {secs:6.1f}s")
    total = sum(secs for _, _, secs in results)
    print(rule)
    print(f"{len(results) - len(failed)}/{len(results)} steps ok in {total:.1f}s")
    if failed:
        print(f"Failed: {', '.join(name for name, _, _ in failed)}")
        return 1
    if plan.pages:
        print("\nPages written to docs/. Commit and push to publish.")
    return 0


def _parse_args():
    p = argparse.ArgumentParser(
        description="Interactive rebuild for the fantasy site.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--preset", choices=list(PRESETS),
                   help="Skip the first menu and use this preset.")
    p.add_argument("--yes", "-y", action="store_true",
                   help="Don't prompt at all: run the preset (default: pages) as-is.")
    return p.parse_args()


def main() -> int:
    args = _parse_args()

    if args.yes:
        plan = plan_from_preset(args.preset or "pages")
        print(f"Running preset '{args.preset or 'pages'}':\n{plan.describe()}")
        return run(plan)

    print("=" * 58)
    print(" Fantasy site rebuild")
    print("=" * 58)

    preset = args.preset or ask_choice("What do you want to do?", PRESETS, default="pages")
    plan = plan_from_prompts() if preset == "custom" else plan_from_preset(preset)

    print("\n" + "-" * 58)
    print("Plan:")
    print(plan.describe())
    print("-" * 58)

    if plan.is_empty():
        print("Nothing to do.")
        return 0
    if not ask_yes_no("\nRun this?", True):
        print("Cancelled.")
        return 0
    return run(plan)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Abort:
        print("\nCancelled.")
        sys.exit(130)
