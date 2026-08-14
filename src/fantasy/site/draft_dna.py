"""
Draft DNA - owner-specific draft habits across every draft (src/).

The Manager Draft Report scores *how well* each manager drafts. This page asks a
different question: *how* do they draft? Five sections:

  * Positional Clock   - when each manager takes their first QB / RB / WR / TE,
                         and the earliest they have ever gone at each spot.
  * Early Blueprint    - what the first five rounds look like for each manager.
  * Availability       - how much of a hit rate is drafting and how much is the
                         player simply staying on the field.
  * Champion Blueprint - how the three title-winning drafts differed from the field.
  * Report Cards       - a per-manager card with signature habits and outlier picks.

Everything here is drawn from three drafts per manager, which is a small sample -
the page says so, and every table carries its own counts.

    python -m src.site.draft_dna
"""
import re

import pandas as pd

from src.config import FORMAL_SEASON, LEAGUE_IDS, ROOT, ROSTER_NAMES
from src.league.playoffs import champion_roster
from src.site import adp, layout, styles
from src.site.frontmatter import add_front_matter

POS = ["QB", "RB", "WR", "TE"]
_GRID = [styles.GRID_TD, styles.GRID_TH, styles.TABLE_STYLE]

_CSS = """<style>
p.caveat{border-left:3px solid #b9c4d0;padding:8px 12px;background:#f2f5f8;font-size:14px;
  color:#3c4a58;border-radius:0 4px 4px 0}
</style>"""

# Roughly how many players at each position start league-wide in a given week:
# 10 teams x (1 QB, 2 RB, 2 WR, 1 TE, 2 FLEX). A pick that finishes inside its
# position's cutoff was a genuine weekly starter - what we count as a "hit".
STARTERS = {"QB": 10, "RB": 24, "WR": 24, "TE": 10}
EARLY_ROUNDS = 5
# Smallest gap from the league average worth calling a positional habit (rounds).
_HABIT_MIN = 0.5

# Availability. src.site.draft counts, for each drafted player, the weeks in the
# first GAMES of the season where they recorded a stat line; anything short of
# that is a week their manager got nothing. HEALTHY_MIN (missed no more than two)
# is the bar for "was available all year", used for the health-adjusted hit rate.
GAMES = 13
HEALTHY_MIN = 11


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #

def _display_name(series: pd.Series) -> pd.Series:
    """Split the CamelCase join key back into words ("JahmyrGibbs" -> "Jahmyr Gibbs")."""
    return series.str.replace(r"(?<=[a-z])(?=[A-Z])", " ", regex=True)


def all_picks() -> pd.DataFrame:
    """Every pick from every draft, tagged with Season, Manager and champion flag.

    Unlike adp.matched_with_manager this keeps picks with no ADP match, because
    positional timing questions ("when does a manager take a QB?") need the full draft.
    Kickers and defenses are already excluded upstream by src.site.draft.
    """
    frames = []
    for season_str in LEAGUE_IDS:
        m = adp._picks_with_adp(season_str).copy()
        m["Season"] = FORMAL_SEASON[season_str]
        m["Manager"] = m["roster_id"].map(ROSTER_NAMES)
        m["Champ"] = m["roster_id"] == champion_roster(season_str)
        frames.append(m)

    df = pd.concat(frames, ignore_index=True)
    df["Player"] = df["adp_player"].fillna(_display_name(df["Name"]))
    df["Hit"] = df.apply(lambda r: r["final_pos_rank"] <= STARTERS.get(r["Pos."], 24), axis=1)
    df["Missed"] = GAMES - df["Games Played"]
    df["Healthy"] = df["Games Played"] >= HEALTHY_MIN

    # Positional, not overall: outcomes measured on the overall board reward
    # QBs, who out-score every other position by construction. Comparing the
    # positional draft rank to the actual positional finish is position-fair.
    # 999 is src.site.draft's sentinel for a player who never took the field.
    played = df["final_pos_rank"] < 900
    df["PosVsPick"] = (df["draft_pos_rank"] - df["final_pos_rank"]).where(played)
    # Overall finish against overall draft slot (+ = outperformed the pick).
    df["VsPick"] = df["overall_pick"] - df["final_rank"]
    return df


