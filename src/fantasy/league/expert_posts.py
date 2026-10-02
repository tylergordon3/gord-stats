"""
Injury takes from physical therapists on X, matched to the players they are
about - the Team and Matchups pages link to the newest one beside a player's
injury pills ("PT ↗").

    jmthrivept      Jeff Mueller, PT, DPT
    TheFantasyPT    The Fantasy PT

X's API (v2), app-only: a bearer token in X_BEARER_TOKEN, which the Pi's
builds read from ~/secrets/gord-stats.env. Without one this does nothing and
the pages carry no links - the site never depends on it.

X bills each post read (pay per use, 2026), so the reader is careful:

  * only new posts: each account is asked for what came after the newest post
    already kept (since_id), so a post is paid for once;
  * at most every REFRESH_MINUTES, however often the pages rebuild;
  * a first read takes the last FIRST_READ posts, not a timeline's worth;
  * a monthly cap (MONTHLY_CAP posts read); past it nothing more is fetched
    until the month turns, and the build says so;
  * user ids are looked up once and kept.

What is kept (data/fantasy/players/expert_posts.json, git-ignored, the Pi's
own): the last KEEP_DAYS of posts - id, account, time, and the text, which is
used only to find the players named in it. The pages show a link to the post
on X, never the post itself.

    refresh()        fetch what is new, within the limits
    links(names)     {player id: newest post about him}, for the names given

    python -m fantasy.league.expert_posts      # refresh and print the matches
"""
import json
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone

import requests

from fantasy import paths

ACCOUNTS = (("jmthrivept", "Jeff Mueller, PT, DPT"),
            ("TheFantasyPT", "The Fantasy PT"))
API = "https://api.x.com/2"
TOKEN_ENV = "X_BEARER_TOKEN"
CACHE = paths.DATA_DIR / "players" / "expert_posts.json"
REFRESH_MINUTES = 30
FIRST_READ = 20
MONTHLY_CAP = 3000          # posts read a month: ~$15 at half a cent a post
KEEP_DAYS = 14
LINK_DAYS = 7               # a take older than this is not linked
TIMEOUT = 20

_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b\.?", re.I)
# Capitalized words that may stand just before a last name used alone without
# being anyone's first name ("And Achane And Etienne", "Update: Hall").
_LEAD = {"and", "the", "for", "with", "on", "of", "at", "to", "in", "is", "but", "or", "from",
         "per", "as", "like", "after", "before", "if", "so", "re", "update", "injury", "news",
         "both", "also", "plus", "then", "when", "while", "now", "why", "how", "what", "rb",
         "wr", "qb", "te"}
_BEFORE = re.compile(r"([A-Z][A-Za-z'.-]*)\s+$")
# What makes a post an injury take. The two accounts post streams, promos and
# chatter too - 24 of the first 65 posts read had any of this - and a post
# that only named a player was linked beside his injury pill all the same. A
# post is linked to a player only with one of these within WINDOW characters
# of his name. Works on the plain text as well (hyphens there are spaces).
INJURY = re.compile(
    r"(?i)\b(injur\w*|hamstring|hammy|ankle|knee|acl|mcl|pcl|meniscus|achilles|concuss\w*"
    r"|shoulder|groin|calf|quads?|hip|foot|feet|toe|wrist|thumb|finger|hand injury|elbow|ribs?"
    r"|oblique|pecs?|pectoral|lisfranc|sprain\w*|strain\w*|tear|torn|fractur\w*|broken"
    r"|surgery|surgical|ir|injured reserve|pup|rehab\w*|recover\w*|setback|aggravat\w*"
    r"|mri|x[- ]?rays?|imaging|limited|dnp|did not practice|practic\w*|questionable"
    r"|doubtful|out for|ruled out|week[- ]to[- ]week|day[- ]to[- ]day|game[- ]time"
    r"|soft tissue|bone bruise|dislocat\w*|contusion|illness|return\w*|timeline)\b")
WINDOW = 200


def _load() -> dict:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(state: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(state, separators=(",", ":")), encoding="utf-8")


