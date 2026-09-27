-- Run once, against a database created before 2026-09-27.
--
--   wrangler d1 execute gordstats --remote --file=deploy/d1-migrate-004-write-limits.sql
--
-- Safe to apply before or after deploying the Functions that use it: the old
-- code never reads these columns, and the new code runs without them until
-- they exist - the daily ceiling switched off, and the league refresh limit
-- back on its old read-then-write check. Applying it first is the better
-- order: those limits are the point.
--
-- Two indexes go. Each was an index on user_id alone, and each table's
-- primary key already starts with user_id, so SQLite answers "this reader's
-- rows" - and the ON DELETE CASCADE from users - from the primary key's own
-- index. The copies bought nothing and cost a write apiece on every insert
-- and delete. DROP INDEX IF EXISTS is idempotent, so these lead.
DROP INDEX IF EXISTS favorites_by_user;
DROP INDEX IF EXISTS leagues_by_user;

-- The per-account daily ceiling on rows changed, and the time of the
-- account's last league sync (functions/api/_lib/limits.js). SQLite has no
-- ADD COLUMN IF NOT EXISTS, so from here the file is run-once like 002 and
-- 003: a second run stops at "duplicate column name", harmlessly.
ALTER TABLE users ADD COLUMN write_day TEXT;
ALTER TABLE users ADD COLUMN write_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN last_league_sync TEXT;