def _first_at_position(df) -> pd.DataFrame:
    """One row per (manager, season, position): their first pick there."""
    return (df[df["Pos."].isin(POS)]
            .sort_values("overall_pick")
            .groupby(["Manager", "Season", "Champ", "Pos."], as_index=False)
            .first())


def _pivot(df, values, aggfunc, index="Manager"):
    p = df.pivot_table(index=index, columns="Pos.", values=values, aggfunc=aggfunc)
    p = p.reindex(columns=[c for c in POS if c in p.columns])
    p.columns.name = None
    return p


# --------------------------------------------------------------------------- #
# Section 1 - positional clock
# --------------------------------------------------------------------------- #

def _clock_tables(first):
    avg = _pivot(first, "round", "mean").round(1)
    earliest = _pivot(first, "round", "min").astype("Int64")
    latest = _pivot(first, "round", "max").astype("Int64")

    # Each position on its own scale: green = goes earliest, red = waits longest.
    heat = (avg.style.format("{:.1f}", na_rep="—")
            .background_gradient(cmap="RdYlGn_r", axis=0)
            .set_table_styles(_GRID, overwrite=False)
            .set_table_attributes('class="sticky-table"')).to_html()

    detail = earliest.astype(str) + " - " + latest.astype(str)
    detail = (detail.style.set_table_styles(_GRID, overwrite=False)
              .set_table_attributes('class="sticky-table"')).to_html()
    return avg, earliest, heat, detail


# A floor of round 1 is true for almost everyone at RB/WR, so it says nothing.
_FLOOR_MIN = 2


def _clock_notes(avg, earliest) -> str:
    """Per-position callouts: who reaches, who waits, and the highest floor."""
    league = avg.mean()
    lines = []
    for pos in [p for p in POS if p in avg.columns]:
        col = avg[pos].dropna()
        if col.empty:
            continue
        note = (f"<li><strong>{pos}</strong> - league average first {pos} lands in round "
                f"{league[pos]:.1f}. <strong>{col.idxmin()}</strong> goes earliest "
                f"(round {col.min():.1f} on average), <strong>{col.idxmax()}</strong> waits "
                f"longest (round {col.max():.1f}).")
        floors = earliest[pos].dropna()
        if not floors.empty and floors.max() >= _FLOOR_MIN:
            note += (f" Highest floor: <strong>{floors.idxmax()}</strong> has never opened at "
                     f"{pos} before round {int(floors.max())}.")
        lines.append(note + "</li>")
    return f"<ul>{''.join(lines)}</ul>"


def positional_clock(df) -> str:
    first = _first_at_position(df)
    avg, earliest, heat, detail = _clock_tables(first)
    n = first["Season"].nunique()

    floor_lines = []
    for mgr in earliest.index:
        parts = [f"{pos} before round {int(earliest.loc[mgr, pos])}"
                 for pos in POS if pos in earliest.columns
                 and pd.notna(earliest.loc[mgr, pos]) and earliest.loc[mgr, pos] >= _FLOOR_MIN]
        if parts:
            floor_lines.append(f"<li><strong>{mgr}</strong> has never taken a "
                               + ", ".join(parts) + ".</li>")
    floors = "".join(floor_lines)

    return (
        f"<p>The round each manager spends their <strong>first</strong> pick at each position, "
        f"averaged over {n} drafts. Colored down each column: "
        "<strong>green = goes earliest</strong>, <strong>red = waits longest</strong>.</p>"
        f"<div class='table-scroll'>{heat}</div>"
        + _clock_notes(avg, earliest)
        + layout.details("Earliest - latest round of the first pick at each position",
                         f"<div class='table-scroll'>{detail}</div>")
        + layout.details(f"Hard floors: the earliest each manager has ever gone ({n} drafts)",
                         f"<ul>{floors}</ul>")
    )


# --------------------------------------------------------------------------- #
# Section 2 - early-round blueprint
# --------------------------------------------------------------------------- #

