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
 *
 * This is the one read-only endpoint that checks a session against the
 * account (one primary-key read of `users`, only for a browser holding a
 * signed cookie - see _lib/session.js), and it has to: it is what every page
 * asks to decide whether to show a reader as signed in. Trusting the cookie
 * alone, a session ended by "sign out everywhere" or by deleting the account
 * would still read as signed in here while every save failed underneath.
 * Measured against D1's free tier, that is one row read per signed-in page
 * view out of five million a day.
 *
 * It is also where cookies are tidied, because every page calls it: a session
 * that no longer opens an account is cleared, so the browser stops presenting
 * it, and one still under the old cookie name is moved to the new one.
 */
import {
  checkSession, clearSessionCookies, configured, json, sessionCookies, withCookies,
} from "./_lib/session.js";

export async function onRequestGet({ request, env }) {
  if (!configured(env)) return json({ signedIn: false, configured: false });
  let found;
  try {
    found = await checkSession(request, env);
  } catch (err) {
    // The database did not answer. Not "signed out" - that would offer a
    // sign-in to someone who is. A 503: favorites.js reads any failed
    // /api/me as "no accounts here" for this view, and /profile/ as "could
    // not reach the server", which is what a failed /api/me already meant.
    console.error("me:", err);
    return json({ signedIn: false, configured: true, unavailable: true,
      error: "accounts are unavailable" }, 503);
  }
  if (!found.session) {
    const res = json({ signedIn: false, configured: true });
    return found.stale ? withCookies(res, clearSessionCookies()) : res;
  }
  const res = json({ signedIn: true, configured: true, email: found.session.email });
  if (found.legacy) {
    // The same token under the new name, for what is left of its life.
    const left = Math.max(1, found.session.exp - Math.floor(Date.now() / 1000));
    withCookies(res, sessionCookies(found.token, left));
  }
  return res;
}
