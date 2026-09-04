/**
 * GET /api/cfb-matchups?week=N  -> the college league's week, live, with CORS
 *
 * A Cloudflare Pages Function in the mould of cfb-draft.js: Yahoo's public
 * read-only API answers anyone but sends no access-control-allow-origin, so
 * the matchups page cannot poll it from the reader's browser. This asks Yahoo
 * for the week's scoreboard and every team's roster with weekly stats (eleven
 * calls, in parallel) and hands back one small JSON the page can apply:
 *
 *   { ok, week, fetched,
 *     teams: { team_key: { name, points, projected, win_probability,
 *                          players: { player_id: { points, line } } } } }
 *
 * `line` is the stat line as text ("13 car, 37 rush yds"), formatted here
 * from Yahoo's stat ids the same way src/cfb/site/matchups.py formats it at
 * build time, so the page swaps text rather than re-deriving it.
 */

const API = "https://pub-api-ro.fantasysports.yahoo.com/fantasy/v2";
const LEAGUE = "474.l.21318";
const TIMEOUT_MS = 8000;

// Stat ids -> how the line reads, by group. Mirrors _LINE in the page builder.
const LINE = [
  ["off", [["4", "pass yds"], ["5", "TD"], ["6", "INT"]]],
  ["off", [["8", "car"], ["9", "rush yds"], ["10", "TD"]]],
  ["off", [["11", "rec"], ["12", "rec yds"], ["13", "TD"]]],
  ["off", [["15", "ret TD"], ["16", "2-pt"], ["18", "fum lost"], ["57", "fum TD"]]],
  ["def", [["31", "PA"], ["32", "sk"], ["33", "INT"], ["34", "FR"], ["35", "TD"],
           ["36", "saf"], ["37", "blk"], ["49", "ret TD"]]],
];

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "access-control-allow-origin": "*",
    },
  });
}

async function yahoo(path) {
  const res = await fetch(`${API}/${path}?format=json&_=${Date.now()}`, {
    cf: { cacheTtl: 0, cacheEverything: false },
    headers: { "user-agent": "Mozilla/5.0 (gordstats matchups)" },
    signal: AbortSignal.timeout(TIMEOUT_MS),
  });
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

function fold(parts) {
  if (!parts) return {};
  if (!Array.isArray(parts)) return typeof parts === "object" ? parts : {};
  const out = {};
  for (const p of parts) if (p && typeof p === "object") Object.assign(out, p);
  return out;
}

function entries(collection) {
  if (!collection || typeof collection !== "object") return [];
  return Object.keys(collection)
    .filter((k) => k !== "count")
    .sort((a, b) => Number(a) - Number(b))
    .map((k) => collection[k]);
}

function num(v) {
  const n = parseFloat(v);
  return Number.isFinite(n) ? n : null;
}

function g(v) {
  return String(Math.round(v * 100) / 100);
}

export function line(stats, pos) {
  const bits = [];
  for (const [group, items] of LINE) {
    if ((group === "def") !== (pos === "DEF")) continue;
    for (const [id, label] of items) {
      const v = stats[id];
      if (v) bits.push(`${g(v)} ${label}`);
    }
  }
  return bits.join(", ");
}

/** scoreboard;week=N -> { team_key: { name, points, projected, win_probability } } */
export function parseScoreboard(raw) {
  const out = {};
  const league = raw?.fantasy_content?.league;
  if (!Array.isArray(league)) return out;
  let sb = null;
  for (const part of league) if (part && typeof part === "object" && "scoreboard" in part) sb = part.scoreboard;
  const matchups = sb?.["0"]?.matchups || {};
  for (const m of entries(matchups)) {
    const teams = m?.matchup?.["0"]?.teams || {};
    for (const t of entries(teams)) {
      const parts = t.team;
      if (!Array.isArray(parts)) continue;
      const meta = fold(parts[0]);
      const rest = fold(parts.slice(1));
      if (!meta.team_key) continue;
      out[meta.team_key] = {
        name: meta.name,
        points: num(rest.team_points?.total),
        projected: num(rest.team_projected_points?.total),
        win_probability: num(rest.win_probability),
      };
    }
  }
  return out;
}

/** team/<key>/roster;week=N/players/stats -> { player_id: { points, line } } */
export function parseRoster(raw) {
  const out = {};
  const team = raw?.fantasy_content?.team;
  if (!Array.isArray(team)) return out;
  let roster = null;
  for (const part of team) if (part && typeof part === "object" && "roster" in part) roster = part.roster;
  const players = roster?.["0"]?.players || roster?.players || {};
  for (const p of entries(players)) {
    const parts = p.player;
    if (!Array.isArray(parts)) continue;
    const meta = fold(parts[0]);
    const rest = fold(parts.slice(1));
    const stats = {};
    for (const s of rest.player_stats?.stats || []) {
      const v = num(s?.stat?.value);
      if (s?.stat?.stat_id != null && v) stats[String(s.stat.stat_id)] = v;
    }
    if (meta.player_id) {
      out[String(meta.player_id)] = {
        points: num(rest.player_points?.total),
        line: line(stats, meta.display_position),
      };
    }
  }
  return out;
}

export async function onRequestGet(context) {
  const week = new URL(context.request.url).searchParams.get("week") || "";
  if (!/^\d{1,2}$/.test(week)) return json({ ok: false, error: "bad params" }, 400);

  let teams;
  try {
    teams = parseScoreboard(await yahoo(`league/${LEAGUE}/scoreboard;week=${week}`));
  } catch (err) {
    return json({ ok: false, error: String(err) }, 502);
  }
  const keys = Object.keys(teams);
  const rosters = await Promise.allSettled(keys.map((key) =>
    yahoo(`team/${key}/roster;week=${week}/players/stats;type=week;week=${week}`)));
  rosters.forEach((r, i) => {
    teams[keys[i]].players = r.status === "fulfilled" ? parseRoster(r.value) : null;
  });
  return json({ ok: true, week: Number(week), fetched: new Date().toISOString(), teams });
}