def early_blueprint(df) -> str:
    early = df[df["round"] <= EARLY_ROUNDS]
    counts = _pivot(early, "overall_pick", "count").fillna(0).astype(int)
    n_drafts = df["Season"].nunique()
    total = EARLY_ROUNDS * n_drafts

    grid = (counts.style.format("{:d}")
            .background_gradient(cmap="Blues", axis=None)
            .set_table_styles(_GRID, overwrite=False)
            .set_table_attributes('class="sticky-table"')).to_html()

    # What each manager opens with.
    opener = df.sort_values("overall_pick").groupby(["Manager", "Season"], as_index=False).first()
    opens = _pivot(opener, "overall_pick", "count").fillna(0).astype(int)
    opens_html = (opens.style.format("{:d}")
                  .background_gradient(cmap="Blues", axis=None)
                  .set_table_styles(_GRID, overwrite=False)
                  .set_table_attributes('class="sticky-table"')).to_html()

    share = (counts.div(counts.sum(axis=1), axis=0) * 100).round(0)
    rb_heavy = share["RB"].idxmax() if "RB" in share else None
    wr_heavy = share["WR"].idxmax() if "WR" in share else None
    note = ""
    if rb_heavy and wr_heavy:
        note = (f"<p><strong>{rb_heavy}</strong> is the most run-heavy start "
                f"({share.loc[rb_heavy, 'RB']:.0f}% of early picks are RBs); "
                f"<strong>{wr_heavy}</strong> the most receiver-heavy "
                f"({share.loc[wr_heavy, 'WR']:.0f}%).</p>")

    return (
        f"<p>Positions taken in the first {EARLY_ROUNDS} rounds, across all {n_drafts} drafts "
        f"({total} picks per manager).</p>"
        f"<div class='table-scroll'>{grid}</div>{note}"
        f"<h2>What they open with</h2>"
        f"<p>Position of each manager's very first pick, counted over {n_drafts} drafts.</p>"
        f"<div class='table-scroll'>{opens_html}</div>"
    )


# --------------------------------------------------------------------------- #
# Section 3 - availability
# --------------------------------------------------------------------------- #

_BUCKETS = [(-1, 6, f"6 or fewer of {GAMES}"), (6, 10, f"7-10 of {GAMES}"),
            (10, GAMES, f"11-{GAMES} of {GAMES}")]


def _availability_buckets(df) -> pd.DataFrame:
    rows = []
    for lo, hi, label in _BUCKETS:
        sub = df[(df["Games Played"] > lo) & (df["Games Played"] <= hi)]
        rows.append({"Weeks active": label, "Picks": len(sub),
                     "Became a starter": round(sub["Hit"].mean() * 100) if len(sub) else 0})
    return pd.DataFrame(rows)


def health_table(df) -> pd.DataFrame:
    """Per manager: games lost, raw hit rate, and the hit rate among healthy picks."""
    healthy = df[df["Healthy"]]
    g = df.groupby("Manager").agg(Picks=("Hit", "count"), Missed=("Missed", "sum"),
                                  Raw=("Hit", "mean")).reset_index()
    h = healthy.groupby("Manager").agg(HealthyPicks=("Hit", "count"),
                                       HealthyHit=("Hit", "mean")).reset_index()
    g = g.merge(h, on="Manager", how="left")
    g["Raw"] = (g["Raw"] * 100).round(0)
    g["HealthyHit"] = (g["HealthyHit"] * 100).round(0)
    g["Swing"] = (g["HealthyHit"] - g["Raw"]).round(0)
    # Kept off the rendered table; drives the "who moves" narrative below.
    g["RawRank"] = g["Raw"].rank(method="min", ascending=False).astype(int)
    g["AdjRank"] = g["HealthyHit"].rank(method="min", ascending=False).astype(int)
    g["Move"] = g["AdjRank"] - g["RawRank"]
    return g.sort_values("HealthyHit", ascending=False).rename(columns={
        "Missed": "Weeks Lost", "Raw": "Starter Hit %", "HealthyPicks": "Healthy Picks",
        "HealthyHit": "Healthy Hit %", "Swing": "Swing"})


