"""
Runs a Pages Function in headless Chromium, against a real SQLite.

This machine has no node, and the Functions talk to D1 - which is SQLite
behind a binding. So the harness supplies both halves: the Function's module
is imported into a Chromium page, and env.DB is a small stand-in that sends
every statement over to Python's sqlite3, built from deploy/d1-schema.sql. A
test then checks the SQL the Function really runs, not a mock's idea of it.

Everything else a Function reaches for is a plain stub on the page (the `T`
object in PRELUDE): fetch, KV, the Workers cache, a Response that keeps its
Set-Cookie. The page is a file: URL rather than about:blank because only a
secure context has crypto.subtle, and the session cookies are HMACs.

One Chromium at a time - the debugging port is fixed - so fixtures built on
this are function-scoped and close it before the next test starts one.
"""
import asyncio
import base64
import json
import re
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from test_my_team_planner import CHROME, Browser

ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS = ROOT / "functions"
SCHEMA = ROOT / "deploy" / "d1-schema.sql"
MIGRATION_004 = ROOT / "deploy" / "d1-migrate-004-write-limits.sql"
SECRET = "test-secret"

__all__ = ["CHROME", "FUNCTIONS", "MIGRATION_004", "ROOT", "SCHEMA", "SECRET",
           "Sqlite", "Worker", "before_004"]


def before_004() -> str:
    """The schema as a database that has not had migration 004 yet.

    Built backwards from today's schema - its new columns dropped, the two
    indexes it removes put back - so it cannot drift from what 004 undoes.
    """
    # Comments out first: SQLite before 3.50 rewrites a table's CREATE
    # statement on DROP COLUMN and chokes on a trailing `--` comment ("error
    # in table users after drop column: incomplete input") - GitHub's runner
    # has one of those. The shape compared is columns and indexes, not text.
    sql = re.sub(r"--[^\n]*", "", SCHEMA.read_text())
    for table, col in re.findall(r"ALTER TABLE (\w+) ADD COLUMN (\w+)",
                                 MIGRATION_004.read_text()):
        sql += f"\nALTER TABLE {table} DROP COLUMN {col};"
    return sql + ("\nCREATE INDEX favorites_by_user ON favorites (user_id);"
                  "\nCREATE INDEX leagues_by_user ON leagues (user_id);")


class Sqlite:
    """An in-memory database answering the page's env.DB over HTTP.

    Foreign keys on, because D1 enforces them. A batch runs in one
    transaction and rolls back whole on an error, which is D1's contract too.
    """

    def __init__(self, script: str | None = None):
        self.db = sqlite3.connect(":memory:", check_same_thread=False,
                                  isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA.read_text() if script is None else script)
        self.lock = threading.Lock()
        self.statements: list[str] = []

        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):                                  # noqa: N802
                size = int(self.headers.get("content-length") or 0)
                ask = json.loads(self.rfile.read(size))
                try:
                    body = {"results": outer._run(ask["statements"], ask["batch"])}
                except sqlite3.Error as err:
                    body = {"error": f"{err}: SQLITE_ERROR"}
                data = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("access-control-allow-origin", "*")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):                       # quiet
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def _one(self, st):
        cur = self.db.execute(st["sql"], st["params"])
        rows = [dict(r) for r in cur.fetchall()]
        changes = cur.rowcount if cur.rowcount > 0 else 0
        self.statements.append(st["sql"])
        if st["mode"] == "first":
            return rows[0] if rows else None
        return {"results": rows, "success": True, "meta": {"changes": changes}}

    def _run(self, statements, batch):
        with self.lock:
            if not batch:
                return [self._one(statements[0])]
            self.db.execute("BEGIN")
            try:
                out = [self._one(st) for st in statements]
            except sqlite3.Error:
                self.db.execute("ROLLBACK")
                raise
            self.db.execute("COMMIT")
            return out

    def rows(self, sql, *params):
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, params).fetchall()]

    def execute(self, sql, *params):
        with self.lock:
            self.db.execute(sql, params)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.db.close()


