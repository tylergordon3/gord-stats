"""
Who in the league owns a college player - the bridge between the box-score
side of the site (cfb.usage: CFBD school names, ESPN athlete ids) and the
Yahoo side (yahoo ids, "Indiana Hoosiers").

The two share no id, so a player is matched by school and name: the full name
folded the way cfb.usage folds play text, then first initial and surname where
that names exactly one player at the school ("Ryan Coleman Williams" on Yahoo
is "Ryan Williams" in the box score).

Anyone not on a roster is a free agent as far as the league is concerned.
Yahoo's board walk stops ~500 deep, so whether Yahoo lists a third-string
back at all is not known here - but nobody owns him, which is the question.

    python -m cfb.ownership
"""
import pandas as pd

from cfb import schools as schools_mod, usage, yahoo

FREE_AGENT = "FA"

# Yahoo lists a few players under the name they go by; the box score uses the
# one on the roster. Folded Yahoo name -> folded box-score name.
ALIASES = {"hollywood smothers": "daylan smothers"}


def league_players(week: int = None) -> pd.DataFrame:
    """Every rostered player, one row each: yahoo_id, player, pos, school,
    team_key, owner (the fantasy team's name), slot, status."""
    lg = yahoo.league()
    names = {t["team_key"]: t["name"] for t in lg["teams"]}
    weeks = yahoo.archived_weeks()
    if not weeks:
        return pd.DataFrame()
    data = yahoo.week_matchups(week or weeks[-1])
    to_school = schools_mod.yahoo_school()
    rows = []
    for key, roster in data["rosters"].items():
        for p in roster:
            rows.append({"yahoo_id": str(p["yahoo_id"]), "player": p["player"],
                         "pos": str(p["pos"]).split(",")[0],
                         "school": to_school.get(p.get("team_full") or ""),
                         "team_key": key, "owner": names.get(key, key),
                         "slot": p.get("slot"), "status": p.get("status") or ""})
    return pd.DataFrame(rows)


def _keys(name: str, school) -> tuple:
    folded = usage._fold(name)
    folded = ALIASES.get(folded, folded)
    parts = folded.split()
    short = (parts[0][:1], parts[-1]) if len(parts) >= 2 else None
    return (school, folded), (school, short)


class Index:
    """(school, name) -> the row of `frame` it names, exact name first."""

    def __init__(self, frame: pd.DataFrame, name: str = "player", school: str = "school"):
        self.exact, loose = {}, {}
        for i, (n, s) in enumerate(zip(frame[name], frame[school])):
            if not isinstance(s, str):
                continue
            full, short = _keys(n, s)
            self.exact.setdefault(full, i)
            if short[1]:
                loose.setdefault(short, []).append(i)
        self.loose = {k: v[0] for k, v in loose.items() if len(v) == 1}
        self.frame = frame

    def find(self, name: str, school):
        full, short = _keys(name, school)
        i = self.exact.get(full)
        if i is None and short[1]:
            i = self.loose.get(short)
        return None if i is None else self.frame.iloc[i]


def attach(frame: pd.DataFrame, week: int = None) -> pd.DataFrame:
    """`frame` (cfb.usage rows: `player`, `team`) with `owner`, `team_key` and
    `yahoo_id` added. Unowned players read FREE_AGENT with a blank team_key."""
    held = league_players(week)
    out = frame.copy()
    out["owner"], out["team_key"], out["yahoo_id"] = FREE_AGENT, "", ""
    if held.empty or out.empty:
        return out
    index = Index(held[held["pos"] != "DEF"].reset_index(drop=True))
    # The board and the free-agent list know a yahoo id for unowned players.
    pool = pd.concat([yahoo.board(), yahoo.free_agents()], ignore_index=True)
    pool["school"] = pool["team_full"].map(schools_mod.yahoo_school())
    pool_index = Index(pool.drop_duplicates("yahoo_id").reset_index(drop=True))
    owner, key, yid = [], [], []
    for name, school in zip(out["player"], out["team"]):
        hit = index.find(name, school)
        if hit is not None:
            owner.append(hit["owner"]); key.append(hit["team_key"]); yid.append(hit["yahoo_id"])
            continue
        listed = pool_index.find(name, school)
        owner.append(FREE_AGENT); key.append("")
        yid.append("" if listed is None else str(listed["yahoo_id"]))
    out["owner"], out["team_key"], out["yahoo_id"] = owner, key, yid
    return out


if __name__ == "__main__":
    table = attach(usage.shares(usage.load()))
    held = league_players()
    skill = held[held["pos"] != "DEF"]
    found = set(table.loc[table["team_key"] != "", "yahoo_id"])
    print(f"{len(skill)} rostered skill players, {len(found)} found in the usage archive")
    print(skill[~skill["yahoo_id"].isin(found)][["player", "school", "owner", "status"]]
          .to_string(index=False))
