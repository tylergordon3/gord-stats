"""
The JavaScript lineup planner agrees with the Python one.

/fantasy/roster/ recommends a lineup for the reader's own league in the
browser, because the roster and its slots come from Sleeper at view time. That
means two implementations of gordstats.lineup.plan, and two implementations of
a greedy selection drift - quietly, into recommending a different lineup than
the page it sits on.

So both are run over the same fixtures and compared. The JS runs in headless
Chromium, since the machine that builds this site has no node; where Chromium
is not available the test skips rather than pretending to pass.
"""
import asyncio
import json
import random
import re
import shutil
import subprocess
import time
import urllib.request

import pandas as pd
import pytest

from conftest import ROOT
from gordstats import lineup, my_team

CHROME = next((p for p in ("/usr/bin/chromium-browser", "/usr/bin/chromium",
                           "/usr/bin/google-chrome") if shutil.which(p)), None)
pytestmark = pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")

FLEX, FLEX_POSITIONS = "FLEX", ("RB", "WR", "TE")
SLOTS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, FLEX: 2, "K": 1, "DEF": 1}


def _planner_source() -> str:
    """The script body, with the Jekyll and <script> wrappers stripped."""
    js = my_team.PLANNER_JS
    js = js.replace("{% raw %}", "").replace("{% endraw %}", "")
    return re.sub(r"</?script>", "", js)


class Browser:
    """Just enough CDP to evaluate an expression."""

    def __init__(self):
        self.proc = subprocess.Popen(
            [CHROME, "--headless=new", "--no-sandbox", "--disable-gpu",
             "--remote-debugging-port=9444", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            try:
                targets = json.load(urllib.request.urlopen("http://127.0.0.1:9444/json"))
                self.ws_url = next(t["webSocketDebuggerUrl"] for t in targets
                                   if t.get("type") == "page")
                return
            except Exception:                                   # noqa: BLE001
                time.sleep(0.5)
        raise RuntimeError("Chromium did not come up")

    def close(self):
        self.proc.terminate()
        self.proc.wait(timeout=10)

    def evaluate(self, expression):
        import websockets

        async def run():
            async with websockets.connect(self.ws_url, max_size=None) as ws:
                await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                                          "params": {"expression": expression,
                                                     "returnByValue": True}}))
                while True:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                    if msg.get("id") == 1:
                        result = msg.get("result", {})
                        if result.get("exceptionDetails"):
                            raise AssertionError(result["exceptionDetails"]["text"])
                        return result["result"].get("value")
        return asyncio.run(run())


@pytest.fixture(scope="module")
def browser():
    b = Browser()
    b.evaluate(_planner_source())
    yield b
    b.close()


def _roster(rng, n_bench=6):
    """A plausible roster: one of each starting slot, then a bench."""
    players, pid = [], 0
    for slot, count in SLOTS.items():
        for _ in range(count):
            pid += 1
            pos = rng.choice(FLEX_POSITIONS) if slot == FLEX else slot
            players.append({"id": f"p{pid}", "pos": pos, "slot": slot})
    for _ in range(n_bench):
        pid += 1
        players.append({"id": f"p{pid}",
                        "pos": rng.choice(["QB", "RB", "WR", "TE", "K", "DEF"]),
                        "slot": "BN"})
    return players


def _case(seed):
    """Returns the kickoffs twice: ISO for Python, epoch ms for the browser.

    That is the split production actually has - the build ships ISO strings and
    my_league_data.kickoffs() turns them into milliseconds for Date - so the
    comparison exercises the same conversion rather than an idealised one.
    """
    rng = random.Random(seed)
    players = _roster(rng)
    proj, kick_iso, kick_ms = {}, {}, {}
    base = pd.Timestamp("2026-09-27T17:00:00Z")
    for p in players:
        proj[p["id"]] = round(rng.uniform(0, 25), 2)
        # A third of the league has no game (bye), the rest are spread across
        # the week so the flex's latest-kickoff rule actually gets exercised.
        if rng.random() > 0.3:
            when = base + pd.Timedelta(hours=rng.choice([0, 3, 6, 50, 72]))
            kick_iso[p["id"]] = when.isoformat()
            kick_ms[p["id"]] = int(when.timestamp() * 1000)
    locked = [p["id"] for p in players
              if kick_iso.get(p["id"]) and rng.random() < 0.2]
    return players, proj, kick_iso, kick_ms, locked


@pytest.mark.parametrize("seed", range(40))
def test_the_two_planners_choose_the_same_lineup(browser, seed):
    players, proj, kick_iso, kick_ms, locked = _case(seed)

    got = lineup.plan(players, SLOTS, proj, kick_iso, set(locked),
                      FLEX, FLEX_POSITIONS)
    js = browser.evaluate(
        f"JSON.stringify(window.GSPlan({json.dumps(players)}, {json.dumps(SLOTS)}, "
        f"{json.dumps(proj)}, {json.dumps(kick_ms)}, {json.dumps(locked)}, "
        f"{json.dumps(FLEX)}, {json.dumps(list(FLEX_POSITIONS))}))")
    mine = json.loads(js)

    assert mine["slot"] == got["slot"], f"seed {seed}: different slots"
    assert sorted(mine["start"]) == sorted(got["start"]), f"seed {seed}: different starters"
    assert {k: v for k, v in mine["cover"].items() if v} == \
           {k: v for k, v in got["cover"].items() if v}, f"seed {seed}: different cover"


def test_the_planner_is_deterministic_under_a_tie():
    """The bug this port found.

    `flex_positions` used to be turned into a set, and two players tied on
    projection were separated by whichever position the flex loop reached
    first - so the recommended lineup depended on string hash order, and the
    same roster came out differently between builds. Seed 31 has an exact tie
    between an RB and a TE, which is what made it visible.

    Run in subprocesses because PYTHONHASHSEED is fixed at interpreter start.
    """
    import os
    import sys as _sys

    players, proj, kick_iso, _ms, locked = _case(31)
    script = (
        "import json,sys;"
        "sys.path.insert(0, %r);"
        "from gordstats import lineup;"
        "players,proj,kick,locked = json.loads(sys.stdin.read());"
        "print(json.dumps(lineup.plan(players, %r, proj, kick, set(locked), %r, %r)['slot'],"
        " sort_keys=True))" % (str(ROOT / "src"), SLOTS, FLEX, list(FLEX_POSITIONS))
    )
    payload = json.dumps([players, proj, kick_iso, locked])

    seen = set()
    for seed in ("0", "1", "2", "3"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        out = subprocess.run([_sys.executable, "-c", script], input=payload,
                             capture_output=True, text=True, env=env, check=True)
        seen.add(out.stdout.strip())
    assert len(seen) == 1, f"the lineup changes with PYTHONHASHSEED: {seen}"
