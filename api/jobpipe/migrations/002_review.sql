-- The review side: the reviewer account, the reviewer's actions, and when a person chose an ad's status.

CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    failed_logins INTEGER NOT NULL DEFAULT 0,
    locked_until TIMESTAMPTZ
);

CREATE TABLE reviews (
    id SERIAL PRIMARY KEY,
    posting_id INTEGER NOT NULL REFERENCES postings (id) ON DELETE CASCADE,
    extraction_id INTEGER REFERENCES extractions (id) ON DELETE SET NULL,
    username TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('edit', 'approve', 'dismiss', 'override_ineligible', 'set_status')),
    edited_fields JSONB,
    from_status TEXT,
    to_status TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX reviews_posting_idx ON reviews (posting_id, created_at);
CREATE INDEX reviews_extraction_idx ON reviews (extraction_id);

-- Set when a person chooses the status. The pipeline never overwrites such a status.
ALTER TABLE postings ADD COLUMN decided_at TIMESTAMPTZ;
