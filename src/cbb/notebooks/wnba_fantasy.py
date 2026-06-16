"""
wnba_fantasy_fetch.py
---------------------
Fetches ESPN Fantasy WNBA league data and saves it to JSON.

Looks for ESPN auth cookies in this order:
  1. ESPN_S2 and SWID in your .env file  (recommended)
  2. Cookies from your logged-in Chrome / Chromium / Firefox browser

Usage:
    python wnba_fantasy_fetch.py                  # fetch and save
    python wnba_fantasy_fetch.py --out /some/path/fantasy.json
    python wnba_fantasy_fetch.py --league 1234567 --season 2026

How to get ESPN_S2 and SWID from your browser:
    1. Log into fantasy.espn.com
    2. Open DevTools → Application → Cookies → https://www.espn.com
    3. Copy the values for espn_s2 and SWID into your .env:
          ESPN_S2=your_value_here
          SWID={your-swid-here}

Requires:
    pip install requests python-dotenv browser-cookie3
"""

import argparse
import json
import os
import sys
import requests
import browser_cookie3
from datetime import datetime
from dotenv import load_dotenv
from pathlib import Path
from zoneinfo import ZoneInfo
from cbb.lib import paths

# ── Config ────────────────────────────────────────────────────────────────────
DEBUG = False
load_dotenv()

LEAGUE_ID        = 1039832288
SEASON           = 2026
DEFAULT_OUT_PATH = paths.WNBA_DATA / "wnba_fantasy_data.json"
ET               = ZoneInfo("America/New_York")

VIEWS = ["mTeam", "mRoster", "mSettings", "mMatchup", "mScoreboard"]

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept":     "application/json,text/plain,*/*",
}

# ── Auth ──────────────────────────────────────────────────────────────────────

def get_espn_cookies() -> dict:
    """
    Returns {"espn_s2": ..., "SWID": ...}.

    Tries .env first, then falls back to reading from your logged-in browser.
    """
    espn_s2 = os.getenv("ESPN_S2")
    swid    = os.getenv("SWID")

    if espn_s2 and swid:
        if DEBUG:
            print("✓ Using ESPN cookies from .env")
        return {"espn_s2": espn_s2, "SWID": swid}

    print("ESPN_S2/SWID not in .env — trying browser cookies...")

    attempts = [
        ("Chrome (default)", lambda: browser_cookie3.chrome(domain_name=".espn.com")),
        ("Chromium",         lambda: browser_cookie3.chromium(domain_name=".espn.com")),
        ("Firefox",          lambda: browser_cookie3.firefox(domain_name=".espn.com")),
    ]

    for name, fn in attempts:
        try:
            cj      = fn()
            cookies = {c.name: c.value for c in cj}
            espn_s2 = cookies.get("espn_s2", "")
            swid    = cookies.get("SWID", "")
            if DEBUG:
                print(f"  {name}: espn_s2={'✓' if espn_s2 else '✗'}  SWID={'✓' if swid else '✗'}")
            if espn_s2 and swid:
                return {"espn_s2": espn_s2, "SWID": swid}
        except Exception as e:
            print(f"  {name}: failed — {e}")

    raise RuntimeError(
        "\nCould not find ESPN cookies. Try one of:\n"
        "  1. Add ESPN_S2 and SWID to your .env file\n"
        "     (grab from browser DevTools → Application → Cookies → espn.com)\n"
        "  2. Launch Chrome with --password-store=basic, log into ESPN, re-run:\n"
        "     google-chrome --password-store=basic"
    )

# ── Fetch ─────────────────────────────────────────────────────────────────────

def fetch_league_data(league_id: int = LEAGUE_ID, season: int = SEASON) -> dict:
    """Fetch full league data from ESPN Fantasy API."""
    url = (
        f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/wfba/"
        f"seasons/{season}/segments/0/leagues/{league_id}"
    )
    headers = {
        **HEADERS,
        "Referer": f"https://fantasy.espn.com/womens-basketball/league?leagueId={league_id}",
        "Origin":  "https://fantasy.espn.com",
    }
    params = [("view", v) for v in VIEWS]

    cookies = get_espn_cookies()
    session = requests.Session()
    session.cookies.set("espn_s2", cookies["espn_s2"], domain=".espn.com")
    session.cookies.set("SWID",    cookies["SWID"],    domain=".espn.com")

    print(f"\nFetching league {league_id} ({season} season)...")
    r = session.get(url, params=params, headers=headers, allow_redirects=False, timeout=20)

    if DEBUG:
        print(f"Status: {r.status_code}  |  Content-Type: {r.headers.get('content-type', 'unknown')}")

    if r.status_code in (301, 302, 303, 307, 308):
        raise RuntimeError(
            f"Redirected by ESPN ({r.headers.get('location')}) — "
            "cookies are likely invalid or expired."
        )

    if "application/json" not in r.headers.get("content-type", ""):
        raise RuntimeError(f"ESPN did not return JSON:\n{r.text[:500]}")

    r.raise_for_status()
    return r.json()

# ── Save ──────────────────────────────────────────────────────────────────────

def fetch_and_save(
    league_id: int  = LEAGUE_ID,
    season:    int  = SEASON,
    out_path:  Path = DEFAULT_OUT_PATH,
) -> Path:
    """Fetch league data, wrap with metadata, and write to JSON."""
    data       = fetch_league_data(league_id, season)
    pulled_at  = datetime.now(ET)

    output = {
        "metadata": {
            "pulled_at":          pulled_at.isoformat(),
            "pulled_at_readable": pulled_at.strftime("%Y-%m-%d %I:%M:%S %p %Z"),
            "league_id":          league_id,
            "season":             season,
        },
        "data": data,
    }

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Saved → {pulled_at.strftime('%Y-%m-%d %I:%M:%S %p %Z')}")
    return out_path

# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch ESPN Fantasy WNBA league data and save to JSON."
    )

    parser.add_argument(
        "--league",
        type=int,
        default=LEAGUE_ID,
        help=f"ESPN Fantasy league ID (default: {LEAGUE_ID})",
    )

    parser.add_argument(
        "--season",
        type=int,
        default=SEASON,
        help=f"Season year (default: {SEASON})",
    )

    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT_PATH,
        help=f"Output JSON file path (default: {DEFAULT_OUT_PATH})",
    )

    return parser


def cli(argv=None) -> Path:
    """
    CLI entry point.

    Can be called from command line:
        python wnba_fantasy_fetch.py

    Or from another Python file:
        from cbb.wnba.wnba_fantasy_fetch import cli
        cli(["--league", "1234567", "--season", "2026"])
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    return fetch_and_save(
        league_id=args.league,
        season=args.season,
        out_path=args.out,
    )


def main(argv=None) -> int:
    """
    Main entry point.

    Returns:
        0 on success
        1 on handled RuntimeError
    """
    try:
        cli(argv)
        return 0

    except RuntimeError as e:
        print(f"\n✗ Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())