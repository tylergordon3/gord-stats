/**
 * In front of every /api/* route: the API answers on the site's own address
 * and nowhere else.
 *
 * Cloudflare keeps every deployment the Pi uploads live at its own
 * <hash>.gordstats-cbb.pages.dev address, with the production bindings - the
 * accounts database, the visit counter - and whatever Functions code it
 * shipped with. The 2026-09-28 audit found one four days old still counting
 * visits with code from before the fixes since. Neither those addresses nor
 * the gordstats-cbb.pages.dev alias pass through the zone's own settings (its
 * bot and rate-limit rules), so from this deployment on the API is www-only.
 * Pages on those addresses still load; they are just not a way in.
 *
 * Sign-in lives under /api/auth, so this covers it too. Local `wrangler pages
 * dev` keeps working on localhost.
 */
const HOSTS = new Set(["www.gordstats.com", "gordstats.com", "localhost", "127.0.0.1"]);

/**
 * A write sent from another site's page. The session cookie is SameSite=Lax,
 * which already keeps it off such a request; this says no on the browser's own
 * word as well (Sec-Fetch-Site, else Origin), so nothing rests on the cookie
 * attribute alone. A request with neither header - curl, an old browser - is
 * let through, as the cookie still decides who it is.
 */
function crossSiteWrite(request) {
  if (["GET", "HEAD", "OPTIONS"].includes(request.method)) return false;
  const site = (request.headers.get("sec-fetch-site") || "").toLowerCase();
  if (site) return site === "cross-site";
  const origin = request.headers.get("origin");
  return !!origin && origin !== new URL(request.url).origin;
}

export async function onRequest(context) {
  const host = new URL(context.request.url).hostname;
  if (!HOSTS.has(host)) {
    return new Response(JSON.stringify({ error: "not found" }), {
      status: 404,
      headers: { "content-type": "application/json", "cache-control": "no-store" },
    });
  }
  if (crossSiteWrite(context.request)) {
    return new Response(JSON.stringify({ error: "write from the site itself" }), {
      status: 403,
      headers: { "content-type": "application/json", "cache-control": "no-store" },
    });
  }
  const res = await context.next();
  // _headers covers pages, not Functions: say it here for every API answer.
  try { res.headers.set("x-content-type-options", "nosniff"); } catch (e) { /* immutable */ }
  return res;
}
