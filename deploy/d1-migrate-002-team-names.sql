-- Run once, against a database created before 2026-09-25.
--
--   wrangler d1 execute gordstats --remote --file=deploy/d1-migrate-002-team-names.sql
--
-- Adds the two columns deploy/d1-schema.sql now creates with the table. SQLite
-- has no ADD COLUMN IF NOT EXISTS, so this is a separate file rather than part
-- of the idempotent schema: running it twice fails with "duplicate column
-- name", which is harmless but means it is not safe to fold into the other.
--
-- Nothing is dropped and nothing is rewritten; existing rows get NULLs and are
-- filled in the next time that league is synced.
ALTER TABLE leagues ADD COLUMN team_name TEXT;
ALTER TABLE leagues ADD COLUMN provider_user_id TEXT;
