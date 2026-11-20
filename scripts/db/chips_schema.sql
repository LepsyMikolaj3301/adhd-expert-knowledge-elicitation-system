-- Tables of notes/new-chips-knowledge.md ("Storage"), in their own schema so that nothing touches
-- backend/db/init.sql or the literature tables. {schema} is filled in by load_chips_pg.py (default
-- chips_eval: `chips` itself is the web application's, created by migration 0003, which holds a
-- frozen copy of these tables; change both together). vector / sparsevec come from the extension
-- in public.
CREATE SCHEMA IF NOT EXISTS {schema};
SET search_path = {schema}, public;

CREATE TABLE IF NOT EXISTS experts (
    id text PRIMARY KEY,                       -- <tier>/<expert id>: tiers share expert ids
    role text
);

CREATE TABLE IF NOT EXISTS vignettes (
    id text NOT NULL, version integer NOT NULL, tier text NOT NULL,
    text text NOT NULL, content_hash text NOT NULL, framing text NOT NULL,
    population text NOT NULL, track text NOT NULL,
    PRIMARY KEY (id, version, tier)
);

CREATE TABLE IF NOT EXISTS elicitation_sessions (
    id text PRIMARY KEY,                       -- <tier>/<session id>
    expert_id text NOT NULL REFERENCES experts ON DELETE CASCADE,
    document jsonb NOT NULL,                   -- the raw ChipDocument
    created_at timestamptz NOT NULL
);

-- one cue key per distinct vignette span, shared across experts (and tiers: same vignettes)
CREATE TABLE IF NOT EXISTS cue_keys (
    id bigserial PRIMARY KEY,
    vignette_id text NOT NULL, vignette_version integer NOT NULL, span int4range NOT NULL,
    text text NOT NULL,
    embedding vector(1024) NOT NULL, sparse sparsevec(1048576),
    UNIQUE (vignette_id, vignette_version, span)
);

CREATE TABLE IF NOT EXISTS highlights (
    id text PRIMARY KEY,                       -- <session>-<vignette>-h<chip> | -i<n> (implicit)
    session_id text NOT NULL REFERENCES elicitation_sessions ON DELETE CASCADE,
    vignette_id text NOT NULL, vignette_version integer NOT NULL,
    chip smallint,                             -- NULL for implicit
    span int4range NOT NULL,
    origin text NOT NULL,                      -- expert | implicit
    direction text,                            -- toward | away | neutral | unclear; NULL for implicit
    direction_changed_after_flag boolean NOT NULL DEFAULT false,
    cue_key_id bigint NOT NULL REFERENCES cue_keys
);

CREATE TABLE IF NOT EXISTS answer_sentences (
    id text PRIMARY KEY,                       -- <session>-<vignette>-Q2.1
    session_id text NOT NULL REFERENCES elicitation_sessions ON DELETE CASCADE,
    vignette_id text NOT NULL, vignette_version integer NOT NULL,
    question_id text NOT NULL, question_version integer NOT NULL DEFAULT 1,
    idx smallint NOT NULL,
    span int4range NOT NULL,                   -- offsets into the stored answer, chip tokens included
    targets text[] NOT NULL,                   -- highlight ids and/or 'case'
    assigned_by text NOT NULL                  -- chip | quote | llm | expert
);

CREATE TABLE IF NOT EXISTS finding_units (
    id text PRIMARY KEY,
    session_id text NOT NULL REFERENCES elicitation_sessions ON DELETE CASCADE,
    expert_id text NOT NULL,
    vignette_id text NOT NULL, vignette_version integer NOT NULL,
    kind text NOT NULL,                        -- fragment | case
    highlight_id text REFERENCES highlights,   -- NULL for case units
    direction text,
    population text NOT NULL, track text NOT NULL, framing text NOT NULL,
    segmenter jsonb NOT NULL,                  -- code version, classifier model + prompt version
    embed_text text NOT NULL,                  -- I1
    embedding vector(1024) NOT NULL, sparse sparsevec(1048576)
);

CREATE TABLE IF NOT EXISTS finding_unit_sentences (
    unit_id text REFERENCES finding_units ON DELETE CASCADE,
    sentence_id text REFERENCES answer_sentences ON DELETE CASCADE,
    ord smallint NOT NULL,
    PRIMARY KEY (unit_id, sentence_id)
);

CREATE TABLE IF NOT EXISTS unit_cues (
    unit_id text REFERENCES finding_units ON DELETE CASCADE,
    cue_key_id bigint NOT NULL REFERENCES cue_keys,
    role text NOT NULL,                        -- cue | context
    PRIMARY KEY (unit_id, cue_key_id, role)
);

CREATE TABLE IF NOT EXISTS review_events (
    session_id text REFERENCES elicitation_sessions ON DELETE CASCADE,
    vignette_id text NOT NULL,
    kind text NOT NULL,                        -- flag_shown | toggle_changed | sentence_moved | skipped
    payload jsonb NOT NULL,
    at timestamptz NOT NULL
);
