/**
 * GET /api/cfb-scores?week=N&dates=YYYY  -> ESPN's CFB scoreboard, with CORS
 *
 * A Cloudflare Pages Function (picked up from /functions at deploy time) in
 * the same mould as cfb-draft.js: ESPN's site.api.espn.com answers anyone,
 * but a real browser gets the JSON back *without* access-control-allow-origin
 * (curl with its default UA gets the header - the edge treats the two
 * differently), so the scoreboard page cannot poll it directly. This fetches
 * it server-side and hands it back with CORS on it.
 *
 * Parameters are validated to two integers rather than passed through: this
 * is a scoreboard proxy, not an open proxy.
 */

const API =
  "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard";
const FBS = "80";
const TIMEOUT_MS = 8000;

export async function onRequestGet(context) {
  const params = new URL(context.request.url).searchParams;
  const week = params.get("week") || "";
  const dates = params.get("dates") || "";
  if (!/^\d{1,2}$/.test(week) || !/^\d{4}$/.test(dates)) {
    return new Response(JSON.stringify({ ok: false, error: "bad params" }), {
      status: 400,
      headers: {
        "content-type": "application/json; charset=utf-8",
        "access-control-allow-origin": "*",
      },
    });
  }

  const upstream =
    `${API}?groups=${FBS}&week=${week}&dates=${dates}&seasontype=2&limit=500`;
  let res;
  try {
    res = await fetch(upstream, {
      // Live scores: never serve one poll's answer to the next minute's poll
      // from Cloudflare's cache.
      cf: { cacheTtl: 0, cacheEverything: false },
      // ESPN 403s browser-fingerprinted clients but answers plain library
      // UAs (same trick as src/cfb/espn.py, which sends requests' default).
      headers: { accept: "application/json",
                 "user-agent": "python-requests/2.32.3" },
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch (err) {
    return new Response(JSON.stringify({ ok: false, error: String(err) }), {
      status: 502,
      headers: {
        "content-type": "application/json; charset=utf-8",
        "access-control-allow-origin": "*",
      },
    });
  }

  return new Response(res.body, {
    status: res.status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "access-control-allow-origin": "*",
    },
  });
}
