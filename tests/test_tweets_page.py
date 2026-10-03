"""
Tweets of the week in the browser: Home's row, /tweets/ and the owner's
review on /profile/ (gordstats.tweets_page, gordstats.profile_page).

Headless Chromium (CDP port 9570) against a local server on a port the OS
picks, which serves small pages built from the real markup and answers
/api/* from the test - no network. X's embed page is played by the same
server (the module's CONFIG points the pages at it): it posts X's messages to
its parent as X's Tweet.html does, so the test can count exactly when it is
asked for - only once a reader taps a card - and what the page takes from it.
"""
import inspect
import json
import re
import shutil
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from browser_util import launch, reap
from gordstats import profile_page, tweets_page

CHROME = next((p for p in ("/usr/bin/chromium-browser", "/usr/bin/chromium",
                           "/usr/bin/google-chrome") if shutil.which(p)), None)
CDP = 9570

TID = "1841234567890123456"

# Sums every layout shift a reader did not cause, from the first paint on.
CLS = ("<script>window.__cls=0;window.__shifts=[];try{new PerformanceObserver(function(l){"
       "l.getEntries().forEach(function(e){if(!e.hadRecentInput){__cls+=e.value;"
       "__shifts.push(e.value);}});}).observe({type:'layout-shift',buffered:true});}catch(e){}"
       "</script>")

# X's Tweet.html as the page meets it: the messages it posts to its parent
# (seen from the real one, 2026-10-03). Id 404404 is a post X no longer has.
FAKE_EMBED = """<!doctype html><html><body style="margin:0"><div id="t">post</div><script>
var id = new URLSearchParams(location.search).get('id');
function say(method, params) {
  parent.postMessage(JSON.stringify({'twttr.embed': {jsonrpc: '2.0', method: method,
    id: 'embed-0', params: [Object.assign({data: {tweet_id: id}}, params || {})]}}), '*');
}
say('twttr.private.initialized');
if (id === '404404') { say('twttr.private.no_results'); }
else { say('twttr.private.resize', {width: 535, height: 420}); say('twttr.private.rendered'); }
</script></body></html>"""


def post(i, **over):
    t = {"id": i, "tweet_id": f"{1841234567890123000 + i}", "url": "",
         "handle": f"user{i}", "author": f"Author {i}",
         "text": f"Post number {i}: the punter threw a touchdown.", "has_media": i % 3,
         "sport": "cfb" if i % 2 else "nfl", "votes": 10 - i, "mine": False}
    t.update(over)
    return t


def listing(n, signed_in=False, **extra):
    return {"ok": True, "configured": True, "signedIn": signed_in,
            "tweets": [post(i) for i in range(1, n + 1)], "week": n, **extra}


def _doc(body: str) -> str:
    body = body.replace("{% raw %}", "").replace("{% endraw %}", "")
    return ("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' "
            "content='width=device-width,initial-scale=1'>" + CLS +
            "<style>body{margin:0;font-family:sans-serif}main{padding:0 16px}"
            "[hidden]{display:none!important}</style></head><body><main>"
            "<div id='above' style='height:120px'>above</div>" + body +
            "<div id='below' style='height:1200px'>below</div></main></body></html>")


