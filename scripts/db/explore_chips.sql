-- A guided tour of the `chips` schema (the expert knowledge base) and the `app` tables that feed it.
-- Read-only: every statement is a SELECT. Run it in psql from the repo root, section by section:
--     scripts/db/psql.sh                 then:   \i scripts/db/explore_chips.sql      (everything)
-- or paste one section at a time. `\x auto` below switches to vertical output for wide rows.
-- Background: notes/new-chips-knowledge.md (design), backend/app/knowledge/ingest.py (the writer).
-- Facts used throughout (all checked against the code, not the docs):
--   * chips.* rows are written in ONE transaction per assignment (ingest.write), replacing that
--     assignment's rows. session_id = app.assignments.id, expert_id = app.users.id (as text).
--   * every chips id is  <session uuid>-<vignette code>-<local id>,  local id = h1, h2, .., i1 .. or case.
--   * a unit stores ONE embedded text: I1 (embed_text). I2 is not a unit column: it is
--     chips.cue_keys (the patient's words alone).

\pset null '∅'
\x auto

-- Pick a session and a unit to look at in detail; change these two lines to look elsewhere.
SELECT id AS session_id FROM chips.elicitation_sessions ORDER BY created_at LIMIT 1 \gset
SELECT id AS unit_id FROM chips.finding_units
 WHERE session_id = :'session_id' AND kind = 'fragment' ORDER BY id LIMIT 1 \gset
\echo 'looking at session' :session_id
\echo 'and unit' :unit_id


-- ======================================================================================
-- 1. WHAT IS IN THERE
-- ======================================================================================
\echo
\echo '== 1.1 row counts: app (staging, the web application) and chips (the knowledge base) =='
SELECT 'app.answer_findings'      AS tbl, count(*) FROM app.answer_findings
UNION ALL SELECT 'app.knowledge_units',       count(*) FROM app.knowledge_units
UNION ALL SELECT 'chips.experts',             count(*) FROM chips.experts
UNION ALL SELECT 'chips.vignettes',           count(*) FROM chips.vignettes
UNION ALL SELECT 'chips.elicitation_sessions',count(*) FROM chips.elicitation_sessions
UNION ALL SELECT 'chips.cue_keys',            count(*) FROM chips.cue_keys
UNION ALL SELECT 'chips.highlights',          count(*) FROM chips.highlights
UNION ALL SELECT 'chips.answer_sentences',    count(*) FROM chips.answer_sentences
UNION ALL SELECT 'chips.finding_units',       count(*) FROM chips.finding_units
UNION ALL SELECT 'chips.finding_unit_sentences', count(*) FROM chips.finding_unit_sentences
UNION ALL SELECT 'chips.unit_cues',           count(*) FROM chips.unit_cues
UNION ALL SELECT 'chips.review_events',       count(*) FROM chips.review_events;

\echo
\echo '== 1.2 one row per session: who, which vignette, how much came out of it =='
SELECT s.id AS session_id,
       u.pseudonym AS expert,
       (SELECT min(vignette_id) FROM chips.finding_units f WHERE f.session_id = s.id) AS vignette,
       (SELECT count(*) FROM chips.highlights h        WHERE h.session_id = s.id)     AS highlights,
       (SELECT count(*) FROM chips.answer_sentences a  WHERE a.session_id = s.id)     AS sentences,
       (SELECT count(*) FROM chips.finding_units f
         WHERE f.session_id = s.id AND f.kind = 'fragment')                           AS fragment_units,
       (SELECT count(*) FROM chips.finding_units f
         WHERE f.session_id = s.id AND f.kind = 'case')                               AS case_units,
       s.created_at
FROM chips.elicitation_sessions s
JOIN chips.experts e ON e.id = s.expert_id
LEFT JOIN app.users u ON u.id::text = e.id
ORDER BY s.created_at;

\echo
\echo '== 1.3 anatomy of an id: <session>-<vignette>-<local id> =='
SELECT id,
       session_id,
       vignette_id,
       substr(id, length(session_id) + length(vignette_id) + 3) AS local_id,
       kind,
       highlight_id
FROM chips.finding_units
ORDER BY id;


-- ======================================================================================
-- 2. THE PATIENT'S TEXT: vignettes, highlights, cue keys (this is I2)
-- ======================================================================================
\echo
\echo '== 2.1 highlights: a span of the vignette (0-based offsets, [a,b)) + the expert''s toggle =='
-- cue_ok must be true everywhere: the span cut out of the vignette IS the cue key's text.
SELECT h.id, h.chip, h.origin, h.direction,
       lower(h.span) AS a, upper(h.span) AS b,
       left(substr(v.text, lower(h.span) + 1, upper(h.span) - lower(h.span)), 60) AS patient_words,
       substr(v.text, lower(h.span) + 1, upper(h.span) - lower(h.span)) = k.text AS cue_ok
FROM chips.highlights h
JOIN chips.vignettes v ON (v.id, v.version) = (h.vignette_id, h.vignette_version) AND v.tier = 'app'
JOIN chips.cue_keys  k ON k.id = h.cue_key_id
WHERE h.session_id = :'session_id'
ORDER BY lower(h.span);

\echo
\echo '== 2.2 cue keys are shared: one row per distinct (vignette, version, span), however many experts cite it =='
-- Today every cue key has 1 highlight because only one expert answered each vignette. With several
-- experts on the same vignette, `highlights_using` > 1 and that is the join that links them.
SELECT k.id, k.vignette_id, k.span, left(k.text, 50) AS patient_words,
       count(h.id) AS highlights_using, count(DISTINCT h.session_id) AS sessions
FROM chips.cue_keys k
LEFT JOIN chips.highlights h ON h.cue_key_id = k.id
GROUP BY k.id
ORDER BY highlights_using DESC, k.id
LIMIT 20;


-- ======================================================================================
-- 3. THE EXPERT'S TEXT: sentences
-- ======================================================================================
\echo
\echo '== 3.1 the sentences of one session, with their text (kept in the session document, not in the table) =='
-- answer_sentences holds only offsets + targets; the words live in elicitation_sessions.document.
SELECT a.question_id, a.idx, a.assigned_by,
       (SELECT string_agg(CASE WHEN t = 'case' THEN 'case'
                               ELSE substr(t, length(a.session_id) + length(a.vignette_id) + 3) END, ', ')
          FROM unnest(a.targets) t) AS targets,
       left(j ->> 'text', 80) AS sentence
FROM chips.answer_sentences a
JOIN chips.elicitation_sessions s ON s.id = a.session_id
CROSS JOIN LATERAL jsonb_array_elements(s.document -> 'sentences') j
WHERE a.session_id = :'session_id'
  AND j ->> 'id' = substr(a.id, length(a.session_id) + length(a.vignette_id) + 3)
ORDER BY a.question_id, a.idx;

\echo
\echo '== 3.2 how sentences were filed: chip (expert clicked), quote (matched the vignette), llm (classifier), expert =='
SELECT assigned_by, count(*) AS sentences,
       count(*) FILTER (WHERE targets = ARRAY['case']) AS filed_as_case_only,
       count(*) FILTER (WHERE cardinality(targets) > 1) AS several_targets
FROM chips.answer_sentences
GROUP BY assigned_by
ORDER BY sentences DESC;


-- ======================================================================================
-- 4. THE UNITS (what is retrieved)
-- ======================================================================================
\echo
\echo '== 4.1 units of the session: a fragment unit per cited highlight + one case unit =='
SELECT substr(f.id, length(f.session_id) + length(f.vignette_id) + 3) AS unit,
       f.kind, f.direction,
       (SELECT count(*) FROM chips.finding_unit_sentences x WHERE x.unit_id = f.id) AS sentences,
       (SELECT count(*) FROM chips.unit_cues c WHERE c.unit_id = f.id AND c.role = 'context') AS context_cues,
       length(f.embed_text) AS len_i1
FROM chips.finding_units f
WHERE f.session_id = :'session_id'
ORDER BY f.kind DESC, f.id;

\echo
\echo '== 4.2 the full lineage of the session: unit -> sentence -> where it was filed from =='
-- A sentence that cites two highlights appears under both units: that duplication is by design.
SELECT substr(f.id, length(f.session_id) + length(f.vignette_id) + 3) AS unit,
       fs.ord, a.question_id || '.' || a.idx AS sentence, a.assigned_by,
       left(j ->> 'text', 70) AS text
FROM chips.finding_units f
JOIN chips.finding_unit_sentences fs ON fs.unit_id = f.id
JOIN chips.answer_sentences a ON a.id = fs.sentence_id
JOIN chips.elicitation_sessions s ON s.id = f.session_id
CROSS JOIN LATERAL jsonb_array_elements(s.document -> 'sentences') j
WHERE f.session_id = :'session_id'
  AND j ->> 'id' = substr(a.id, length(a.session_id) + length(a.vignette_id) + 3)
ORDER BY f.kind DESC, f.id, fs.ord;

\echo
\echo '== 4.3 sentences that sit in more than one unit =='
SELECT fs.sentence_id, count(*) AS in_units,
       string_agg(f.kind || ':' || coalesce(substr(f.highlight_id, length(f.session_id) + length(f.vignette_id) + 3), 'case'), ', ') AS units
FROM chips.finding_unit_sentences fs
JOIN chips.finding_units f ON f.id = fs.unit_id
GROUP BY fs.sentence_id
HAVING count(*) > 1
ORDER BY in_units DESC, fs.sentence_id
LIMIT 20;

\echo
\echo '== 4.4 unit_cues: role cue = the unit''s own highlight, role context = co-cited highlights =='
SELECT c.role, count(*) AS rows, count(DISTINCT c.unit_id) AS units
FROM chips.unit_cues c
GROUP BY c.role;


-- ======================================================================================
-- 5. THE TWO EMBEDDED TEXTS: I1, I2
-- ======================================================================================
\echo
\echo '== 5.1 size of each stored representation (dense dims; sparse non-zero terms) =='
-- sparsevec text looks like {12:0.8,407:1.2}/1048576: the number of "term:weight" pairs is the BM25 terms.
SELECT substr(id, length(session_id) + length(vignette_id) + 3) AS unit, kind,
       vector_dims(embedding) AS dim_i1,
       cardinality(string_to_array(trim(both '{}' from split_part(sparse::text, '/', 1)), ',')) AS bm25_terms_i1,
       round(vector_norm(embedding)::numeric, 3) AS norm_i1
FROM chips.finding_units
WHERE session_id = :'session_id'
ORDER BY kind DESC, id;

\echo
\echo '== 5.2 I2 = chips.cue_keys.embedding (the patient''s words alone); the units point to it through unit_cues =='
SELECT substr(c.unit_id, length(f.session_id) + length(f.vignette_id) + 3) AS unit, c.role,
       k.id AS cue_key_id, left(k.text, 50) AS patient_words,
       vector_dims(k.embedding) AS dim_i2
FROM chips.unit_cues c
JOIN chips.finding_units f ON f.id = c.unit_id
JOIN chips.cue_keys k ON k.id = c.cue_key_id
WHERE f.session_id = :'session_id'
ORDER BY c.unit_id, c.role;


-- ======================================================================================
-- 6. RETRIEVAL, DONE BY HAND IN SQL (what expert-knowledge-rag sends to the database)
-- ======================================================================================
-- The unit chosen at the top is the "query" (its stored vectors stand in for an embedded question).
\echo
\echo '== 6.1 dense (cosine) over I1: the five units closest to the chosen unit =='
SELECT f.id AS unit, f.kind, f.direction,
       round((1 - (f.embedding <=> q.embedding))::numeric, 4) AS cosine,
       left(replace(f.embed_text, E'\n', ' '), 70) AS text
FROM chips.finding_units f, chips.finding_units q
WHERE q.id = :'unit_id' AND f.id <> q.id
ORDER BY f.embedding <=> q.embedding
LIMIT 5;

\echo
\echo '== 6.2 BM25 over I1: `sparse <#> q` is -BM25, so more negative = better; 0 = no shared term =='
SELECT f.id AS unit, f.kind,
       round((-(f.sparse <#> q.sparse))::numeric, 3) AS bm25,
       left(replace(f.embed_text, E'\n', ' '), 70) AS text
FROM chips.finding_units f, chips.finding_units q
WHERE q.id = :'unit_id' AND f.id <> q.id AND (f.sparse <#> q.sparse) < 0
ORDER BY f.sparse <#> q.sparse
LIMIT 5;

\echo
\echo '== 6.3 hybrid = both rankings fused with RRF (k = 60, depth 50), the production default over I1 =='
WITH q AS (SELECT embedding, sparse FROM chips.finding_units WHERE id = :'unit_id'),
dense AS (
  SELECT f.id, row_number() OVER (ORDER BY f.embedding <=> q.embedding) AS rank
  FROM chips.finding_units f, q ORDER BY f.embedding <=> q.embedding LIMIT 50),
sparse AS (
  SELECT f.id, row_number() OVER (ORDER BY f.sparse <#> q.sparse) AS rank
  FROM chips.finding_units f, q WHERE (f.sparse <#> q.sparse) < 0 ORDER BY f.sparse <#> q.sparse LIMIT 50),
fused AS (
  SELECT id, sum(1.0 / (60 + rank)) AS score
  FROM (SELECT * FROM dense UNION ALL SELECT * FROM sparse) r GROUP BY id)
SELECT f.id AS unit, f.kind, round(fused.score, 5) AS rrf_score,
       left(replace(f.embed_text, E'\n', ' '), 70) AS text
FROM fused JOIN chips.finding_units f ON f.id = fused.id
WHERE f.id <> :'unit_id'
ORDER BY fused.score DESC, f.id
LIMIT 5;

\echo
\echo '== 6.4 patient-text mode: nearest CUE KEYS (I2) to the chosen unit''s own cue, then the units behind them =='
SELECT k.id AS cue_key_id, left(k.text, 50) AS patient_words,
       round((1 - (k.embedding <=> q.embedding))::numeric, 4) AS cosine,
       f.id AS unit, f.kind, f.direction
FROM chips.unit_cues qc
JOIN chips.cue_keys q ON q.id = qc.cue_key_id
CROSS JOIN LATERAL (
  SELECT * FROM chips.cue_keys k2 WHERE k2.id <> q.id ORDER BY k2.embedding <=> q.embedding LIMIT 5) k
JOIN chips.unit_cues uc ON uc.cue_key_id = k.id AND uc.role = 'cue'
JOIN chips.finding_units f ON f.id = uc.unit_id
WHERE qc.unit_id = :'unit_id' AND qc.role = 'cue'
ORDER BY k.embedding <=> q.embedding;


-- ======================================================================================
-- 7. STAGING (app) VERSUS THE KNOWLEDGE BASE (chips)
-- ======================================================================================
-- app.knowledge_units = the cut units with their TEXTS (no vectors), status approved -> ingested.
-- chips.finding_units = the same units with VECTORS, written by the ingest job. 'removed' units are deleted from chips.
\echo
\echo '== 7.1 staging units by status and kind =='
SELECT status, kind, count(*) AS units, count(DISTINCT assignment_id) AS assignments
FROM app.knowledge_units
GROUP BY status, kind
ORDER BY status, kind;

\echo
\echo '== 7.2 every staged unit and whether (and how identically) it is in chips =='
SELECT ku.assignment_id, ku.review_round AS round, ku.ordinal, ku.status, ku.kind,
       coalesce(ku.highlight_id, 'case') AS local_id,
       fu.id IS NOT NULL AS in_chips,
       fu.embed_text = ku.embed_text AS same_i1
FROM app.knowledge_units ku
JOIN app.assignments a ON a.id = ku.assignment_id
JOIN app.vignette_versions vv ON vv.id = a.vignette_version_id
JOIN app.vignettes v ON v.id = vv.vignette_id
LEFT JOIN chips.finding_units fu
       ON fu.id = ku.assignment_id::text || '-' || v.code || '-' || coalesce(ku.highlight_id, 'case')
ORDER BY ku.assignment_id, ku.review_round, ku.ordinal;

\echo
\echo '== 7.3 workflow state of each assignment next to what it has in chips =='
SELECT a.id AS assignment_id, a.state, a.review_round,
       (SELECT count(*) FROM app.knowledge_units ku WHERE ku.assignment_id = a.id AND ku.status = 'ingested') AS ingested_units,
       (SELECT count(*) FROM chips.finding_units fu WHERE fu.session_id = a.id::text) AS units_in_chips
FROM app.assignments a
WHERE EXISTS (SELECT 1 FROM app.knowledge_units ku WHERE ku.assignment_id = a.id)
ORDER BY a.updated_at DESC;


-- ======================================================================================
-- 8. INTEGRITY CHECKS (each should return 0 rows / 0)
-- ======================================================================================
\echo
\echo '== 8.1 units with no sentence =='
SELECT f.id FROM chips.finding_units f
WHERE NOT EXISTS (SELECT 1 FROM chips.finding_unit_sentences x WHERE x.unit_id = f.id);

\echo
\echo '== 8.2 cue keys no highlight uses (removal should have deleted them) =='
SELECT k.id, k.text FROM chips.cue_keys k
WHERE NOT EXISTS (SELECT 1 FROM chips.highlights h WHERE h.cue_key_id = k.id);

\echo
\echo '== 8.3 sentence targets that name no highlight of the same session =='
SELECT a.id, t AS dangling_target
FROM chips.answer_sentences a, unnest(a.targets) t
WHERE t <> 'case' AND NOT EXISTS (SELECT 1 FROM chips.highlights h WHERE h.id = t AND h.session_id = a.session_id);

\echo
\echo '== 8.4 missing vectors (dense or sparse), units and cue keys =='
SELECT 'units: dense missing'  AS problem, count(*) FROM chips.finding_units WHERE embedding IS NULL
UNION ALL SELECT 'units: sparse missing', count(*) FROM chips.finding_units WHERE sparse IS NULL
UNION ALL SELECT 'cue keys: sparse missing', count(*) FROM chips.cue_keys WHERE sparse IS NULL;

\echo
\echo '== 8.5 fragment units whose highlight has no cue row in unit_cues, and case units that have one =='
SELECT f.id, f.kind FROM chips.finding_units f
WHERE (f.kind = 'fragment' AND NOT EXISTS (SELECT 1 FROM chips.unit_cues c WHERE c.unit_id = f.id AND c.role = 'cue'))
   OR (f.kind = 'case'     AND EXISTS     (SELECT 1 FROM chips.unit_cues c WHERE c.unit_id = f.id));
