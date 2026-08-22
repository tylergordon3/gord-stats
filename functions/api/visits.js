/**
 * GET /api/visits            -> read the counters
 * GET /api/visits?count=1    -> count this visit, then read
 *
 * Runs as a Cloudflare Pages Function (picked up from /functions at deploy
 * time) against the VISITS KV namespace bound in wrangler.toml.
 *
 * Two numbers:
 *   total  - visits since launch. The footer script calls with count=1 once
 *            per browser tab (sessionStorage), so this is closer to sessions
 *            than raw page loads.
 *   today  - approximate unique visitors in the current UTC day, found by
 *            hashing IP + user agent + day; the hash key expires with the day.
 *
 * KV is eventually consistent and rate-limits writes to one key to ~1/s, so a
 * burst can drop a few increments. Fine for a footer number; nothing here is
 * allowed to fail the page — every error path still returns what it can.
 */

const BOT_UA = /bot|crawl|spider|slurp|preview|facebookexternalhit|headless|lighthouse|monitor|curl|wget|python-requests/i;

export async function onRequestGet({ request, env }) {
  const url = new URL(request.url);
  const count = url.searchParams.get("count") === "1";
  const day = new Date().toISOString().slice(0, 10);

  let total = 0, today = 0;
  try {
    if (count && env.VISITS && !BOT_UA.test(request.headers.get("user-agent") || "")) {
      await record(request, env.VISITS, day);
    }
    if (env.VISITS) {
      [total, today] = await Promise.all([
        env.VISITS.get("total").then(Number),
        env.VISITS.get(`day:${day}`).then(Number),
      ]);
    }
  } catch (err) {
    console.error("visits:", err);
  }

  return new Response(JSON.stringify({ total: total || 0, today: today || 0, day }), {
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

async function record(request, kv, day) {
  const ip = request.headers.get("cf-connecting-ip") || "";
  const ua = request.headers.get("user-agent") || "";
  const seenKey = `seen:${day}:${await sha256(`${day}|${ip}|${ua}`)}`;

  const writes = [bump(kv, "total")];
  if (!(await kv.get(seenKey))) {
    writes.push(
      bump(kv, `day:${day}`),
      // Expire a little past the day boundary so a late read still finds it.
      kv.put(seenKey, "1", { expirationTtl: 60 * 60 * 26 }),
    );
  }
  await Promise.all(writes);
}

async function bump(kv, key) {
  const n = Number(await kv.get(key)) || 0;
  await kv.put(key, String(n + 1));
}

async function sha256(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].slice(0, 16).map((b) => b.toString(16).padStart(2, "0")).join("");
}