class Site:
    """Pages, /api answers and X's embed page, with a log of every request."""

    def __init__(self):
        self.pages, self.api, self.log = {}, {}, []
        self.embed = (200, FAKE_EMBED)
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self, method):
                size = int(self.headers.get("content-length") or 0)
                body = self.rfile.read(size).decode() if size else ""
                outer.log.append((method, self.path, body))
                path = self.path
                if path in outer.pages and method == "GET":
                    return self._send(200, outer.pages[path], "text/html; charset=utf-8")
                if path.split("?")[0] == "/embed.html":
                    status, page = outer.embed
                    return self._send(status, page, "text/html; charset=utf-8")
                hit = outer.api.get((method, path))
                if hit is None:
                    return self._send(404, '{"ok":false}', "application/json")
                status, data, delay = (list(hit) + [0])[:3]
                if delay:
                    time.sleep(delay)
                return self._send(status, json.dumps(data), "application/json")

            def _send(self, status, text, ctype):
                data = text.encode()
                self.send_response(status)
                self.send_header("content-type", ctype)
                self.send_header("content-length", str(len(data)))
                self.send_header("cache-control", "no-store")
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):                                   # noqa: N802
                self._answer("GET")

            def do_POST(self):                                  # noqa: N802
                self._answer("POST")

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.origin = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def asked(self, method, prefix):
        return [e for e in self.log if e[0] == method and e[1].startswith(prefix)]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class Tab:
    """One persistent DevTools session on the browser's page."""

    def __init__(self):
        from websockets.sync.client import connect

        self.proc = launch(CHROME, CDP)
        for _ in range(60):
            try:
                targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{CDP}/json"))
                url = next(t["webSocketDebuggerUrl"] for t in targets if t.get("type") == "page")
                break
            except Exception:                                   # noqa: BLE001
                time.sleep(0.5)
        else:
            raise RuntimeError("Chromium did not come up")
        self._conn = connect(url, max_size=None, open_timeout=30)
        self.ws = self._conn.__enter__()
        self.n = 0

    def send(self, method, params=None):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv(timeout=30))
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise AssertionError(msg["error"])
                return msg.get("result", {})

    def ev(self, expression):
        res = self.send("Runtime.evaluate", {"expression": expression, "returnByValue": True,
                                             "awaitPromise": True})
        if res.get("exceptionDetails"):
            d = res["exceptionDetails"]
            raise AssertionError((d.get("exception") or {}).get("description") or d["text"])
        return res["result"].get("value")

    def wait(self, expression, timeout=8.0):
        end = time.time() + timeout
        while time.time() < end:
            if self.ev(expression):
                return
            time.sleep(0.05)
        raise AssertionError(f"timed out waiting for {expression}")

    def open(self, url, width=390, height=844):
        self.send("Emulation.setDeviceMetricsOverride", {
            "width": width, "height": height, "deviceScaleFactor": 1, "mobile": width < 600})
        self.send("Page.navigate", {"url": url})
        self.wait(f"location.href === {json.dumps(url)} && document.readyState === 'complete'")

    def close(self):
        try:
            self._conn.__exit__(None, None, None)
        finally:
            self.proc.terminate()
            reap(self.proc)


@pytest.fixture(scope="module")
def browser():
    if CHROME is None:
        pytest.skip("no Chromium to run the JS in")
    site = Site()
    keep = dict(tweets_page.CONFIG)
    # Served here; and a blocked embed is called after 1.5 s, not 15.
    tweets_page.CONFIG.update(embed="/embed.html", wait=1500)
    try:
        site.pages["/home.html"] = _doc(tweets_page.home_card())
        site.pages["/grid.html"] = _doc(tweets_page.body())
        site.pages["/profile.html"] = _doc(profile_page.body(""))
    finally:
        tweets_page.CONFIG.clear()
        tweets_page.CONFIG.update(keep)
    tab = Tab()
    try:
        yield tab, site
    finally:
        tab.close()
        site.close()


@pytest.fixture
def page(browser):
    tab, site = browser
    site.api.clear()
    site.log.clear()
    site.embed = (200, FAKE_EMBED)
    return tab, site


def drawn(tab):
    tab.wait("!document.querySelector('.tw-list[aria-busy]')")


# --------------------------------------------------------------------------- #
# Markup, placement, the page
# --------------------------------------------------------------------------- #