def availability(df) -> str:
    buckets = _availability_buckets(df)
    bucket_html = (buckets.style.hide(axis="index")
                   .format({"Became a starter": "{:.0f}%"})
                   .background_gradient(cmap="RdYlGn", subset=["Became a starter"])
                   .set_table_styles(_GRID, overwrite=False)
                   .set_table_attributes('class="sticky-table"')).to_html()

    health = health_table(df)
    shown = health.drop(columns=["RawRank", "AdjRank", "Move"])
    health_html = (shown.style.hide(axis="index")
                   .format({"Starter Hit %": "{:.0f}%", "Healthy Hit %": "{:.0f}%",
                            "Swing": "{:+.0f}"})
                   .background_gradient(cmap="RdYlGn_r", subset=["Weeks Lost"])
                   .background_gradient(cmap="RdYlGn", subset=["Healthy Hit %"])
                   .set_table_styles(_GRID, overwrite=False)
                   .set_table_attributes('class="sticky-table"')).to_html()

    worst = health.loc[health["Weeks Lost"].idxmax()]
    best = health.loc[health["Weeks Lost"].idxmin()]
    top = health.iloc[0]
    dead = buckets.iloc[0]

    return (
        f"<p>Every hit rate on this page is really two things at once: whether the pick was any "
        f"good, and whether they stayed on the field. This section separates them. "
        f"<strong>Weeks active</strong> counts the weeks in the first {GAMES} where a drafted "
        f"player recorded a stat line &mdash; a week they missed is a week their manager got "
        f"nothing from that roster spot.</p>"
        f"<h2>Availability decides almost everything</h2>"
        f"<div class='table-scroll'>{bucket_html}</div>"
        f"<p>Of the {dead['Picks']} picks who were active for {dead['Weeks active'].lower()} weeks, "
        f"<strong>{dead['Became a starter']:.0f}%</strong> finished as a weekly starter. Availability "
        f"isn't a factor in draft success so much as a precondition for it.</p>"
        f"<h2>Health-adjusted drafting</h2>"
        f"<p><strong>Healthy Hit %</strong> is the hit rate counting only picks who were active for "
        f"at least {HEALTHY_MIN} of {GAMES} weeks &mdash; it asks how good the picks were when they "
        f"were actually available, which is the part a manager controls.</p>"
        f"<div class='table-scroll'>{health_html}</div>"
        f"<p><strong>{worst['Manager']}</strong>'s picks sat out "
        f"{int(worst['Weeks Lost'])} player-weeks against {int(best['Weeks Lost'])} for "
        f"<strong>{best['Manager']}</strong> &mdash; a gap of "
        f"{(worst['Weeks Lost'] - best['Weeks Lost']) / GAMES:.1f} full player-seasons across "
        f"three drafts, none of it a drafting decision. Adjusting for it puts "
        f"<strong>{top['Manager']}</strong> on top at {top['Healthy Hit %']:.0f}%.</p>"
        + _movers(health)
        + _health_caveat()
    )


def _movers(health) -> str:
    """Who the adjustment helps and hurts, and whether it closes the field up."""
    raw_spread = health["Starter Hit %"].max() - health["Starter Hit %"].min()
    adj_spread = health["Healthy Hit %"].max() - health["Healthy Hit %"].min()
    faller = health.loc[health["Move"].idxmax()]
    riser = health.loc[health["Move"].idxmin()]

    parts = []
    if faller["Move"] > 0:
        parts.append(
            f"<strong>{faller['Manager']}</strong> loses the most, sliding from "
            f"{_ordinal(int(faller['RawRank']))} to {_ordinal(int(faller['AdjRank']))} &mdash; "
            f"only {int(faller['Weeks Lost'])} player-weeks lost meant there was little "
            f"bad luck inflating their raw number to begin with")
    if riser["Move"] < 0:
        parts.append(
            f"<strong>{riser['Manager']}</strong> gains the most, "
            f"{_ordinal(int(riser['RawRank']))} to {_ordinal(int(riser['AdjRank']))}")

    verdict = ("widens" if adj_spread > raw_spread else
               "narrows" if adj_spread < raw_spread else "leaves unchanged")
    tail = (f"What it does not do is close the field up: the gap between best and worst "
            f"{verdict} from {raw_spread:.0f} points to {adj_spread:.0f}. Bad luck explains a "
            f"lot of the middle of this table and none of the bottom of it."
            if adj_spread >= raw_spread else
            f"It also pulls the field together: the gap between best and worst {verdict} from "
            f"{raw_spread:.0f} points to {adj_spread:.0f}.")

    return f"<p>{'; '.join(parts)}. {tail}</p>" if parts else f"<p>{tail}</p>"


