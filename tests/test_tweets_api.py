"""
/api/tweets: readers send in posts from X, the owner approves, readers vote.

The Functions run in headless Chromium against a real SQLite built from
deploy/d1-schema.sql (tests/functions_harness.py), so the SQL is exercised as
written. X's oEmbed is never reached: every fetch a Function makes goes
through the harness's T.routes, and the tests below answer oEmbed there.
"""
import json
import re
import sqlite3

import pytest

from functions_harness import CHROME, FUNCTIONS, SCHEMA, Worker

pytestmark = pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")

TWEETS = FUNCTIONS / "api" / "tweets.js"
ROUTE = FUNCTIONS / "api" / "tweets" / "[[route]].js"
MIDDLEWARE = FUNCTIONS / "api" / "_middleware.js"
MIGRATION_005 = SCHEMA.parent / "d1-migrate-005-tweets.sql"
URL = "https://www.gordstats.com/api/tweets"
ID = "1841234567890123456"            # past 2^53, as X's are


@pytest.fixture
def worker():
    with Worker() as w:
        w.load(TWEETS, "tw")
        w.load(ROUTE, "twr")
        yield w


def oembed_body(tid, handle="CFBHumor", name="CFB Humor",
                words="Big Noon Kickoff &amp; friends", media=""):
    """What X's oEmbed answers for a public post."""
    html = (f'<blockquote class="twitter-tweet" data-dnt="true"><p lang="en" dir="ltr">'
            f'{words}{media}</p>&mdash; {name} (@{handle}) <a href="https://twitter.com/'
            f'{handle}/status/{tid}?ref_src=twsrc%5Etfw">October 2, 2026</a></blockquote>\n')
    return {"url": f"https://twitter.com/{handle}/status/{tid}", "author_name": name,
            "author_url": f"https://twitter.com/{handle}", "html": html, "width": 550,
            "type": "rich", "provider_name": "Twitter", "version": "1.0"}


def stub_oembed(w, answers):
    """oEmbed answered from {tweet_id: (status, body)}; anything else is a 404."""
    w.js("""
      const answers = %s;
      T.routes = T.routes.filter((r) => !r[0].startsWith('^https://publish'));
      T.routes.push(['^https://publish[.]x[.]com/oembed[?]', (url) => {
        const inner = new URL(url).searchParams.get('url') || '';
        const a = answers[inner.split('/').pop()] || [404, { error: 'not found' }];
        return { status: a[0], body: a[1] };
      }]);
    """ % json.dumps(answers))


def oembed_calls(w):
    return [u for u in w.js("return T.fetches;") if "oembed" in u]


def submit(w, who, url, sport=None):
    body = {"url": url}
    if sport is not None:
        body["sport"] = sport
    return w.call("tw.onRequestPost", URL, method="POST", headers=who, body=body)


def on_post(w, who, ident, action, body=None):
    return w.call("twr.onRequestPost", f"{URL}/{ident}/{action}", method="POST", headers=who,
                  body=body if body is not None else {},
                  ctx="{ params: { route: [%s, %s] } }" % (json.dumps(str(ident)),
                                                          json.dumps(action)))


def owner(w):
    who = w.user("owner")
    w.sql.execute("UPDATE users SET is_admin = 1 WHERE id = 'owner'")
    return who


def add(w, tid, status="approved", days_ago=1, handle="h", text="t", uid=None):
    """A post put straight into the table, approved `days_ago` days back."""
    w.sql.execute(
        "INSERT INTO tweets (tweet_id, handle, author, text, has_media, sport, submitted_by,"
        " submitted_at, status, reviewed_at) VALUES (?, ?, ?, ?, 0, 'cfb', ?,"
        " strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?), ?,"
        " strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?))",
        tid, handle, f"Author {tid}", text, uid, f"-{days_ago} days", status,
        f"-{days_ago} days")
    return w.sql.rows("SELECT id FROM tweets WHERE tweet_id = ?", tid)[0]["id"]


def votes_for(w, post_id, *uids):
    for uid in uids:
        if not w.sql.rows("SELECT id FROM users WHERE id = ?", uid):
            w.user(uid)
        w.sql.execute("INSERT INTO tweet_votes (tweet_id, user_id) VALUES (?, ?)", post_id, uid)


