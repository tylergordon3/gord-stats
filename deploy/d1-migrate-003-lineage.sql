-- Run once, against a database created before 2026-09-25.
--
--   wrangler d1 execute gordstats --remote --file=deploy/d1-migrate-003-lineage.sql
--
-- Adds the column deploy/d1-schema.sql now creates with the table. Separate
-- file for the same reason as 002: SQLite has no ADD COLUMN IF NOT EXISTS, so
-- this is not safe to fold into the idempotent schema.
--
-- Existing rows get NULL and are backfilled the next time that league syncs.
ALTER TABLE leagues ADD COLUMN lineage_id TEXT;
