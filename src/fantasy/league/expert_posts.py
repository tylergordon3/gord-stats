"""
Injury posts on X, matched to the players they are about - the Team and
Matchups pages link to one beside a player's injury pills ("PT ↗", "Dr ↗",
"News ↗").

Two kinds of account (ACCOUNTS):

  experts   physical therapists and a team doctor, whose posts are analysis -
            how long, how bad, what it means;
  news      national insiders and Underdog's NFL desk, whose posts are status
            lines for nearly every fantasy-relevant player ("Ladd McConkey
            (foot) listed questionable for Week 4").

A player with both gets the expert's take: his pill already says the status.

X's API (v2), app-only: a bearer token in X_BEARER_TOKEN, which the Pi's
builds read from ~/secrets/gord-stats.env. Without one this does nothing and
the pages carry no links - the site never depends on it.

X bills each post read (pay per use, about half a cent a post, 2026), and the
budget is MONTHLY_CAP posts (the owner's $15), so the reader asks for exactly
what it wants and nothing else:

  * one recent search per kind of account - `from:` the accounts, AND injury
    words, no reposts - so only injury posts are read and billed (the two PTs'
    timelines were 63% streams and promos; the insiders post dozens a day);
  * only new posts: each search continues from the newest post already read
    (since_id), so a post is paid for once;
  * at most every REFRESH_MINUTES, however often the pages rebuild;
  * a first search takes one page (FIRST_READ), never the whole week;
  * a day's allowance - twice the day's even share of what is left of the
    month - so a Sunday can spend more than a Tuesday but cannot spend the
    month; and the monthly cap itself, past which nothing is fetched until
    the month turns.

What is kept (data/fantasy/players/expert_posts.json, git-ignored, the Pi's
own): the last KEEP_DAYS of posts - id, account, time, and the text, which is
used only to find the players named in it. The pages show a link to the post
on X, never the post itself.

    refresh()        fetch what is new, within the limits
    links(names)     {player id: the post to link}, for the names given

    python -m fantasy.league.expert_posts      # refresh and print the matches
"""
import calendar
import json
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone

import requests

from fantasy import paths

# (handle, who, kind, label) - every handle checked against X's user lookup
# on 2026-10-02 (guessed handles for two other analysts were empty accounts).
ACCOUNTS = (
    ("jmthrivept", "Jeff Mueller, PT, DPT", "experts", "PT"),
    ("TheFantasyPT", "Matthew Betz, PT (The Fantasy PT)", "experts", "PT"),
    ("FBInjuryDoc", "Edwin Porras, DPT", "experts", "PT"),
    ("ProFootballDoc", "Dr. David Chao, former NFL team doctor", "experts", "Dr"),
    ("AdamSchefter", "Adam Schefter, ESPN", "news", "News"),
    ("RapSheet", "Ian Rapoport, NFL Network", "news", "News"),
    ("TomPelissero", "Tom Pelissero", "news", "News"),
    ("UnderdogNFL", "Underdog NFL", "news", "News"),
)
# What each search asks X for besides the accounts. The experts write about
# bodies; the news accounts' injury posts are status lines, and asking them for
# body parts would pay for every "a foot in the end zone".
TERMS = {
    "experts": ('injury OR injured OR hamstring OR ankle OR knee OR ACL OR MCL OR concussion '
                'OR shoulder OR groin OR calf OR quad OR hip OR foot OR toe OR wrist OR elbow '
                'OR Achilles OR IR OR surgery OR MRI OR sprain OR strain OR torn OR fracture '
                'OR rehab OR setback OR timeline'),
    "news": ('questionable OR doubtful OR "ruled out" OR "will not play" OR "out for" '
             'OR "will miss" OR "expected to miss" OR "placed on IR" OR "injured reserve" '
             'OR "did not practice" OR DNP OR "limited practice" OR "day-to-day" '
             'OR "week-to-week" OR surgery OR torn OR MRI OR concussion'),
}
API = "https://api.x.com/2"
TOKEN_ENV = "X_BEARER_TOKEN"
CACHE = paths.DATA_DIR / "players" / "expert_posts.json"
REFRESH_MINUTES = 30
FIRST_READ = 100            # a first search: a page - about a week of a news desk's
                            # injury lines, once (~$0.50), so coverage starts full
MONTHLY_CAP = 3000          # posts read a month: ~$15 at half a cent a post
PAGES = 3                   # pages of 100 a search may take in one refresh
KEEP_DAYS = 14
LINK_DAYS = 7               # a post older than this is not linked
TIMEOUT = 20
QUERY_MAX = 512             # X's longest search query on this plan

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


