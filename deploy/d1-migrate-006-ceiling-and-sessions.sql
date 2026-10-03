-- Run once, against a database created before 2026-10-02.
--
--   wrangler d1 execute gordstats --remote --file=deploy/d1-migrate-006-ceiling-and-sessions.sql
--
-- Two hardening changes, both in deploy/d1-schema.sql now:
--
--   site_writes          one row counting what favourites, leagues and Tweets
--                        of the week wrote today, against a site-wide ceiling
--                        that keeps D1's daily quota for sign-in
--                        (functions/api/_lib/limits.js).
--   users.session_epoch  signed into every session; "Sign out everywhere"
--                        moves it on and so ends every session issued before
--                        (functions/api/_lib/session.js).
--
-- Safe either side of the deploy that uses it. The old code never reads
-- either. The new code runs without them: no site ceiling (each account's
-- own allowance still holds), every session at epoch 0 - which is what every
-- session issued so far carries - and "Sign out everywhere" answering that it
-- is not switched on yet. Applying it first is the better order: the ceiling
-- is the point.
--
-- No rows to backfill. site_writes makes its one row on the first metered
-- write; every existing account starts at epoch 0, so no session ends.
--
-- The table leads because CREATE TABLE IF NOT EXISTS is idempotent. SQLite
-- has no ADD COLUMN IF NOT EXISTS, so from the ALTER on the file is run-once
-- like 002-005: a second run stops at "duplicate column name", harmlessly.

CREATE TABLE IF NOT EXISTS site_writes (
  id       INTEGER PRIMARY KEY CHECK (id = 1),
  day      TEXT NOT NULL,
  written  INTEGER NOT NULL DEFAULT 0
);

ALTER TABLE users ADD COLUMN session_epoch INTEGER NOT NULL DEFAULT 0;
