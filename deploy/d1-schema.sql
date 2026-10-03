-- GordStats accounts. Applied with:
--
--   wrangler d1 execute gordstats --remote --file=deploy/d1-schema.sql
--
-- Two tables, and that is the whole feature. A reader signs in with Google so
-- their stars follow them between devices; nothing else about them is stored.
--
-- What is deliberately absent: no name, no picture, no Google access or
-- refresh token. The ID token is read once at callback for the two fields
-- below and then dropped, so a copy of this database is worth very little to
-- anyone who takes it.

CREATE TABLE IF NOT EXISTS users (
  id            TEXT PRIMARY KEY,       -- our own uuid, never Google's
  email         TEXT NOT NULL,
  -- Google's stable subject id. This, not the email, is the join key: an
  -- address can be reassigned within a Workspace domain, and matching on it
  -- would hand the new holder the old holder's favourites.
  provider_sub  TEXT NOT NULL UNIQUE,
  created_at    TEXT NOT NULL,
  last_seen_at  TEXT NOT NULL,
  -- 1 for the site's owner: who may approve readers' posts for Tweets of the
  -- week (functions/api/tweets.js). Set by hand, never by any endpoint:
  --   UPDATE users SET is_admin = 1 WHERE email = '<the owner's address>';
  -- Declared ahead of migration 004's columns, which tests/functions_harness
  -- rebuilds by dropping them off the end; a database migrated by 005 has it
  -- last, and nothing here reads columns by position.
  is_admin      INTEGER NOT NULL DEFAULT 0,
  -- Signed into every session (as `ep`); a session is good only while it
  -- matches (functions/api/_lib/session.js). "Sign out everywhere" adds one,
  -- which ends every session issued before. Old sessions carry none and count
  -- as 0. Declared here, ahead of 004's columns, for the reason is_admin is;
  -- a database migrated by 006 has it last.
  session_epoch INTEGER NOT NULL DEFAULT 0,
  -- How many rows this reader has changed today (UTC), against the daily
  -- allowance in functions/api/_lib/limits.js. D1's free tier has one pool of
  -- writes for the whole site, and without a per-account ceiling a single
  -- script could empty it - taking sign-in down for everyone with it.
  write_day     TEXT,
  write_count   INTEGER NOT NULL DEFAULT 0,
  -- When this reader last synced a league, which is what the refresh button
  -- is rate-limited on. On the account rather than on the leagues' own rows,
  -- so it can be claimed in one atomic UPDATE and so removing a league does
  -- not reset it.
  last_league_sync TEXT
);

-- Deleting an account is one statement; the cascade takes the stars with it.
-- It finds them through the primary key, whose first column is user_id - a
-- separate index on user_id alone was a copy of that prefix, and cost a
-- third write for every star saved.
CREATE TABLE IF NOT EXISTS favorites (
  user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  -- Stored split rather than as the "cfb:194" key the browser uses, so a
  -- section can be counted or migrated without parsing strings.
  sport      TEXT NOT NULL,
  team_id    TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (user_id, sport, team_id)
);

-- --------------------------------------------------------------------------
-- Synced leagues: the reader's own fantasy league, attached to their account.
--
-- Only what is needed to fetch the league again from Sleeper's public API,
-- which is keyless - so there are no credentials here, and a copy of this
-- database stays worth very little to anyone who takes it.
--
-- Sleeper only. Yahoo was offered briefly and withdrawn: its public API serves
-- only leagues a commissioner has set public, and a private one needs OAuth
-- and a stored refresh token, which is a different security posture and wants
-- its own decision. `provider` stays so that decision needs no migration.
--
-- `last_synced_at` is when each row last came from Sleeper - the "synced"
-- time the page shows. The refresh limit is users.last_league_sync.
CREATE TABLE IF NOT EXISTS leagues (
  user_id        TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  -- "sleeper" or "yahoo". The sport follows from it here (Sleeper for the NFL
  -- league, Yahoo for the college one), but it is stored so that a second
  -- Sleeper sport later does not need a migration.
  provider       TEXT NOT NULL,
  sport          TEXT NOT NULL,
  -- The provider's own id: a Sleeper league id, or a Yahoo league key
  -- ("474.l.21318"). Opaque here; the provider is the one that parses it.
  league_id      TEXT NOT NULL,
  name           TEXT,
  season         TEXT,
  -- The reader's own team in that league, and their id with the provider.
  -- Both are filled in at sync: the league picker says "League - Your Team",
  -- which is the only way to tell two leagues apart when someone names them
  -- the same thing, and people do.
  team_name        TEXT,
  provider_user_id TEXT,
  -- A league is one row per season: Sleeper gives each season its own id and
  -- links them with previous_league_id. `lineage_id` is the oldest id in that
  -- chain, so every season of one league groups under it and the picker can
  -- offer "this league, that season" instead of four unrelated entries with
  -- the same name.
  lineage_id       TEXT,
  created_at     TEXT NOT NULL,
  last_synced_at TEXT NOT NULL,
  -- user_id leads the key, so "this reader's leagues" is a range of the
  -- primary key's own index and needs no second one.
  PRIMARY KEY (user_id, provider, league_id)
);