# --------------------------------------------------------------------------- #
# Reading a link and X's answer
# --------------------------------------------------------------------------- #

GOOD = [
    (f"https://x.com/CFBHumor/status/{ID}", ID, "CFBHumor"),
    (f"https://twitter.com/CFBHumor/status/{ID}?s=46&t=abc", ID, "CFBHumor"),
    (f"https://www.x.com/a_b/status/{ID}/photo/1", ID, "a_b"),
    (f"https://mobile.twitter.com/NFL/status/{ID}", ID, "NFL"),
    (f"https://www.twitter.com/NFL/statuses/{ID}#m", ID, "NFL"),
    (f"https://X.COM/NFL/status/{ID}/video/1", ID, "NFL"),
    (f"  x.com/NFL/status/{ID}  ", ID, "NFL"),                  # pasted without a scheme
    (f"https://x.com/i/status/{ID}", ID, None),
    (f"https://x.com/i/web/status/{ID}", ID, None),
    (f"https://x.com:443/NFL/status/{ID}", ID, "NFL"),          # the default port is no port
]

BAD = [
    f"http://x.com/NFL/status/{ID}",                            # not https
    f"https://x.com.evil.example/NFL/status/{ID}",              # lookalike hosts
    f"https://evilx.com/NFL/status/{ID}",
    f"https://twitter.com.evil.example/NFL/status/{ID}",
    f"https://fxtwitter.com/NFL/status/{ID}",
    f"https://vxtwitter.com/NFL/status/{ID}",
    f"https://x.co/NFL/status/{ID}",
    f"https://twitter.com./NFL/status/{ID}",
    f"https://x.com@evil.example/NFL/status/{ID}",              # a user, not a host
    f"https://user:pw@x.com/NFL/status/{ID}",
    f"https://x.com:8443/NFL/status/{ID}",
    f"https://evil.example/x.com/NFL/status/{ID}",
    f"https://evil.example/?u=https://x.com/NFL/status/{ID}",
    f"https://evil.example#https://x.com/NFL/status/{ID}",
    f"https://xn--80ak6aa92e.com/NFL/status/{ID}",              # a Cyrillic look-alike, punycoded
    "https://x.com/NFL",                                        # not a post
    "https://x.com/NFL/likes",
    "https://x.com/search?q=status/123",
    "https://x.com/NFL/status/",
    "https://x.com/NFL/status/abc",
    "https://x.com/NFL/status/0123",
    "https://x.com/NFL/status/123456789012345678901",           # 21 digits
    f"https://x.com/this_handle_is_too_long/status/{ID}",
    f"https://x.com/NFL/status/{ID} and some words",
    f"javascript:alert(1)//x.com/NFL/status/{ID}",
    "", None, 7,
]


def test_only_a_link_to_a_post_on_x_is_read(worker):
    got = worker.js("return %s.map((u) => tw.tweetId(u));" % json.dumps([g[0] for g in GOOD]))
    assert got == [{"id": i, "handle": h} for _, i, h in GOOD]
    bad = worker.js("return %s.map((u) => tw.tweetId(u));" % json.dumps(BAD))
    assert bad == [None] * len(BAD), [b for b, g in zip(BAD, bad) if g]


