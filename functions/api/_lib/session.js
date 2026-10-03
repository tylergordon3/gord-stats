/**
 * Signed session cookies, and the cookie plumbing around them.
 *
 * A session is a JSON payload plus an HMAC of it, both base64url, joined by a
 * dot. That is a JWT in spirit without the library: there is exactly one
 * issuer and one audience here, so the header block a real JWT carries would
 * only be somewhere for an attacker to propose `alg: none`.
 *
 * Two kinds of token are signed with the one key: the session, and the OAuth
 * state stamp that carries a login across the trip to Google. Each says which
 * it is in a signed `typ`, and verify() is told which it wants - without that,
 * the state cookie any visitor can get from /api/auth/login was a validly
 * signed token that /api/me would read as someone signed in.
 *
 * A session is revocable although nothing about it is stored: it carries the
 * account's `session_epoch` (`ep`), and readSession accepts it only while the
 * account's row still holds that number. "Sign out everywhere" moves the
 * number on, which ends every session issued before; deleting the account
 * removes the row, which ends them all. Before this a session was good for
 * its whole 90 days whatever happened to the account, and a leaked cookie
 * could only be stopped by rotating SESSION_SECRET for everybody.
 *
 * Lives under _lib/ because Cloudflare Pages routes every file in functions/
 * except those whose path contains a segment starting with an underscore.
 */

const enc = new TextEncoder();

export const TYP = { session: "session", state: "oauth-state" };

function b64url(bytes) {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function unb64url(text) {
  const pad = text.replace(/-/g, "+").replace(/_/g, "/");
  const bin = atob(pad + "=".repeat((4 - (pad.length % 4)) % 4));
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}

async function key(secret) {
  return crypto.subtle.importKey(
    "raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" },
    false, ["sign", "verify"]);
}

/** `payload.signature`, both base64url, with `typ` signed into the payload. */
export async function sign(payload, secret, typ) {
  if (!Object.values(TYP).includes(typ)) throw new Error(`unknown token type: ${typ}`);
  const body = b64url(enc.encode(JSON.stringify({ ...payload, typ })));
  const mac = await crypto.subtle.sign("HMAC", await key(secret), enc.encode(body));
  return `${body}.${b64url(new Uint8Array(mac))}`;
}

/**
 * Whether a verified payload is the kind of token the caller asked for.
 *
 * Sessions signed before `typ` existed carry none, and they last SESSION_DAYS;
 * signing every reader out to close this would be a cost with nothing bought,
 * because such a token is still told apart by what it holds - a session has a
 * uid, and a state stamp never has. So an untyped token passes as a session
 * if it has a uid, and never as anything else. Once this has been live for
 * SESSION_DAYS, no untyped session is left unexpired and the branch can go.
 */
export function isType(payload, typ) {
  if (payload.typ !== undefined) return payload.typ === typ;
  return typ === TYP.session && typeof payload.uid === "string" && payload.uid !== "";
}

/**
 * The payload, or null for anything that fails: bad shape, bad signature,
 * expired, or the wrong kind of token. Verification goes through
 * crypto.subtle.verify rather than comparing two strings, so it cannot leak
 * the signature a byte at a time.
 */
export async function verify(token, secret, typ) {
  if (!Object.values(TYP).includes(typ)) return null;
  if (typeof token !== "string" || !token.includes(".")) return null;
  const [body, mac] = token.split(".", 2);
  if (!body || !mac) return null;
  try {
    const ok = await crypto.subtle.verify(
      "HMAC", await key(secret), unb64url(mac), enc.encode(body));
    if (!ok) return null;
    const payload = JSON.parse(new TextDecoder().decode(unb64url(body)));
    // An expiry the holder could edit is not an expiry, which is why it sits
    // inside the signed body rather than beside it in the cookie.
    if (!payload || typeof payload.exp !== "number") return null;
    if (payload.exp * 1000 < Date.now()) return null;
    return isType(payload, typ) ? payload : null;
  } catch {
    return null;
  }
}

/**
 * The request's cookies by name. One that will not decode is skipped rather
 * than thrown: decodeURIComponent throws on a stray '%', and a throw here
 * came out of every endpoint as a 500 for as long as that browser kept the
 * cookie - which need not be one this site set.
 */
export function cookies(request) {
  const out = {};
  const raw = request.headers.get("cookie") || "";
  for (const part of raw.split(";")) {
    const i = part.indexOf("=");
    if (i < 1) continue;
    try {
      out[part.slice(0, i).trim()] = decodeURIComponent(part.slice(i + 1).trim());
    } catch {
      // not ours to repair; as if it were not there
    }
  }
  return out;
}

/**
 * `Secure` and `HttpOnly` always: the cookie is never read by page script, and
 * the site is HTTPS-only. `SameSite=Lax` rather than Strict so that arriving
 * from Google's consent screen still carries it.
 */
