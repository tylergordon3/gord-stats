/**
 * A short-lived answer, shared by everyone asking the same question.
 *
 * The live proxies (cfb-scores, cfb-matchups) used to go upstream on every
 * hit - every poll from every open tab, and anyone with a loop could make
 * ESPN or Yahoo see this site as the one hammering them. With this, a data
 * centre asks upstream at most once per `seconds` per question and every
 * other reader gets that answer; the pages poll every 30-60 s, so live
 * scores are no staler than they were.
 *
 * The Workers cache is per data centre and best-effort - it can drop
 * anything at any time, and it is a no-op on *.pages.dev - so a miss is
 * always handled by simply asking upstream. Only a 200 is kept: a failure
 * should be retried by the next poll, not repeated to everyone for
 * `seconds`.
 */

/**
 * `produce()` -> { status, body: string }. Returns the same shape, from the
 * cache when it can. `key` is a URL built from the validated, normalised
 * parameters - never the raw query, or a cache-busting `_=` would make every
 * request its own entry.
 */
export async function cached(context, key, seconds, produce) {
  const cache = globalThis.caches?.default;
  if (cache) {
    const hit = await cache.match(key).catch(() => undefined);
    if (hit) return { status: hit.status, body: await hit.text() };
  }
  const out = await produce();
  if (cache && out.status === 200) {
    const copy = new Response(out.body, {
      headers: {
        "content-type": "application/json; charset=utf-8",
        "cache-control": `public, max-age=${seconds}`,
      },
    });
    const put = cache.put(key, copy).catch(() => {});
    if (context.waitUntil) context.waitUntil(put);
    else await put;
  }
  return out;
}
