"""
Who is actually getting the ball (data/cfb/usage_{season}.parquet).

College backfields are committees - two or three backs, a share that moves
week to week - and a season projection divided by games cannot see that. This
builds the per-game record instead, from three CFBD calls a week:

    /games/players   carries, receptions, yards, touchdowns per player, and
                     the team totals the shares divide by (its own players
                     added up, so a share can never exceed what was carried)
    /plays           the intended receiver on each pass, which is the only
                     place a target exists
    /ppa/players/games   each player's predicted points added, and his position

Targets are parsed out of the play text ("... pass complete short right to #0
E.Mitchell ..."), matched to a player by jersey number and surname inside the
offence's own roster. A pass whose receiver cannot be matched is counted for
the team but not for a player, so shares never exceed what was thrown.

A finished week never changes, so each is fetched once and read from the
parquet after that.

    python -m cfb.usage             # fetch any missing weeks, print the top backfields
    python -m cfb.usage --refresh
"""
import argparse
import json
import re
import unicodedata

import pandas as pd

from cfb import cfbd, espn
from cfb.config import DATA_DIR, SEASON

# "to #0 E.Mitchell caught at ..." / "incomplete short left to #1 P.Billups II"
_TARGET = re.compile(r"\bto #(\d+) ([A-Z][\w.'-]*(?: [\w.'-]+)*?)(?=,| caught| thrown| for |$)")
# The feed's other two voices, neither with a jersey number:
# "O. McCown pass to B. Young Jr. for 1 yd" and "Coy Eakin 32 Yd pass from Will Hammond".
_TARGET_PLAIN = re.compile(r"\bpass (?:complete |incomplete )?to ([A-Z][\w.'-]*(?: [\w.'-]+)*?)"
                           r"(?=,| for | \(|$)")
_TARGET_SCORE = re.compile(r"^([A-Z][\w.'-]*(?: [\w.'-]+)*?) \d+ Yde? pass from ", re.I)
_SACK = re.compile(r"\bsack(?:ed)?\b", re.I)
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def _fold(text: str) -> str:
    """Lower case, accents and punctuation off, generational suffix dropped -
    "Melin Öhrström" and "Barney Jr." have to meet the roster's spelling."""
    flat = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    words = [w for w in re.sub(r"[^a-z ]", "", flat.lower().replace("-", " ")).split()
             if w not in _SUFFIXES]
    return " ".join(words)


def _split(token: str) -> tuple:
    """"J.Burton" / "J. Burton" / "Jalen Burton" -> ("j", "burton").

    Play text abbreviates the first name to an initial and can carry a suffix
    or a two-word surname, so the surname is everything after the first name
    with the suffix folded away.
    """
    token = str(token).strip()
    if "." in token.split(" ")[0]:
        first, tail = token.split(".", 1)
    elif " " in token:
        first, tail = token.split(" ", 1)
    else:
        first, tail = "", token
    return _fold(first)[:1], _fold(tail)


def _surname(token: str) -> str:
    return _split(token)[1]


class _Receivers:
    """One offence's names, looked up the three ways the play text allows.

    Jersey and surname first - exact, but CFBD's roster numbers go stale with
    every transfer window (Nebraska matched 6 of 32 passes on them). So the
    fallbacks ignore the number: initial and surname, then surname alone, each
    only where it names exactly one player. The box score's own names are
    folded in because a freshman who caught a pass is in the box before he is
    on the roster.
    """

    def __init__(self, jerseys: dict, names: dict):
        self.jersey = {}
        for key, pid in jerseys.items():
            number, _, last = key.partition(" ")
            self.jersey[(number, _fold(last))] = pid
        by_initial, by_last = {}, {}
        for pid, name in names.items():
            initial, last = _split(name)
            if last:
                by_initial.setdefault((initial, last), set()).add(pid)
                by_last.setdefault(last, set()).add(pid)
        self.initial = {k: next(iter(v)) for k, v in by_initial.items() if len(v) == 1}
        self.last = {k: next(iter(v)) for k, v in by_last.items() if len(v) == 1}

    def find(self, token: str, jersey: str = None):
        initial, last = _split(token)
        if jersey is not None:
            pid = self.jersey.get((str(int(jersey)), last))
            if pid:
                return pid
        return self.initial.get((initial, last)) or self.last.get(last)


_STATS = {("rushing", "CAR"): "carries", ("rushing", "YDS"): "rush_yds",
          ("rushing", "TD"): "rush_td", ("receiving", "REC"): "rec",
          ("receiving", "YDS"): "rec_yds", ("receiving", "TD"): "rec_td",
          # CFBD reports passing as one "18/35" cell, so completions and
          # attempts are split out of it rather than read from two columns.
          ("passing", "C/ATT"): "pass_cmp", ("passing", "YDS"): "pass_yds",
          ("passing", "TD"): "pass_td"}
