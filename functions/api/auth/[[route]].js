/**
 * Sign in with Google, so a reader's starred teams follow them between devices.
 *
 *   GET /api/auth/login?next=/cfb/power/   -> Google's consent screen
 *   GET /api/auth/callback?code=&state=    -> sets the session, returns to `next`
 *   GET /api/auth/logout?next=/            -> clears it
 *
 * Authorization-code flow with a client secret. The one thing worth explaining
 * is what this deliberately does *not* do: it never verifies the ID token's
 * signature against Google's JWKS. That check exists for tokens handed to you
 * by a third party, and this one is not - it comes straight back from a POST
 * this Function made to oauth2.googleapis.com over TLS. Google's own guidance
 * says the signature may be skipped in exactly this case. The claims that
 * still matter (`aud`, `iss`, `exp`) are checked, because a right answer from
 * the wrong client is still the wrong answer.
 *
 * Every endpoint is inert until GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and
 * SESSION_SECRET exist as Pages environment variables and DB is bound, so
 * deploying this before any of that is configured changes nothing on the site.
 */
import {
  SESSION_COOKIE, SESSION_DAYS, cookies, configured, json,
  setCookie, sign, verify,
} from "../_lib/session.js";

const AUTH = "https://accounts.google.com/o/oauth2/v2/auth";
const TOKEN = "https://oauth2.googleapis.com/token";
const ISSUERS = new Set(["accounts.google.com", "https://accounts.google.com"]);
const STATE_COOKIE = "gs_oauth";
const STATE_MINUTES = 10;
const TIMEOUT_MS = 8000;

export async function onRequestGet(context) {
  const { request, env } = context;
  const url = new URL(request.url);
  const route = (context.params.route || []).join("/");

  if (!configured(env)) {
    return json({ ok: false, error: "accounts are not configured" }, 503);
  }

  if (route === "login") return login(url, env);
  if (route === "callback") return callback(request, url, env);
  if (route === "logout") return logout(url);
  return json({ ok: false, error: "not found" }, 404);
}

/**
 * Only same-site paths: `next` comes from the query string, so it is untrusted.
 * Resolved the way a browser resolves the Location header it ends up in, and
 * kept only if it lands on this origin. A pattern on the raw string let
 * "/\evil.com" through - browsers read the backslash as a slash - so
 * /api/auth/logout?next=/%5Cevil.com signed a reader out onto another site.
 */
function safeNext(raw, origin) {
  try {
    const to = new URL(raw || "/", origin);
    if (to.origin === origin) return to.pathname + to.search + to.hash;
  } catch (e) {
    // not a URL at all
  }
  return "/";
}

function redirectUri(url) {
  return `${url.origin}/api/auth/callback`;
}

async function login(url, env) {
  const state = crypto.randomUUID();
  const next = safeNext(url.searchParams.get("next"), url.origin);

  // State is carried in a signed cookie, not in a store: it only has to
  // survive the round trip to Google, and this way the CSRF check needs no
  // database and cannot be defeated by editing the cookie.
  const stamp = await sign(
    { state, next, exp: Math.floor(Date.now() / 1000) + STATE_MINUTES * 60 },
    env.SESSION_SECRET);

  const to = new URL(AUTH);
  to.searchParams.set("client_id", env.GOOGLE_CLIENT_ID);
  to.searchParams.set("redirect_uri", redirectUri(url));
  to.searchParams.set("response_type", "code");
  to.searchParams.set("scope", "openid email");
  to.searchParams.set("state", state);
  // Nothing here needs offline access, so no refresh token is ever issued.
  to.searchParams.set("prompt", "select_account");

  return new Response(null, {
    status: 302,
    headers: {
      location: to.toString(),
      "set-cookie": setCookie(STATE_COOKIE, stamp, { maxAge: STATE_MINUTES * 60 }),
      "cache-control": "no-store",
    },
  });
}

