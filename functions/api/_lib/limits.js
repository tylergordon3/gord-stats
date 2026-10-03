/**
 * Ceilings on what readers can make the database do: one per account, and one
 * for the whole site.
 *
 * D1's free tier allows 100,000 rows written a day across the whole site, and
 * sign-in itself writes to it - so the day those run out, nobody can sign in.
 * Before this, one scripted account could spend the lot in under a hundred
 * requests.
 *
 *   spend  - a daily allowance of rows changed, per account (on the reader's
 *            own `users` row, deploy/d1-migrate-004-write-limits.sql), shared
 *            by favourites, leagues and Tweets of the week; and, inside the
 *            same call, the site's own daily ceiling (`site_writes`,
 *            deploy/d1-migrate-006-ceiling-and-sessions.sql), which stops
 *            all of those writes for everyone well short of D1's quota so
 *            that what is left is sign-in's.
 *   claim  - "one of these every N seconds", for the league sync, whose cost
 *            is mostly calls to Sleeper rather than rows.
 *
 * Every ceiling is taken with a single conditional write (an UPDATE, or for
 * the site an upsert): of any number of requests racing for one, only those
 * that fit see `meta.changes === 1`, so
 * opening a second tab or firing in parallel buys nothing. A read-then-write
 * check could not promise that.
 *
 * Deployed ahead of its migration, a column or table is missing: each check
 * then says so (`unmetered`, `ok: null`) instead of failing the request, and
 * the caller decides what that means. Nothing here turns a missing column or
 * table into a 500.
 */
import { json } from "./session.js";

// Rows one account may change in a UTC day - the same day D1's own quota
// resets on, so a reader who hits it waits exactly as long as D1 would. Far
// above anything done by hand (a full 500-team favourites list fits twice),
// so the only thing it ever stops is a script.
export const DAILY_CHANGES = 1000;

// The site's ceiling, in D1 rows written (indexes included, as D1 counts
// them) by the metered endpoints, per UTC day. D1's free tier is 100,000; the
// other 60,000 are sign-in's (a returning reader is one row, a new one three)
// and the few writes nothing meters - a league sync's claim stamp, signing
// out everywhere, deleting an account. Roughly twenty accounts at their own
// allowance reach it; then saving stops for everyone until midnight UTC and
// sign-in carries on.
export const SITE_DAILY_WRITES = 40000;
// What one changed row costs D1, as near as one number can say: the row and
// its primary key's index (favourites, leagues, a submitted post; a vote is
// one, a re-synced league whose key did not move is one). Over rather than
// under, on purpose.
export const WRITES_PER_ROW = 2;
// The two meter rows themselves: the account's and the site's.
export const METER_WRITES = 2;

export const SITE_FULL = "Saving is paused for everyone until midnight UTC: the site has "
  + "reached its limit on changes for today. Nothing was changed.";

/** What `n` changed rows cost the site's ceiling. Approximate, by design. */
export function siteCost(n) {
  return n * WRITES_PER_ROW + METER_WRITES;
}

export function utcDay(now) {
  return now.toISOString().slice(0, 10);
}

export function secondsToMidnight(now) {
  const next = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1);
  return Math.max(1, Math.ceil((next - now.getTime()) / 1000));
}

/** Seconds left before `at` (an ISO time) is `seconds` old; 0 once it is. */
export function secondsLeft(at, seconds, now) {
  const then = Date.parse(at || "");
  if (!Number.isFinite(then)) return 0;
  // Never more than the window: a parallel request can stamp its claim a few
  // milliseconds after this one read the clock, and "300 less a negative
  // age" rounded up to 301.
  return Math.max(0, Math.min(seconds, Math.ceil(seconds - (now.getTime() - then) / 1000)));
}

function missingColumn(err) {
  return /no such column/i.test(String(err && err.message || err));
}

function missingTable(err) {
  return /no such table/i.test(String(err && err.message || err));
}

// Column names cannot be bound as parameters, so the two functions that take
// one splice it in - and only ever accept a plain identifier.
function column(name) {
  if (!/^[a-z_]+$/.test(name)) throw new Error(`not a column name: ${name}`);
  return name;
}

// The allowance is taken before the rows are written, and only if the whole
// of it fits. A count left over from yesterday is read as zero rather than
// reset by a separate statement, so there is no window between the two.
const SPEND =
  `UPDATE users
      SET write_count = CASE WHEN write_day = ?2 THEN write_count ELSE 0 END + ?3,
          write_day = ?2
    WHERE id = ?1
      AND CASE WHEN write_day = ?2 THEN write_count ELSE 0 END + ?3 <= ?4`;

// The site's day, as one row. An upsert rather than a plain UPDATE so that the
// row makes itself: a database whose row went missing starts counting again
// instead of refusing everybody for ever. Yesterday's count reads as zero,
// as in SPEND.
const SITE_USED =
  `SELECT CASE WHEN day = ?1 THEN written ELSE 0 END AS used
     FROM site_writes WHERE id = 1`;
const SITE_SPEND =
  `INSERT INTO site_writes (id, day, written)
   SELECT 1, ?1, ?2 WHERE ?2 <= ?3
   ON CONFLICT (id) DO UPDATE
      SET written = CASE WHEN day = ?1 THEN written ELSE 0 END + ?2,
          day = ?1
    WHERE CASE WHEN day = ?1 THEN written ELSE 0 END + ?2 <= ?3`;

