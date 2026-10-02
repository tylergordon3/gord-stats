"""
Injury posts on X (fantasy.league.expert_posts): paid per post read, so one
search per kind of account asks only for injury posts, only new ones, at most
every half hour, within a day's share of a monthly cap; matched to players by
name - full name, or a capitalized last name nobody else on the report shares -
with an injury word near it. The pages link to the post, never show it.
"""
from datetime import datetime, timedelta, timezone

import pytest

from fantasy.league import expert_posts as ep
from fantasy.site import matchups as mu

NOW = datetime(2026, 10, 2, 3, 0, tzinfo=timezone.utc)
IDS = {h: f"id-{h}" for h, *_ in ep.ACCOUNTS}


class FakeX:
    """X's recent search: posts from the accounts in the query, newer than
    since_id, newest first, in pages."""

    def __init__(self, posts):
        self.posts, self.calls = posts, []          # {handle: [post]}

    def __call__(self, url, headers=None, params=None, timeout=None):
        params = dict(params or {})
        self.calls.append((url, params))
        assert headers["Authorization"] == "Bearer tok"
        assert url.endswith("/tweets/search/recent")
        q = params["query"]
        assert "-is:retweet" in q and len(q) <= ep.QUERY_MAX
        hits = [dict(p, author_id=IDS[h]) for h, ps in self.posts.items()
                if f"from:{h} " in q + " " or f"from:{h})" in q for p in ps
                if not params.get("since_id") or int(p["id"]) > int(params["since_id"])]
        hits.sort(key=lambda p: int(p["id"]), reverse=True)
        start = int(params.get("pagination_token") or 0)
        page = hits[start:start + params["max_results"]]
        meta = {"newest_id": hits[0]["id"]} if hits else {}
        if start + params["max_results"] < len(hits):
            meta["next_token"] = str(start + params["max_results"])
        users = [{"id": IDS[h], "username": h} for h in self.posts]
        return _Resp({"data": page, "meta": meta, "includes": {"users": users}} if page
                     else {"meta": meta})


class _Resp:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(ep, "CACHE", tmp_path / "expert_posts.json")
    monkeypatch.setenv(ep.TOKEN_ENV, "tok")
    return tmp_path


