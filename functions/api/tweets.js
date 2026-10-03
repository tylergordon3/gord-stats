/**
 * Tweets of the week: funny college football and NFL posts from X, sent in by
 * readers, approved by the site's owner, voted up by readers.
 *
 *   GET  /api/tweets                         -> the week's approved posts, most votes first
 *   GET  /api/tweets?status=pending          -> the review queue (owner only; also
 *                                               approved | rejected)
 *   POST /api/tweets  <- { url, sport? }     send one in (signed in); the owner's
 *                                            own go straight on the list
 *   POST /api/tweets/<id>/vote               toggle this reader's vote (tweets/[[route]].js)
 *   POST /api/tweets/<id>/review <- { action: approve | reject | remove, sport? }
 *                                            owner only (tweets/[[route]].js)
 *
 * Nothing here reads X's API. A submission is looked up once, through X's
 * free and keyless oEmbed endpoint, at a fixed address with only the post's
 * number in it - the reader's own link is parsed, never fetched, so it cannot
 * point this Function anywhere else. What comes back is kept as plain text
 * (author, handle, the words, whether there is a photo or video) and the cards
 * are drawn from that; the post itself is embedded only when a reader taps one.
 *
 * "This week" is the last seven days by when a post was approved. A thin week
 * is filled out with the best-voted posts of earlier weeks, marked as such.
 *
 * Costs, kept small on purpose. The public list is the same for everyone who
 * is signed out, so it is shared through the Workers cache for a minute; a
 * signed-in reader's carries their own votes and is never cached. A
 * submission is a row; five a day an account, counted inside the INSERT so
 * that parallel requests cannot pass it. A vote is a row, and is taken from
 * the per-account daily allowance in _lib/limits.js like every other write -
 * and from the site's daily ceiling there, over which both are a 503.
 * The owner is whoever has users.is_admin = 1, read from the database on each
 * request - from the account row readSession reads to check the session,
 * never from the signed token, which a sign-in issued before the flag was set
 * would still carry.
 */
import { configured, json, readSession } from "./_lib/session.js";
import { refusal, secondsToMidnight, spend, utcDay } from "./_lib/limits.js";
import { cached } from "./_lib/cache.js";

export const WEEK_DAYS = 7;
// Fewer than this many posts this week and earlier weeks' best fill it out.
export const FILL_TO = 6;
// The most one list carries: Home shows a row, /tweets/ the lot.
export const MAX_LIST = 40;
export const DAILY_SUBMISSIONS = 5;
// The owner's own need no review and no reader's cap; this only stops a
// stuck script. The per-account write allowance in _lib/limits.js still applies.
export const OWNER_SUBMISSIONS = 100;
const QUEUE_MAX = 100;
const CACHE_SECONDS = 60;
const MAX_TEXT = 400;
const MAX_AUTHOR = 80;
const TIMEOUT_MS = 8000;
// publish.twitter.com answers 301 to this address (checked 2026-10-02), so it
// is asked directly: one call to X, not two. The answer's author_url is
// x.com's, its photo links still pic.twitter.com.
const OEMBED = "https://publish.x.com/oembed";
const SPORTS = new Set(["cfb", "nfl"]);
const STATUSES = new Set(["pending", "approved", "rejected"]);
const HOSTS = new Set(["x.com", "www.x.com", "mobile.x.com",
  "twitter.com", "www.twitter.com", "mobile.twitter.com"]);
// /<handle>/status/<id>, /i/status/<id>, /i/web/status/<id>, with anything
// after the id (/photo/1, /video/1). X's handles are 1-15 word characters
// and its ids have no leading zero.
const STATUS_PATH =
  /^\/(i\/web|[A-Za-z0-9_]{1,15})\/status(?:es)?\/([1-9][0-9]{0,19})(?:\/.*)?$/;
const HANDLE = /^[A-Za-z0-9_]{1,15}$/;
const ID = /^[1-9][0-9]{0,19}$/;

/**
 * The post a pasted link points at -> { id, handle } | null.
 *
 * Only an https link to x.com or twitter.com (www. and mobile. too) whose
 * path is a post. A link pasted without its scheme is read as https; any
 * other scheme, a user:password@, a port, or a host that merely contains one
 * of those names is refused. The id stays a string: it is past 2^53, and a
 * Number would round it to a different post.
 */
