/**
 * /api/tweets/<id>/vote and /api/tweets/<id>/review - the two calls on one
 * post. Everything else about Tweets of the week, and the logic of these two,
 * is in ../tweets.js; this file only routes.
 *
 * `<id>` is this site's own number for the post (tweets.id), not X's.
 *
 * Should Pages ever hand this catch-all the bare /api/tweets as well, it
 * answers exactly as ../tweets.js does rather than with a 404.
 */
import { json } from "../_lib/session.js";
import {
  onRequestGet as list, onRequestPost as submit, review, vote,
} from "../tweets.js";

function parts(context) {
  const route = context.params?.route;
  return (Array.isArray(route) ? route : route ? [route] : []).filter(Boolean);
}

export async function onRequestGet(context) {
  if (!parts(context).length) return list(context);
  return json({ ok: false, error: "not found" }, 404);
}

export async function onRequestPost(context) {
  const route = parts(context);
  if (!route.length) return submit(context);
  if (route.length === 2 && /^[1-9][0-9]{0,11}$/.test(route[0])) {
    const id = Number(route[0]);
    if (route[1] === "vote") return vote(context, id);
    if (route[1] === "review") return review(context, id);
  }
  return json({ ok: false, error: "not found" }, 404);
}
