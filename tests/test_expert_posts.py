"""
Physical therapists' takes on X (fantasy.league.expert_posts): paid per post
read, so only new posts, at most every half hour, under a monthly cap; and
matched to players by name - full name, or a capitalized last name nobody else
on the report shares. The pages link to the post, never show it.
"""
from datetime import datetime, timedelta, timezone

import pytest

from fantasy.league import expert_posts as ep
from fantasy.site import matchups as mu

NOW = datetime(2026, 10, 2, 3, 0, tzinfo=timezone.utc)


class FakeX:
    """X's two endpoints, recording what was asked."""

    def __init__(self, timelines):
        self.timelines, self.calls = timelines, []

    def __call__(self, url, headers=None, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        assert headers["Authorization"] == "Bearer tok"
        if "/users/by/username/" in url:
            handle = url.rsplit("/", 1)[-1]
            return _Resp({"data": {"id": f"id-{handle}"}})
        handle = url.split("/users/id-")[1].split("/")[0]
        posts = [p for p in self.timelines.get(handle, [])
                 if not params.get("since_id") or int(p["id"]) > int(params["since_id"])]
        meta = {"newest_id": max((p["id"] for p in posts), key=int)} if posts else {}
        return _Resp({"data": posts, "meta": meta} if posts else {"meta": {}})


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


def test_without_a_token_nothing_is_fetched(cache, monkeypatch):
    monkeypatch.delenv(ep.TOKEN_ENV)
    fake = FakeX({})
    monkeypatch.setattr(ep.requests, "get", fake)
    assert ep.refresh(force=True, now=NOW) == {}
    assert fake.calls == []


def test_only_new_posts_are_paid_for_and_the_half_hour_holds(cache, monkeypatch):
    fake = FakeX({"jmthrivept": [_post(10, "Achane ACL: season over")], "TheFantasyPT": []})
    monkeypatch.setattr(ep.requests, "get", fake)
    st = ep.refresh(now=NOW)
    tweets = [c for c in fake.calls if "/tweets" in c[0]]
    assert all(c[1]["max_results"] == ep.FIRST_READ and "since_id" not in c[1] for c in tweets)
    assert st["reads"] == 1 and st["since"]["jmthrivept"] == "10"
    # Ten minutes on: nothing asked at all.
    n = len(fake.calls)
    ep.refresh(now=NOW + timedelta(minutes=10))
    assert len(fake.calls) == n
    # An hour on: only what came after the newest kept, and the ids are not looked up again.
    fake.timelines["jmthrivept"].append(_post(11, "Etienne hamstring, 4-6 weeks", hours_ago=0))
    st = ep.refresh(now=NOW + timedelta(hours=1))
    later = fake.calls[n:]
    assert not any("/users/by/username/" in c[0] for c in later)
    mine = [c for c in later if "id-jmthrivept" in c[0]][0]
    assert mine[1]["since_id"] == "10" and mine[1]["max_results"] == 100
    assert st["reads"] == 2 and [p["id"] for p in st["posts"]] == ["11", "10"]


def test_the_monthly_cap_stops_fetching_until_the_month_turns(cache, monkeypatch):
    fake = FakeX({"jmthrivept": [_post(10, "x")], "TheFantasyPT": []})
    monkeypatch.setattr(ep.requests, "get", fake)
    ep._save({"month": "2026-10", "reads": ep.MONTHLY_CAP, "users": {}, "since": {}, "posts": []})
    ep.refresh(force=True, now=NOW)
    assert fake.calls == []
    ep.refresh(force=True, now=NOW + timedelta(days=30))           # November
    assert fake.calls


def test_old_posts_are_dropped(cache, monkeypatch):
    fake = FakeX({"jmthrivept": [_post(1, "old", hours_ago=24 * (ep.KEEP_DAYS + 1)),
                                 _post(2, "new")], "TheFantasyPT": []})
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