def _health_caveat() -> str:
    return (
        "<p class='caveat'><strong>What this does and doesn't measure.</strong> Weeks active "
        "counts absences of every kind &mdash; injury, benching, a release &mdash; not injuries "
        "specifically. The league's weekly injury reports (data/injuries) can't fill that gap: "
        "they list players ruled <em>Out</em> week by week, and a player lost for the season "
        "drops off the report entirely, so they under-count the absences that matter most. "
        "Nick Chubb's two-game 2023 and Brandon Aiyuk's lost 2025 appear nowhere in them. "
        "Weeks active catches both.</p>"
    )


# --------------------------------------------------------------------------- #
# Section 4 - champion blueprint
# --------------------------------------------------------------------------- #

_CHAMP_PICK_COLS = ["round", "overall_pick", "Player", "Pos.", "final_pos_rank", "VsPick", "adp"]
_CHAMP_PICK_RENAME = {"round": "Rd", "overall_pick": "Pick", "Pos.": "Pos",
                      "final_pos_rank": "Pos Finish", "VsPick": "Finish vs Pick", "adp": "ADP"}


def _champ_vs_field(df) -> pd.DataFrame:
    g = df.groupby(["Season", "Champ"]).agg(
        Picks=("overall_pick", "count"),
        HitRate=("Hit", "mean"),
        WeeksLost=("Missed", "mean"),
        FinishVsPick=("VsPick", "mean"),
        AvgValue=("OvrValue", "mean"),
    ).reset_index()
    g["Who"] = g["Champ"].map({True: "Champion", False: "Everyone else"})
    g["HitRate"] = (g["HitRate"] * 100).round(0)
    g[["WeeksLost", "FinishVsPick", "AvgValue"]] = (
        g[["WeeksLost", "FinishVsPick", "AvgValue"]].round(1))
    return g[["Season", "Who", "Picks", "HitRate", "WeeksLost", "FinishVsPick", "AvgValue"]].rename(
        columns={"HitRate": "Starter Hit %", "WeeksLost": "Weeks Lost / Pick",
                 "FinishVsPick": "Avg Finish vs Pick", "AvgValue": "Avg ADP Value"})


def _champ_picks_table(df, season) -> str:
    c = df[(df["Season"] == season) & df["Champ"]].sort_values("overall_pick").head(6)
    d = c[_CHAMP_PICK_COLS].rename(columns=_CHAMP_PICK_RENAME)
    return (d.style.hide(axis="index")
            .format({"ADP": "{:.1f}", "Finish vs Pick": "{:+.0f}"}, na_rep="—")
            .background_gradient(cmap="RdYlGn_r", subset=["Pos Finish"])
            .background_gradient(cmap="RdYlGn", subset=["Finish vs Pick"])
            .set_table_styles(_GRID, overwrite=False)
            .set_table_attributes('class="sticky-table"')).to_html()


def _unhealthiest_champ(champ, field) -> str:
    """The season a title was won despite the worst health, if there was one."""
    gap = champ["Weeks Lost / Pick"] - field["Weeks Lost / Pick"]
    if gap.max() <= 0:
        return ""
    season = gap.idxmax()
    return (f", and {season}'s winner took the title with their picks missing "
            f"{champ.loc[season, 'Weeks Lost / Pick']:.1f} weeks apiece against the field's "
            f"{field.loc[season, 'Weeks Lost / Pick']:.1f}")