def test_the_card_is_plain_text_from_oembed(worker):
    hostile = ("<b>Bold</b> &lt;script&gt;alert(1)&lt;/script&gt; Tom &amp; Jerry&#39;s "
               "&#x1F3C8; &quot;q&quot; &amp;lt;x&amp;gt; &#0; &#xD800;<br>line two "
               "‮evil‬ <a href=\"https://t.co/abc\">espn.com/story</a> "
               "<a href=\"https://t.co/p\">pic.twitter.com/AbC123</a>")
    out = worker.js("return tw.fromOembed(%s);" % json.dumps(oembed_body(ID, words=hostile)))
    assert out["handle"] == "CFBHumor" and out["author"] == "CFB Humor"
    assert out["has_media"] == 1
    assert out["text"] == ("Bold <script>alert(1)</script> Tom & Jerry's \U0001F3C8 \"q\" "
                           "&lt;x&gt; � �\nline two evil espn.com/story")

    video = oembed_body(ID, words="Watch", media=' <a href="https://t.co/v">'
                        'twitter.com/x/status/1/video/1</a>')
    assert worker.js("return tw.fromOembed(%s).has_media;" % json.dumps(video)) == 2
    assert worker.js("return tw.fromOembed(%s).has_media;" % json.dumps(oembed_body(ID))) == 0
    picx = oembed_body(ID, words='Look <a href="https://t.co/p">pic.x.com/Zz9</a>')
    assert worker.js("return tw.fromOembed(%s);" % json.dumps(picx))["text"] == "Look"

    long = worker.js("return tw.fromOembed(%s).text;" % json.dumps(
        oembed_body(ID, words="\U0001F3C8" * 600)))
    assert len(list(long)) == 400 and long.endswith("…")

    # X's own answer for a photo post, as it came back on 2026-10-02.
    real = {"url": "https://x.com/TheEllenShow/status/440322224407314432",
            "author_name": "The Ellen Show", "author_url": "https://x.com/TheEllenShow",
            "html": '<blockquote class="twitter-tweet" data-dnt="true"><p lang="en" dir="ltr">'
                    "If only Bradley&#39;s arm was longer. Best photo ever. <a href=\"https://x.com/"
                    'hashtag/oscars?src=hash&amp;ref_src=twsrc%5Etfw">#oscars</a> <a href="http://'
                    't.co/C9U5NOtGap">pic.twitter.com/C9U5NOtGap</a></p>&mdash; The Ellen Show '
                    '(@TheEllenShow) <a href="https://x.com/TheEllenShow/status/440322224407314432'
                    '?ref_src=twsrc%5Etfw">March 3, 2014</a></blockquote>\n\n',
            "width": 550, "height": None, "type": "rich", "provider_name": "X", "version": "1.0"}
    assert worker.js("return tw.fromOembed(%s);" % json.dumps(real)) == {
        "handle": "TheEllenShow", "author": "The Ellen Show", "has_media": 1,
        "text": "If only Bradley's arm was longer. Best photo ever. #oscars"}

    odd = dict(oembed_body(ID), author_url="https://twitter.com/../evil", author_name="A\x00B")
    got = worker.js("return tw.fromOembed(%s);" % json.dumps(odd))
    assert got["handle"] is None and got["author"] == "AB"
    assert worker.js("return tw.fromOembed(null);") == {
        "handle": None, "author": None, "text": "", "has_media": 0}
    assert worker.js("return tw.postUrl('12', 'a/../b');") == "https://x.com/i/status/12"
    assert worker.js("return tw.postUrl('javascript:1', 'a');") is None


# --------------------------------------------------------------------------- #
# Sending one in
# --------------------------------------------------------------------------- #

def test_signed_out_and_unconfigured_cannot_send(worker):
    got = submit(worker, {}, f"https://x.com/a/status/{ID}")
    assert got["status"] == 401 and got["json"]["ok"] is False
    off = worker.call("tw.onRequestPost", URL, method="POST", body={"url": "x"},
                      env="({})")
    assert off["status"] == 503
    assert oembed_calls(worker) == [] and worker.sql.rows("SELECT * FROM tweets") == []


def test_a_post_goes_in_pending_from_xs_fixed_address(worker):
    who = worker.user()
    stub_oembed(worker, {ID: (200, oembed_body(ID, words="Ref &amp; the coin toss",
                                               media=' <a href="x">pic.twitter.com/AbC</a>'))})
    bad = submit(worker, who, "https://evil.example/a/status/1")
    assert bad["status"] == 400 and "status" in bad["json"]["error"]
    assert submit(worker, who, "not json at all")["status"] == 400

    got = submit(worker, who, f"https://twitter.com/whoever/status/{ID}?s=20", sport="CFB")
    assert got["status"] == 201 and got["json"]["ok"] is True
    assert got["json"]["status"] == "pending" and "queue" in got["json"]["message"]
    assert got["headers"]["cache-control"] == "no-store"
    # One call, to oEmbed's own host, with nothing from the pasted link but the number.
    assert oembed_calls(worker) == [
        "https://publish.x.com/oembed?url=https%3A%2F%2Ftwitter.com%2Fi%2Fstatus%2F"
        f"{ID}&omit_script=1&dnt=true"]
    row = worker.sql.rows("SELECT * FROM tweets")[0]
    assert row["tweet_id"] == ID and row["handle"] == "CFBHumor" and row["author"] == "CFB Humor"
    assert row["text"] == "Ref & the coin toss" and row["has_media"] == 1
    assert row["sport"] == "cfb" and row["status"] == "pending" and row["submitted_by"] == "u1"
    assert row["reviewed_at"] is None

    # Pending posts are not public.
    assert worker.call("tw.onRequestGet", URL)["json"]["tweets"] == []
    other = submit(worker, who, f"https://x.com/i/status/{'9' * 18}", sport="golf")
    assert other["status"] == 422                           # oEmbed 404: deleted or never was
    assert len(worker.sql.rows("SELECT * FROM tweets")) == 1


