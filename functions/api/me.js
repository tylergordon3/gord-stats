/**
 * GET /api/me -> who is signed in, if anyone.
 *
 *   { signedIn: false, configured: false }   accounts not set up on this deploy
 *   { signedIn: false, configured: true }    set up, nobody signed in
 *   { signedIn: true, email: "..." }         signed in
 *
 * `configured` is what lets the page decide whether to offer a sign-in control
 * at all. Before the Pages environment variables and the D1 binding exist the
 * site should look exactly as it does today, and a control that leads to a 503
 * is worse than no control.
 */
import { configured, json, readSession } from "./_lib/session.js";

export async function onRequestGet({ request, env }) {
  if (!configured(env)) return json({ signedIn: false, configured: false });
  const session = await readSession(request, env);
  if (!session) return json({ signedIn: false, configured: true });
  return json({ signedIn: true, configured: true, email: session.email });
}
