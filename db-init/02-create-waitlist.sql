-- =============================================================
-- Lumora waitlist table
-- =============================================================
-- Stores emails of people who want early access.
-- This runs ONLY on a fresh database (when the postgres pod
-- starts with an empty volume). To re-run it on an existing
-- database, you'd wipe the volume or run the SQL manually.
--
-- Design choices:
--   * email is UNIQUE so the same person can't be on the list
--     twice. We catch the resulting error in the API.
--   * email is stored lowercase + trimmed (the API does this
--     before insert).
--   * created_at lets us know when each signup happened.
--   * source is for if we add UTM/campaign tracking later.
-- =============================================================

CREATE TABLE IF NOT EXISTS waitlist (
    id         SERIAL PRIMARY KEY,
    email      VARCHAR(255) UNIQUE NOT NULL,
    source     VARCHAR(50) DEFAULT 'website',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_waitlist_created_at ON waitlist(created_at);
