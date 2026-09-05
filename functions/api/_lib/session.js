/**
 * Signed session cookies, and the cookie plumbing around them.
 *
 * A session is a JSON payload plus an HMAC of it, both base64url, joined by a
 * dot. That is a JWT in spirit without the library: there is exactly one
 * issuer and one audience here, so the header block a real JWT carries would
 * only be somewhere for an attacker to propose `alg: none`.
 *
 * Lives under _lib/ because Cloudflare Pages routes every file in functions/
 * except those whose path contains a segment starting with an underscore.
 */

const enc = new TextEncoder();

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

/** `payload.signature`, both base64url. */
export async function sign(payload, secret) {
  const body = b64url(enc.encode(JSON.stringify(payload)));
  const mac = await crypto.subtle.sign("HMAC", await key(secret), enc.encode(body));
  return `${body}.${b64url(new Uint8Array(mac))}`;
}

/**
 * The payload, or null for anything that fails: bad shape, bad signature, or
 * expired. Verification goes through crypto.subtle.verify rather than
 * comparing two strings, so it cannot leak the signature a byte at a time.
 */
export async function verify(token, secret) {
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
    return payload;
  } catch {
    return null;
  }
}

export function cookies(request) {
  const out = {};
  const raw = request.headers.get("cookie") || "";
  for (const part of raw.split(";")) {
    const i = part.indexOf("=");
    if (i < 1) continue;
    out[part.slice(0, i).trim()] = decodeURIComponent(part.slice(i + 1).trim());
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

export const SESSION_COOKIE = "gs_session";
export const SESSION_DAYS = 90;

/** The signed-in user's payload for this request, or null. */
export async function readSession(request, env) {
  if (!env.SESSION_SECRET) return null;
  return verify(cookies(request)[SESSION_COOKIE], env.SESSION_SECRET);
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
