# ElicitationDocument

One expert's output from one session on the web platform: the vignettes they were shown, in order,
and their written answers. **It is the unit the backend ingests.** Code: `backend/app/elicitation/schema.py`;
JSON Schema: `data/schemas/elicitation_document.schema.json` (regenerate with `python scripts/elicitation/export_schema.py`).

A document is immutable once submitted. Everything derived from it (extracted claims, member-check
results, approval) lives in separate backend records that point to `session_id`.

## Fields

| Field | Type | Notes |
|---|---|---|
| `session_id` | str | unique per session |
| `expert_id` | str | `SYN-…` for synthetic experts |
| `created_at` | datetime (tz-aware) | |
| `schema_version` | `"1.1"` | 1.1: Q4 is a what-if scale, Q1–Q3 gate the rest (1.0 files: `migrate_q4_whatif.py`) |
| `is_synthetic` | bool | must be true exactly when `expert_id` starts with `SYN-` |
| `vignettes[]` | `Vignette` | in the order shown; ids unique |
| `responses[]` | `Response` | at most one per vignette; may be fewer than vignettes (session ended early) |

**Vignette** — `id` (`V001`), `version`, `text` (120–250 words, checked by the fixture generator),
`framing` (`forum_post` / `personal_journal` / `email`), `question_ids` (subset of Q1–Q6),
`q4_whatif` (written by the vignette author: a clause completing "how would your hypothesis change
if …?", e.g. *the writer had an exam earlier that day*; not a quote from `text`; required when Q4 is
asked), optional `variant` (`pair_id`, `arm` A/B, `change`
for B), `content_hash` (sha256 of `text`, auto-filled, verified) and the hidden `design` block
(`purpose`, `planted_cues`, `confounders`, `is_control`). Every cue/confounder `quote` must be an exact
substring of `text`. The platform shows the expert `Vignette.expert_view()`, which omits `design`.

**Response** — `vignette_id` + `vignette_version` + `vignette_hash` (must match the vignette shown),
`expert_id`, `is_synthetic`, `answers` (`{"Q1": "…"}`: open questions and Q4's optional *why*, none
blank), `quoted_fragments` (fragments the expert marked in the text; exact substrings), `rating` (1–5,
Q6), `insufficient_information` (Q6 alternative, exclusive with `rating`), `q4` (`ShiftAnswer`, see
below), `started_at`, `submitted_at`.

**ShiftAnswer** (`Response.q4`): Q4 is a short Script Concordance item. `hypothesis` (optional, the
expert's working hypothesis in one sentence), `shift` (−2 *strongly reinforced*, −1 *somewhat
reinforced*, 0 *unchanged*, +1 *partly changes*, +2 *changes completely*; labels in
`questions.SHIFT_LABELS`), `toward` (`more_adhd` / `less_adhd` / `other`, only for +1 and +2) and
`other_explanation` (exactly when `toward` is `other`). The *why* lives in `answers["Q4"]` and is
allowed only with a non-zero shift. The answering apps require the hypothesis, the direction (for
+1/+2) and the why (for a non-zero shift); the schema keeps them optional.

**Gate**: Q1–Q3 (`questions.GATE`) come first. A response with anything for Q4, Q5 or Q6 must have a
non-blank answer to every gate question the vignette asks (`gate_not_passed`). The answering apps
also lock Q1–Q3 once the expert has moved on, so the hypothesis is recorded before the what-if is seen.

Error codes added in 1.1: `q4_without_whatif`, `q4_why_without_shift`, `toward_without_change`,
`other_without_name`, `gate_not_passed`.

**ReferenceClaim** is not part of the document. Fixtures store a flat `list[ReferenceClaim]` next to it
(`data/fixtures/<source>/<tier>/claims/<session_id>.claims.json`) as the expected output of claim extraction;
how far to trust it depends on the tier, see [fixtures.md](fixtures.md).

## Lifecycle

```
submitted → extracted → member_checked → approved
                                       ↘ rejected
```

1. **submitted** – document validated and stored.
2. **extracted** – an LLM pulled claims out of the answers.
3. **member_checked** – the expert confirmed/corrected the extracted claims.
4. **approved / rejected** – terminal. Only approved claims reach the knowledge base.

Transitions are defined in `backend/app/elicitation/lifecycle.py`.

## Synthetic documents

Synthetic documents (`is_synthetic=true`, `expert_id` starting `SYN-`) exist for tests and evaluation.
**They can never be ingested into the production knowledge base.** `assert_ingestible(doc, production=True)`
raises `SyntheticIngestionError`; any ingestion path to the production KB must call it. They may go
through the lifecycle and into a test KB.