def test_duplicates_are_turned_away_kindly_without_asking_x(worker):
    who, admin = worker.user(), owner(worker)
    stub_oembed(worker, {ID: (200, oembed_body(ID))})
    assert submit(worker, who, f"https://x.com/a/status/{ID}")["status"] == 201
    calls = len(oembed_calls(worker))

    again = submit(worker, admin, f"https://twitter.com/b/status/{ID}/photo/1")
    assert again["status"] == 409 and again["json"]["status"] == "pending"
    assert "waiting" in again["json"]["error"]

    pid = worker.sql.rows("SELECT id FROM tweets")[0]["id"]
    assert on_post(worker, admin, pid, "review", {"action": "approve"})["json"]["ok"]
    picked = submit(worker, who, f"https://x.com/a/status/{ID}")
    assert picked["status"] == 409 and picked["json"]["status"] == "approved"
    assert "Already picked" in picked["json"]["error"]

    on_post(worker, admin, pid, "review", {"action": "remove"})
    gone = submit(worker, who, f"https://x.com/a/status/{ID}")
    assert gone["status"] == 409 and gone["json"]["status"] == "rejected"
    assert len(oembed_calls(worker)) == calls
    assert len(worker.sql.rows("SELECT * FROM tweets")) == 1


def test_x_down_or_the_post_gone_stores_nothing(worker):
    who = worker.user()
    stub_oembed(worker, {"111": (403, {"error": "protected"}), "222": (500, "oops"),
                         "333": (200, "not json")})
    gone = submit(worker, who, "https://x.com/a/status/111")
    assert gone["status"] == 422 and "deleted, protected or not public" in gone["json"]["error"]
    assert submit(worker, who, "https://x.com/a/status/222")["status"] == 502
    assert submit(worker, who, "https://x.com/a/status/333")["status"] == 502
    worker.js("T.routes.push(['^https://publish', () => new TypeError('offline')]);"
              "T.routes = T.routes.slice(-1);")
    assert submit(worker, who, "https://x.com/a/status/444")["status"] == 502
    assert worker.sql.rows("SELECT * FROM tweets") == []


def test_five_a_day_and_parallel_sends_cannot_beat_it(worker):
    who = worker.user()
    ids = [str(10**17 + i) for i in range(30)]
    stub_oembed(worker, {i: (200, oembed_body(i)) for i in ids})
    for i in ids[:5]:
        assert submit(worker, who, f"https://x.com/a/status/{i}")["status"] == 201
    calls = len(oembed_calls(worker))
    sixth = submit(worker, who, f"https://x.com/a/status/{ids[5]}")
    assert sixth["status"] == 429 and 0 < int(sixth["headers"]["retry-after"]) <= 86400
    assert len(oembed_calls(worker)) == calls, "refused before asking X"

    # Yesterday's do not count.
    worker.sql.execute("UPDATE tweets SET submitted_at = '2000-01-01T00:00:00.000Z'")
    statuses = worker.js(f"""
      const env = {worker.env()};
      const one = (i) => tw.onRequestPost({{ env, request: T.req({json.dumps(URL)}, {{
        method: "POST", headers: {json.dumps(who)},
        body: JSON.stringify({{ url: "https://x.com/a/status/" + i }}) }}) }});
      return (await Promise.all({json.dumps(ids[10:30])}.map(one))).map((r) => r.status);
    """)
    assert statuses.count(201) == 5 and statuses.count(429) == 15
    assert len(worker.sql.rows("SELECT * FROM tweets")) == 10


