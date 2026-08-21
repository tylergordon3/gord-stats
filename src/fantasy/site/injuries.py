"""
All-Time Injury Impacts section of the homepage.

Aggregates per-season games missed - by drafted players (all 14 weeks) and by
waiver / free-agent pickups held a substantial stretch (only the weeks they were
actually rostered; see fantasy.site.draft.PICKUP_MIN_WEEKS) - into a by-season stacked
bar chart and a league table, and weights each injury by how much the player
mattered: not every missed game hurts equally, so a round-1/2 pick or a player
producing at weekly-starter pace relative to his position-mates counts as
"high-impact", and every absence is also priced in estimated points lost
(games missed x median weekly score).

`impact_detail()` is the reusable classifier — import it from other pages as
injury weighting spreads across the site.

Data sources: the archive (data/historical.json -> per-season `missing_df` and
`injury_detail_df`, both written by fantasy.site.draft.save_games_missed).
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

from fantasy.config import DATA_DIR, FANTASY_REG_WEEKS, ROSTER_NAMES  # noqa: E402
from fantasy.site import styles                                         # noqa: E402
from fantasy.site.draft import PLAYABLE_WEEKS                           # noqa: E402

ARCHIVE_PATH = DATA_DIR / "historical.json"

REG_WEEKS = FANTASY_REG_WEEKS   # fantasy regular season, matches fantasy.site.draft
PREMIUM_ROUNDS = 2              # drafted this early = high-impact regardless of PPG
# Starter-level scoring is judged against position-mates, not a fixed PPG line:
# a player qualifies when his median weekly score reaches this percentile of
# drafted players at his position (per season, when a season column is present).
# The median (not the mean) is the yardstick so two spike weeks before an injury
# don't read as starter-level production, and a minimum share of the season must
# be played before the sample counts at all.
STARTER_PCTL = 0.75
MIN_GAMES_SHARE = 0.25


def impact_detail(detail: pd.DataFrame) -> pd.DataFrame:
    """Add injury-impact columns to a per-player `injury_detail_df` frame.

    Adds: Games Missed, Med PPG (median weekly score), High Impact (premium
    draft capital OR starter-level median scoring relative to drafted
    position-mates, with a minimum games-played sample), and Est. Pts Lost
    (games missed x median weekly score). Players who never played have no
    scoring sample, so their Est. Pts Lost is 0 — draft capital is the only
    signal that flags them.
    """
    out = detail.copy()
    # Pickup rows carry their own accountability window ("Window Weeks", the
    # weeks they were actually on the roster) and season-wide scoring sample
    # ("Sample Games"). Drafted rows - and archives from before pickups were
    # included - default to the full regular season / their own games played.
    # Archives from before the bye was accounted for carry no window at all;
    # they get the playable season, not the full one.
    if "Window Weeks" not in out.columns:
        out["Window Weeks"] = PLAYABLE_WEEKS
    out["Window Weeks"] = out["Window Weeks"].fillna(PLAYABLE_WEEKS)
    if "Source" not in out.columns:
        out["Source"] = "Drafted"
    out["Source"] = out["Source"].fillna("Drafted")
    sample = (out["Sample Games"].fillna(out["Games Played"])
              if "Sample Games" in out.columns else out["Games Played"])

    out["Games Missed"] = (out["Window Weeks"] - out["Games Played"]).astype(int)
    if "Med PPG" not in out.columns:    # seasons archived before the median existed
        out["Med PPG"] = out["Pts."] / out["Games Played"].where(out["Games Played"] > 0)
    out["Med PPG"] = out["Med PPG"].fillna(0.0)

    qualified = sample >= REG_WEEKS * MIN_GAMES_SHARE
    group_keys = (["season"] if "season" in out.columns else []) + ["Pos."]
    # The starter-pace bar stays defined by drafted position-mates, but is
    # applied to every row - a pickup scoring like a drafted starter counts.
    pool = out[qualified & out["Source"].eq("Drafted")]
    cutoffs = pool.groupby(group_keys)["Med PPG"].quantile(STARTER_PCTL)
    cutoff = pd.Series(
        cutoffs.reindex(out.set_index(group_keys).index).values, index=out.index)
    starter = qualified & (out["Med PPG"] >= cutoff)

    out["High Impact"] = (out["round"] <= PREMIUM_ROUNDS) | starter
    out["Est. Pts Lost"] = out["Games Missed"] * out["Med PPG"]
    return out


def _load_detail():
    """All-seasons per-player impact frame, skipping seasons archived before
    injury_detail_df existed. May be empty."""
    with open(ARCHIVE_PATH, encoding="utf-8") as f:
        history = json.load(f)
    frames = []
    for szn, stats in history.items():
        if "injury_detail_df" not in stats:
            continue
        df = pd.DataFrame(stats["injury_detail_df"])
        df["season"] = szn
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    return impact_detail(pd.concat(frames, ignore_index=True))


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


def _table(missing: pd.DataFrame, detail: pd.DataFrame):
    grouped = missing.groupby("roster_id")[["Total Games Missed", "tot_games"]].sum().reset_index()
    grouped["% of Games Missed"] = (
        grouped["Total Games Missed"] / grouped["tot_games"]
    ).map("{:.2%}".format)
    grouped["Team"] = grouped["roster_id"].map(ROSTER_NAMES)

    cols = ["Team", "Total Games Missed", "% of Games Missed"]
    gradient_cols = ["Total Games Missed"]
    if not detail.empty:
        impact = detail.groupby("roster_id").agg(**{
            "High-Impact Games Missed": ("Games Missed",
                                         lambda s: s[detail.loc[s.index, "High Impact"]].sum()),
            "Est. Pts Lost": ("Est. Pts Lost", "sum"),
        }).reset_index()
        grouped = grouped.merge(impact, on="roster_id", how="left")
        grouped["High-Impact Games Missed"] = grouped["High-Impact Games Missed"].fillna(0).astype(int)
        grouped["Est. Pts Lost"] = grouped["Est. Pts Lost"].fillna(0.0).round(0).astype(int)
        cols += ["High-Impact Games Missed", "Est. Pts Lost"]
        gradient_cols += ["High-Impact Games Missed", "Est. Pts Lost"]

    grouped = grouped.sort_values(
        "Est. Pts Lost" if "Est. Pts Lost" in cols else "Total Games Missed", ascending=False)
    return styles.default_style(grouped[cols], gradient_cols, cmap="RdYlGn_r")


def top_injuries(detail: pd.DataFrame, n: int = 12):
    """Styled table of the n most damaging individual injuries by Est. Pts Lost,
    or None when no per-player detail has been archived yet."""
    if detail.empty:
        return None
    hurt = detail[detail["Games Missed"] > 0].copy()
    hurt = hurt.sort_values("Est. Pts Lost", ascending=False).head(n)
    hurt["Med PPG"] = hurt["Med PPG"].map("{:.1f}".format)
    hurt["Est. Pts Lost"] = hurt["Est. Pts Lost"].round(0).astype(int)
    hurt = hurt.rename(columns={"season": "Season"})
    hurt = hurt[["Season", "Name", "Pos.", "Owner", "Pick", "Med PPG",
                 "Games Missed", "Est. Pts Lost"]]
    return styles.default_style(hurt, ["Est. Pts Lost"], cmap="RdYlGn_r")


def all_time_missed():
    """Return (base64 chart png, styled league table, styled top-injuries table
    or None) for the injury section."""
    missing, seasons = _load_missing()
    detail = _load_detail()
    return _chart(missing, seasons), _table(missing, detail), top_injuries(detail)
