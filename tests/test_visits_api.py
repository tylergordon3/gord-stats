"""
The visit counter spends KV writes on new visitors only.

`total` went up on every ?count=1, deduplicated only by the footer script's
sessionStorage, which a script calling the URL does not have - and KV's free
tier allows 1,000 writes a day, so a few hundred scripted hits stopped the
counter until midnight. A repeat visitor now costs one read and no writes.

Run in headless Chromium with KV stubbed (tests/functions_harness.py).
"""
import pytest

from functions_harness import CHROME, FUNCTIONS, Worker

pytestmark = pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")

URL = "https://www.gordstats.com/api/visits"
BROWSER = "Mozilla/5.0 (X11; Linux x86_64) Chrome/140"


@pytest.fixture
def worker():
    with Worker() as w:
        w.load(FUNCTIONS / "api" / "visits.js", "visits")
        w.js("window.kv = T.kv({ total: '100' });")
        yield w


def visit(w, ip="203.0.113.7", ua=BROWSER, count=True):
    got = w.call("visits.onRequestGet", URL + ("?count=1" if count else ""),
                 headers={"cf-connecting-ip": ip, "user-agent": ua}, env="{ VISITS: kv }")
    return got["json"], w.js("return kv.log.puts.length;")


def test_a_repeat_visitor_costs_no_writes(worker):
    body, puts = visit(worker)
    assert (body["total"], body["today"], puts) == (101, 1, 3)
    for _ in range(5):
        body, puts = visit(worker)
    assert (body["total"], body["today"], puts) == (101, 1, 3)

    body, puts = visit(worker, ip="198.51.100.9")
    assert (body["total"], body["today"], puts) == (102, 2, 6)


def test_reads_and_bots_write_nothing(worker):
    body, puts = visit(worker, count=False)
    assert (body["total"], body["today"], puts) == (100, 0, 0)
    body, puts = visit(worker, ua="curl/8.5.0")
    assert (body["total"], puts) == (100, 0)
    assert len(body["day"]) == 10