def _post(pid, text, hours_ago=1):
    return {"id": str(pid), "text": text,
            "created_at": (NOW - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")}


def test_each_search_asks_only_for_injury_posts_from_its_own_accounts():
    experts, news = ep.query("experts"), ep.query("news")
    assert "from:jmthrivept" in experts and "from:ProFootballDoc" in experts
    assert "from:UnderdogNFL" in news and "from:AdamSchefter" in news
    assert "from:UnderdogNFL" not in experts and "from:jmthrivept" not in news
    assert "hamstring" in experts and '"ruled out"' in news and "questionable" in news
    # The news search asks for status lines, not body parts ("a foot in the end zone").
    assert " foot " not in news
    assert all(len(q) <= ep.QUERY_MAX and q.endswith("-is:retweet") for q in (experts, news))


def test_without_a_token_nothing_is_fetched(cache, monkeypatch):
    monkeypatch.delenv(ep.TOKEN_ENV)
    fake = FakeX({})
    monkeypatch.setattr(ep.requests, "get", fake)
    assert ep.refresh(force=True, now=NOW) == {}
    assert fake.calls == []


def test_only_new_posts_are_paid_for_and_the_half_hour_holds(cache, monkeypatch):
    fake = FakeX({"jmthrivept": [_post(10, "Achane ACL: season over")],
                  "UnderdogNFL": [_post(20, "Ladd McConkey (foot) listed questionable")]})
    monkeypatch.setattr(ep.requests, "get", fake)
    st = ep.refresh(now=NOW)
    assert len(fake.calls) == 2                     # one search per kind
    assert all(c[1]["max_results"] == ep.FIRST_READ and "since_id" not in c[1] for c in fake.calls)
    assert st["reads"] == 2 and st["search_since"] == {"experts": "10", "news": "20"}
    assert {p["handle"] for p in st["posts"]} == {"jmthrivept", "UnderdogNFL"}
    # Ten minutes on: nothing asked at all.
    n = len(fake.calls)
    ep.refresh(now=NOW + timedelta(minutes=10))
    assert len(fake.calls) == n
    # An hour on: only what came after the newest read, in pages of 100.
    fake.posts["jmthrivept"].append(_post(11, "Etienne hamstring, 4-6 weeks", hours_ago=0))
    st = ep.refresh(now=NOW + timedelta(hours=1))
    later = fake.calls[n:]
    assert [c[1]["since_id"] for c in later] == ["10", "20"]
    assert all(c[1]["max_results"] == 100 for c in later)
    assert st["reads"] == 3 and [p["id"] for p in st["posts"]][:1] == ["11"]


def test_a_busy_hour_pages_on_and_the_since_id_is_the_newest(cache, monkeypatch):
    monkeypatch.setattr(ep, "MONTHLY_CAP", 30000)       # the day's share is not what is tested
    ep._save({"search_since": {"experts": "0", "news": "0"}})
    fake = FakeX({"UnderdogNFL": [_post(i, f"Player {i} (ankle) ruled out") for i in range(1, 251)]})
    monkeypatch.setattr(ep.requests, "get", fake)
    st = ep.refresh(force=True, now=NOW)
    news = [c for c in fake.calls if "UnderdogNFL" in c[1]["query"]]
    assert len(news) == 3 and st["search_since"]["news"] == "250"
    assert st["reads"] == 250


def test_a_day_spends_at_most_twice_its_share_and_the_month_its_cap(cache, monkeypatch):
    fake = FakeX({"UnderdogNFL": [_post(i, f"P{i} (knee) out for the season") for i in range(1, 400)]})
    monkeypatch.setattr(ep.requests, "get", fake)
    # October 2 with the whole month left: 30 days -> twice 3000/30 = 200 today.
    ep._save({"search_since": {"experts": "0", "news": "0"}})
    st = ep.refresh(force=True, now=NOW)
    assert st["day_budget"] == 200 and st["day_reads"] <= 200
    n = len(fake.calls)
    ep.refresh(force=True, now=NOW + timedelta(hours=1))
    assert len(fake.calls) == n, "today's share spent: nothing more until tomorrow"
    # The monthly cap: nothing at all until November.
    ep._save({"month": "2026-10", "reads": ep.MONTHLY_CAP, "posts": [], "search_since": {}})
    fake.calls.clear()
    ep.refresh(force=True, now=NOW + timedelta(days=1))
    assert fake.calls == []
    ep.refresh(force=True, now=NOW + timedelta(days=30))           # November
    assert fake.calls


def test_old_posts_are_dropped(cache, monkeypatch):
    fake = FakeX({"jmthrivept": [_post(1, "old ankle", hours_ago=24 * (ep.KEEP_DAYS + 1)),
                                 _post(2, "new ankle")]})
    monkeypatch.setattr(ep.requests, "get", fake)
    st = ep.refresh(force=True, now=NOW)
    assert [p["id"] for p in st["posts"]] == ["2"]


def _state(*posts):
    return {"posts": [{"id": str(i), "handle": "jmthrivept", "at": at, "text": t}
                      for i, (t, at) in enumerate(posts, 1)]}


def _at(hours_ago):
    return (NOW - timedelta(hours=hours_ago)).isoformat()


def test_names_match_in_full_or_by_an_unshared_capitalized_last_name():
    names = {"9226": "De'Von Achane", "4892": "Travis Etienne Jr.", "1": "A.J. Brown",
             "2": "Marquise Brown", "3": "Jaylen Waddle"}
    st = _state(("Etienne looks like a 4-6 week hamstring", _at(2)),
                ("Devon Achane ACL, out for the year", _at(3)),
                ("Brown (ankle) - which one? lots of brown bruising", _at(1)),
                ("waddle walk", _at(1)))
    got = ep.links(names, st, now=NOW)
    assert set(got) == {"9226", "4892"}
    assert got["4892"]["url"] == "https://x.com/jmthrivept/status/1"
    assert got["9226"]["who"] == "Jeff Mueller, PT, DPT"


def test_a_last_name_after_someone_elses_first_name_is_not_him():
    # The first read's posts: "Mike Hall Jr" is a defensive tackle, not
    # Breece Hall; a lead-in word or a typo of his own first name still counts.
    names = {"1": "Breece Hall", "2": "Mike Evans", "3": "De'Von Achane", "4": "Cam Ward"}
    st = _state(("Officially an ankle injury?? Mike Hall Jr may have dodged a bullet.", _at(1)),
                ("Injury updates: Jalen Coker And Mke Evans And Terrance Ferguson", _at(2)),
                ("Limited in practice: And Baker And Breece And Achane And Etienne", _at(3)),
                ("Cameron Ward elbow, should be fine", _at(4)))
    assert set(ep.links(names, st, now=NOW)) == {"2", "3", "4"}
    st = _state(("Hall (ankle) limited Wednesday", _at(1)))
    assert set(ep.links(names, st, now=NOW)) == {"1"}


def test_the_newest_post_wins_and_old_ones_are_not_linked():
    names = {"9226": "De'Von Achane"}
    st = _state(("Achane hamstring update", _at(1)), ("Achane first look at the injury", _at(30)))
    assert ep.links(names, st, now=NOW)["9226"]["url"].endswith("/1")
    stale = _state(("Achane ankle", _at(24 * (ep.LINK_DAYS + 1))))
    assert ep.links(names, stale, now=NOW) == {}


def test_the_page_links_to_the_post_and_shows_none_of_it():
    card = {"pt": {"handle": "jmthrivept", "who": "Jeff Mueller, PT, DPT", "at": _at(1),
                   "url": "https://x.com/jmthrivept/status/123\"><script>"}}
    html = mu.avail_badges(card)
    assert "class=\"mu-pt\"" in html and "PT&nbsp;&#8599;" in html
    assert "<script>" not in html and "&quot;&gt;&lt;script&gt;" in html
    assert "Jeff Mueller, PT, DPT on X" in html


def test_only_a_post_about_an_injury_is_linked():
    """The accounts post streams and promos too (41 of their first 65 posts had
    no injury word in them); naming a player is not a take on his injury."""
    names = {"9226": "De'Von Achane", "1": "Breece Hall"}
    st = _state(("Live tonight at 9! Talking Achane, Hall and more - subscribe", _at(1)),)
    assert ep.links(names, st, now=NOW) == {}
    st = _state(("Achane hamstring: tight Thursday, I'd expect him to play", _at(1)),
                ("Breece Hall " + "and a long way of talking about other things " * 6
                 + "while somebody else's ACL is the news", _at(2)))
    assert set(ep.links(names, st, now=NOW)) == {"9226"}, "an injury word 200+ characters off"
    # Plain-text forms count: "x-ray" written "x ray", "week-to-week".
    st = _state(("Breece Hall week-to-week per the x-ray", _at(1)),)
    assert set(ep.links(names, st, now=NOW)) == {"1"}


def test_an_experts_take_comes_before_the_news_and_says_whose_it_is():
    names = {"9226": "De'Von Achane", "1": "Ladd McConkey"}
    st = {"posts": [
        {"id": "30", "handle": "UnderdogNFL", "at": _at(1), "text": "De'Von Achane (hamstring) questionable"},
        {"id": "31", "handle": "UnderdogNFL", "at": _at(1), "text": "Ladd McConkey (foot) listed questionable"},
        {"id": "12", "handle": "ProFootballDoc", "at": _at(20), "text": "Achane hamstring looked mild on film"},
        {"id": "13", "handle": "someone_else", "at": _at(0), "text": "Ladd McConkey foot injury"}]}
    got = ep.links(names, st, now=NOW)
    assert got["9226"]["handle"] == "ProFootballDoc" and got["9226"]["label"] == "Dr"
    assert got["1"]["label"] == "News" and got["1"]["url"].endswith("/UnderdogNFL/status/31")
    html = mu.avail_badges({"pt": got["1"]})
    assert "News&nbsp;&#8599;" in html and "Underdog NFL on X" in html
