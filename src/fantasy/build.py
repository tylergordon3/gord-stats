"""
Entry point for the new player-database pipeline.

Usage (from the project root):
    python -m fantasy.build            # build using cached source pulls if present
    python -m fantasy.build --refresh  # re-fetch Sleeper + nflverse from the network
    python src/build.py            # also works (bootstraps sys.path below)
"""
import sys
from pathlib import Path

# Allow running this file directly (python src/build.py) as well as -m fantasy.build.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fantasy.identity.registry import build_registry  # noqa: E402


def main():
    refresh = "--refresh" in sys.argv
    registry, unmatched = build_registry(refresh=refresh)
    if not unmatched.empty:
        print("\nUnmatched (candidates for a manual crosswalk / new-source fix):")
        print(unmatched.to_string(index=False))


if __name__ == "__main__":
    main()
