"""
Rebuild the NFL section: refetch this season's games, archive the board,
build the pages (the stats page refetches its own nflverse play-by-play, at
most every 12 hours - nfl.advanced). gordstats.daily's nfl task calls
build_all().

    python -m nfl.build
    python -m nfl.build --refresh
"""
import argparse
import traceback

# previews after teams (it links to team pages) and before everything that
# links to a preview - predictions, watch, schedule - which ask the disk.
PAGES = ["power", "teams", "previews", "predictions", "watch", "stats", "schedule",
         "homecards"]


def build_all(refresh: bool = False) -> list[str]:
    from nfl import games, results

    for label, pull in [("espn schedule", lambda: games.schedule(refresh=refresh)),
                        # A prediction scored after kickoff is not a prediction,
                        # so the board goes on record before the pages build.
                        ("prediction archive", lambda: results.capture())]:
        try:
            pull()
        except Exception as exc:                        # noqa: BLE001
            print(f"  ! {label} failed ({exc}); pages will use the cache")

    failed = []
    for name in PAGES:
        try:
            import importlib
            importlib.import_module(f"nfl.site.{name}").generate()
        except Exception:                               # noqa: BLE001
            traceback.print_exc()
            failed.append(name)
    return failed


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--refresh", action="store_true")
    if build_all(refresh=p.parse_args().refresh):
        raise SystemExit(1)
