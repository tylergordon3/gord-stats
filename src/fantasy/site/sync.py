"""
Sync your league (docs/fantasy/sync/) - the page itself is
gordstats.league_sync, shared so the college side can mount the same one.

    python -m fantasy.site.sync
"""
from fantasy import paths
from gordstats import league_sync


def generate():
    league_sync.generate(paths.WEB_SYNC)


if __name__ == "__main__":
    generate()
