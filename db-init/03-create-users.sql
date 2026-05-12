-- =============================================================
-- Lumora users table - the foundation of real accounts
-- =============================================================
-- This is the table that turns Lumora from "a Coming Soon page"
-- into "an app where real humans have accounts."
--
-- Security notes:
--   * password_hash stores an argon2id hash, NEVER a plain
--     password. argon2-cffi produces strings like
--     "$argon2id$v=19$m=65536,t=3,p=4$..." - that's the hash,
--     salt, and parameters all in one string.
--   * email_verified starts false. We don't enforce verification
--     in Phase 1, but the column exists so Phase 1b can add it
--     without a schema migration.
--   * UNIQUE on email means two people can't sign up with the
--     same email. The API catches the resulting error.
-- =============================================================

CREATE TABLE IF NOT EXISTS users (
    id              SERIAL PRIMARY KEY,
    email           VARCHAR(255) UNIQUE NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    email_verified  BOOLEAN DEFAULT false,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