function siteRefusal(now) {
  return { ok: false, site: true, retryAfter: secondsToMidnight(now) };
}

/** What the site has written today, by its own count; null before 006. */
async function siteUsed(db, day) {
  try {
    const row = await db.prepare(SITE_USED).bind(day).first();
    return Number(row?.used || 0);
  } catch (err) {
    if (!missingTable(err)) throw err;
    console.warn("limits: site_writes missing - apply d1-migrate-006");
    return null;
  }
}

/**
 * The early answer for the site's ceiling, from a plain read: a refusal if
 * `n` more rows would pass it, else null - null too before migration 006.
 * Costs no write, so a refused request spends nothing of the day; for the
 * league sync it also comes before any call to Sleeper and the claim stamp.
 */
export async function siteFull(db, n = 1, now = new Date(), ceiling = SITE_DAILY_WRITES) {
  const used = await siteUsed(db, utcDay(now));
  return used !== null && used + siteCost(n) > ceiling ? siteRefusal(now) : null;
}

/**
 * Take `n` rows from today's allowance - the account's and the site's.
 * -> { ok: true } | { ok: false, retryAfter, site? } | { ok: true, unmetered?, siteUnmetered? }
 *
 * In this order, because each wrong order lets someone spend what is not
 * theirs:
 *   1. the site's day, read: once it is full, nothing below writes anything;
 *   2. the account's allowance, atomically - a refusal here never touches
 *      the site's count, so one account at its own limit cannot run the
 *      site's down with requests that write nothing;
 *   3. the site's ceiling, atomically, for what got past 2.
 * Only a race at the very top of the site's day can see 2 pass and 3 refuse;
 * the account then loses `n` of its own allowance for nothing, which is not
 * worth a refund write at the moment writes are scarcest.
 */
export async function spend(db, uid, n, now = new Date(), limit = DAILY_CHANGES,
                            ceiling = SITE_DAILY_WRITES) {
  if (n <= 0) return { ok: true };
  const out = { ok: true };
  const day = utcDay(now);
  const cost = siteCost(n);

  // A refusal from here on costs reads only - favorites.js asks again every
  // 15 seconds while a change is unsaved, whatever Retry-After says.
  const used = await siteUsed(db, day);
  if (used === null) out.siteUnmetered = true;
  else if (used + cost > ceiling) return siteRefusal(now);

  try {
    const r = await db.prepare(SPEND).bind(uid, day, n, limit).run();
    if (!r?.meta?.changes) return { ok: false, retryAfter: secondsToMidnight(now) };
  } catch (err) {
    if (!missingColumn(err)) throw err;
    console.warn("limits: users.write_day/write_count missing - apply d1-migrate-004");
    out.unmetered = true;
  }

  if (used !== null) {
    const r = await db.prepare(SITE_SPEND).bind(day, cost, ceiling).run();
    if (!r?.meta?.changes) return siteRefusal(now);
  }
  return out;
}

/**
 * The answer for a spend() that said no. The account's own allowance is a
 * 429 in the endpoint's words (`error`); the site's ceiling is a 503 in its
 * own - nothing the reader did, and the same for everyone - with
 * `site_limit` so a page can tell the two apart. Both carry Retry-After.
 */
export function refusal(allowed, error = "too many changes today") {
  const wait = allowed.retryAfter;
  const headers = { "retry-after": String(wait) };
  if (allowed.site) {
    return json({ ok: false, site_limit: true, error: SITE_FULL, retry_after: wait }, 503, headers);
  }
  return json({ ok: false, error, retry_after: wait }, 429, headers);
}

/**
 * Seconds this account must still wait before `name` is `seconds` old, from a
 * plain read - the cheap early answer, so a refused request costs no calls to
 * anyone. `claim` is what actually decides.
 * -> number | null (column missing)
 */
export async function waiting(db, uid, name, seconds, now = new Date()) {
  try {
    const row = await db.prepare(`SELECT ${column(name)} AS at FROM users WHERE id = ?`)
      .bind(uid).first();
    return secondsLeft(row?.at, seconds, now);
  } catch (err) {
    if (!missingColumn(err)) throw err;
    return null;
  }
}

/**
 * Stamp `name` with now, if it is at least `seconds` old.
 * -> { ok: true } | { ok: false, retryAfter } | { ok: null } (column missing)
 *
 * toISOString() always gives the same shape, so comparing two of them as
 * text is comparing them as times.
 */
export async function claim(db, uid, name, seconds, now = new Date()) {
  const col = column(name);
  const cutoff = new Date(now.getTime() - seconds * 1000).toISOString();
  try {
    const r = await db.prepare(
      `UPDATE users SET ${col} = ?1 WHERE id = ?2 AND (${col} IS NULL OR ${col} <= ?3)`)
      .bind(now.toISOString(), uid, cutoff).run();
    if (r?.meta?.changes) return { ok: true };
  } catch (err) {
    if (!missingColumn(err)) throw err;
    return { ok: null };
  }
  const left = await waiting(db, uid, col, seconds, now);
  return { ok: false, retryAfter: Math.max(1, left || 0) };
}