def test_the_card_is_literal_holds_its_room_and_loads_nothing_from_x():
    card = tweets_page.home_card()
    assert card.startswith("{% raw %}") and card.endswith("{% endraw %}")
    inner = card[len("{% raw %}"):-len("{% endraw %}")]
    assert not re.search(r"\{\{|\{%", inner), "render_home writes Home without the raw wrapping"
    css = tweets_page.CSS
    for rule in (".tw-row{display:flex;gap:12px;overflow-x:auto;overflow-y:hidden;height:290px;",
                 "height:268px;min-width:0;display:flex;flex-direction:column;",
                 "grid-column:1/-1;height:268px;", "min-height:100vh;",
                 ".tw .tw-said{min-height:3.9em;", "scroll-snap-type:x mandatory"):
        assert rule in css, rule
    # Placeholders are drawn with the page; the form waits for a tap.
    assert card.count("tw-card tw-ghost") == 3
    assert '<form class="tw-form" id="tw-form-home" hidden' in card
    assert "Tweets of the week" in card and "href=\"/tweets/\"" in card
    # X is asked for nothing until a tap: no script tag, no oEmbed markup -
    # and never X's script in this page at all, only its page in a sandbox.
    assert tweets_page.CONFIG["embed"] == "https://platform.twitter.com/embed/Tweet.html"
    assert "<script src" not in card and "twitter-tweet" not in card
    assert "widgets.js" not in card and "createTweet" not in card
    assert "allow-top-navigation" not in tweets_page.SANDBOX
    assert "allow-forms" not in tweets_page.SANDBOX
    assert "WNBA" not in card


def test_home_puts_it_under_whats_new(tmp_path, monkeypatch):
    from cbb import paths
    from cbb.render import render_home as rh

    monkeypatch.setattr(paths, "WEB_HOME", tmp_path / "index.html")
    monkeypatch.setattr(rh, "_my_teams", lambda today: "<section id='my-teams'></section>")
    rh.render_home()
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    mine, news, tweets = (html.index("id='my-teams'"),
                          html.index("<section class='home-card gs-whatsnew'>"),
                          html.index('<section class="home-card tw tw-home"'))
    assert mine < news < tweets
    between = html[news + 1:tweets]
    assert between.count("<section") == 0, "nothing between What's new and the tweets"
    assert html.count("tw-home") == 1


def test_the_page_is_built_with_the_others(tmp_path, monkeypatch):
    from gordstats import daily

    assert "tweets_page.generate()" in inspect.getsource(daily)
    monkeypatch.setattr(tweets_page, "OUT", tmp_path / "tweets" / "index.html")
    tweets_page.generate()
    doc = tweets_page.OUT.read_text(encoding="utf-8")
    assert doc.startswith("---\nlayout: default\ntitle: Tweets of the week\ndescription: ")
    body = doc.split("---\n", 2)[2]
    assert body.startswith("{% raw %}<h1>Tweets of the week</h1>") and body.endswith("{% endraw %}")
    assert body.count("{% raw %}") == 1 and 'data-tw="grid"' in body
    assert "page-updated" not in body, "the posts are live; a build time would mislead"


# --------------------------------------------------------------------------- #
# In the browser
# --------------------------------------------------------------------------- #

def test_hostile_posts_are_drawn_as_text(page):
    tab, site = page
    evil = post(5, author='<img src=x onerror="window.__xss=1">',
                handle='bad"onmouseover=x', sport="constructor", has_media=1,
                text="</div><script>window.__xss=2</script><b>bold</b> & 'quotes'")
    site.api[("GET", "/api/tweets")] = (200, {
        "ok": True, "signedIn": False, "configured": True,
        "tweets": [evil, post(6, tweet_id="javascript:alert(1)"), post(7, id="7 onclick=x")]})
    tab.open(site.origin + "/home.html")
    drawn(tab)
    got = tab.ev("""(() => { const c = document.querySelectorAll('.tw-list .tw-card');
      return { n: c.length, xss: window.__xss || null,
        tags: document.querySelectorAll('.tw-list img, .tw-list script, .tw-list b').length,
        name: c[0].querySelector('.tw-name').textContent,
        text: c[0].querySelector('.tw-text').textContent,
        href: c[0].querySelector('.tw-x').getAttribute('href'),
        badges: [...c[0].querySelectorAll('.tw-badge')].map((b) => b.textContent) }; })()""")
    assert got["n"] == 1, "a post with a bad id is dropped, not drawn"
    assert got["xss"] is None and got["tags"] == 0
    assert got["name"] == evil["author"] and got["text"] == evil["text"]
    assert got["href"] == f"https://x.com/i/status/{evil['tweet_id']}"
    assert got["badges"] == ["▣ Photo or video"], "an unknown sport draws no badge"


