-- Runs once on first database initialisation. Migrations also ensure these exist.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
