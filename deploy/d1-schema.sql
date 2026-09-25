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
  last_seen_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS favorites (
  user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  -- Stored split rather than as the "cfb:194" key the browser uses, so a
  -- section can be counted or migrated without parsing strings.
  sport      TEXT NOT NULL,
  team_id    TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (user_id, sport, team_id)
);

-- Deleting an account is one statement; the cascade takes the stars with it.
CREATE INDEX IF NOT EXISTS favorites_by_user ON favorites (user_id);

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
-- `last_synced_at` is what the refresh button is rate-limited on, so the
-- limit survives a reader reloading the page or opening a second tab.
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
  created_at     TEXT NOT NULL,
  last_synced_at TEXT NOT NULL,
  PRIMARY KEY (user_id, provider, league_id)
);

CREATE INDEX IF NOT EXISTS leagues_by_user ON leagues (user_id);
