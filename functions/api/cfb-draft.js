/**
 * GET /api/cfb-draft         -> the college league's draft, as it happens
 *
 * A Cloudflare Pages Function (picked up from /functions at deploy time) that
 * exists for one reason: Yahoo's public read-only fantasy API answers anyone,
 * with no OAuth, but it sends no access-control-allow-origin, so the live draft
 * page cannot call it from the reader's browser the way the NFL board called
 * Sleeper. This fetches it server-side and hands back JSON with CORS on it.
 *
 * Yahoo does not publish "the draft, live" as one endpoint, and which of its
 * feeds fills in first during a draft is not something the documentation says.
 * So this asks all three and returns whichever has picks in it:
 *
 *   draftresults        pick number -> team + player key. The real thing, if
 *                       Yahoo writes it during the draft rather than after.
 *   teams;out=roster    every team's roster. Populates as picks land, but says
 *                       nothing about pick order.
 *   players;status=T    every player already taken. The floor: enough to know
 *                       who is off the board even if nothing else works.
 *
 * The page reconciles what it gets with the picks the user has entered by hand,
 * so a draft where none of these updates live still works - it just needs
 * tapping. Nothing here is allowed to fail the page: every error path returns a
 * body the client can read.
 */

const API = "https://pub-api-ro.fantasysports.yahoo.com/fantasy/v2";
const LEAGUE = "474.l.21318";
const TIMEOUT_MS = 8000;

// Yahoo's edge caches this family for five minutes, which during a draft is
// several rounds. A changing query parameter is what makes the poll live.
function bust() {
  return `_=${Date.now()}`;
}

async function yahoo(path) {
  const url = `${API}/${path}?format=json&${bust()}`;
  const res = await fetch(url, {
    cf: { cacheTtl: 0, cacheEverything: false },
    headers: { "user-agent": "Mozilla/5.0 (gordstats live draft board)" },
    signal: AbortSignal.timeout(TIMEOUT_MS),
  });
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

/** Yahoo's list-of-single-key-objects, folded into one object.
 *
 * Yahoo is not consistent about this: the players collection nests a team's
 * metadata as a list of one-key objects, while the league endpoints hand back
 * a plain object for the same thing. Both arrive here. */
function fold(parts) {
  if (!parts) return {};
  if (!Array.isArray(parts)) return typeof parts === "object" ? parts : {};
  const out = {};
  for (const p of parts) if (p && typeof p === "object") Object.assign(out, p);
  return out;
}

/** The `league` array's first element that carries `key`. */
function block(raw, key) {
  const league = raw?.fantasy_content?.league;
  if (!Array.isArray(league)) return null;
  for (const part of league) {
    if (part && typeof part === "object" && key in part) return part[key];
  }
  return null;
}

/** Every numbered entry of a Yahoo collection, in order, ignoring `count`. */
function entries(collection) {
  if (!collection || typeof collection !== "object") return [];
  return Object.keys(collection)
    .filter((k) => k !== "count")
    .sort((a, b) => Number(a) - Number(b))
    .map((k) => collection[k]);
}

function parseDraft(raw) {
  const results = block(raw, "draft_results");
  const picks = [];
  for (const entry of entries(results)) {
    const r = entry?.draft_result;
    if (!r || !r.player_key) continue;
    picks.push({
      pick: Number(r.pick),
      round: Number(r.round),
      team_key: r.team_key || null,
      player_key: r.player_key,
      player_id: String(r.player_key).split(".p.")[1] || null,
    });
  }
  picks.sort((a, b) => a.pick - b.pick);
  return picks;
}

function parseRosters(raw) {
  const out = {};
  for (const entry of entries(block(raw, "teams"))) {
    const team = entry?.team;
    if (!Array.isArray(team)) continue;
    const meta = fold(team[0]);
    const key = meta.team_key;
    if (!key) continue;
    const ids = [];
    for (const part of team.slice(1)) {
      const players = part?.roster?.["0"]?.players || part?.roster?.players;
      for (const p of entries(players)) {
        const pm = fold(p?.player?.[0]);
        if (pm.player_id) ids.push(String(pm.player_id));
      }
    }
    out[key] = ids;
  }
  return out;
}

function parseTaken(raw) {
  const ids = [];
  for (const entry of entries(block(raw, "players"))) {
    const pm = fold(entry?.player?.[0]);
    if (pm.player_id) ids.push(String(pm.player_id));
  }
  return ids;
}

async function settle(promise, fallback) {
  try {
    return await promise;
  } catch (err) {
    console.error("cfb-draft:", err.message);
    return fallback;
  }
}

export async function onRequestGet() {
  const [draftRaw, rosterRaw, takenRaw] = await Promise.all([
    settle(yahoo(`league/${LEAGUE}/draftresults`), null),
    settle(yahoo(`league/${LEAGUE}/teams;out=roster`), null),
    // 200 is past a full 10-team draft of 17 rounds, so one page is enough.
    settle(yahoo(`league/${LEAGUE}/players;status=T;count=200`), null),
  ]);

  const meta = fold(draftRaw?.fantasy_content?.league?.[0]);
  const picks = draftRaw ? parseDraft(draftRaw) : [];
  const rosters = rosterRaw ? parseRosters(rosterRaw) : {};
  const taken = takenRaw ? parseTaken(takenRaw) : [];

  const body = {
    fetched: Date.now(),
    draft_status: meta.draft_status || null,
    picks,
    rosters,
    taken,
    // Which feed actually had something, so the page can say so rather than
    // leaving the reader guessing why the board is empty.
    source: picks.length ? "draftresults"
      : Object.values(rosters).some((r) => r.length) ? "rosters"
        : taken.length ? "taken" : "none",
    ok: Boolean(draftRaw || rosterRaw || takenRaw),
  };

  return new Response(JSON.stringify(body), {
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "access-control-allow-origin": "*",
    },
  });
}
