"""
Rebuild the college football section, non-interactively.

    python -m cfb.build             # cached data if fresh, then every page
    python -m cfb.build --refresh   # refetch Yahoo + ESPN first

The list of pages lives here and only here (the way fantasy.rebuild.PAGES
works for the NFL section); gordstats.daily's cfb task calls build_all().
"""
import argparse
import traceback

PAGES = ["home", "draft", "schedule", "league"]


def build_all(refresh: bool = False) -> list[str]:
    """Fetch (or reuse) the data, build every page; returns failed page names."""
    from cfb import espn, yahoo

    # Fetch up front so one network failure surfaces once, not per page, and a
    # fetch that does fail leaves the pages building from the last good cache.
    for label, pull in [("yahoo league", lambda: yahoo.league(refresh=refresh)),
                        ("yahoo board", lambda: yahoo.board(refresh=refresh)),
                        ("yahoo scoreboard", lambda: yahoo.scoreboard(refresh=refresh)),
                        ("yahoo transactions", lambda: yahoo.transactions(refresh=refresh)),
                        ("yahoo draft", lambda: yahoo.draft_results(refresh=refresh)),
                        ("espn schedule", lambda: espn.schedule(refresh=refresh))]:
        try:
            pull()
        except Exception as exc:
            print(f"  ! {label} fetch failed ({exc}); pages will use the cache")

    failed = []
    for name in PAGES:
        try:
            import importlib
            importlib.import_module(f"cfb.site.{name}").generate()
        except Exception:
            traceback.print_exc()
            failed.append(name)
    return failed


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Rebuild the CFB pages.")
    p.add_argument("--refresh", action="store_true",
                   help="refetch Yahoo and ESPN data instead of using caches")
    args = p.parse_args()
    if build_all(refresh=args.refresh):
        raise SystemExit(1)