export function tweetId(raw) {
  let text = String(raw ?? "").trim();
  if (!text || text.length > 500) return null;
  if (!/^[a-z][a-z0-9+.-]*:/i.test(text)) text = `https://${text.replace(/^\/+/, "")}`;
  let url;
  try {
    url = new URL(text);
  } catch {
    return null;
  }
  if (url.protocol !== "https:" || url.username || url.password || url.port) return null;
  if (!HOSTS.has(url.hostname.toLowerCase())) return null;
  const m = STATUS_PATH.exec(url.pathname);
  if (!m) return null;
  const handle = m[1].startsWith("i/") || m[1] === "i" ? null : m[1];
  return { id: m[2], handle };
}

// The entities an oEmbed blockquote carries. Anything else numeric is decoded
// by number; an unknown name is left as written.
const NAMED = {
  amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " ", mdash: "—",
  ndash: "–", hellip: "…", lsquo: "‘", rsquo: "’",
  ldquo: "“", rdquo: "”", middot: "·", bull: "•",
};

/** HTML entities to characters, in one pass: "&amp;lt;" is "&lt;", as written. */
export function decode(text) {
  return String(text).replace(/&(#[xX][0-9a-fA-F]{1,6}|#[0-9]{1,7}|[A-Za-z]{2,8});/g,
    (all, e) => {
      if (e[0] === "#") {
        const n = e[1] === "x" || e[1] === "X" ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10);
        const ok = n > 0 && n <= 0x10ffff && !(n >= 0xd800 && n <= 0xdfff);
        return ok ? String.fromCodePoint(n) : "�";
      }
      return NAMED[e] ?? NAMED[e.toLowerCase()] ?? all;
    });
}

// Control characters and the bidi overrides, which would let a post's text
// reorder the card it sits in.
const UNPRINTABLE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f‪-‮⁦-⁩]/g;

function clip(text, max) {
  const chars = Array.from(text);        // by code point: never half an emoji
  return chars.length <= max ? text : `${chars.slice(0, max - 1).join("").trimEnd()}…`;
}