@pytest.mark.parametrize("width,height", [(390, 844), (1280, 900)])
def test_nothing_moves_as_the_row_fills(page, width, height):
    tab, site = page
    for answer in ((200, listing(3)), (200, listing(12)),
                   (200, {"ok": True, "tweets": [], "configured": True}),
                   (500, {"ok": False})):
        site.api[("GET", "/api/tweets")] = (*answer, 0.6)
        for path in ("/home.html", "/grid.html"):
            tab.open(site.origin + path, width, height)
            # Home's card keeps its height outright. The page's grid may grow,
            # but only from a screen below its top, so all it moves is off-screen.
            measure = ("[document.querySelector('.tw').offsetHeight, "
                       "document.querySelector('.tw-list').getBoundingClientRect().top, "
                       "document.getElementById('below').getBoundingClientRect().top]")
            before = tab.ev(measure)
            assert tab.ev("!!document.querySelector('.tw-list[aria-busy]')"), "drawn too early"
            drawn(tab)
            time.sleep(0.15)
            after = tab.ev(measure)
            if path == "/home.html":
                assert after == before, (path, answer[0], before, after)
            else:
                assert after[1] == before[1] and before[2] >= height, (answer[0], before, after)
            assert tab.ev("window.__cls") < 0.001, (path, tab.ev("window.__shifts"))
            shown = len(answer[1].get("tweets") or [])
            if path == "/home.html" and (shown > 4 or (shown and width < 600)):
                # A row, not a wrap: the cards sit side by side and scroll.
                assert tab.ev("(() => { const r = document.querySelector('.tw-row'); "
                              "return r.scrollWidth > r.clientWidth; })()")


EMBEDS = "document.querySelectorAll('dialog.tw-dlg iframe.tw-embed')"


def test_the_embed_loads_only_on_tap(page):
    tab, site = page
    site.api[("GET", "/api/tweets")] = (200, {"ok": True, "configured": True, "signedIn": False,
        "tweets": [post(1), post(2), post(3, tweet_id="404404")]})
    tab.open(site.origin + "/home.html")
    drawn(tab)
    time.sleep(0.3)
    assert site.asked("GET", "/embed.html") == []
    assert tab.ev("document.querySelectorAll('iframe').length") == 0

    tab.ev("document.querySelectorAll('.tw-card')[1].querySelector('.tw-show').click()")
    tab.wait("!document.querySelector('.tw-dlg-wait')")
    [(_, path, _)] = site.asked("GET", "/embed.html")
    assert path == f"/embed.html?id={post(2)['tweet_id']}&dnt=true&lang=en&theme=light"
    frame = tab.ev(f"(function(f){{return [f.getAttribute('sandbox'), f.style.height, "
                   f"f.title];}})({EMBEDS}[0])")
    assert frame == [tweets_page.SANDBOX, "420px", "Post from X"]
    assert tab.ev("document.querySelector('.tw-dlg-t').textContent") == "Author 2"
    assert tab.ev("document.querySelector('.tw-dlg-go').href") == \
        f"https://x.com/user2/status/{post(2)['tweet_id']}"
    assert tab.ev("document.querySelectorAll('.tw-list iframe').length") == 0, "one post only"
    # Nothing of X's runs in this page.
    assert tab.ev("[!!window.twttr, document.querySelectorAll('script[src]').length]") == [False, 0]

    tab.ev("document.querySelector('.tw-dlg-x').click()")
    assert tab.ev("[document.querySelector('dialog.tw-dlg').open, "
                  "document.querySelector('.tw-dlg-body').innerHTML]") == [False, ""]

    # The card itself is the other way in.
    tab.ev("document.querySelectorAll('.tw-card')[0].querySelector('.tw-text').click()")
    tab.wait(f"{EMBEDS}.length === 1 && !document.querySelector('.tw-dlg-wait')")
    assert site.asked("GET", "/embed.html")[-1][1].startswith(f"/embed.html?id={post(1)['tweet_id']}&")
    tab.ev("document.querySelector('.tw-dlg-x').click()")

    # The vote button and the X link are not "show me".
    tab.ev("document.querySelectorAll('.tw-card')[0].querySelector('.tw-vote').click()")
    assert tab.ev("document.querySelector('dialog.tw-dlg').open") is False

    # A post X will not render (deleted since) says so.
    tab.ev("document.querySelectorAll('.tw-card')[2].querySelector('.tw-show').click()")
    tab.wait("/deleted/.test(document.querySelector('.tw-dlg-body').textContent)")
    assert tab.ev(f"{EMBEDS}.length") == 0


