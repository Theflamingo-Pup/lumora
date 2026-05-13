-- =============================================================
-- profiles table - Phase 2a
-- =============================================================
-- This runs on FRESH DB inits only (when postgres pod starts
-- with empty volume). For existing DBs we use the migration
-- script instead.
--
-- Design notes:
--   * user_id is BOTH primary key AND foreign key. That enforces
--     1:1 - each user has at most one profile.
--   * ON DELETE CASCADE: when a user is deleted, their profile
--     auto-deletes. (We don't want orphan rows.)
--   * Age check at DB level: defense in depth. Even if the API
--     has a bug, postgres rejects underage profiles.
-- =============================================================

CREATE TABLE IF NOT EXISTS profiles (
    user_id             INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    display_name        VARCHAR(50)  NOT NULL,
    age                 INTEGER      NOT NULL CHECK (age >= 18 AND age <= 120),
    bio                 TEXT,
    location_city       VARCHAR(100),
    looking_for_min_age INTEGER      DEFAULT 18  CHECK (looking_for_min_age >= 18 AND looking_for_min_age <= 120),
    looking_for_max_age INTEGER      DEFAULT 99  CHECK (looking_for_max_age >= 18 AND looking_for_max_age <= 120),
    created_at          TIMESTAMP    DEFAULT NOW(),
    updated_at          TIMESTAMP    DEFAULT NOW()
);