def champion_blueprint(df) -> str:
    vs = _champ_vs_field(df)
    vs_html = (vs.style.hide(axis="index")
               .format({"Starter Hit %": "{:.0f}%", "Weeks Lost / Pick": "{:.1f}",
                        "Avg Finish vs Pick": "{:+.1f}", "Avg ADP Value": "{:+.1f}"})
               .background_gradient(cmap="RdYlGn", subset=["Starter Hit %"])
               .background_gradient(cmap="RdYlGn", subset=["Avg Finish vs Pick"])
               .background_gradient(cmap="RdYlGn_r", subset=["Weeks Lost / Pick"])
               .set_table_styles(_GRID, overwrite=False)
               .set_table_attributes('class="sticky-table"')).to_html()

    first = _first_at_position(df)
    timing = _pivot(first, "round", "mean", index="Champ").round(1)
    timing.index = timing.index.map({True: "Champions", False: "Everyone else"})
    timing.index.name = None
    timing_html = (timing.style.format("{:.1f}", na_rep="—")
                   .set_table_styles(_GRID, overwrite=False)
                   .set_table_attributes('class="sticky-table"')).to_html()

    champ = vs[vs["Who"] == "Champion"].set_index("Season")
    field = vs[vs["Who"] == "Everyone else"].set_index("Season")
    seasons = len(champ)
    beat_hits = int((champ["Starter Hit %"] > field["Starter Hit %"]).sum())
    beat_finish = int((champ["Avg Finish vs Pick"] > field["Avg Finish vs Pick"]).sum())
    beat_value = int((champ["Avg ADP Value"] > field["Avg ADP Value"]).sum())
    healthier = int((champ["Weeks Lost / Pick"] < field["Weeks Lost / Pick"]).sum())

    verdict = (
        f"<p>Across all {seasons} titles the champion beat the field's hit rate "
        f"<strong>{beat_hits} of {seasons}</strong> times and got more finish out of their draft "
        f"slots <strong>{beat_finish} of {seasons}</strong> times, but only led the field in "
        f"draft-day value against ADP <strong>{beat_value} of {seasons}</strong> times. On this "
        "sample, titles track picks that <em>worked</em> more than picks that looked like "
        "bargains on draft day &mdash; though three seasons cannot separate that from simple "
        "luck.</p>"
        f"<p>Health is not the explanation. The champion's picks were the healthier group in "
        f"only <strong>{healthier} of {seasons}</strong> seasons"
        + _unhealthiest_champ(champ, field) + ".</p>"
    )

    drafts = "".join(
        f"<h3>{FORMAL_SEASON[s]} &mdash; {ROSTER_NAMES[champion_roster(s)]}</h3>"
        f"<div class='table-scroll'>{_champ_picks_table(df, FORMAL_SEASON[s])}</div>"
        for s in LEAGUE_IDS if champion_roster(s) is not None
    )

    return (
        "<p>Champions taken from Sleeper's playoff bracket, then measured against everyone "
        "else who drafted that same year. <strong>Starter Hit %</strong> is the share of a "
        "manager's picks that finished inside their position's weekly starter pool "
        f"(top {STARTERS['QB']} QB / {STARTERS['RB']} RB / {STARTERS['WR']} WR / "
        f"{STARTERS['TE']} TE for a 10-team, 2-flex league). <strong>Weeks Lost / Pick</strong> "
        f"is how many of the {GAMES} weeks the average pick spent inactive. "
        "<strong>Avg Finish vs Pick</strong> = draft position minus fantasy finish "
        "(+ = picks outperformed their slots); <strong>Avg ADP Value</strong> = pick minus "
        "consensus ADP &mdash; draft-day context, not an outcome.</p>"
        f"<div class='table-scroll'>{vs_html}</div>"
        + verdict +
        "<h2>When champions went to each position</h2>"
        f"<div class='table-scroll'>{timing_html}</div>"
        "<h2>The title-winning drafts, round by round</h2>"
        "<p>First six picks of each championship team. <strong>Pos Finish</strong> is where the "
        "player ended the season at their position (green = better); <strong>Finish vs Pick</strong> "
        "= overall pick minus overall finish (+ = outperformed the slot). ADP is draft-day "
        "context.</p>"
        + drafts
    )


# --------------------------------------------------------------------------- #
# Section 4 - per-manager report cards
# --------------------------------------------------------------------------- #