def test_the_daily_write_allowance_covers_sends_and_votes(worker):
    who = worker.user()
    stub_oembed(worker, {ID: (200, oembed_body(ID))})
    today = worker.js("return new Date().toISOString().slice(0, 10);")
    worker.sql.execute("UPDATE users SET write_day = ?, write_count = 1000", today)
    got = submit(worker, who, f"https://x.com/a/status/{ID}")
    assert got["status"] == 429 and oembed_calls(worker) == []
    pid = add(worker, "77")
    assert on_post(worker, who, pid, "vote")["status"] == 429
    assert worker.sql.rows("SELECT * FROM tweet_votes") == []


# --------------------------------------------------------------------------- #
# The owner's review
# --------------------------------------------------------------------------- #

def test_only_the_owner_sees_the_queue_or_reviews(worker):
    reader, admin = worker.user(), owner(worker)
    stub_oembed(worker, {ID: (200, oembed_body(ID))})
    submit(worker, reader, f"https://x.com/a/status/{ID}", sport="nfl")
    pid = worker.sql.rows("SELECT id FROM tweets")[0]["id"]

    q = f"{URL}?status=pending"
    assert worker.call("tw.onRequestGet", q)["status"] == 401
    assert worker.call("tw.onRequestGet", q, headers=reader)["status"] == 403
    assert on_post(worker, reader, pid, "review", {"action": "approve"})["status"] == 403
    assert on_post(worker, {}, pid, "review", {"action": "approve"})["status"] == 401
    assert worker.sql.rows("SELECT status FROM tweets")[0]["status"] == "pending"
    assert worker.call("tw.onRequestGet", f"{URL}?status=bogus", headers=admin)["status"] == 400

    got = worker.call("tw.onRequestGet", q, headers=admin)
    assert got["status"] == 200 and got["headers"]["cache-control"] == "no-store"
    [item] = got["json"]["tweets"]
    assert item["tweet_id"] == ID and item["submitter"] == "u1@example.com"
    assert item["status"] == "pending" and item["sport"] == "nfl"
    assert item["url"] == f"https://x.com/CFBHumor/status/{ID}"

    # The public list says who is the owner, so the profile page asks for the queue only then.
    assert worker.call("tw.onRequestGet", URL, headers=admin)["json"]["admin"] is True
    assert worker.call("tw.onRequestGet", URL, headers=reader)["json"]["admin"] is False

    bad = on_post(worker, admin, pid, "review", {"action": "delete"})
    assert bad["status"] == 400
    assert on_post(worker, admin, 999, "review", {"action": "approve"})["status"] == 404
    ok = on_post(worker, admin, pid, "review", {"action": "approve", "sport": "cfb"})
    assert ok["json"]["ok"] and ok["json"]["status"] == "approved" and ok["json"]["sport"] == "cfb"
    first = worker.sql.rows("SELECT reviewed_at FROM tweets")[0]["reviewed_at"]
    on_post(worker, admin, pid, "review", {"action": "approve"})    # a second click
    row = worker.sql.rows("SELECT reviewed_at, sport FROM tweets")[0]
    assert row == {"reviewed_at": first, "sport": "cfb"}, "no second week, sport kept"

    pub = worker.call("tw.onRequestGet", URL)["json"]["tweets"]
    assert [t["tweet_id"] for t in pub] == [ID]
    assert worker.call("tw.onRequestGet", f"{URL}?status=approved",
                       headers=admin)["json"]["tweets"][0]["id"] == pid

    assert on_post(worker, admin, pid, "review", {"action": "remove"})["json"]["status"] == "rejected"
    assert worker.call("tw.onRequestGet", URL)["json"]["tweets"] == []
    assert worker.call("tw.onRequestGet", f"{URL}?status=rejected",
                       headers=admin)["json"]["tweets"][0]["id"] == pid


def test_the_owner_flag_is_read_from_the_database_not_the_session(worker):
    who = worker.user()
    pid = add(worker, "5", status="pending")
    assert on_post(worker, who, pid, "review", {"action": "approve"})["status"] == 403
    worker.sql.execute("UPDATE users SET is_admin = 1 WHERE id = 'u1'")
    assert on_post(worker, who, pid, "review", {"action": "approve"})["status"] == 200


# --------------------------------------------------------------------------- #
# The week, and votes
# --------------------------------------------------------------------------- #