NUMERIC = sorted(set(_STATS.values())) + ["pass_att", "targets", "team_carries",
                                          "team_pass_att", "ppa"]


def path(season: int = SEASON):
    return DATA_DIR / f"usage_{season}.parquet"


def _roster_path(season: int = SEASON):
    return DATA_DIR / f"cfbd_roster_{season}.json"


def rosters(season: int = SEASON, refresh: bool = False) -> dict:
    """{team: {"#jersey surname": athlete id}} plus {athlete id: [name, pos]}."""
    cache = _roster_path(season)
    if cache.exists() and not refresh:
        return json.loads(cache.read_text(encoding="utf-8"))
    rows = cfbd.get("/roster", year=season) or []
    by_team, who = {}, {}
    for p in rows:
        pid = str(p.get("id") or "")
        last = str(p.get("lastName") or "").strip()
        if not pid or not last:
            continue
        name = f"{p.get('firstName') or ''} {last}".strip()
        who[pid] = [name, str(p.get("position") or "")]
        jersey = p.get("jersey")
        if jersey is not None:
            key = f"{int(jersey)} {last.lower()}"
            by_team.setdefault(str(p.get("team")), {})[key] = pid
    out = {"by_team": by_team, "who": who}
    cache.write_text(json.dumps(out), encoding="utf-8")
    return out


def _num(v) -> float:
    try:
        return float(str(v).replace(",", "").split("/")[0])
    except (TypeError, ValueError):
        return 0.0


def _box(season: int, week: int) -> dict:
    """{(team, athlete id): row} from the week's box scores."""
    out = {}
    for game in cfbd.get("/games/players", year=season, week=week) or []:
        for team in game.get("teams") or []:
            name = str(team.get("team"))
            for cat in team.get("categories") or []:
                for kind in cat.get("types") or []:
                    col = _STATS.get((cat.get("name"), kind.get("name")))
                    if not col:
                        continue
                    for athlete in kind.get("athletes") or []:
                        pid = str(athlete.get("id") or "")
                        if not pid:
                            continue
                        row = out.setdefault((name, pid), {
                            "game_id": str(game.get("id") or ""), "week": week,
                            "team": name, "athlete_id": pid,
                            "player": athlete.get("name") or "",
                            **{c: 0.0 for c in NUMERIC}})
                        raw = athlete.get("stat")
                        row[col] += _num(raw)
                        if col == "pass_cmp" and "/" in str(raw):
                            row["pass_att"] += _num(str(raw).split("/")[1])
    return out


def _targets(season: int, week: int, roster: dict, box: dict = None) -> dict:
    """{(team, athlete id): targets} parsed out of the week's play text.

    Only the play text names the intended receiver, and only by jersey number
    and abbreviated name, so each is matched inside the offence's own names
    (_Receivers). A receiver who cannot be matched is simply not counted - the
    team's pass attempts come from the box score either way, so nobody's share
    inflates.
    """
    out, finders = {}, {}
    by_team, who = roster["by_team"], roster["who"]
    box_names = {}
    for (team, pid), row in (box or {}).items():
        box_names.setdefault(team, {})[pid] = row["player"]

    def finder(team: str) -> _Receivers:
        if team not in finders:
            jerseys = by_team.get(team) or {}
            names = {pid: who[pid][0] for pid in jerseys.values() if pid in who}
            names.update(box_names.get(team) or {})
            finders[team] = _Receivers(jerseys, names)
        return finders[team]

    for play in cfbd.get("/plays", year=season, week=week, classification="fbs") or []:
        text = str(play.get("playText") or "")
        if "pass" not in text.lower() or _SACK.search(text):
            continue
        offense = str(play.get("offense") or "")
        m = _TARGET.search(text)
        if m:
            pid = finder(offense).find(m.group(2), m.group(1))
        else:
            m = _TARGET_PLAIN.search(text) or _TARGET_SCORE.search(text)
            pid = finder(offense).find(m.group(1)) if m else None
        if pid:
            out[(offense, pid)] = out.get((offense, pid), 0) + 1
    return out


def _ppa(season: int, week: int) -> dict:
    """{(team, athlete id): (ppa, position)}."""
    out = {}
    for row in cfbd.get("/ppa/players/games", year=season, week=week) or []:
        pid = str(row.get("id") or "")
        if pid:
            out[(str(row.get("team")), pid)] = ((row.get("averagePPA") or {}).get("all"),
                                                str(row.get("position") or ""))
    return out


