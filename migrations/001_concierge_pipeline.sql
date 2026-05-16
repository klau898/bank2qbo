-- Bank2QBO concierge pipeline schema.
-- Single SQLite DB tracks every prospect, every PDF, every dollar, every Codex review.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ── leads — every inbound, whether they paid or not ─────────────────────────
CREATE TABLE IF NOT EXISTS leads (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source          TEXT NOT NULL,    -- "linkedin_dm" | "ig_dm" | "reddit_reply" | "landing_form" | "show_hn" | "indie_hackers" | "warm_intro"
    name            TEXT,
    email           TEXT,
    business_name   TEXT,
    business_type   TEXT,             -- "solo_bookkeeper" | "small_cpa_firm" | "smb_owner" | "other"
    qbo_user        INTEGER,          -- 1=yes, 0=no, NULL=unknown
    current_workflow TEXT,            -- their answer to "how do you do this today?"
    pain_score      INTEGER,          -- 1-5; how acute their bank-pdf pain is
    klau_notes      TEXT,
    bought          INTEGER DEFAULT 0
);

-- ── conversions — actual paid events ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS conversions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    lead_id             INTEGER REFERENCES leads(id),
    stripe_session_id   TEXT UNIQUE,
    stripe_customer_id  TEXT,
    product_slug        TEXT NOT NULL,    -- "single_39" | "pack_99" | "firm_99_mo" | "pro_249_mo"
    amount_cents        INTEGER NOT NULL,
    email               TEXT,
    metadata_json       TEXT
);

-- ── pdfs — every file submitted (paid or trial 5-page) ──────────────────────
CREATE TABLE IF NOT EXISTS pdfs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    lead_id         INTEGER REFERENCES leads(id),
    conversion_id   INTEGER REFERENCES conversions(id),
    filename        TEXT NOT NULL,
    file_size_bytes INTEGER,
    page_count      INTEGER,
    bank_guess      TEXT,              -- "chase" | "bofa" | "wellsfargo" | "citi" | etc. — Klau enters at intake
    pdf_type        TEXT,              -- "text_native" | "scanned" | "mixed"
    state           TEXT DEFAULT 'received',  -- received → processing → reconciling → delivered | failed
    s3_url          TEXT,
    sha256          TEXT
);

-- ── deliveries — every CSV+IIF sent + accuracy score ────────────────────────
CREATE TABLE IF NOT EXISTS deliveries (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    pdf_id                  INTEGER REFERENCES pdfs(id) UNIQUE,
    row_count               INTEGER,
    sum_debits_cents        INTEGER,
    sum_credits_cents       INTEGER,
    opening_balance_cents   INTEGER,
    closing_balance_cents   INTEGER,
    reconciliation_score    REAL,      -- 0.0 to 1.0; >=0.99 = clean delivery
    flagged_rows            INTEGER DEFAULT 0,
    csv_path                TEXT,
    iif_path                TEXT,
    delivery_email_id       TEXT,      -- Resend message ID
    delivered_at            TIMESTAMP,
    klau_reviewed_at        TIMESTAMP,
    klau_approved           INTEGER     -- 1=ok, 0=re-run, NULL=pending
);

-- ── feedback — what customers say after delivery ────────────────────────────
CREATE TABLE IF NOT EXISTS feedback (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    delivery_id     INTEGER REFERENCES deliveries(id),
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    channel         TEXT,              -- "email" | "telegram_forward" | "dm" | "stripe_review"
    sentiment       TEXT,              -- "positive" | "neutral" | "negative" | "silence"
    paid_again      INTEGER DEFAULT 0,
    referred_someone INTEGER DEFAULT 0,
    body            TEXT
);

-- ── decisions — every kill/scale moment + Codex review pinned ───────────────
CREATE TABLE IF NOT EXISTS decisions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    day_number      INTEGER NOT NULL,  -- 1..14
    snapshot_json   TEXT NOT NULL,     -- counts: leads, conversions, deliveries, accuracy
    codex_verdict   TEXT,              -- "continue" | "extend" | "kill" | "course_correct"
    codex_rationale TEXT,
    klau_override   TEXT,
    final_action    TEXT NOT NULL
);

-- ── codex_reviews — every adversarial peer-review checkpoint ────────────────
CREATE TABLE IF NOT EXISTS codex_reviews (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    artifact_type   TEXT NOT NULL,     -- "landing_copy" | "dm_script" | "reddit_post" | "stripe_pricing" | "pdf_processor_logic" | "delivery_email" | "day_14_decision"
    artifact_ref    TEXT,              -- file path or DB row reference
    severity        TEXT,              -- "OK" | "MINOR" | "SERIOUS" | "FATAL"
    findings        TEXT NOT NULL,
    action_taken    TEXT
);
