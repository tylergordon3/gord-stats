# Player database (`src/`)

The new, ID-first player pipeline. Replaces the fuzzy name-matching in
`py/names.py` / `py/player.py`.

## Why it works

Sleeper records already carry `gsis_id` (the NFL's universal player ID), and so
does every nflverse table. nflverse's `load_ff_playerids()` is a ready-made
crosswalk (`sleeper_id ↔ gsis_id ↔ espn_id ↔ yahoo_id ↔ ...`). So we match on
**IDs**, not names:

1. Direct `gsis_id`.
2. Recover `gsis_id` from any other shared ID via the crosswalk.
3. Name + position fallback (only for brand-new players with no ID anywhere).

Result: every player who has ever recorded an NFL stat matches, with no
hand-maintained nickname dictionary.

## Build it

```bash
python -m src.build            # uses cached source pulls if present
python -m src.build --refresh  # re-fetch Sleeper + nflverse
```

Output: `data/players/registry.parquet` — one row per player with every
source's IDs plus a coalesced identity. Load it anywhere with:

```python
from src.identity.registry import load_registry
players = load_registry()
```

## Layout

| File | Role |
|------|------|
| `config.py` | Paths + the identity schema (`ID_COLS`, `IDENTITY_COLS`). |
| `normalize.py` | ID / name cleaning helpers. |
| `sources/base.py` | `PlayerSource` ABC + schema enforcement. |
| `sources/sleeper.py` | Sleeper adapter. |
| `sources/nflverse.py` | nflverse adapter (`load_players` + `load_ff_playerids`). |
| `identity/crosswalk.py` | gsis_id resolution + name fallback. |
| `identity/registry.py` | Merges all sources into the canonical table. |

## Adding a new source (e.g. ESPN, PFF, Yahoo)

1. Create `sources/yoursite.py` subclassing `PlayerSource`:

   ```python
   from src.sources.base import PlayerSource

   class YourSiteSource(PlayerSource):
       name = "yoursite"

       def fetch(self):
           ...  # return raw data

       def normalize(self, raw):
           ...  # return a DataFrame; set source_id + whatever ID_COLS you have
   ```

   Populate as many `ID_COLS` as the site exposes (even just one shared ID like
   `espn_id` is enough for the crosswalk to place the player). Leave the rest
   `None` — `base._finalize` fills gaps and derives the match key.

2. Add it to the source list in `identity/registry.py::build_registry`.

That's it — the matcher is source-agnostic and does not change.
```