def _place(summary, row, rank_col: str) -> str:
    """"3rd", or "tied 3rd" when someone else shares the rank."""
    shared = (summary[rank_col] == row[rank_col]).sum() > 1
    return ("tied " if shared else "") + _ordinal(int(row[rank_col]))


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _manager_summary(df) -> pd.DataFrame:
    g = df.groupby("Manager").agg(
        Picks=("overall_pick", "count"),
        HitRate=("Hit", "mean"),
        WeeksLost=("Missed", "sum"),
        FinishVsPick=("VsPick", "mean"),
        AvgValue=("OvrValue", "mean"),
    ).reset_index()
    healthy = df[df["Healthy"]].groupby("Manager")["Hit"].mean().rename("HealthyHit")
    g = g.merge(healthy, on="Manager", how="left")

    g["HitRate"] = (g["HitRate"] * 100).round(0)
    g["HealthyHit"] = (g["HealthyHit"] * 100).round(0)
    g[["FinishVsPick", "AvgValue"]] = g[["FinishVsPick", "AvgValue"]].round(1)
    # method="min" so managers tied on a rate share a rank rather than being
    # ordered arbitrarily by row position.
    g["Hit Rank"] = g["HitRate"].rank(method="min", ascending=False).astype(int)
    g["Healthy Rank"] = g["HealthyHit"].rank(method="min", ascending=False).astype(int)
    return g.sort_values(["HealthyHit", "HitRate"], ascending=False).rename(
        columns={"HitRate": "Starter Hit %", "WeeksLost": "Weeks Lost",
                 "HealthyHit": "Healthy Hit %", "FinishVsPick": "Avg Finish vs Pick",
                 "AvgValue": "Avg ADP Value"})


def _extremes(sub) -> str:
    """That manager's best and worst pick, by positional finish against where
    they actually drafted the player (ADP is a parenthetical note)."""
    scored = sub[sub["PosVsPick"].notna()]
    if scored.empty:
        return ""

    def line(row, label):
        # A pick that vanished for half the year failed differently from one that
        # played all season and simply wasn't good; say which.
        note = ("" if row["Healthy"] else
                f" &mdash; active only {int(row['Games Played'])} of {GAMES} weeks")
        adp_note = ("" if pd.isna(row["adp_pos"]) else
                    f" (consensus had him {_ordinal(int(row['adp_pos']))})")
        return (f"<li><strong>{label}:</strong> {row['Player']} ({row['Pos.']}, {row['Season']}) "
                f"&mdash; taken at pick {int(row['overall_pick'])} as the "
                f"{_ordinal(int(row['draft_pos_rank']))} {row['Pos.']} off the board, "
                f"finished {_ordinal(int(row['final_pos_rank']))}{adp_note}{note}.</li>")

    best = scored.loc[scored["PosVsPick"].idxmax()]
    worst = scored.loc[scored["PosVsPick"].idxmin()]
    return f"<ul>{line(best, 'Best pick')}{line(worst, 'Worst pick')}</ul>"


def _card(df, avg_clock, summary, mgr) -> str:
    sub = df[df["Manager"] == mgr]
    row = summary[summary["Manager"] == mgr].iloc[0]
    league = avg_clock.mean()
    mine = avg_clock.loc[mgr]

    # The position this manager times most differently from the league.
    gaps = (mine - league).dropna()
    habits = []
    if not gaps.empty and gaps.abs().max() >= _HABIT_MIN:
        pos = gaps.abs().idxmax()
        direction = "earlier than" if gaps[pos] < 0 else "later than"
        habits.append(f"<li>Takes their first <strong>{pos}</strong> "
                      f"{abs(gaps[pos]):.1f} rounds {direction} the league average "
                      f"(round {mine[pos]:.1f} vs {league[pos]:.1f}).</li>")
    else:
        habits.append("<li>Times every position within half a round of the league average - "
                      "no positional signature.</li>")

    titles = [FORMAL_SEASON[s] for s in LEAGUE_IDS if champion_roster(s) == _roster_of(mgr)]
    if titles:
        habits.append(f"<li>Champion in <strong>{', '.join(titles)}</strong>.</li>")

    finish = row["Avg Finish vs Pick"]
    verdict = (f"finished {finish:.1f} spots better than where it was drafted" if finish >= 0
               else f"finished {abs(finish):.1f} spots worse than where it was drafted")
    habits.append(
        f"<li>{row['Starter Hit %']:.0f}% of picks became weekly starters "
        f"({_place(summary, row, 'Hit Rank')} of {len(summary)} in the league); "
        f"the average pick {verdict}.</li>")
    habits.append(
        f"<li>Lost <strong>{int(row['Weeks Lost'])} player-weeks</strong> to absences. Counting "
        f"only picks who stayed available, the hit rate is "
        f"<strong>{row['Healthy Hit %']:.0f}%</strong> "
        f"({_place(summary, row, 'Healthy Rank')} of {len(summary)}).</li>")

    clock = ", ".join(f"{p} rd {mine[p]:.1f}" for p in POS if p in mine and pd.notna(mine[p]))
    return layout.details(
        mgr,
        f"<p><strong>First pick by position:</strong> {clock}</p>"
        f"<ul>{''.join(habits)}</ul>" + _extremes(sub))


