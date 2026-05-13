-- =============================================================
-- profiles table - Phase 2b
-- =============================================================
-- Same as Phase 2a + photo_url column.
-- =============================================================

CREATE TABLE IF NOT EXISTS profiles (
    user_id             INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    display_name        VARCHAR(50)  NOT NULL,
    age                 INTEGER      NOT NULL CHECK (age >= 18 AND age <= 120),
    bio                 TEXT,
    location_city       VARCHAR(100),
    looking_for_min_age INTEGER      DEFAULT 18  CHECK (looking_for_min_age >= 18 AND looking_for_min_age <= 120),
    looking_for_max_age INTEGER      DEFAULT 99  CHECK (looking_for_max_age >= 18 AND looking_for_max_age <= 120),
    photo_url           TEXT,
    created_at          TIMESTAMP    DEFAULT NOW(),
    updated_at          TIMESTAMP    DEFAULT NOW()
);
