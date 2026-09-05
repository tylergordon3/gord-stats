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