def _roster_of(manager):
    return next((rid for rid, name in ROSTER_NAMES.items() if name == manager), None)


def report_cards(df) -> str:
    summary = _manager_summary(df)
    avg_clock = _pivot(_first_at_position(df), "round", "mean")

    table = (summary.drop(columns=["Hit Rank", "Healthy Rank"]).style.hide(axis="index")
             .format({"Starter Hit %": "{:.0f}%", "Healthy Hit %": "{:.0f}%",
                      "Avg Finish vs Pick": "{:+.1f}", "Avg ADP Value": "{:+.1f}"})
             .background_gradient(cmap="RdYlGn", subset=["Starter Hit %"])
             .background_gradient(cmap="RdYlGn_r", subset=["Weeks Lost"])
             .background_gradient(cmap="RdYlGn", subset=["Healthy Hit %"])
             .background_gradient(cmap="RdYlGn", subset=["Avg Finish vs Pick"])
             .set_table_styles(_GRID, overwrite=False)
             .set_table_attributes('class="sticky-table"')).to_html()

    cards = "".join(_card(df, avg_clock, summary, m) for m in summary["Manager"])
    return (
        "<p><strong>Starter Hit %</strong> = share of picks that finished inside their "
        "position's weekly starter pool. <strong>Weeks Lost</strong> = player-weeks their picks "
        f"spent inactive. <strong>Healthy Hit %</strong> = the same hit rate counting only picks "
        f"active at least {HEALTHY_MIN} of {GAMES} weeks. <strong>Avg Finish vs Pick</strong> = "
        "draft position minus where the player actually finished (+ = the pick outperformed its "
        "slot). <strong>Avg ADP Value</strong> = pick minus consensus ADP (+ = waited for value) "
        "&mdash; draft-day context, not an outcome. Sorted by the health-adjusted rate.</p>"
        f"<div class='table-scroll'>{table}</div>"
        "<h2>Individual cards</h2>" + cards
    )


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #

def generate():
    """Build and write docs/draft-dna/index.html."""
    df = all_picks()
    n_drafts, n_picks = df["Season"].nunique(), len(df)

    sections = [
        ("clock", "Positional Clock - when each manager goes to each position", positional_clock(df)),
        ("blueprint", f"Early Blueprint - the first {EARLY_ROUNDS} rounds", early_blueprint(df)),
        ("health", "Availability - separating bad picks from hurt ones", availability(df)),
        ("champions", "Champion Blueprint - how the title winners drafted", champion_blueprint(df)),
        ("cards", "Manager Report Cards", report_cards(df)),
    ]

    intro = (
        "<p>Not <em>how well</em> each manager drafts &mdash; that's the "
        + layout.internal_link("/draft-report/", "Manager Draft Report")
        + " &mdash; but <em>how</em> they draft. Positional timing, early-round shape, how much "
        "of the result came down to players simply staying on the field, and what the "
        "championship drafts had in common.</p>"
        f"<p><strong>Sample size:</strong> {n_drafts} drafts, {n_picks} picks in total, so roughly "
        f"{n_picks // len(ROSTER_NAMES)} picks per manager. That is enough to describe a habit "
        "and not enough to prove one &mdash; read the 'never before round N' lines as "
        "'hasn't yet', not as a law. Kickers and defenses are excluded throughout.</p>"
    )

    nav = layout.section_nav([(a, title.split(" - ")[0]) for a, title, _ in sections])
    body = layout.HEAD + _CSS + intro + nav + "".join(
        layout.details(title, html, open=(i == 0), anchor=a)
        for i, (a, title, html) in enumerate(sections))

    page = add_front_matter(body, "Draft DNA")
    out = ROOT / "docs" / "draft-dna" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"Wrote Draft DNA page -> {out}")


if __name__ == "__main__":
    generate()
