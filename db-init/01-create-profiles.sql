-- =============================================================
-- Lumora database initialization
-- =============================================================
-- This file runs ONCE, the very first time the postgres container
-- starts (because we mount it into /docker-entrypoint-initdb.d/,
-- which the postgres image automatically executes).
--
-- It creates the table and inserts our starting profiles.
-- =============================================================

CREATE TABLE IF NOT EXISTS profiles (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    age         INTEGER NOT NULL,
    bio         TEXT,
    distance_mi INTEGER,
    created_at  TIMESTAMP DEFAULT NOW()
);

INSERT INTO profiles (name, age, bio, distance_mi) VALUES
    ('Emma',   28, 'Photographer. Coffee, hikes, golden hour.',         2),
    ('Marcus', 31, 'Software engineer. Cooks. Bad at small talk.',      5),
    ('Sofia',  26, 'PhD student in marine biology. Loves tide pools.',  3),
    ('Daniel', 34, 'Architect. Sketches in cafes. Plays the cello.',    8),
    ('Aisha',  29, 'ER nurse. Long shifts, longer playlists.',          4),
    ('Leo',    27, 'Standup comedian by night, accountant by day.',     6),
    ('Priya',  30, 'Civil engineer. Building bridges, literally.',      7),
    ('Jamal',  32, 'Music producer. Vinyl collector. Insomniac.',       9);
