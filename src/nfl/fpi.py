"""
ESPN's Football Power Index for the NFL (data/nfl/fpi_<season>.json): the
computer rating beside ours on /nfl/power/, and the projected record and
playoff odds each team page quotes.

The same public endpoint espn.com's own FPI page reads, the college one's
NFL twin (cfb.site.power), and the same shape: each team's figures arrive as
bare positional arrays, `values` (the numbers) beside `totals` (ESPN's
rendering, "-" where a figure does not exist yet). Positions are read by name
from the payload's own header block, never assumed, so a column ESPN inserts
upstream cannot quietly shift every figure after it.

The raw payload is 250 KB - logos in eight styles per team and a glossary -
and data/ is committed by the Pi, so only what is read is cached (~25 KB):
the header block and each team's identity and figures. An unchanged pull
only touches the file, which is what the staleness check reads, so git sees
a new version when ESPN's numbers move and not every twelve hours.

    python -m nfl.fpi              # refresh if stale, print the table
    python -m nfl.fpi --refresh
"""
import argparse
import json
import os
import time

import requests

from nfl.config import DATA_DIR, SEASON

_URL = "https://site.web.api.espn.com/apis/fitt/v3/sports/football/nfl/powerindex"
# No User-Agent, the cfb.espn convention: ESPN's edge 403s a browser UA from a
# non-browser TLS stack and answers requests' own normally.
_TIMEOUT = 25
MAX_AGE_HOURS = 12

# What the pages read, by category. `fpi` carries the rating, its offence /
# defence / special-teams split (points each adds to the margin against an
# average team), ESPN's rank and the resume ranks; `projections` the
# season simulations.
FIELDS = {
    "fpi": ["fpi", "epaoffense", "epadefense", "epaspecialteams", "fpirank",
            "accomplishmentrank", "avgsosrank", "sosremainingrank",
            "numwins", "numlosses", "numties"],
    "projections": ["projectedw", "projectedl", "probwinout", "probwindiv",
                    "probmakeplayoffs", "probmakedivplayoffs", "probmakeconfchamp",
                    "probmaketitlegame", "probwintitle"],
}
# Where the figures sat when this was written, used only for a payload that
# arrives without its header block: the rating and the projected record are
# the ones worth surviving that.
_FALLBACK = {"fpi": {"fpi": 0, "epaoffense": 1, "epadefense": 2, "epaspecialteams": 3},
             "projections": {"projectedw": 0, "projectedl": 1}}


def cache_path(season: int = SEASON):
    return DATA_DIR / f"fpi_{season}.json"


def _trim(data: dict) -> dict:
    """The payload with only what `rows` reads: the header block, and per team
    its identity and the two categories of figures."""
    keep = set(FIELDS)
    teams = []
    for entry in data.get("teams") or []:
        team = entry.get("team") or {}
        group = team.get("group") or {}
        teams.append({
            "team": {k: team.get(k) for k in ("id", "abbreviation", "displayName",
                                              "shortDisplayName", "name")}
            | {"group": {"name": group.get("name"),
                         "parent": {"abbreviation": (group.get("parent") or {}).get("abbreviation")}}},
            "categories": [{k: c.get(k) for k in ("name", "values", "totals")}
                           for c in entry.get("categories") or [] if c.get("name") in keep],
        })
    return {"requestedSeason": {"year": (data.get("requestedSeason") or {}).get("year")},
            "categories": [{"name": c.get("name"), "names": c.get("names")}
                           for c in data.get("categories") or [] if c.get("name") in keep],
            "teams": teams}


def fetch(refresh: bool = False, season: int = SEASON) -> dict:
    """The trimmed payload, pulled again when the cache is older than
    MAX_AGE_HOURS (or `refresh`); the cache as it stands if ESPN fails."""
    cache = cache_path(season)
    fresh = cache.exists() and time.time() - cache.stat().st_mtime < MAX_AGE_HOURS * 3600
    if fresh and not refresh:
        return json.loads(cache.read_text(encoding="utf-8"))
    try:
        r = requests.get(_URL, params={"region": "us", "lang": "en", "limit": 40,
                                       "season": season}, timeout=_TIMEOUT)
        r.raise_for_status()
        data = _trim(r.json())
        assert data["teams"], "no teams in FPI payload"
    except Exception as exc:                            # noqa: BLE001
        if not cache.exists():
            raise
        print(f"  ! NFL FPI fetch failed ({exc}); using the cached copy")
        return json.loads(cache.read_text(encoding="utf-8"))
    text = json.dumps(data, separators=(",", ":"))
    if cache.exists() and cache.read_text(encoding="utf-8") == text:
        os.utime(cache)
    else:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(text, encoding="utf-8")
    return data


def field_index(data: dict) -> dict:
    """{category: {field name: position}}, from the payload's own header."""
    index = {c.get("name"): {n: i for i, n in enumerate(c.get("names") or [])}
             for c in data.get("categories") or []}
    return {cat: index.get(cat) or _FALLBACK[cat] for cat in FIELDS}


def figures(entry: dict, index: dict) -> dict:
    """{field: float or None} for one team, None where ESPN prints "-"."""
    out = {}
    for cat_name, fields in FIELDS.items():
        cat = next((c for c in entry.get("categories") or [] if c.get("name") == cat_name), {})
        values, totals = cat.get("values") or [], cat.get("totals") or []
        for field in fields:
            pos = index[cat_name].get(field)
            shown = str(totals[pos]).strip() if pos is not None and pos < len(totals) else "-"
            if pos is None or pos >= len(values) or shown in ("-", "") or values[pos] is None:
                out[field] = None
                continue
            try:
                out[field] = float(values[pos])
            except (TypeError, ValueError):
                out[field] = None
    return out


def rows(data: dict = None) -> list:
    """One dict per team - ESPN id, abbreviation, names, division and every
    figure - best FPI first. `data` defaults to the cached pull."""
    data = fetch() if data is None else data
    index = field_index(data)
    out = []
    for entry in data.get("teams") or []:
        team = entry.get("team") or {}
        figs = figures(entry, index)
        if figs["fpi"] is None or team.get("id") is None:
            continue
        group = team.get("group") or {}
        out.append({"id": str(team["id"]), "abbr": team.get("abbreviation"),
                    "full": team.get("displayName") or team.get("shortDisplayName"),
                    "div": group.get("name"),
                    "conf": (group.get("parent") or {}).get("abbreviation"), **figs})
    out.sort(key=lambda t: -t["fpi"])
    # ESPN's own rank where it gives one; the order otherwise.
    for i, t in enumerate(out, 1):
        t["rank"] = int(t["fpirank"]) if t.get("fpirank") else i
    return out


def by_id(refresh: bool = False) -> dict:
    """{ESPN team id: row}, or {} when there is no pull and ESPN is down - the
    pages stand without FPI."""
    try:
        return {t["id"]: t for t in rows(fetch(refresh=refresh))}
    except Exception as exc:                            # noqa: BLE001
        print(f"  ! NFL FPI unavailable ({exc})")
        return {}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--refresh", action="store_true")
    for t in rows(fetch(refresh=p.parse_args().refresh)):
        print(f"{t['rank']:>2} {t['abbr']:<4} {t['fpi']:+5.1f}  "
              f"{t['projectedw'] or 0:4.1f}-{t['projectedl'] or 0:4.1f}  "
              f"playoffs {t['probmakeplayoffs'] or 0:5.1f}%  SB {t['probwintitle'] or 0:4.1f}%")
