-- Run once, against a database created before 2026-10-03. (Unlike 002-006 it
-- is safe to run again: there is no ALTER in it, only CREATE ... IF NOT EXISTS.)
--
--   wrangler d1 execute gordstats --remote --file=deploy/d1-migrate-007-pickem.sql
--
-- Reader pick'em (functions/api/pickem.js): each week readers pick the winners
-- of the featured college games and every NFL game, ranked by confidence.
-- Two tables, the same two deploy/d1-schema.sql now creates:
--
--   pickem_players  the display name a reader plays under. Its own table,
--                   not a users column: joining is a row here, and the
--                   leaderboard reads names without touching users (where
--                   the email is).
--   pickem_entries  one row per reader per week, the week's picks as JSON.
--
-- Safe either side of the deploy that uses it: the old code never reads
-- either table, and the new code answers without them - the slate and the
-- GordStats entry show, saving says "not switched on yet".
--
-- Why one row per week and not one per pick: a save rewrites a reader's whole
-- week (a confidence change is usually a swap, two picks at once), and as one
-- row it is one D1 write instead of up to ~26 rows plus their index entries;
-- it is also atomic, so two tabs saving at once can never leave two picks on
-- the same value. The leaderboard reads one row per reader per week. `rev`
-- is the optimistic lock a save writes against.
--
-- No index beyond the keys (see 004): pickem_entries is WITHOUT ROWID, so a
-- save is one write; the names' UNIQUE key is the case-insensitive uniqueness
-- check, written only when a reader joins or renames.

CREATE TABLE IF NOT EXISTS pickem_players (
  user_id    TEXT NOT NULL PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  name       TEXT NOT NULL,
  name_key   TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS pickem_entries (
  season     INTEGER NOT NULL,
  user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  week       INTEGER NOT NULL,
  picks      TEXT NOT NULL,
  rev        INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (season, user_id, week)
) WITHOUT ROWID;