def test_only_the_embeds_own_messages_count(page):
    """Anything else on the page - this window, another frame - saying it is X
    changes nothing: no height, no "deleted", no "drawn"."""
    tab, site = page
    site.api[("GET", "/api/tweets")] = (200, listing(1))
    site.embed = (200, "<!doctype html><p>slow</p>")       # an embed that says nothing
    tab.open(site.origin + "/home.html")
    drawn(tab)
    tab.ev("document.querySelector('.tw-show').click()")
    tab.wait(f"{EMBEDS}.length === 1")
    forged = ("JSON.stringify({'twttr.embed': {method: 'twttr.private.%s', "
              "params: [{height: 9999}]}})")
    tab.ev(f"window.postMessage({forged % 'resize'}, '*');"
           f"window.postMessage({forged % 'no_results'}, '*');"
           "var f=document.createElement('iframe');"
           "f.srcdoc='<script>parent.postMessage(' + JSON.stringify(" + (forged % 'rendered')
           + ") + ', \"*\")<\\/script>';"
           "document.body.appendChild(f);")
    time.sleep(0.4)            # well inside CONFIG wait (1.5 s here)
    assert tab.ev(f"{EMBEDS}[0].style.height") in ("", "0px")
    assert "Loading" in tab.ev("document.querySelector('.tw-dlg-body').textContent")
    tab.ev("document.querySelector('.tw-dlg-x').click()")


def test_a_blocked_embed_says_so_and_a_later_tap_tries_again(page):
    tab, site = page
    site.api[("GET", "/api/tweets")] = (200, listing(2))
    site.embed = (404, "")
    tab.open(site.origin + "/home.html")
    drawn(tab)
    tab.ev("document.querySelector('.tw-show').click()")
    tab.wait("/content blocker/.test(document.querySelector('.tw-dlg-body').textContent)")
    assert tab.ev("document.querySelector('.tw-dlg-go').href").startswith("https://x.com/user1/")
    tab.ev("document.querySelector('.tw-dlg-x').click()")
    site.embed = (200, FAKE_EMBED)
    tab.ev("document.querySelector('.tw-show').click()")
    tab.wait(f"{EMBEDS}.length === 1 && !document.querySelector('.tw-dlg-wait')")
    assert len(site.asked("GET", "/embed.html")) == 2


