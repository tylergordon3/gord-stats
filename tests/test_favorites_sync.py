"""A star this browser set is not undone by the server's older copy.

The push was debounced 600ms and fire-and-forget, and every page load then
took the server's list as the truth. A star set just before navigating away,
before the account lookup answered, or refused by the server came undone on
the next page. favorites.js now keeps a "not yet confirmed" flag until a PUT
comes back 2xx, and while it is set the local list is sent rather than
overwritten.

Runs the real favorites.js in headless Chromium against a stubbed fetch, on a
page served over http so localStorage exists.
"""
import http.server
import json
import threading
import time

import pytest

from conftest import DOCS
from test_my_team_planner import CHROME, Browser

pytestmark = pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")
JS = (DOCS / "assets" / "js" / "favorites.js").read_text()


@pytest.fixture
def page(tmp_path):
    (tmp_path / "index.html").write_text("<html><body></body></html>")
    handler = lambda *a: http.server.SimpleHTTPRequestHandler(*a, directory=str(tmp_path))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    browser = Browser()
    try:
        browser.evaluate(f"location.href='http://127.0.0.1:{server.server_address[1]}/';true")
        time.sleep(1.0)
        yield browser
    finally:
        browser.close()
        server.shutdown()


def _boot(browser, local, dirty, remote, put_status=200):
    browser.evaluate(
        "localStorage.clear();"
        f"localStorage.setItem('gs:favorites', {json.dumps(json.dumps(local))});"
        "localStorage.setItem('gs:favorites:sync', 'r@x.com');"
        + ("localStorage.setItem('gs:favorites:dirty', '1');" if dirty else "")
        + "window.PUTS=[];"
        "window.fetch=function(url,opt){opt=opt||{};"
        "  if(url==='/api/me')return Promise.resolve({json:function(){return {configured:true,signedIn:true,email:'r@x.com'};}});"
        "  if(opt.method==='PUT'){PUTS.push(JSON.parse(opt.body).favorites);"
        f"    return Promise.resolve({{ok:{str(put_status < 300).lower()},status:{put_status}}});}}"
        f"  return Promise.resolve({{ok:true,json:function(){{return {{favorites:{json.dumps(remote)}}};}}}});}};"
        + JS + ";true")
    time.sleep(1.5)                     # the account lookup, then the 600ms debounce


def _state(browser):
    return browser.evaluate(
        "JSON.stringify({list:GSFavorites.list(),puts:PUTS,"
        "dirty:localStorage.getItem('gs:favorites:dirty')})")


def test_an_unconfirmed_local_change_is_sent_not_overwritten(page):
    _boot(page, local=["cfb:1", "cfb:2"], dirty=True, remote=["cfb:1"])
    got = json.loads(_state(page))
    assert got["list"] == ["cfb:1", "cfb:2"], "the server's older copy won"
    assert got["puts"] == [["cfb:1", "cfb:2"]] and got["dirty"] is None


def test_a_refused_save_stays_unconfirmed(page):
    _boot(page, local=["cfb:1", "cfb:2"], dirty=True, remote=["cfb:1"], put_status=429)
    got = json.loads(_state(page))
    assert got["puts"] and got["dirty"] == "1", "a 429 must not clear the flag"


def test_with_nothing_pending_the_account_is_the_truth(page):
    """Un-starring on another device has to stick here too."""
    _boot(page, local=["cfb:1", "cfb:2"], dirty=False, remote=["cfb:1"])
    got = json.loads(_state(page))
    assert got["list"] == ["cfb:1"] and got["puts"] == []
