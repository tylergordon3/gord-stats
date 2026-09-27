/**
 * Per-account ceilings on what one signed-in reader can make the database do.
 *
 * D1's free tier allows 100,000 rows written a day across the whole site, and
 * sign-in itself writes to it - so the day those run out, nobody can sign in.
 * Before this, one scripted account could spend the lot in under a hundred
 * requests. The ceiling lives on the reader's own `users` row
 * (deploy/d1-migrate-004-write-limits.sql) and is taken with a single
 * conditional UPDATE: of any number of requests racing for it, only those
 * that fit see `meta.changes === 1`, so opening a second tab or firing in
 * parallel buys nothing. A read-then-write check could not promise that.
 *
 * Deployed ahead of its migration, the columns are missing: this then says so
 * (`unmetered`) instead of failing the request. Nothing here is allowed to
 * turn a missing column into a 500.
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

function missingColumn(err) {
  return /no such column/i.test(String(err && err.message || err));
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
