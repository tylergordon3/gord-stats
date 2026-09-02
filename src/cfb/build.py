"""
Rebuild the college football section, non-interactively.

    python -m cfb.build             # cached data if fresh, then every page
    python -m cfb.build --refresh   # refetch Yahoo + ESPN first

The list of pages lives here and only here (the way fantasy.rebuild.PAGES
works for the NFL section); gordstats.daily's cfb task calls build_all().
"""
import argparse
import traceback

def projection_years() -> list[int]:
    from cfb import projections
    return projections.CURVE_SEASONS


# teams before predictions AND schedule: both link only to team pages that
# exist, and ask the filesystem. The pre-draft pages (draft, draft_live)
# retired when the draft did - draft_review now owns their URL; the scoreboard
# folded into the schedule page, which /cfb/scoreboard/ now redirects to.
PAGES = ["home", "draft_review", "league", "league_power",
         "power", "teams", "predictions", "schedule", "countdown"]


def build_all(refresh: bool = False) -> list[str]:
    """Fetch (or reuse) the data, build every page; returns failed page names."""
    from cfb import espn, gameinfo, odds, players, results, schools, yahoo

    # Fetch up front so one network failure surfaces once, not per page, and a
    # fetch that does fail leaves the pages building from the last good cache.
    for label, pull in [("yahoo league", lambda: yahoo.league(refresh=refresh)),
                        ("yahoo board", lambda: yahoo.board(refresh=refresh)),
                        ("yahoo scoreboard", lambda: yahoo.scoreboard(refresh=refresh)),
                        ("yahoo transactions", lambda: yahoo.transactions(refresh=refresh)),
                        ("yahoo draft", lambda: yahoo.draft_results(refresh=refresh)),
                        ("yahoo rosters", lambda: yahoo.rosters(refresh=refresh)),
                        ("espn schedule", lambda: espn.schedule(refresh=refresh)),
                        # FPI win chance, DraftKings moneyline and the forecast,
                        # per game. Frozen at kickoff: ESPN's post-game payload
                        # drops the projection and prices the moneyline at
                        # -100000, so what is not captured before is gone.
                        ("espn game summaries", lambda: gameinfo.capture(refresh=refresh)),
                        # The live draft board prices players off real seasons,
                        # so it needs the school-name bridge and two years of
                        # CFBD stat lines in the cache before it builds.
                        ("school name map", lambda: schools.load()),
                        ("cfbd player seasons",
                         lambda: [players.season_stats(y) for y in projection_years()]),
                        # The board is only served before kickoff, so capture it on
                        # every build rather than only when a page happens to ask.
                        ("espn betting lines", lambda: odds.capture()),
                        # Archive the predictions too: one scored after kickoff
                        # is not a prediction, so they have to be on record first.
                        ("prediction archive", lambda: results.capture())]:
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