def test_the_week_ranks_by_votes_and_earlier_weeks_fill_it_out(worker):
    a, b, c = add(worker, "1", days_ago=1), add(worker, "2", days_ago=2), add(worker, "3", days_ago=3)
    old_best, old_rest = add(worker, "4", days_ago=20), add(worker, "5", days_ago=9)
    add(worker, "6", status="pending", days_ago=0)
    add(worker, "7", status="rejected", days_ago=1)
    votes_for(worker, c, "x1", "x2")
    votes_for(worker, b, "x1")
    votes_for(worker, old_best, "x1", "x2", "x3")

    got = worker.call("tw.onRequestGet", URL)
    body = got["json"]
    assert got["status"] == 200 and body["ok"] and body["signedIn"] is False
    assert got["headers"]["cache-control"] == "public, max-age=60"
    assert got["headers"]["vary"] == "cookie"
    # This week by votes, ties newest first; then earlier weeks' best, marked.
    assert [t["id"] for t in body["tweets"]] == [c, b, a, old_best, old_rest]
    assert body["week"] == 3
    assert [t.get("earlier", False) for t in body["tweets"]] == [False] * 3 + [True] * 2
    assert [t["votes"] for t in body["tweets"]] == [2, 1, 0, 3, 0]
    first = body["tweets"][0]
    assert set(first) == {"id", "tweet_id", "url", "handle", "author", "text", "has_media",
                          "sport", "votes", "mine"}
    assert first["mine"] is False and first["url"] == "https://x.com/h/status/3"

    # A full week needs no filling.
    for i in range(10, 16):
        add(worker, str(i), days_ago=0)
    full = worker.call("tw.onRequestGet", URL)["json"]
    assert full["week"] == 9 and not any(t.get("earlier") for t in full["tweets"])


def test_a_vote_toggles_and_counts(worker):
    who, other = worker.user(), worker.user("u2")
    pid = add(worker, ID)
    pending = add(worker, "42", status="pending")

    assert on_post(worker, {}, pid, "vote")["status"] == 401
    assert on_post(worker, who, pending, "vote")["status"] == 404
    assert on_post(worker, who, 999, "vote")["status"] == 404

    on = on_post(worker, who, pid, "vote")
    assert on["status"] == 200 and on["json"] == {"ok": True, "id": pid, "votes": 1, "mine": True}
    assert on_post(worker, other, pid, "vote")["json"]["votes"] == 2

    mine = worker.call("tw.onRequestGet", URL, headers=who)
    assert mine["headers"]["cache-control"] == "no-store"
    assert mine["json"]["signedIn"] is True
    assert mine["json"]["tweets"][0]["mine"] is True and mine["json"]["tweets"][0]["votes"] == 2

    off = on_post(worker, who, pid, "vote")
    assert off["json"] == {"ok": True, "id": pid, "votes": 1, "mine": False}
    assert worker.sql.rows("SELECT user_id FROM tweet_votes") == [{"user_id": "u2"}]
    # Each toggle is taken from the reader's allowance: one row each.
    assert worker.sql.rows("SELECT write_count FROM users WHERE id = 'u1'")[0]["write_count"] == 2


def test_routes_that_are_not_a_post_action_are_not_found(worker):
    who = worker.user()
    pid = add(worker, "8")
    for route in (["x", "vote"], [str(pid), "boost"], [str(pid)], ["0", "vote"],
                  [str(pid), "vote", "again"]):
        got = worker.call("twr.onRequestPost", f"{URL}/{'/'.join(route)}", method="POST",
                          headers=who, body={}, ctx="{ params: { route: %s } }" % json.dumps(route))
        assert got["status"] == 404, route
    # The bare path through the catch-all answers as /api/tweets does.
    bare = worker.call("twr.onRequestGet", URL, ctx="{ params: {} }")
    assert bare["status"] == 200 and bare["json"]["tweets"][0]["id"] == pid


def test_deleting_an_account_takes_its_votes_and_keeps_its_posts(worker):
    who = worker.user()
    pid = add(worker, "9", uid="u1")
    on_post(worker, who, pid, "vote")
    worker.load(FUNCTIONS / "api" / "account.js", "acct")
    assert worker.call("acct.onRequestDelete", "https://www.gordstats.com/api/account",
                       method="DELETE", headers=who)["status"] == 200
    assert worker.sql.rows("SELECT * FROM tweet_votes") == []
    assert worker.sql.rows("SELECT submitted_by, status FROM tweets") == [
        {"submitted_by": None, "status": "approved"}]
    # The deleted account's cookie is still signed; its writes are refused, not a 500.
    assert on_post(worker, who, pid, "vote")["status"] == 401


