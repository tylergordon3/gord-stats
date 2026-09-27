"""Sign-in's `next` redirect cannot leave the site.

safeNext used to test the raw string against /^\\/(?!\\/)/, and "/\\evil.com"
passed: browsers read a backslash in a Location header as a slash, so
/api/auth/logout?next=/%5Cevil.com signed the reader out onto evil.com. It now
resolves the value the way the browser will and keeps it only on this origin.
Run in headless Chromium, whose URL parser is the one that matters.
"""
import json
import re
from pathlib import Path

import pytest

from test_my_team_planner import CHROME, Browser

pytestmark = pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")

AUTH = (Path(__file__).parent.parent / "functions" / "api" / "auth" / "[[route]].js").read_text()
ORIGIN = "https://www.gordstats.com"

CASES = {
    "/fantasy/roster/?x=1#top": "/fantasy/roster/?x=1#top",
    None: "/",
    "": "/",
    "//evil.com": "/",
    "/\\evil.com": "/",
    "/\t/evil.com": "/",
    "https://evil.com/": "/",
    "javascript:alert(1)": "/",
    "https://www.gordstats.com/profile/": "/profile/",
    "/%5Cevil.com": "/%5Cevil.com",          # still encoded: a path here, harmless
}


@pytest.fixture(scope="module")
def browser():
    fn = re.search(r"^function safeNext\(.*?^\}", AUTH, re.S | re.M).group(0)
    b = Browser()
    b.evaluate(fn.replace("function safeNext", "window.safeNext = function"))
    yield b
    b.close()


@pytest.mark.parametrize("raw, expected", list(CASES.items()))
def test_next_stays_on_this_site(browser, raw, expected):
    got = browser.evaluate(f"safeNext({json.dumps(raw)}, {json.dumps(ORIGIN)})")
    assert got == expected
    # And wherever it points, the browser lands on this origin.
    landed = browser.evaluate(f"new URL({json.dumps(got)}, {json.dumps(ORIGIN)}).origin")
    assert landed == ORIGIN
