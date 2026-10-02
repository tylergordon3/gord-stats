"""
College football's advanced numbers for the season, from CollegeFootballData:
the nerd stats (/cfb/stats/).

Five CFBD tables, each cached trimmed under data/cfb/cfbd/ (the raw answers
are ~2 MB a day, too much to commit every run) and refreshed every HOURS:

    wepa          opponent-adjusted team EPA and success rate, offence and
                  defence (CFBD's own adjustment - its "WEPA")
    advanced      the raw season splits, garbage time excluded: success rate,
                  explosiveness, line yards, stuff rate, havoc, points per
                  scoring opportunity, field position, standard/passing downs
    season_stats  the box-score totals: third and fourth downs, turnovers,
                  sacks, tackles for loss, penalties, time of possession
    talent        247's team talent composite
    ppa_players   each player's EPA per play ("PPA", CFBD's name for it),
                  passing and rushing, garbage time excluded

Tempo (plays a game) is the one figure from elsewhere: cfb.efficiency's
per-game archive, which counts every snap.

EPA is expected points added: how many points a play was worth, from where
the offence stood before it to where it stood after. Success is a play that
gains 50% of the yards needed on first down, 70% on second, 100% on third or
fourth. Explosiveness is the average EPA of the successful plays.

    teams()     one dict per FBS team, every figure the page shows
    players()   {position group: [player, ...]} for the leaderboards

    python -m cfb.advanced            # refresh what is stale
    python -m cfb.advanced --refresh
"""
import pandas as pd

from cfb import cfbd
from cfb.config import SEASON

HOURS = 12


def _num(v, places=4):
    try:
        return None if v is None else round(float(v), places)
    except (TypeError, ValueError):
        return None


def _get(d: dict, *path):
    for p in path:
        if not isinstance(d, dict):
            return None
        d = d.get(p)
    return d


def _wepa() -> dict:
    out = {}
    for t in cfbd.get("/wepa/team/season", year=SEASON):
        out[t["team"]] = {
            "id": str(t.get("teamId") or ""), "conf": t.get("conference") or "",
            "off": _num(_get(t, "epa", "total")), "off_pass": _num(_get(t, "epa", "passing")),
            "off_rush": _num(_get(t, "epa", "rushing")),
            "def": _num(_get(t, "epaAllowed", "total")),
            "def_pass": _num(_get(t, "epaAllowed", "passing")),
            "def_rush": _num(_get(t, "epaAllowed", "rushing")),
            "sr": _num(_get(t, "successRate", "total")),
            "sr_sd": _num(_get(t, "successRate", "standardDowns")),
            "sr_pd": _num(_get(t, "successRate", "passingDowns")),
            "sr_a": _num(_get(t, "successRateAllowed", "total")),
            "sr_sd_a": _num(_get(t, "successRateAllowed", "standardDowns")),
            "sr_pd_a": _num(_get(t, "successRateAllowed", "passingDowns")),
            "line": _num(_get(t, "rushing", "lineYards")),
            "line_a": _num(_get(t, "rushingAllowed", "lineYards")),
            "expl": _num(t.get("explosiveness")), "expl_a": _num(t.get("explosivenessAllowed")),
        }
    return out


def _side(s: dict) -> dict:
    start = _get(s, "fieldPosition", "averageStart")
    return {
        "plays": s.get("plays"), "drives": s.get("drives"),
        "ppa": _num(s.get("ppa")), "sr": _num(s.get("successRate")),
        "expl": _num(s.get("explosiveness")), "power": _num(s.get("powerSuccess")),
        "stuff": _num(s.get("stuffRate")), "line": _num(s.get("lineYards")),
        "second": _num(s.get("secondLevelYards")), "open": _num(s.get("openFieldYards")),
        "ppo": _num(s.get("pointsPerOpportunity")),
        # CFBD gives the distance to the goal line at the start of a drive;
        # the yard line from the offence's own goal reads the right way round.
        "start": None if start is None else round(100 - float(start), 1),
        "havoc": _num(_get(s, "havoc", "total")), "havoc_f7": _num(_get(s, "havoc", "frontSeven")),
        "havoc_db": _num(_get(s, "havoc", "db")),
        "pass_rate": _num(_get(s, "passingPlays", "rate")),
        "pd_rate": _num(_get(s, "passingDowns", "rate")),
    }