def week_rows(season: int, week: int, roster: dict) -> list:
    box = _box(season, week)
    if not box:
        return []
    targets = _targets(season, week, roster, box)
    ppa = _ppa(season, week)
    who = roster["who"]
    # The denominators come from the box score itself: a team's carries are its
    # players' carries. Taking them from the play feed instead priced FCS teams
    # against the handful of their snaps that appear in an FBS-classified game,
    # and their backs came out with 300% of the carries.
    team_car, team_att = {}, {}
    for (team, _pid), row in box.items():
        key = (team, row["game_id"])
        team_car[key] = team_car.get(key, 0.0) + row["carries"]
        team_att[key] = team_att.get(key, 0.0) + row["pass_att"]
    for (team, pid), row in box.items():
        row["targets"] = float(targets.get((team, pid), 0))
        row["team_carries"] = float(team_car.get((team, row["game_id"]), 0.0))
        row["team_pass_att"] = float(team_att.get((team, row["game_id"]), 0.0))
        got = ppa.get((team, pid))
        row["ppa"] = float(got[0]) if got and got[0] is not None else None
        row["pos"] = (got[1] if got and got[1] else (who.get(pid) or ["", ""])[1])
    return list(box.values())


def capture(season: int = SEASON, refresh: bool = False) -> pd.DataFrame:
    """Every played week on disk; only missing weeks are fetched."""
    schedule = espn.schedule()
    done = schedule[(schedule["state"] == "post")
                    & (schedule["home_score"].fillna(0) + schedule["away_score"].fillna(0) > 0)]
    weeks = sorted({int(w) for w in done["week"].dropna().unique()})
    out = path(season)
    have = pd.read_parquet(out) if (out.exists() and not refresh) else pd.DataFrame()
    seen = set(have["week"].unique()) if len(have) else set()
    # The newest played week is refetched once more: a game finishing after the
    # build would otherwise be missing from it for good.
    todo = [w for w in weeks if w not in seen or w == weeks[-1]]
    if not todo:
        return have

    roster = rosters(season)
    rows = []
    for week in todo:
        got = week_rows(season, week, roster)
        print(f"[usage] week {week}: {len(got)} player-games")
        rows.extend(got)
    if not rows:
        return have
    frame = pd.DataFrame(rows)
    if len(have):
        have = have[~have["week"].isin(frame["week"].unique())]
        frame = pd.concat([have, frame], ignore_index=True)
    frame.to_parquet(out, index=False)
    return frame


def load(season: int = SEASON) -> pd.DataFrame:
    out = path(season)
    return pd.read_parquet(out) if out.exists() else pd.DataFrame()


def shares(frame: pd.DataFrame, weeks: int = None) -> pd.DataFrame:
    """Per player: games, carries, targets and catches, and the share of his
    team's that is. `weeks` limits it to the most recent N played weeks.

    A `fpts` column on the way in (the page scores each game with the league's
    modifiers) comes out summed, so the caller can divide it by games."""
    if frame.empty:
        return frame
    if weeks:
        keep = sorted(frame["week"].unique())[-weeks:]
        frame = frame[frame["week"].isin(keep)]
    frame = frame.copy()
    # Catches share the way carries do: against the team's own players added up.
    frame["team_rec"] = frame.groupby(["team", "game_id"])["rec"].transform("sum")
    if "fpts" not in frame:
        frame["fpts"] = float("nan")
    grouped = frame.groupby(["team", "athlete_id", "player", "pos"], as_index=False).agg(
        games=("week", "nunique"), carries=("carries", "sum"), rush_yds=("rush_yds", "sum"),
        rush_td=("rush_td", "sum"), targets=("targets", "sum"), rec=("rec", "sum"),
        rec_yds=("rec_yds", "sum"), rec_td=("rec_td", "sum"), ppa=("ppa", "mean"),
        pass_yds=("pass_yds", "sum"), pass_td=("pass_td", "sum"), fpts=("fpts", "sum"),
        team_carries=("team_carries", "sum"), team_pass_att=("team_pass_att", "sum"),
        team_rec=("team_rec", "sum"))
    grouped["car_share"] = (grouped["carries"] / grouped["team_carries"]).where(
        grouped["team_carries"] > 0)
    grouped["tgt_share"] = (grouped["targets"] / grouped["team_pass_att"]).where(
        grouped["team_pass_att"] > 0)
    grouped["rec_share"] = (grouped["rec"] / grouped["team_rec"]).where(
        grouped["team_rec"] > 0)
    return grouped


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Archive college player usage.")
    p.add_argument("--refresh", action="store_true")
    args = p.parse_args()
    frame = capture(refresh=args.refresh)
    if frame.empty:
        print("nothing archived")
    else:
        table = shares(frame, weeks=3)
        backs = table[(table["pos"] == "RB") & (table["carries"] >= 10)]
        print(f"{len(frame)} player-games, weeks {sorted(frame['week'].unique())}")
        print(backs.nlargest(10, "car_share")[
            ["team", "player", "games", "carries", "car_share", "targets", "ppa"]]
            .to_string(index=False))
