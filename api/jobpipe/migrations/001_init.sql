CREATE TABLE companies (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('greenhouse', 'lever', 'ashby')),
    slug TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (source, slug)
);

CREATE TABLE postings (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies (id),
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    posted_at TIMESTAMPTZ,
    board JSONB NOT NULL DEFAULT '{}'::jsonb,
    text TEXT,
    text_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('skipped', 'review', 'tracked', 'ineligible', 'dismissed',
                                           'applied', 'interview', 'offer', 'rejected')),
    skip_reason TEXT,
    closing_date DATE,
    closed_at TIMESTAMPTZ,
    text_deleted_at TIMESTAMPTZ,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, source_id)
);
CREATE INDEX postings_company_idx ON postings (company_id);
CREATE INDEX postings_status_idx ON postings (status);

CREATE TABLE extractions (
    id SERIAL PRIMARY KEY,
    posting_id INTEGER NOT NULL REFERENCES postings (id) ON DELETE CASCADE,
    text_hash TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    fields JSONB,
    checks JSONB NOT NULL DEFAULT '[]'::jsonb,
    route TEXT NOT NULL,
    reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    fit JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX extractions_posting_idx ON extractions (posting_id, created_at DESC);

CREATE TABLE llm_calls (
    id SERIAL PRIMARY KEY,
    posting_id INTEGER REFERENCES postings (id) ON DELETE SET NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd NUMERIC(12, 6),
    latency_ms INTEGER,
    request_id TEXT,
    outcome TEXT NOT NULL,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE ingest_calls (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies (id),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    fetched INTEGER NOT NULL DEFAULT 0,
    created INTEGER NOT NULL DEFAULT 0,
    changed INTEGER NOT NULL DEFAULT 0,
    unchanged INTEGER NOT NULL DEFAULT 0,
    skipped INTEGER NOT NULL DEFAULT 0,
    extracted INTEGER NOT NULL DEFAULT 0,
    tracked INTEGER NOT NULL DEFAULT 0,
    review INTEGER NOT NULL DEFAULT 0,
    ineligible INTEGER NOT NULL DEFAULT 0,
    closed INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0
);