async function callback(request, url, env) {
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  const stamp = await verify(cookies(request)[STATE_COOKIE], env.SESSION_SECRET);

  // A callback without the cookie this Function set is not a login this
  // Function started.
  if (!code || !state || !stamp || stamp.state !== state) {
    return fail(url, "sign-in expired or was interrupted; try again");
  }

  let claims;
  try {
    claims = await exchange(code, url, env);
  } catch (err) {
    console.error("auth callback:", err);
    return fail(url, "could not complete sign-in with Google");
  }

  if (!ISSUERS.has(claims.iss) || claims.aud !== env.GOOGLE_CLIENT_ID) {
    return fail(url, "sign-in did not verify");
  }
  if (!claims.sub || !claims.email) {
    return fail(url, "Google did not return an email address");
  }

  const user = await upsert(env.DB, claims);
  const session = await sign({
    uid: user.id,
    email: claims.email,
    exp: Math.floor(Date.now() / 1000) + SESSION_DAYS * 86400,
  }, env.SESSION_SECRET);

  const headers = new Headers({ location: safeNext(stamp.next, url.origin), "cache-control": "no-store" });
  headers.append("set-cookie",
    setCookie(SESSION_COOKIE, session, { maxAge: SESSION_DAYS * 86400 }));
  headers.append("set-cookie", setCookie(STATE_COOKIE, "", { maxAge: 0 }));
  return new Response(null, { status: 302, headers });
}

async function exchange(code, url, env) {
  const res = await fetch(TOKEN, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      code,
      client_id: env.GOOGLE_CLIENT_ID,
      client_secret: env.GOOGLE_CLIENT_SECRET,
      redirect_uri: redirectUri(url),
      grant_type: "authorization_code",
    }),
    signal: AbortSignal.timeout(TIMEOUT_MS),
  });
  if (!res.ok) throw new Error(`token endpoint -> ${res.status}`);
  const body = await res.json();
  if (!body.id_token) throw new Error("no id_token in token response");
  return claimsOf(body.id_token);
}

/** The payload of a JWT we just fetched ourselves; see the note at the top. */
function claimsOf(idToken) {
  const part = idToken.split(".")[1];
  if (!part) throw new Error("malformed id_token");
  const pad = part.replace(/-/g, "+").replace(/_/g, "/");
  const bin = atob(pad + "=".repeat((4 - (pad.length % 4)) % 4));
  return JSON.parse(new TextDecoder().decode(
    Uint8Array.from(bin, (c) => c.charCodeAt(0))));
}

/**
 * One row per Google subject. A returning reader keeps their id - and so their
 * favourites - even if the address on the account has changed.
 */
async function upsert(db, claims) {
  const now = new Date().toISOString();
  const found = await db.prepare("SELECT id FROM users WHERE provider_sub = ?")
    .bind(claims.sub).first();

  if (found) {
    await db.prepare("UPDATE users SET email = ?, last_seen_at = ? WHERE id = ?")
      .bind(claims.email, now, found.id).run();
    return { id: found.id };
  }

  const id = crypto.randomUUID();
  await db.prepare(
    "INSERT INTO users (id, email, provider_sub, created_at, last_seen_at) "
    + "VALUES (?, ?, ?, ?, ?)")
    .bind(id, claims.email, claims.sub, now, now).run();
  return { id };
}

function logout(url) {
  return new Response(null, {
    status: 302,
    headers: {
      location: safeNext(url.searchParams.get("next"), url.origin),
      "set-cookie": setCookie(SESSION_COOKIE, "", { maxAge: 0 }),
      "cache-control": "no-store",
    },
  });
}

/** Back to the page they came from, with something the UI can show. */
function fail(url, message) {
  const to = new URL(safeNext(url.searchParams.get("next"), url.origin), url.origin);
  to.searchParams.set("signin", "failed");
  to.searchParams.set("why", message);
  const headers = new Headers({ location: to.toString(), "cache-control": "no-store" });
  headers.append("set-cookie", setCookie(STATE_COOKIE, "", { maxAge: 0 }));
  return new Response(null, { status: 302, headers });
}
