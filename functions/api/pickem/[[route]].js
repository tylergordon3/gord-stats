/**
 * /api/pickem/picks and /api/pickem/name - a reader's week and the name they
 * play under. Everything else about pick'em, and the logic of these two, is
 * in ../pickem.js; this file only routes.
 *
 * Should Pages ever hand this catch-all the bare /api/pickem as well, it
 * answers exactly as ../pickem.js does rather than with a 404.
 */
import { json } from "../_lib/session.js";
import { onRequestGet as view, saveName, savePicks } from "../pickem.js";

function parts(context) {
  const route = context.params?.route;
  return (Array.isArray(route) ? route : route ? [route] : []).filter(Boolean);
}

export async function onRequestGet(context) {
  if (!parts(context).length) return view(context);
  return json({ ok: false, error: "not found" }, 404);
}

export async function onRequestPost(context) {
  const route = parts(context);
  if (route.length === 1 && route[0] === "picks") return savePicks(context);
  if (route.length === 1 && route[0] === "name") return saveName(context);
  return json({ ok: false, error: "not found" }, 404);
}