def _advanced() -> dict:
    return {t["team"]: {"conf": t.get("conference") or "", "off": _side(t.get("offense") or {}),
                        "def": _side(t.get("defense") or {})}
            for t in cfbd.get("/stats/season/advanced", year=SEASON, excludeGarbageTime="true")}


SEASON_STATS = {"games", "thirdDowns", "thirdDownConversions", "fourthDowns",
                "fourthDownConversions", "turnovers", "sacks", "tacklesForLoss",
                "penalties", "penaltyYards", "possessionTime", "totalYards"}


def _season_stats() -> dict:
    out = {}
    for row in cfbd.get("/stats/season", year=SEASON):
        name = row.get("statName") or ""
        base = name[:-len("Opponent")] if name.endswith("Opponent") else name
        if base not in SEASON_STATS:
            continue
        out.setdefault(row["team"], {})[name] = _num(row.get("statValue"), 1)
    return out


def _talent() -> dict:
    return {t["team"]: _num(t.get("talent"), 1) for t in cfbd.get("/talent", year=SEASON)}


# Plays enough for a player's rate to mean something, and small enough to keep
# the cache small: the leaderboards' own minimums sit well above these.
_KEEP_PLAYS = 10


def _ppa_players() -> list:
    # FBS teams only (the ones CFBD adjusts, cached just before this) and the
    # four positions the page ranks: the whole answer is 1.6 MB.
    fbs = set(cfbd._read("wepa") or {})
    out = []
    for p in cfbd.get("/ppa/players/season", year=SEASON, excludeGarbageTime="true"):
        if p.get("position") not in {"QB", "RB", "WR", "TE"} or (fbs and p.get("team") not in fbs):
            continue
        avg, tot = p.get("averagePPA") or {}, p.get("totalPPA") or {}
        row = {"name": p.get("name"), "pos": p.get("position"), "team": p.get("team")}
        for kind in ("pass", "rush"):
            a, t = avg.get(kind), tot.get(kind)
            plays = round(t / a) if a and t else 0
            row[kind] = _num(a, 3) if plays else None
            row[f"{kind}_n"] = plays
        if max(row["pass_n"], row["rush_n"]) >= _KEEP_PLAYS:
            out.append(row)
    return out


FETCH = {"wepa": _wepa, "advanced": _advanced, "season_stats": _season_stats,
         "talent": _talent, "ppa_players": _ppa_players}


def capture(refresh: bool = False) -> dict:
    """Every table, refetched where stale; a failed fetch keeps the cache."""
    return {name: cfbd._cached(name, HOURS, fetch, refresh=refresh) or {}
            for name, fetch in FETCH.items()}


def _load(name: str):
    return cfbd._read(name) or ({} if name != "ppa_players" else [])


def _per_game(stats: dict, key: str):
    g = stats.get("games")
    v = stats.get(key)
    return None if not g or v is None else round(v / g, 2)


def _rate(stats: dict, made: str, tried: str):
    a, b = stats.get(made), stats.get(tried)
    return None if not b or a is None else round(a / b, 4)


def _plays_per_game() -> dict:
    """{CFBD team: offensive plays a game, every snap counted} from
    cfb.efficiency's per-game archive (CFBD /stats/game/advanced, garbage time
    in; refreshed with every fit and committed, so no call of its own).

    Not the season table's plays: those leave garbage time out, which reads
    backwards as tempo - a team thirty up at half runs few plays that count,
    and Georgia, 61 snaps a game, was "38 plays a game (137th most)"."""
    from cfb.efficiency import ARCHIVE
    try:
        games = pd.read_parquet(ARCHIVE / f"{SEASON}.parquet", columns=["team", "offense_plays"])
    except Exception:                         # noqa: BLE001 - the column goes blank
        return {}
    games = games[games["offense_plays"] > 0]
    return {str(t): round(float(v), 1)
            for t, v in games.groupby("team")["offense_plays"].mean().items()}


