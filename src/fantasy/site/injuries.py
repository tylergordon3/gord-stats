"""
All-Time Injury Impacts section of the homepage.

Aggregates per-season "games missed by drafted players" into a by-season stacked
bar chart and a league table.

Data source: the archive (data/historical.json -> per-season `missing_df`).
NOTE: that per-season missing_df is still produced by the legacy draft pipeline;
migrating its *computation* belongs with the draft page, not the homepage.
"""
import base64
import io
import json

import matplotlib
matplotlib.use("Agg")          # non-interactive backend (no Qt/GUI needed)
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd              # noqa: E402

from src.config import DATA_DIR, ROSTER_NAMES  # noqa: E402
from src.site import styles                      # noqa: E402

ARCHIVE_PATH = DATA_DIR / "historical.json"


def _load_missing():
    """Return (all-seasons missing_df, ordered season keys) from the archive."""
    with open(ARCHIVE_PATH, encoding="utf-8") as f:
        history = json.load(f)
    seasons = list(history.keys())
    frames = []
    for szn in seasons:
        df = pd.DataFrame(history[szn]["missing_df"])
        df["season"] = szn
        frames.append(df)
    return pd.concat(frames, ignore_index=True), seasons


def _chart(missing: pd.DataFrame, seasons) -> str:
    """Stacked bar of games missed per team, stacked by season -> base64 png."""
    pivot = (
        missing.assign(Team=missing["roster_id"].map(ROSTER_NAMES))
        .pivot_table(index="Team", columns="season",
                     values="Total Games Missed", aggfunc="sum")
        .reindex(columns=seasons)
        .reset_index()
    )
    pivot.plot(x="Team", kind="bar", stacked=True,
               title="Games Missed for Injury by Season", rot=45)
    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight")
    buf.seek(0)
    img = base64.b64encode(buf.read()).decode("utf-8")
    buf.close()
    plt.close()
    return img


def _table(missing: pd.DataFrame):
    grouped = missing.groupby("roster_id")[["Total Games Missed", "tot_games"]].sum().reset_index()
    grouped["% of Games Missed"] = (
        grouped["Total Games Missed"] / grouped["tot_games"]
    ).map("{:.2%}".format)
    grouped["Team"] = grouped["roster_id"].map(ROSTER_NAMES)
    grouped = grouped.sort_values("Total Games Missed", ascending=False)
    grouped = grouped[["Team", "Total Games Missed", "% of Games Missed"]]
    return styles.default_style(grouped, ["Total Games Missed"], cmap="RdYlGn_r")


def all_time_missed():
    """Return (base64 chart png, styled league table) for the injury section."""
    missing, seasons = _load_missing()
    return _chart(missing, seasons), _table(missing)
