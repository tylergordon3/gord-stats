"""
Every Pages Function loads as an ES module, and CI checks the same on push.

A syntax error under functions/ fails the Pi's `wrangler pages deploy`, and
with it the upload of the whole site. CI now runs `node --check` over them;
this machine has no node, so here each file is imported into headless
Chromium instead - which also catches an import of a name its _lib module
does not export, something a syntax check alone would pass.
"""
import json

import pytest
import yaml

from functions_harness import CHROME, FUNCTIONS, ROOT, Worker, module_url

FILES = sorted(p for p in FUNCTIONS.rglob("*.js"))
ROUTES = [p for p in FILES if "_lib" not in p.parts]


@pytest.mark.skipif(CHROME is None, reason="no Chromium to run the JS in")
def test_every_function_loads_and_routes_export_a_handler():
    with Worker() as w:
        loaded = w.js("""
          const out = {};
          for (const [name, url] of Object.entries(%s)) {
            try {
              out[name] = Object.keys(await import(url));
            } catch (err) {
              out[name] = "failed: " + err;
            }
          }
          return out;""" % json.dumps(
            {str(p.relative_to(FUNCTIONS)): module_url(p) for p in FILES}))
    failed = {k: v for k, v in loaded.items() if isinstance(v, str)}
    assert not failed
    for p in ROUTES:
        exports = loaded[str(p.relative_to(FUNCTIONS))]
        assert any(e.startswith("onRequest") for e in exports), p


def test_ci_syntax_checks_the_functions_with_a_read_only_token():
    flow = yaml.safe_load((ROOT / ".github" / "workflows" / "tests.yml").read_text())
    assert flow["permissions"] == {"contents": "read"}
    steps = flow["jobs"]["tests"]["steps"]
    check = next(s for s in steps if "node --check" in s.get("run", ""))
    assert "--input-type=module" in check["run"] and "find functions" in check["run"]
    # Before pytest, so a broken Function fails fast and on its own line.
    assert steps.index(check) < next(i for i, s in enumerate(steps) if s.get("run") == "pytest")
