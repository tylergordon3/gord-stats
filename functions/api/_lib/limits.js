/**
 * Per-account ceilings on what one signed-in reader can make the database do.
 *
 * D1's free tier allows 100,000 rows written a day across the whole site, and
 * sign-in itself writes to it - so the day those run out, nobody can sign in.
 * Before this, one scripted account could spend the lot in under a hundred
 * requests. Both ceilings here live on the reader's own `users` row
 * (deploy/d1-migrate-004-write-limits.sql) and are taken with a single
 * conditional UPDATE: of any number of requests racing for one, only those
 * that fit see `meta.changes === 1`, so opening a second tab or firing in
 * parallel buys nothing. A read-then-write check could not promise that.
 *
 *   spend  - a daily allowance of rows changed, shared by favourites and
 *            leagues.
 *   claim  - "one of these every N seconds", for the league sync, whose cost
 *            is mostly calls to Sleeper rather than rows.
 *
 * Deployed ahead of its migration, the columns are missing: both then say so
 * (`unmetered`, `ok: null`) instead of failing the request, and the caller
 * decides what that means. Nothing here turns a missing column into a 500.
 */

// Rows one account may change in a UTC day - the same day D1's own quota
// resets on, so a reader who hits it waits exactly as long as D1 would. Far
// above anything done by hand (a full 500-team favourites list fits twice),
// so the only thing it ever stops is a script.
export const DAILY_CHANGES = 1000;

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

/**
 * Take `n` rows from today's allowance.
 * -> { ok: true } | { ok: false, retryAfter } | { ok: true, unmetered: true }
 */
export async function spend(db, uid, n, now = new Date(), limit = DAILY_CHANGES) {
  if (n <= 0) return { ok: true };
  try {
    const r = await db.prepare(SPEND).bind(uid, utcDay(now), n, limit).run();
    if (r?.meta?.changes) return { ok: true };
    return { ok: false, retryAfter: secondsToMidnight(now) };
  } catch (err) {
    if (!missingColumn(err)) throw err;
    console.warn("limits: users.write_day/write_count missing - apply d1-migrate-004");
    return { ok: true, unmetered: true };
  }
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