def teams() -> list:
    """One dict per FBS team (the teams CFBD adjusts - FBS only), keyed as the
    page's columns are."""
    wepa, adv = _load("wepa"), _load("advanced")
    box, talent = _load("season_stats"), _load("talent")
    talent_rank = {t: i for i, (t, _v) in enumerate(
        sorted(((t, v) for t, v in talent.items() if v is not None), key=lambda x: -x[1]), 1)}
    plays = _plays_per_game()
    out = []
    for name, w in wepa.items():
        a = adv.get(name) or {}
        o, d = a.get("off") or {}, a.get("def") or {}
        s = box.get(name) or {}
        g = s.get("games")
        out.append({
            "name": name, "id": w["id"], "conf": w["conf"] or a.get("conf", ""),
            # Opponent-adjusted (CFBD's WEPA)
            "adj_net": None if w["off"] is None or w["def"] is None else round(w["off"] - w["def"], 4),
            "adj_off": w["off"], "adj_off_pass": w["off_pass"], "adj_off_rush": w["off_rush"],
            "adj_def": w["def"], "adj_def_pass": w["def_pass"], "adj_def_rush": w["def_rush"],
            "adj_sr": w["sr"], "adj_sr_sd": w["sr_sd"], "adj_sr_pd": w["sr_pd"],
            "adj_sr_a": w["sr_a"], "adj_sr_sd_a": w["sr_sd_a"], "adj_sr_pd_a": w["sr_pd_a"],
            "adj_line": w["line"], "adj_line_a": w["line_a"],
            "adj_expl": w["expl"], "adj_expl_a": w["expl_a"],
            # Raw, garbage time out
            "off_ppa": o.get("ppa"), "def_ppa": d.get("ppa"),
            "off_expl": o.get("expl"), "def_expl": d.get("expl"),
            "off_power": o.get("power"), "def_power": d.get("power"),
            "off_stuff": o.get("stuff"), "def_stuff": d.get("stuff"),
            "off_ppo": o.get("ppo"), "def_ppo": d.get("ppo"),
            "off_start": o.get("start"), "def_start": d.get("start"),
            "off_havoc": o.get("havoc"), "def_havoc": d.get("havoc"),
            "def_havoc_f7": d.get("havoc_f7"), "def_havoc_db": d.get("havoc_db"),
            "pass_rate": o.get("pass_rate"),
            # Tempo: every snap (see _plays_per_game), not the raw splits'.
            "plays_pg": plays.get(name),
            # The box score
            "third": _rate(s, "thirdDownConversions", "thirdDowns"),
            "third_a": _rate(s, "thirdDownConversionsOpponent", "thirdDownsOpponent"),
            "fourth": _rate(s, "fourthDownConversions", "fourthDowns"),
            "to_pg": _per_game(s, "turnovers"), "take_pg": _per_game(s, "turnoversOpponent"),
            "to_margin": None if not g or s.get("turnovers") is None or s.get("turnoversOpponent") is None
            else round((s["turnoversOpponent"] - s["turnovers"]) / g, 2),
            "sacks_pg": _per_game(s, "sacks"), "sacked_pg": _per_game(s, "sacksOpponent"),
            "tfl_pg": _per_game(s, "tacklesForLoss"),
            "pen_pg": _per_game(s, "penalties"), "pen_yds_pg": _per_game(s, "penaltyYards"),
            "top_pg": None if not g or s.get("possessionTime") is None
            else round(s["possessionTime"] / g / 60, 1),       # minutes; CFBD counts seconds
            "talent": talent.get(name), "talent_rank": talent_rank.get(name),
        })
    return out


GROUPS = [("QB", "Quarterbacks", "pass", 80, "Passing EPA per play", "pass plays"),
          ("RB", "Running backs", "rush", 35, "Rushing EPA per carry", "carries"),
          ("WR", "Receivers", "pass", 15, "EPA per target", "targets"),
          ("TE", "Tight ends", "pass", 10, "EPA per target", "targets")]


def players(fbs: set = None) -> dict:
    """{position: [row, ...]}, best EPA per play first, each over its
    group's minimum plays and on an FBS team when `fbs` (team names) is
    given."""
    rows = _load("ppa_players")
    out = {}
    for pos, _label, kind, minimum, _metric, _vol in GROUPS:
        keep = [r for r in rows if r.get("pos") == pos and r.get(kind) is not None
                and (r.get(f"{kind}_n") or 0) >= minimum and (fbs is None or r.get("team") in fbs)]
        out[pos] = sorted(keep, key=lambda r: -r[kind])
    return out


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--refresh", action="store_true")
    got = capture(refresh=p.parse_args().refresh)
    print({k: len(v) for k, v in got.items()})
