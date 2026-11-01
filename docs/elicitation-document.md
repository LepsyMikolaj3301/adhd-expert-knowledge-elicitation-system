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
| `schema_version` | `"1.0"` | |
| `is_synthetic` | bool | must be true exactly when `expert_id` starts with `SYN-` |
| `vignettes[]` | `Vignette` | in the order shown; ids unique |
| `responses[]` | `Response` | at most one per vignette; may be fewer than vignettes (session ended early) |

**Vignette** — `id` (`V001`), `version`, `text` (120–250 words, checked by the fixture generator),
`framing` (`forum_post` / `personal_journal` / `email`), `question_ids` (subset of Q1–Q6),
`q4_element` (fills Q4, required when Q4 is asked), optional `variant` (`pair_id`, `arm` A/B, `change`
for B), `content_hash` (sha256 of `text`, auto-filled, verified) and the hidden `design` block
(`purpose`, `planted_cues`, `confounders`, `is_control`). Every cue/confounder `quote` must be an exact
substring of `text`. The platform shows the expert `Vignette.expert_view()`, which omits `design`.

**Response** — `vignette_id` + `vignette_version` + `vignette_hash` (must match the vignette shown),
`expert_id`, `is_synthetic`, `answers` (`{"Q1": "…"}`, open questions only, none blank),
`quoted_fragments` (fragments the expert marked in the text; exact substrings), `rating` (1–5, Q6),
`insufficient_information` (Q6 alternative, exclusive with `rating`), `started_at`, `submitted_at`.

**ReferenceClaim** is not part of the document. Fixtures store a flat `list[ReferenceClaim]` next to it
(`data/fixtures/<tier>/claims/<session_id>.claims.json`) as the expected output of claim extraction;
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
