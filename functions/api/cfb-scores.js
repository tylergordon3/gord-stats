/**
 * GET /api/cfb-scores?week=N&dates=YYYY[&seasontype=2|3]  -> ESPN's CFB scoreboard, with CORS
 *
 * A Cloudflare Pages Function (picked up from /functions at deploy time):
 * ESPN's site.api.espn.com answers anyone, but a real browser gets the JSON
 * back *without* access-control-allow-origin (curl with its default UA gets
 * the header - the edge treats the two differently), so the scoreboard page
 * cannot poll it directly. This fetches it server-side and hands it back with
 * CORS on it.
 *
 * Parameters are validated to two integers rather than passed through: this
 * is a scoreboard proxy, not an open proxy. They are held to what a college
 * season can ask for - weeks 0 to 20, a season from 2000 to next year - and
 * normalised, so "07" and "7" are one question and one cache entry.
 * seasontype is 2 (the regular season, the default) or 3 (bowls and the CFP,
 * which ESPN files as week 1 of seasontype 3).
 *
 * Answers are shared for CACHE_SECONDS through the Workers cache
 * (_lib/cache.js): the page polls every 30 s at its fastest, so readers in
 * one data centre now share one call to ESPN rather than making one each.
 */
import { cached } from "./_lib/cache.js";

const API =
  "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard";
const FBS = "80";
const TIMEOUT_MS = 8000;
const CACHE_SECONDS = 20;
const MAX_WEEK = 20;
const FIRST_SEASON = 2000;

const HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
  "access-control-allow-origin": "*",
};

/** The validated question, or null. -> { week, dates, seasontype } as numbers */
export function question(params, now = new Date()) {
  const week = params.get("week") || "";
  const dates = params.get("dates") || "";
  const type = params.get("seasontype") || "2";
  if (!/^\d{1,2}$/.test(week) || !/^\d{4}$/.test(dates) || !/^[23]$/.test(type)) return null;
  const q = { week: Number(week), dates: Number(dates), seasontype: Number(type) };
  if (q.week > MAX_WEEK) return null;
  if (q.dates < FIRST_SEASON || q.dates > now.getUTCFullYear() + 1) return null;
  return q;
}

export async function onRequestGet(context) {
  const url = new URL(context.request.url);
  const q = question(url.searchParams);
  if (!q) {
    return new Response(JSON.stringify({ ok: false, error: "bad params" }),
      { status: 400, headers: HEADERS });
  }

  const key = `${url.origin}/api/cfb-scores?week=${q.week}&dates=${q.dates}&seasontype=${q.seasontype}`;
  let out;
  try {
    out = await cached(context, key, CACHE_SECONDS, async () => {
      const res = await fetch(
        `${API}?groups=${FBS}&week=${q.week}&dates=${q.dates}&seasontype=${q.seasontype}&limit=500`, {
          // Cloudflare's own fetch cache stays out of it: the Workers cache
          // above is the one deciding how fresh "live" is.
          cf: { cacheTtl: 0, cacheEverything: false },
          // ESPN 403s browser-fingerprinted clients but answers plain library
          // UAs (same trick as src/cfb/espn.py, which sends requests' default).
          headers: { accept: "application/json",
                     "user-agent": "python-requests/2.32.3" },
          signal: AbortSignal.timeout(TIMEOUT_MS),
        });
      return { status: res.status, body: await res.text() };
    });
  } catch (err) {
    return new Response(JSON.stringify({ ok: false, error: String(err) }),
      { status: 502, headers: HEADERS });
  }

  return new Response(out.body, { status: out.status, headers: HEADERS });
}