export function setCookie(name, value, { maxAge, path = "/" } = {}) {
  const bits = [
    `${name}=${encodeURIComponent(value)}`,
    `Path=${path}`,
    "HttpOnly", "Secure", "SameSite=Lax",
  ];
  bits.push(`Max-Age=${maxAge ?? 0}`);
  return bits.join("; ");
}

/**
 * The session cookie's name. `__Host-` makes the browser refuse it unless it
 * is Secure, Path=/ and has no Domain - so no other host under gordstats.com
 * (and nothing on plain http, which HSTS does not cover for subdomains) can
 * plant one here to sign a reader into an account of its choosing.
 */
export const SESSION_COOKIE = "__Host-gs_session";
/**
 * The name sessions were issued under before the `__Host-` one (2026-10-02's
 * change). Still read, so the switch signed nobody out: /api/me - which every
 * page asks on load - moves a session found under this name to the new one,
 * and every response that ends a session clears both. A session lasts
 * SESSION_DAYS, so 90 days after the deploy that brought this in none is left
 * unmoved and unexpired: then delete this, its fallback in checkSession, and
 * the second cookie in sessionCookies/clearSessionCookies. Until then the
 * planted-cookie protection holds only for a browser that has the new one.
 */
export const LEGACY_SESSION_COOKIE = "gs_session";
export const SESSION_DAYS = 90;

/**
 * The account epoch a session was issued at. Sessions from before epochs
 * existed carry none and count as 0 - the epoch every account starts at - so
 * they stay good until the account's first "sign out everywhere". Anything
 * else that is not a whole number matches no account.
 */
export function epochOf(payload) {
  if (payload.ep === undefined) return 0;
  return Number.isSafeInteger(payload.ep) && payload.ep >= 0 ? payload.ep : -1;
}

/**
 * This request's session, checked against the account it names.
 * -> { session, stale, legacy, token }
 *
 *   session  the payload, with the account's `users` row as `user`; or null
 *   stale    a cookie that verifies but opens no account any more - signed
 *            out everywhere, or the account deleted. Worth clearing.
 *   legacy   it came under LEGACY_SESSION_COOKIE
 *
 * One primary-key read of `users`, and only when a cookie verifies: a reader
 * who is not signed in costs the database nothing. The whole row is read
 * (`SELECT *`) so that this works on every database the code can meet - a
 * column a migration has not added yet is simply absent - and so that the
 * endpoints can take what else they need from it (is_admin, the league
 * refresh stamp) instead of reading the row a second time.
 */
export async function checkSession(request, env) {
  const none = { session: null, stale: false, legacy: false, token: null };
  if (!env.SESSION_SECRET || !env.DB) return none;
  const jar = cookies(request);
  let legacy = false;
  let token = jar[SESSION_COOKIE];
  let payload = await verify(token, env.SESSION_SECRET, TYP.session);
  if (!payload && jar[LEGACY_SESSION_COOKIE] !== undefined) {
    legacy = true;
    token = jar[LEGACY_SESSION_COOKIE];
    payload = await verify(token, env.SESSION_SECRET, TYP.session);
  }
  if (!payload || typeof payload.uid !== "string" || !payload.uid) return none;

  const user = await env.DB.prepare("SELECT * FROM users WHERE id = ?").bind(payload.uid).first();
  if (!user || epochOf(payload) !== Number(user.session_epoch ?? 0)) {
    return { session: null, stale: true, legacy, token };
  }
  return { session: { ...payload, user }, stale: false, legacy, token };
}

/** The signed-in reader's session for this request, or null. See checkSession. */
export async function readSession(request, env) {
  return (await checkSession(request, env)).session;
}

/** Set-Cookie values that make `token` this browser's session. */
export function sessionCookies(token, maxAge) {
  return [setCookie(SESSION_COOKIE, token, { maxAge }),
          setCookie(LEGACY_SESSION_COOKIE, "", { maxAge: 0 })];
}

/** Set-Cookie values that end this browser's session, under either name. */
export function clearSessionCookies() {
  return [setCookie(SESSION_COOKIE, "", { maxAge: 0 }),
          setCookie(LEGACY_SESSION_COOKIE, "", { maxAge: 0 })];
}

/** `res` with each Set-Cookie value appended; a Headers object keeps them apart. */
export function withCookies(res, values) {
  for (const value of values) res.headers.append("set-cookie", value);
  return res;
}

/** Everything the account endpoints need before they can do anything. */
export function configured(env) {
  return Boolean(env.DB && env.SESSION_SECRET
                 && env.GOOGLE_CLIENT_ID && env.GOOGLE_CLIENT_SECRET);
}

export function json(body, status = 200, extra = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      // Never let an answer about one reader be served to the next.
      "cache-control": "no-store",
      ...extra,
    },
  });
}