def test_votes_need_a_reader_and_go_to_the_api(page):
    tab, site = page
    site.api[("GET", "/api/tweets")] = (200, listing(2))
    tab.open(site.origin + "/home.html")
    drawn(tab)
    tab.ev("document.querySelector('.tw-vote').click()")
    assert "Sign in" in tab.ev("document.querySelector('.tw-say').textContent")
    assert tab.ev("document.querySelector('.tw-say a').getAttribute('href')") == \
        "/api/auth/login?next=%2Fhome.html"
    assert site.asked("POST", "/api/") == []
    # Signed out: the submit control is the sign-in link.
    assert tab.ev("[document.querySelector('.tw-signin').hidden, "
                  "document.querySelector('.tw-open').hidden]") == [False, True]

    site.api[("GET", "/api/tweets")] = (200, listing(2, signed_in=True))
    site.api[("POST", "/api/tweets/1/vote")] = (200, {"ok": True, "id": 1, "votes": 10,
                                                      "mine": True})
    tab.open(site.origin + "/home.html")
    drawn(tab)
    tab.ev("document.querySelector('.tw-vote').click()")
    tab.wait("document.querySelector('.tw-vote').classList.contains('on')")
    assert tab.ev("[document.querySelector('.tw-vote .tw-n').textContent, "
                  "document.querySelector('.tw-vote').getAttribute('aria-pressed')]") == ["10", "true"]
    assert [e[1] for e in site.asked("POST", "/api/")] == ["/api/tweets/1/vote"]


def test_sending_one_in_shows_the_servers_answer(page):
    tab, site = page
    site.api[("GET", "/api/tweets")] = (200, listing(1, signed_in=True))
    site.api[("POST", "/api/tweets")] = (201, {"ok": True, "status": "pending",
                                               "message": "Thanks - it's in the queue."})
    tab.open(site.origin + "/grid.html")
    drawn(tab)
    assert tab.ev("[document.querySelector('.tw-signin').hidden, "
                  "document.querySelector('.tw-open').hidden]") == [True, False]
    below = tab.ev("document.getElementById('below').getBoundingClientRect().top")
    tab.ev("document.querySelector('.tw-open').click()")
    assert tab.ev("document.querySelector('.tw-form').hidden") is False
    opened = tab.ev("document.getElementById('below').getBoundingClientRect().top")

    tab.ev("document.querySelector('.tw-form .tw-send').click()")
    assert "Paste the link" in tab.ev("document.querySelector('.tw-said').textContent")
    assert site.asked("POST", "/api/tweets") == []

    tab.ev(f"""document.querySelector('.tw-url').value = ' https://x.com/a/status/{TID} ';
               document.querySelector('.tw-sport').value = 'nfl';
               document.querySelector('.tw-form .tw-send').click()""")
    tab.wait("/queue/.test(document.querySelector('.tw-said').textContent)")
    [(_, _, sent)] = site.asked("POST", "/api/tweets")
    assert json.loads(sent) == {"url": f"https://x.com/a/status/{TID}", "sport": "nfl"}
    assert tab.ev("document.querySelector('.tw-url').value") == ""
    # The answer had its room before it came.
    assert tab.ev("document.getElementById('below').getBoundingClientRect().top") == opened
    assert opened > below

    site.api[("POST", "/api/tweets")] = (409, {"ok": False, "duplicate": True, "status": "pending",
                                               "error": "Already sent in - it's waiting for review."})
    tab.ev(f"""document.querySelector('.tw-url').value = 'https://x.com/a/status/{TID}';
               document.querySelector('.tw-form .tw-send').click()""")
    tab.wait("/waiting for review/.test(document.querySelector('.tw-said').textContent)")

    site.api[("POST", "/api/tweets")] = (401, {"ok": False, "error": "Sign in to do that."})
    tab.ev(f"""document.querySelector('.tw-url').value = 'https://x.com/a/status/{TID}';
               document.querySelector('.tw-form .tw-send').click()""")
    tab.wait("/Sign in first/.test(document.querySelector('.tw-said').textContent)")
    assert tab.ev("document.querySelector('.tw-signin').hidden") is False