def _get(path: str, token: str, params: dict = None) -> dict:
    r = requests.get(f"{API}{path}", headers={"Authorization": f"Bearer {token}"},
                     params=params or {}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def refresh(force: bool = False, now: datetime = None) -> dict:
    """Fetch each account's new posts, within the limits above. Returns the
    kept state; a missing token, a cap reached or an error leaves it as it
    was."""
    state = _load()
    token = os.getenv(TOKEN_ENV)
    if not token:
        return state
    now = now or datetime.now(timezone.utc)
    last = state.get("checked")
    if not force and last:
        try:
            if now - datetime.fromisoformat(last) < timedelta(minutes=REFRESH_MINUTES):
                return state
        except ValueError:
            pass
    month = now.strftime("%Y-%m")
    if state.get("month") != month:
        state["month"], state["reads"] = month, 0
    users, since = state.setdefault("users", {}), state.setdefault("since", {})
    posts = state.setdefault("posts", [])
    for handle, _name in ACCOUNTS:
        if state.get("reads", 0) >= MONTHLY_CAP:
            print(f"  ! X posts: the month's cap of {MONTHLY_CAP} reads is reached; "
                  "nothing more fetched until next month")
            break
        try:
            if handle not in users:
                users[handle] = _get(f"/users/by/username/{handle}", token)["data"]["id"]
            params = {"tweet.fields": "created_at", "exclude": "retweets",
                      "max_results": 100 if since.get(handle) else FIRST_READ}
            if since.get(handle):
                params["since_id"] = since[handle]
            got = _get(f"/users/{users[handle]}/tweets", token, params)
        except Exception as exc:                            # noqa: BLE001
            print(f"  ! X posts for @{handle} unavailable ({exc})")
            continue
        new = got.get("data") or []
        state["reads"] = state.get("reads", 0) + len(new)
        newest = (got.get("meta") or {}).get("newest_id")
        if newest:
            since[handle] = newest
        posts.extend({"id": p["id"], "handle": handle, "at": p.get("created_at"),
                      "text": p.get("text") or ""} for p in new)
    cutoff = now - timedelta(days=KEEP_DAYS)
    seen, kept = set(), []
    for p in sorted(posts, key=lambda p: p.get("at") or "", reverse=True):
        if p["id"] in seen or not _within(p.get("at"), cutoff):
            continue
        seen.add(p["id"])
        kept.append(p)
    state["posts"] = kept
    state["checked"] = now.isoformat(timespec="seconds")
    _save(state)
    return state


def _within(at, cutoff: datetime) -> bool:
    try:
        return datetime.fromisoformat(str(at).replace("Z", "+00:00")) >= cutoff
    except ValueError:
        return False


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()


def _plain(text: str) -> str:
    """Lower case, accents off, suffixes and punctuation out: how names are compared."""
    text = _SUFFIX.sub(" ", _ascii(text))
    return re.sub(r"[^a-z ]+", " ", text.lower())


def _patterns(names: dict) -> dict:
    """{player id: [regex]} - his full name, and his last name alone where no
    other player given shares it (the callers give the injured, a few dozen)."""
    last_count = {}
    parts = {}
    for pid, name in names.items():
        words = _plain(name).split()
        if len(words) < 2:
            continue
        parts[pid] = words
        last_count[words[-1]] = last_count.get(words[-1], 0) + 1
    out = {}
    for pid, words in parts.items():
        # (regex, on the plain text?, his first name) - a full name on the
        # plain text; a last name alone only as written, capitalized, so
        # "Brown" is a player and "brown" is not, and not after another first
        # name ("Mike Hall Jr" is not Breece Hall).
        pats = [(re.compile(r"\b" + r"\s+".join(map(re.escape, words)) + r"\b"), True, None)]
        if last_count[words[-1]] == 1 and len(words[-1]) >= 4:
            first = re.sub(r"[^a-z]", "", _ascii(names[pid]).lower().split()[0])
            pats.append((re.compile(r"\b" + re.escape(words[-1].capitalize()) + r"\b"), False,
                         first))
        out[pid] = pats
    return out


def _near(a: str, b: str) -> bool:
    """The same first name give or take a typo ("Mke"), or one cut short ("Cam")."""
    if a == b or (min(len(a), len(b)) >= 3 and (a.startswith(b) or b.startswith(a))):
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    return a[i + 1:] == b[i + 1:] or a[i + 1:] == b[i:] or a[i:] == b[i + 1:]


def _named_at(regex, text: str, first: str = None):
    """Where the post names him (the offset), or None: any match of a full
    name; a last name alone unless the capitalized word just before it is
    someone else's first name."""
    for m in regex.finditer(text):
        if first is None:
            return m.start()
        before = _BEFORE.search(text[max(0, m.start() - 30):m.start()])
        word = re.sub(r"[^a-z]", "", before.group(1).lower()) if before else ""
        if not word or word in _LEAD or _near(word, first):
            return m.start()
    return None


def _names(regex, text: str, first: str = None) -> bool:
    return _named_at(regex, text, first) is not None


def _about_injury(text: str, at: int) -> bool:
    """An injury word within WINDOW characters of the name at `at`."""
    return bool(INJURY.search(text[max(0, at - WINDOW):at + WINDOW]))


def links(names: dict, state: dict = None, now: datetime = None) -> dict:
    """{player id: {"handle", "who", "url", "at"}}: the newest kept post naming
    each player in `names` ({id: full name}) with an injury word near his name
    (INJURY, WINDOW), from the last LINK_DAYS."""
    state = _load() if state is None else state
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=LINK_DAYS)
    who = dict(ACCOUNTS)
    pats = _patterns(names)
    out = {}
    for p in sorted(state.get("posts") or [], key=lambda p: p.get("at") or "", reverse=True):
        if not _within(p.get("at"), cutoff):
            continue
        plain, raw = _plain(p.get("text") or ""), _ascii(p.get("text") or "")
        for pid, regexes in pats.items():
            if pid in out:
                continue
            if any(_about_injury(t, at) for t, at in
                   ((plain if on_plain else raw,
                     _named_at(r, plain if on_plain else raw, first))
                    for r, on_plain, first in regexes) if at is not None):
                out[pid] = {"handle": p["handle"], "who": who.get(p["handle"], p["handle"]),
                            "url": f"https://x.com/{p['handle']}/status/{p['id']}",
                            "at": p.get("at")}
    return out


if __name__ == "__main__":
    st = refresh(force=True)
    print(f"{len(st.get('posts') or [])} posts kept; {st.get('reads', 0)} read this month "
          f"(cap {MONTHLY_CAP})" if os.getenv(TOKEN_ENV) else f"no {TOKEN_ENV}: nothing fetched")