-- --------------------------------------------------------------------------
-- Tweets of the week (functions/api/tweets.js; deploy/d1-migrate-005-tweets.sql
-- for a database created before 2026-10-02).
--
-- Readers send in posts from X, the owner (users.is_admin) approves them, and
-- readers vote; Home shows the week's approved posts, most votes first. What
-- is stored is what X's keyless oEmbed says about a public post - author,
-- handle, the text as plain text, whether it carries a photo or video - so
-- the cards draw without asking X anything. The post itself is embedded only
-- when a reader taps one.
--
-- No index beyond the keys: each one is a write on every insert (see 004),
-- and at this size a scan of the approved posts is cheaper than keeping one.
-- `tweet_id` is X's id as text - it is past 2^53, so never a number here.
CREATE TABLE IF NOT EXISTS tweets (
  id            INTEGER PRIMARY KEY,
  tweet_id      TEXT NOT NULL UNIQUE,
  handle        TEXT,
  author        TEXT,
  text          TEXT,
  -- 0 none, 1 a photo or video (oEmbed's pic.twitter.com link does not say
  -- which), 2 a video for certain (a /video/ link).
  has_media     INTEGER NOT NULL DEFAULT 0,
  -- 'cfb', 'nfl' or NULL. Checked in code rather than by a CHECK, so another
  -- sport later needs no table rebuild.
  sport         TEXT,
  -- Kept when the account goes: the post was approved on its own merits.
  submitted_by  TEXT REFERENCES users(id) ON DELETE SET NULL,
  submitted_at  TEXT NOT NULL,
  -- 'pending', 'approved' or 'rejected'; a removed post goes back to
  -- 'rejected', so it cannot simply be sent in again.
  status        TEXT NOT NULL DEFAULT 'pending',
  -- When it was approved (or turned down): "this week" counts from here.
  reviewed_at   TEXT
);

-- One row per reader per post. WITHOUT ROWID: the primary key is the table,
-- so a vote is one row written rather than a row plus its key's index - the
-- difference between one write and two on every tap. The key leads with the
-- post, which is how votes are counted; an account's own votes go with it
-- through the cascade, a scan that runs only when an account is deleted.
CREATE TABLE IF NOT EXISTS tweet_votes (
  tweet_id  INTEGER NOT NULL REFERENCES tweets(id) ON DELETE CASCADE,
  user_id   TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (tweet_id, user_id)
) WITHOUT ROWID;

-- --------------------------------------------------------------------------
-- The site's own daily ceiling on writes (functions/api/_lib/limits.js;
-- deploy/d1-migrate-006-ceiling-and-sessions.sql for a database created
-- before 2026-10-02).
--
-- D1's free tier is 100,000 rows written a day for the whole database, and
-- sign-in writes too. Each account has its own daily allowance (users.
-- write_count), but some twenty accounts at theirs would still spend the
-- site's day and leave nobody able to sign in. One row counts what the
-- metered endpoints - favourites, leagues, Tweets of the week - have written
-- today (estimated in D1's own rows, indexes included), and they stop at a
-- ceiling well short of the quota. Taken with one conditional upsert per
-- request, as the account's allowance is; the row makes itself on the first.
CREATE TABLE IF NOT EXISTS site_writes (
  id       INTEGER PRIMARY KEY CHECK (id = 1),   -- one row, ever
  day      TEXT NOT NULL,                        -- UTC, as D1's quota day
  written  INTEGER NOT NULL DEFAULT 0
);
