"""
Bridge exposing the new src/ pipeline to the legacy py/ scripts (TEMPORARY).

Adds the project root to sys.path so `import src...` resolves no matter how a
py/ script is launched, then re-exports the compatibility helpers. Legacy modules
should do `import src_bridge as bridge` and call `bridge.sleeper_players()`.

Remove once py/ is fully migrated into src/.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.compat import sleeper_players             # noqa: E402,F401
from src.identity.registry import load_registry    # noqa: E402,F401
from src.identity.history import load_player_seasons  # noqa: E402,F401