# Stubs every test page gets. `T.fetches` records what a Function asked the
# network for; `T.routes` answers it. The real fetch is kept for env.DB only.
PRELUDE = r"""
(() => {
  const realFetch = window.fetch.bind(window);

  class FakeResponse {
    constructor(body = null, init = {}) {
      this._body = body;
      this.status = init.status ?? 200;
      this.headers = new Headers(init.headers || {});
    }
    get ok() { return this.status >= 200 && this.status < 300; }
    get body() { return this._body; }
    async text() {
      const b = this._body;
      if (b == null) return "";
      if (typeof b === "string") return b;
      if (b instanceof FakeResponse) return b.text();
      return new window.__RealResponse(b).text();
    }
    async json() { return JSON.parse(await this.text()); }
    clone() {
      return new FakeResponse(this._body, { status: this.status, headers: this.headers });
    }
  }
  window.__RealResponse = window.Response;
  // A browser drops Set-Cookie from any Response script builds; a Worker does
  // not, and the auth tests need to see it.
  Object.defineProperty(window, "Response",
    { value: FakeResponse, configurable: true, writable: true });

  async function q(sqlUrl, statements, batch) {
    for (const s of statements) {
      if (s.params.some((p) => p === undefined)) {
        // D1 refuses undefined rather than binding NULL; so does this.
        throw new Error("D1_TYPE_ERROR: Type 'undefined' not supported for value 'undefined'");
      }
    }
    const r = await realFetch(sqlUrl, { method: "POST",
      body: JSON.stringify({ statements, batch }) });
    const out = await r.json();
    if (out.error) throw new Error("D1_ERROR: " + out.error);
    return out.results;
  }

  function db(sqlUrl) {
    const stmt = (sql, params = []) => ({
      sql, params,
      bind: (...p) => stmt(sql, p),
      all: async () => (await q(sqlUrl, [{ sql, params, mode: "all" }], false))[0],
      run: async () => (await q(sqlUrl, [{ sql, params, mode: "run" }], false))[0],
      first: async (col) => {
        const row = (await q(sqlUrl, [{ sql, params, mode: "first" }], false))[0];
        return col ? (row ? row[col] : null) : row;
      },
    });
    return {
      prepare: (sql) => stmt(sql),
      batch: (list) => q(sqlUrl,
        list.map((s) => ({ sql: s.sql, params: s.params, mode: "all" })), true),
    };
  }

  function kv(init = {}) {
    const store = new Map(Object.entries(init));
    const log = { gets: 0, puts: [] };
    return {
      store, log,
      async get(k) { log.gets++; return store.has(k) ? store.get(k) : null; },
      async put(k, v) { log.puts.push(k); store.set(k, String(v)); },
    };
  }

  // caches.default: keyed on the URL, the way the Workers cache is.
  function cache() {
    const store = new Map();
    const log = { match: 0, put: 0 };
    const key = (r) => (typeof r === "string" ? r : r.url);
    return {
      store, log,
      async match(r) { log.match++; const hit = store.get(key(r)); return hit ? hit.clone() : undefined; },
      async put(r, res) { log.put++; store.set(key(r), res.clone()); },
    };
  }

  function req(url, { method = "GET", headers = {}, body } = {}) {
    return {
      url: new URL(url, "https://www.gordstats.com").toString(),
      method,
      // A standalone Headers has no guard, so Cookie and Sec-Fetch-Site
      // survive - a Request built in a page would silently drop both.
      headers: new Headers(headers),
      async json() { return JSON.parse(body); },
      async text() { return body ?? ""; },
    };
  }

  const T = window.T = {
    fetches: [],
    // [pattern, handler(url, init) -> {status, body} | FakeResponse]
    routes: [],
    waits: [],
    db, kv, cache, req,
    ctx(extra = {}) {
      return { waitUntil: (p) => T.waits.push(p), params: {}, ...extra };
    },
    async settle() { await Promise.all(T.waits.splice(0)); },
    async answer(res) {
      return { status: res.status, headers: Object.fromEntries(res.headers),
               cookies: res.headers.getSetCookie(), text: await res.text() };
    },
  };

  window.fetch = async (input, init = {}) => {
    const url = typeof input === "string" ? input : input.url;
    T.fetches.push(url);
    for (const [pattern, handler] of T.routes) {
      if (new RegExp(pattern).test(url)) {
        const out = await handler(url, init);
        if (out instanceof FakeResponse) return out;
        if (out instanceof Error) throw out;
        const body = typeof out.body === "string" ? out.body : JSON.stringify(out.body);
        return new FakeResponse(body, { status: out.status ?? 200 });
      }
    }
    throw new TypeError("no route for " + url);
  };
})();
"""