def query(kind: str) -> str:
    """The search for one kind of account: from them, about an injury, no reposts."""
    handles = " OR ".join(f"from:{h}" for h, _w, k, _l in ACCOUNTS if k == kind)
    return f"({handles}) ({TERMS[kind]}) -is:retweet"


def _day_budget(state: dict, now: datetime) -> int:
    """Twice the day's even share of what is left of the month."""
    days = calendar.monthrange(now.year, now.month)[1]
    left = max(0, MONTHLY_CAP - state.get("reads", 0))
    return int(2 * left / (days - now.day + 1))


def refresh(force: bool = False, now: datetime = None) -> dict:
    """Search each kind of account for new injury posts, within the limits
    above. Returns the kept state; a missing token, a spent budget or an
    error leaves it as it was."""
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
    month, day = now.strftime("%Y-%m"), now.strftime("%Y-%m-%d")
    if state.get("month") != month:
        state["month"], state["reads"] = month, 0
    if state.get("day") != day:
        state["day"], state["day_reads"] = day, 0
        state["day_budget"] = _day_budget(state, now)
    since = state.setdefault("search_since", {})
    posts = state.setdefault("posts", [])

    def left():
        return min(MONTHLY_CAP - state.get("reads", 0),
                   state.get("day_budget", 0) - state.get("day_reads", 0))

    for kind in TERMS:
        params = {"query": query(kind), "tweet.fields": "created_at,author_id",
                  "expansions": "author_id", "user.fields": "username"}
        if since.get(kind):
            params["since_id"] = since[kind]
        first, newest = True, None
        for _page in range(PAGES if since.get(kind) else 1):
            room = left()
            if room < 10:                       # X will not return fewer than 10
                print(f"  ! X posts: today's share of the month's {MONTHLY_CAP} reads is "
                      "spent; nothing more fetched until tomorrow")
                break
            params["max_results"] = (min(100, room) if since.get(kind)
                                     else max(10, min(FIRST_READ, room)))
            try:
                got = _get("/tweets/search/recent", token, params)
            except Exception as exc:                        # noqa: BLE001
                print(f"  ! X posts ({kind}) unavailable ({exc})")
                break
            new = got.get("data") or []
            state["reads"] = state.get("reads", 0) + len(new)
            state["day_reads"] = state.get("day_reads", 0) + len(new)
            names = {u["id"]: u["username"] for u in (got.get("includes") or {}).get("users", [])}
            posts.extend({"id": p["id"], "handle": names.get(p.get("author_id"), "?"),
                          "at": p.get("created_at"), "text": p.get("text") or ""} for p in new)
            meta = got.get("meta") or {}
            if first:
                newest = meta.get("newest_id")
                first = False
            if not meta.get("next_token"):
                break
            params["pagination_token"] = meta["next_token"]
        if newest:
            since[kind] = newest
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
    """{player id: {"handle", "who", "label", "url", "at"}}: for each player in
    `names` ({id: full name}), the newest kept post from the last LINK_DAYS
    that names him with an injury word near his name (INJURY, WINDOW) - an
    expert's take before a news account's, since his pill already says the
    status. Posts from accounts no longer read are not linked."""
    state = _load() if state is None else state
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=LINK_DAYS)
    acct = {h.lower(): (h, w, k, lbl) for h, w, k, lbl in ACCOUNTS}
    pats = _patterns(names)
    out = {}
    rank = {"experts": 0, "news": 1}
    ordered = sorted((p for p in state.get("posts") or [] if p.get("handle", "").lower() in acct),
                     key=lambda p: p.get("at") or "", reverse=True)
    ordered.sort(key=lambda p: rank[acct[p["handle"].lower()][2]])     # stable: newest within each
    for p in ordered:
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
                handle, who, _kind, label = acct[p["handle"].lower()]
                out[pid] = {"handle": handle, "who": who, "label": label,
                            "url": f"https://x.com/{handle}/status/{p['id']}",
                            "at": p.get("at")}
    return out


if __name__ == "__main__":
    st = refresh(force=True)
    print(f"{len(st.get('posts') or [])} posts kept; {st.get('reads', 0)} read this month "
          f"(cap {MONTHLY_CAP}); today {st.get('day_reads', 0)} of {st.get('day_budget', 0)}"
          if os.getenv(TOKEN_ENV) else f"no {TOKEN_ENV}: nothing fetched")
