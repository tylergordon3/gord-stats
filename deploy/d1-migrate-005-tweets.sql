-- Run once, against a database created before 2026-10-02.
--
--   wrangler d1 execute gordstats --remote --file=deploy/d1-migrate-005-tweets.sql
--
-- Tweets of the week (functions/api/tweets.js): readers send in posts from X,
-- the site's owner approves them, readers vote. Two tables and one column -
-- the same two tables deploy/d1-schema.sql now creates.
--
-- Safe either side of the deploy that uses it: the old code never reads any
-- of this, and the new code answers without it - the list empty and "not
-- switched on yet" for a submission until the tables exist, and nobody an
-- owner until is_admin does.
--
-- The tables lead because CREATE TABLE IF NOT EXISTS is idempotent. SQLite
-- has no ADD COLUMN IF NOT EXISTS, so from the ALTER on the file is run-once
-- like 002-004: a second run stops at "duplicate column name", harmlessly.
--
-- No index beyond the keys. Each one is a write on every insert (see 004),
-- and at this site's size a scan of the approved posts is cheaper than
-- keeping one: the public list is shared through the Workers cache, and a
-- reader's vote is found through tweet_votes' own primary key.

CREATE TABLE IF NOT EXISTS tweets (
  id            INTEGER PRIMARY KEY,
  tweet_id      TEXT NOT NULL UNIQUE,
  handle        TEXT,
  author        TEXT,
  text          TEXT,
  has_media     INTEGER NOT NULL DEFAULT 0,
  sport         TEXT,
  submitted_by  TEXT REFERENCES users(id) ON DELETE SET NULL,
  submitted_at  TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'pending',
  reviewed_at   TEXT
);

CREATE TABLE IF NOT EXISTS tweet_votes (
  tweet_id  INTEGER NOT NULL REFERENCES tweets(id) ON DELETE CASCADE,
  user_id   TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (tweet_id, user_id)
) WITHOUT ROWID;

ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0;