/** Markup to plain text: tags out first, then entities, so "&lt;b&gt;" stays words. */
function plain(html) {
  return decode(String(html).replace(/<br\s*\/?>/gi, "\n").replace(/<[^>]*>/g, ""))
    .replace(UNPRINTABLE, "")
    .replace(/[ \t ]+/g, " ")
    .replace(/ ?\n ?/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

/**
 * What a card needs, from oEmbed's answer -> { handle, author, text, has_media }.
 *
 * The words are the blockquote's first <p>, as plain text. A photo or video
 * shows up there only as a pic.twitter.com (or pic.x.com) link, which does
 * not say which it is - so 1 is "a photo or video" and 2 is kept for a link
 * that names a video outright. The pic link itself comes out of the text: the
 * card says "media" in its own badge.
 */
export function fromOembed(data) {
  const html = String(data?.html || "");
  const author = clip(String(data?.author_name || "").replace(UNPRINTABLE, "").trim(),
    MAX_AUTHOR) || null;
  const from = /^https:\/\/(?:www\.|mobile\.)?(?:twitter|x)\.com\/([^/?#]+)\/?$/i
    .exec(String(data?.author_url || ""));
  const handle = from && HANDLE.test(from[1]) ? from[1] : null;
  const p = /<p\b[^>]*>([\s\S]*?)<\/p>/i.exec(html);
  const words = p ? plain(p[1]) : "";
  const video = /\/video\/\d/i.test(html);
  const pic = /\bpic\.(?:twitter|x)\.com\/\w+/i.test(html);
  const text = words.replace(/\s*\bpic\.(?:twitter|x)\.com\/\w+/gi, "").trim();
  return { handle, author, text: clip(text, MAX_TEXT), has_media: video ? 2 : pic ? 1 : 0 };
}

/** The link a card opens. Built from checked parts, never from stored text. */
export function postUrl(tweetId, handle) {
  if (!ID.test(String(tweetId))) return null;
  return `https://x.com/${HANDLE.test(handle || "") ? handle : "i"}/status/${tweetId}`;
}

function shape(row, earlier = false) {
  const out = {
    id: row.id, tweet_id: String(row.tweet_id), url: postUrl(row.tweet_id, row.handle),
    handle: row.handle || null, author: row.author || null, text: row.text || "",
    has_media: Number(row.has_media) || 0, sport: SPORTS.has(row.sport) ? row.sport : null,
    votes: Number(row.votes) || 0, mine: Boolean(row.mine),
  };
  if (earlier) out.earlier = true;
  return out;
}

/**
 * The tables arrive in a migration applied by hand, which can lag the deploy.
 * Until then "no such table" would be a 500 on every Home view; it is an
 * answer instead. A session whose account has since been deleted fails the
 * foreign key on any write, which is "signed out", not a server error.
 */
class Migrating extends Error {}
class SignedOut extends Error {}

async function db(run) {
  try {
    return await run();
  } catch (err) {
    const text = String(err && err.message || err);
    if (text.includes("no such table")) throw new Migrating(text);
    if (text.includes("FOREIGN KEY constraint failed")) throw new SignedOut(text);
    throw err;
  }
}

function answerFor(err) {
  if (err instanceof Migrating) {
    return json({ ok: false, migrating: true,
      error: "Tweets of the week is not switched on for this site yet." }, 503);
  }
  if (err instanceof SignedOut) return json({ ok: false, error: "Sign in again to do that." }, 401);
  throw err;
}

async function guard(request, env) {
  if (!configured(env)) return json({ ok: false, error: "accounts are not configured" }, 503);
  const session = await readSession(request, env);
  if (!session) return json({ ok: false, signedIn: false, error: "Sign in to do that." }, 401);
  return session;
}

/**
 * Whether a session's account is the owner, from the row readSession read
 * for it this request. A database before 005 has no is_admin, so no owner.
 */
export function isAdmin(session) {
  return Number(session?.user?.is_admin) === 1;
}

async function owner(request, env) {
  const session = await guard(request, env);
  if (session instanceof Response) return session;
  if (!isAdmin(session)) {
    return json({ ok: false, error: "Only the site's owner can review posts." }, 403);
  }
  return session;
}

// Votes counted per post through tweet_votes' primary key (it leads with the
// post); `mine` is one more lookup on the same key. ?2 is NULL signed out,
// which matches nobody.
const LIST = (where) =>
  `SELECT t.id, t.tweet_id, t.handle, t.author, t.text, t.has_media, t.sport,
          (SELECT COUNT(*) FROM tweet_votes v WHERE v.tweet_id = t.id) AS votes,
          EXISTS (SELECT 1 FROM tweet_votes v
                   WHERE v.tweet_id = t.id AND v.user_id = ?2) AS mine
     FROM tweets t
    WHERE t.status = 'approved' AND ${where}
    ORDER BY votes DESC, t.reviewed_at DESC, t.id DESC
    LIMIT ?3`;
const THIS_WEEK = LIST("t.reviewed_at >= ?1");
const EARLIER = LIST("t.reviewed_at < ?1");

/** -> { tweets, week } : this week's posts, then earlier weeks' best to fill out a thin one. */
export async function listing(DB, uid, now = new Date()) {
  const cutoff = new Date(now.getTime() - WEEK_DAYS * 86400e3).toISOString();
  const week = (await db(() => DB.prepare(THIS_WEEK).bind(cutoff, uid, MAX_LIST).all())).results || [];
  let earlier = [];
  if (week.length < FILL_TO) {
    earlier = (await db(() => DB.prepare(EARLIER)
      .bind(cutoff, uid, FILL_TO - week.length).all())).results || [];
  }
  return {
    tweets: [...week.map((r) => shape(r)), ...earlier.map((r) => shape(r, true))],
    week: week.length,
  };
}

export async function onRequestGet(context) {
  const { request, env } = context;
  const url = new URL(request.url);
  if (url.searchParams.has("status")) return queue(request, env, url.searchParams.get("status"));

  // Public: answers 200 whatever the state of the deploy, because Home asks
  // on every view and a red console line for each reader is the wrong price
  // for "not switched on yet".
  if (!env.DB) return json({ ok: true, configured: false, signedIn: false, tweets: [], week: 0 });
  const session = configured(env) ? await readSession(request, env) : null;

  if (!session) {
    const key = `${url.origin}/api/tweets?public=1`;
    const out = await cached(context, key, CACHE_SECONDS, async () => {
      let body;
      try {
        body = { ok: true, configured: configured(env), signedIn: false,
                 ...(await listing(env.DB, null)) };
      } catch (err) {
        if (!(err instanceof Migrating)) throw err;
        body = { ok: true, configured: configured(env), signedIn: false, migrating: true,
                 tweets: [], week: 0 };
      }
      return { status: 200, body: JSON.stringify(body) };
    });
    return new Response(out.body, {
      status: out.status,
      headers: {
        "content-type": "application/json; charset=utf-8",
        "cache-control": `public, max-age=${CACHE_SECONDS}`,
        // Signing in changes the answer (your own votes), so a browser must
        // not hand a signed-in page the copy it kept from before.
        vary: "cookie",
      },
    });
  }

  const admin = isAdmin(session);
  let got;
  try {
    got = await listing(env.DB, session.uid);
    // The owner's card points at the queue when readers have sent posts in:
    // the review list is at the foot of /profile/, which nothing else leads to.
    if (admin) {
      const waiting = await db(() => env.DB.prepare(
        "SELECT COUNT(*) AS n FROM tweets WHERE status = 'pending'").first());
      got.pending = Number(waiting?.n || 0);
    }
  } catch (err) {
    if (!(err instanceof Migrating)) throw err;
    got = { tweets: [], week: 0, migrating: true };
  }
  return json({ ok: true, configured: true, signedIn: true, admin, ...got });
}

const QUEUE = (order) =>
  `SELECT t.id, t.tweet_id, t.handle, t.author, t.text, t.has_media, t.sport, t.status,
          t.submitted_at, t.reviewed_at, u.email AS submitter,
          (SELECT COUNT(*) FROM tweet_votes v WHERE v.tweet_id = t.id) AS votes
     FROM tweets t LEFT JOIN users u ON u.id = t.submitted_by
    WHERE t.status = ?1
    ORDER BY ${order}
    LIMIT ?2`;
const ORDER = { pending: "t.submitted_at ASC, t.id ASC",
                approved: "t.reviewed_at DESC, t.id DESC",
                rejected: "t.reviewed_at DESC, t.id DESC" };

async function queue(request, env, status) {
  if (!STATUSES.has(status)) return json({ ok: false, error: "unknown status" }, 400);
  const who = await owner(request, env);
  if (who instanceof Response) return who;
  try {
    const { results } = await db(() => env.DB.prepare(QUEUE(ORDER[status]))
      .bind(status, QUEUE_MAX).all());
    return json({ ok: true, status, tweets: (results || []).map((r) => ({
      ...shape(r), status: r.status, submitted_at: r.submitted_at,
      reviewed_at: r.reviewed_at || null, submitter: r.submitter || null })) });
  } catch (err) {
    return answerFor(err);
  }
}

const SAID = {
  approved: "Already picked - it's on the list. Give it a vote.",
  pending: "Already sent in - it's waiting for review.",
  rejected: "That one has already been looked at and passed over.",
};

function duplicate(status) {
  return json({ ok: false, duplicate: true, status, error: SAID[status] || SAID.pending }, 409);
}

function tooMany(now, cap = DAILY_SUBMISSIONS) {
  const wait = secondsToMidnight(now);
  return json({ ok: false, error: `That's ${cap} for today - thanks! Send more tomorrow.`,
    retry_after: wait }, 429, { "retry-after": String(wait) });
}

// The day's count is inside the INSERT: of any number of submissions racing,
// only those that still fit go in. ON CONFLICT covers two readers sending the
// same post at once - the second is told it is already waiting. The owner's
// go in approved, stamped now: the owner is the one who would approve them,
// and a post waiting on its own sender's review is a post nobody ever sees.
const INSERT =
  `INSERT INTO tweets (tweet_id, handle, author, text, has_media, sport,
                       submitted_by, submitted_at, status, reviewed_at)
   SELECT ?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?11, ?12
    WHERE (SELECT COUNT(*) FROM tweets WHERE submitted_by = ?7 AND submitted_at >= ?9) < ?10
   ON CONFLICT (tweet_id) DO NOTHING`;
const TODAY = "SELECT COUNT(*) AS n FROM tweets WHERE submitted_by = ? AND submitted_at >= ?";
const SEEN = "SELECT status FROM tweets WHERE tweet_id = ?";
// The same, and whether the session's account still exists. readSession has
// already turned away a cookie whose account is gone; this catches one
// deleted in the moment since, which spend() would read as "allowance used
// up".
const SEEN_BY =
  `SELECT (SELECT status FROM tweets WHERE tweet_id = ?1) AS status,
          EXISTS (SELECT 1 FROM users WHERE id = ?2) AS known`;

/** X's own card for a post, by number only. -> { ok, data } | { ok: false, gone } */
async function oembed(id) {
  const post = `https://twitter.com/i/status/${id}`;
  const url = `${OEMBED}?url=${encodeURIComponent(post)}&omit_script=1&dnt=true`;
  let res;
  try {
    res = await fetch(url, { headers: { accept: "application/json" },
                             signal: AbortSignal.timeout(TIMEOUT_MS) });
  } catch {
    return { ok: false, gone: false };
  }
  // 404 deleted or never was; 403 protected or suspended.
  if ([400, 403, 404, 410].includes(res.status)) return { ok: false, gone: true };
  if (!res.ok) return { ok: false, gone: false };
  try {
    const data = await res.json();
    return data && typeof data === "object" ? { ok: true, data } : { ok: false, gone: false };
  } catch {
    return { ok: false, gone: false };
  }
}

export async function onRequestPost({ request, env }) {
  const session = await guard(request, env);
  if (session instanceof Response) return session;

  let body;
  try {
    body = await request.json();
  } catch {
    return json({ ok: false, error: "expected JSON" }, 400);
  }
  const post = tweetId(body?.url);
  if (!post) {
    return json({ ok: false, error: "That isn't a link to a post. Copy it from X with Share "
      + "→ Copy link: it looks like x.com/name/status/123…" }, 400);
  }
  const sport = SPORTS.has(String(body?.sport || "").toLowerCase())
    ? String(body.sport).toLowerCase() : null;

  const now = new Date();
  const dayStart = `${utcDay(now)}T00:00:00.000Z`;
  const admin = isAdmin(session);
  const cap = admin ? OWNER_SUBMISSIONS : DAILY_SUBMISSIONS;
  const status = admin ? "approved" : "pending";
  try {
    // Every refusal that costs nothing comes before anything that costs: a
    // post already here, or a reader already at today's five, never reaches X.
    const seen = await db(() => env.DB.prepare(SEEN_BY).bind(post.id, session.uid).first());
    if (!seen?.known) return json({ ok: false, error: "Sign in again to do that." }, 401);
    if (seen.status) return duplicate(seen.status);
    const today = await db(() => env.DB.prepare(TODAY).bind(session.uid, dayStart).first());
    if (Number(today?.n || 0) >= cap) return tooMany(now, cap);

    // Taken before asking X, so that the allowance also bounds how often one
    // account can make this Function call out - deleted posts included.
    const allowed = await spend(env.DB, session.uid, 1, now);
    if (!allowed.ok) return refusal(allowed, "Too many changes today - try again tomorrow.");

    const card = await oembed(post.id);
    if (!card.ok) {
      return card.gone
        ? json({ ok: false, error: "X says that post is deleted, protected or not public. "
            + "Only public posts can go in." }, 422)
        : json({ ok: false, error: "Couldn't reach X just now. Try again in a minute." }, 502);
    }
    const t = fromOembed(card.data);

    const stamp = now.toISOString();
    const put = await db(() => env.DB.prepare(INSERT).bind(
      post.id, t.handle, t.author, t.text, t.has_media, sport, session.uid,
      stamp, dayStart, cap, status, admin ? stamp : null).run());
    if (put?.meta?.changes) {
      return json({ ok: true, status,
        message: admin
          ? "Posted - it's on the list now."
          : "Thanks - it's in the queue. Once it's picked, it shows up here for everyone to vote on.",
        tweet: { tweet_id: post.id, handle: t.handle, author: t.author, text: t.text,
                 has_media: t.has_media, sport } }, 201);
    }
    // Nothing went in: the same post arrived a moment ago, or today's five
    // filled up in parallel.
    const again = await db(() => env.DB.prepare(SEEN).bind(post.id).first());
    return again ? duplicate(again.status) : tooMany(now, cap);
  } catch (err) {
    return answerFor(err);
  }
}

/** POST /api/tweets/<id>/vote: one vote a reader a post, on or off. */
export async function vote({ request, env }, id) {
  const session = await guard(request, env);
  if (session instanceof Response) return session;
  try {
    const row = await db(() => env.DB.prepare(
      `SELECT (SELECT status FROM tweets WHERE id = ?1) AS status,
              EXISTS (SELECT 1 FROM users WHERE id = ?2) AS known`).bind(id, session.uid).first());
    if (!row?.known) return json({ ok: false, error: "Sign in again to do that." }, 401);
    if (row.status !== "approved") {
      return json({ ok: false, error: "That post isn't up for votes." }, 404);
    }
    const allowed = await spend(env.DB, session.uid, 1);
    if (!allowed.ok) {
      return refusal(allowed, "That's a lot of votes for one day - try again tomorrow.");
    }
    // Off if it was on, else on: one statement each way, and the delete's
    // own count says which way this went.
    const off = await db(() => env.DB.prepare(
      "DELETE FROM tweet_votes WHERE tweet_id = ? AND user_id = ?").bind(id, session.uid).run());
    let mine = false;
    if (!off?.meta?.changes) {
      await db(() => env.DB.prepare(
        `INSERT INTO tweet_votes (tweet_id, user_id) VALUES (?, ?)
         ON CONFLICT (tweet_id, user_id) DO NOTHING`).bind(id, session.uid).run());
      mine = true;
    }
    const n = await db(() => env.DB.prepare(
      "SELECT COUNT(*) AS n FROM tweet_votes WHERE tweet_id = ?").bind(id).first());
    return json({ ok: true, id, votes: Number(n?.n || 0), mine });
  } catch (err) {
    return answerFor(err);
  }
}

const ACTIONS = { approve: "approved", reject: "rejected", remove: "rejected" };

/**
 * POST /api/tweets/<id>/review: the owner's call. Approving stamps the time,
 * which is when its week starts - unless it was approved already, so a second
 * click does not give a post a second week. A sport sent with it is set too.
 */
export async function review({ request, env }, id) {
  const who = await owner(request, env);
  if (who instanceof Response) return who;
  let body;
  try {
    body = await request.json();
  } catch {
    return json({ ok: false, error: "expected JSON" }, 400);
  }
  const status = ACTIONS[String(body?.action || "")];
  if (!status) return json({ ok: false, error: "action is approve, reject or remove" }, 400);
  const setSport = body && Object.prototype.hasOwnProperty.call(body, "sport");
  const sport = setSport && SPORTS.has(String(body.sport || "").toLowerCase())
    ? String(body.sport).toLowerCase() : null;
  const now = new Date().toISOString();
  try {
    const done = await db(() => env.DB.prepare(
      `UPDATE tweets
          SET reviewed_at = CASE WHEN status = ?1 AND reviewed_at IS NOT NULL
                                 THEN reviewed_at ELSE ?2 END,
              status = ?1,
              sport = CASE WHEN ?3 THEN ?4 ELSE sport END
        WHERE id = ?5`).bind(status, now, setSport ? 1 : 0, sport, id).run());
    if (!done?.meta?.changes) return json({ ok: false, error: "no such post" }, 404);
    const row = await db(() => env.DB.prepare(
      "SELECT status, reviewed_at, sport FROM tweets WHERE id = ?").bind(id).first());
    return json({ ok: true, id, status: row.status, reviewed_at: row.reviewed_at,
                  sport: row.sport || null });
  } catch (err) {
    return answerFor(err);
  }
}