def test_the_owner_is_pointed_at_the_queue_and_sees_their_own_post_go_on(page):
    tab, site = page
    site.api[("GET", "/api/tweets")] = (200, listing(1, signed_in=True, admin=True, pending=3))
    tab.open(site.origin + "/home.html")
    drawn(tab)
    say = "document.querySelector('.tw-say')"
    assert tab.ev(f"{say}.textContent") == "3 posts waiting for your review. Review"
    assert tab.ev(f"{say}.querySelector('a').getAttribute('href')") == "/profile/#pf-tw"

    # Posted straight on: the list is asked for again and draws the new one.
    site.api[("POST", "/api/tweets")] = (201, {"ok": True, "status": "approved",
                                               "message": "Posted - it's on the list now."})
    site.api[("GET", "/api/tweets")] = (200, listing(2, signed_in=True, admin=True, pending=0))
    before = len(site.asked("GET", "/api/tweets"))
    tab.ev("document.querySelector('.tw-open').click()")
    tab.ev(f"""document.querySelector('.tw-url').value = 'https://x.com/a/status/{TID}';
               document.querySelector('.tw-form .tw-send').click()""")
    tab.wait("document.querySelectorAll('.tw-card:not(.tw-ghost)').length === 2")
    assert len(site.asked("GET", "/api/tweets")) == before + 1
    assert "on the list now" in tab.ev("document.querySelector('.tw-said').textContent")
    # Nothing waiting any more: the line goes back to the invitation.
    assert tab.ev(f"{say}.textContent") == "Readers send them in, we pick, you vote."


def test_a_reader_is_never_shown_the_queue(page):
    tab, site = page
    site.api[("GET", "/api/tweets")] = (200, listing(1, signed_in=True, admin=False, pending=4))
    tab.open(site.origin + "/home.html")
    drawn(tab)
    assert tab.ev("document.querySelector('.tw-say').textContent") == \
        "Readers send them in, we pick, you vote."


@pytest.mark.parametrize("admin", [False, True])
def test_review_shows_only_for_the_owner(page, admin):
    tab, site = page
    site.api[("GET", "/api/me")] = (200, {"signedIn": True, "configured": True,
                                          "email": "reader@example.com"})
    site.api[("GET", "/api/tweets")] = (200, listing(0, signed_in=True, admin=admin))
    waiting = post(3, submitter="fan@example.com", status="pending", sport="nfl",
                   author="<b>Fan</b>")
    site.api[("GET", "/api/tweets?status=pending")] = (200, {"ok": True, "tweets": [waiting]})
    site.api[("GET", "/api/tweets?status=approved")] = (200, {"ok": True, "tweets": [post(4)]})
    site.api[("POST", "/api/tweets/3/review")] = (200, {"ok": True, "id": 3, "status": "approved"})
    tab.open(site.origin + "/profile.html", 1280, 900)
    tab.wait("/Signed in as/.test(document.getElementById('pf-who').textContent)")
    time.sleep(0.4)
    if not admin:
        assert tab.ev("document.getElementById('pf-tw').hidden") is True
        assert site.asked("GET", "/api/tweets?status") == [], "nobody else is sent a 403"
        return
    tab.wait("!document.getElementById('pf-tw').hidden")
    rows = tab.ev("[...document.querySelectorAll('#pf-tw-q .pf-tw-item')].map((li) => "
                  "[li.querySelector('.pf-name').textContent, li.querySelector('.pf-meta').textContent,"
                  " li.querySelector('.pf-tw-sport').value, li.querySelectorAll('button').length])")
    assert rows == [["<b>Fan</b>", "@user3 \u00b7 from fan@example.com", "nfl", 2]]
    assert tab.ev("document.querySelectorAll('#pf-tw-on [data-act=remove]').length") == 1
    tab.ev("document.querySelector('#pf-tw-q [data-act=approve]').click()")
    tab.wait("/Approved/.test(document.getElementById('pf-tw-msg').textContent)")
    [(_, path, sent)] = site.asked("POST", "/api/tweets/")
    assert path == "/api/tweets/3/review"
    assert json.loads(sent) == {"action": "approve", "sport": "nfl"}