def test_writes_from_another_site_never_reach_the_function(worker):
    worker.load(MIDDLEWARE, "mw")
    who = worker.user()
    pid = add(worker, "10")
    out = worker.js(f"""
      let reached = 0;
      const env = {worker.env()};
      const ask = (headers, host) => mw.onRequest({{ env,
        request: T.req("https://" + host + "/api/tweets/{pid}/vote",
                       {{ method: "POST", headers: Object.assign({{}}, {json.dumps(who)}, headers),
                          body: "{{}}" }}),
        next: async () => {{ reached++; return new Response("{{}}", {{ status: 200 }}); }} }});
      const site = await ask({{ "sec-fetch-site": "cross-site" }}, "www.gordstats.com");
      const origin = await ask({{ origin: "https://evil.example" }}, "www.gordstats.com");
      const pages = await ask({{ "sec-fetch-site": "same-origin" }}, "abc.gordstats-cbb.pages.dev");
      const ours = await ask({{ "sec-fetch-site": "same-origin" }}, "www.gordstats.com");
      return [site.status, origin.status, pages.status, ours.status, reached];
    """)
    assert out == [403, 403, 404, 200, 1]
    assert worker.sql.rows("SELECT * FROM tweet_votes") == []


# --------------------------------------------------------------------------- #
# Deployed ahead of migration 005
# --------------------------------------------------------------------------- #

def _before_005() -> str:
    """Today's schema less what 005 adds: no tweets tables, no is_admin."""
    sql = re.sub(r"--[^\n]*", "", SCHEMA.read_text())
    sql = re.sub(r"CREATE TABLE IF NOT EXISTS tweet(?:s|_votes) \(.*?\)( WITHOUT ROWID)?;", "",
                 sql, flags=re.S)
    return sql + "\nALTER TABLE users DROP COLUMN is_admin;"


def _columns(db):
    tables = [r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
    # By name: 005 can only append is_admin, where the schema declares it
    # before 004's columns (see d1-schema.sql).
    return {t: sorted(tuple(c)[1:] for c in db.execute(f"PRAGMA table_xinfo({t})"))
            for t in tables}, sorted(r[0] for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"))


def test_migration_005_brings_a_database_to_the_schema():
    old = sqlite3.connect(":memory:")
    old.executescript(_before_005())
    assert "tweets" not in _columns(old)[0]
    old.executescript(MIGRATION_005.read_text())
    fresh = sqlite3.connect(":memory:")
    fresh.executescript(SCHEMA.read_text())
    assert _columns(old) == _columns(fresh)
    # Run-once like 004: a second run stops at the ALTER, harmlessly.
    with pytest.raises(sqlite3.OperationalError, match="duplicate column"):
        old.executescript(MIGRATION_005.read_text())


def test_a_vote_is_one_row_and_counting_uses_the_key():
    db = sqlite3.connect(":memory:")
    db.executescript(SCHEMA.read_text())
    plan = " ".join(r[-1] for r in db.execute(
        "EXPLAIN QUERY PLAN SELECT COUNT(*) FROM tweet_votes WHERE tweet_id = ?", (1,)))
    assert "SCAN" not in plan, plan
    assert "WITHOUT ROWID" in MIGRATION_005.read_text()
    indexes = [r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name LIKE 'tweet%'")]
    assert indexes == ["sqlite_autoindex_tweets_1"], "an index is a write on every insert"


def test_deployed_before_the_migration_it_answers_rather_than_failing():
    with Worker(_before_005()) as w:
        w.load(TWEETS, "tw")
        w.load(ROUTE, "twr")
        who = w.user()
        got = w.call("tw.onRequestGet", URL)
        assert got["status"] == 200 and got["json"]["migrating"] is True
        assert got["json"]["tweets"] == []
        mine = w.call("tw.onRequestGet", URL, headers=who)
        assert mine["status"] == 200 and mine["json"]["admin"] is False
        sent = submit(w, who, f"https://x.com/a/status/{ID}")
        assert sent["status"] == 503 and sent["json"]["migrating"] is True
        assert on_post(w, who, 1, "vote")["status"] == 503
        assert w.call("tw.onRequestGet", f"{URL}?status=pending", headers=who)["status"] == 403