_IMPORT = re.compile(r'''(from\s+)(["'])(\.{1,2}/[^"']+\.js)\2''')


def module_url(path: Path) -> str:
    """The file as a data: URL module, its relative imports made data: URLs too."""
    src = path.read_text()

    def inline(m):
        return f'{m.group(1)}"{module_url((path.parent / m.group(3)).resolve())}"'

    src = _IMPORT.sub(inline, src)
    return "data:text/javascript;base64," + base64.b64encode(src.encode()).decode()


class Worker(Browser):
    """Chromium on a secure-context page, with PRELUDE and a SQLite behind env.DB."""

    def __init__(self, script: str | None = None):
        self.sql = Sqlite(script)
        try:
            super().__init__()
            self._cdp("Page.navigate", {"url": Path(__file__).parent.as_uri() + "/"})
            for _ in range(100):
                if self.evaluate("location.protocol + document.readyState") == "file:complete":
                    break
                time.sleep(0.05)
            else:
                raise RuntimeError("the test page did not load")
            self.evaluate(PRELUDE)
            self.js(f"window.SQL = {json.dumps(self.sql.url)};")
            self.load(FUNCTIONS / "api" / "_lib" / "session.js", "session")
        except Exception:
            self.close()
            raise

    def close(self):
        try:
            if getattr(self, "proc", None):
                super().close()
        finally:
            self.sql.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _cdp(self, method, params):
        import websockets

        async def run():
            async with websockets.connect(self.ws_url, max_size=None) as ws:
                await ws.send(json.dumps({"id": 1, "method": method, "params": params}))
                while True:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
                    if msg.get("id") == 1:
                        return msg
        return asyncio.run(run())

    def js(self, body: str):
        """Run `body` as the inside of an async function; returns its value."""
        msg = self._cdp("Runtime.evaluate", {
            "expression": f"(async () => {{ {body}\n }})()",
            "awaitPromise": True, "returnByValue": True})
        result = msg.get("result", {})
        if result.get("exceptionDetails"):
            details = result["exceptionDetails"]
            raise AssertionError(details.get("exception", {}).get("description")
                                 or details["text"])
        return result["result"].get("value")

    def load(self, path: Path, name: str):
        """Import a Functions file as window[name]."""
        self.js(f"window[{json.dumps(name)}] = await import({json.dumps(module_url(path))});")

    def env(self, **extra) -> str:
        """JS for an env with accounts configured and DB pointed at this SQLite."""
        base = {"SESSION_SECRET": SECRET, "GOOGLE_CLIENT_ID": "cid",
                "GOOGLE_CLIENT_SECRET": "csecret"}
        base.update(extra)
        return f"Object.assign({{ DB: T.db(SQL) }}, {json.dumps(base)})"

    def user(self, uid: str = "u1") -> dict:
        """A users row, and the Cookie header of a session for it."""
        self.sql.execute(
            "INSERT INTO users (id, email, provider_sub, created_at, last_seen_at) "
            "VALUES (?, ?, ?, '2026-09-01T00:00:00Z', '2026-09-01T00:00:00Z')",
            uid, f"{uid}@example.com", f"sub-{uid}")
        token = self.js(
            "return await session.sign({ typ: 'session', uid: %s, email: %s,"
            " exp: Math.floor(Date.now() / 1000) + 3600 }, %s, 'session');"
            % (json.dumps(uid), json.dumps(f"{uid}@example.com"), json.dumps(SECRET)))
        return {"cookie": "gs_session=" + token}

    def call(self, fn: str, url: str, *, method: str = "GET", headers: dict | None = None,
             body=None, env: str | None = None, ctx: str = "{}") -> dict:
        """Run handler `fn` (a JS expression) on one request.

        -> {status, headers, cookies, text, json}. `body` is sent as-is when it
        is a string, as JSON otherwise.
        """
        if body is not None and not isinstance(body, str):
            body = json.dumps(body)
        out = self.js(f"""
          const request = T.req({json.dumps(url)}, {{ method: {json.dumps(method)},
            headers: {json.dumps(headers or {})}, body: {json.dumps(body)} }});
          const res = await {fn}({{ request, env: {env or self.env()}, ...T.ctx({ctx}) }});
          return await T.answer(res);""")
        try:
            out["json"] = json.loads(out["text"])
        except ValueError:
            out["json"] = None
        return out
