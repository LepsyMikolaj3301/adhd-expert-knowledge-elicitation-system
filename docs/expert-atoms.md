# Expert atoms: a proposed architecture for expert knowledge

How the knowledge in expert answers to vignettes could be extracted as small, checked, retrievable
**atoms**, stored in Postgres and put into the generator's prompt. This is a design, not code:
nothing here is built. The shipped representation is still B1 (verbatim units, see
[expert-knowledge.md](expert-knowledge.md)) until atoms beat it on the same eval (see *Decision rule*).

Constraints this design keeps:

- **Elicitation stays vignette-based.** Admins create vignettes and choose or write the questions per
  vignette; questions can change over time.
- **Retrieval stays Postgres hybrid:** pgvector dense + BM25 `sparsevec`, fused with RRF. No graph
  database; relations are foreign keys and columns.
- **Models are local** (qwen3.5:9b class, `num_ctx 8192`). Extraction is offline and may use a larger
  local model.

## Why atoms, and what the earlier results say

- Retrieval units that are atomic and self-contained retrieve better than passages
  ([Dense X Retrieval](https://arxiv.org/abs/2312.06648)). Rule-cut verbatim units (B) are tied to how
  Claude wrote the silver answers (quote marks, `(a)` labels, clean punctuation); real experts will
  write differently.
- LLM paraphrases without checks distort: on silver, 7.7% of reading rules flip a claim's direction and
  33% drop its condition (word-overlap heuristic, `data/eval/expert_units/latest.json`). In generation,
  rules alone passed less often than verbatim units (0.25 / 0.17 against 0.45 / 0.38).
- So an atom is never shown alone: **the LLM-written fields are for search and summary; the expert's
  verbatim sentences are the evidence, cited and shown next to them.** Extraction is done in stages and
  checked, following claim-extraction work ([Claimify](https://arxiv.org/abs/2502.10855v1),
  [FActScore-style verification](https://arxiv.org/html/2404.10774v1)).

## Terms

| Term | Meaning |
|---|---|
| **atom** | one piece of expert reasoning about a vignette: what in the text, what it means, under which condition, how sure |
| **cue** | a span of the vignette text the atom is about (character offsets) |
| **evidence** | spans of the expert's own answers that support the atom (character offsets, verbatim) |
| **point** | atoms from different experts that make the same point about the same cue (`point_id`) |
| **panel view** | per point: how many of the experts who answered the vignette made it, and who differs |

## Atom types

Types do not depend on the questions, so admins can change questions without breaking extraction. A
question can carry `expected_types` as a hint; any type can come from any answer, and one atom can draw
on several answers.

| Type | What it holds | Typical source |
|---|---|---|
| `reading` | cue → interpretation (trait, why) | "which fragments are relevant" |
| `alternative` | cue → other explanation(s) and how to tell them apart | "what else could explain it" |
| `info_need` | what is missing before the reading means anything | "what is missing" |
| `sensitivity` | if X were different → the reading changes this way | "how would it change if…" |
| `pitfall` | what a less experienced clinician would over- or under-read | "what would a novice miss" |
| `null_finding` | this is not evidence / normal variation / base rate | any, often control vignettes |
| `overall` | judgement about the case as a whole, not tied to one cue | first reading, rating rationale |

## Who fills what

Four kinds of content, kept apart in storage and in the prompt:

| Kind | Written by | Changed later? | Shown in the prompt as |
|---|---|---|---|
| **Source data** | the expert (answers, highlights, rating) and the admin (vignette text, question text) | never; versioned | the expert's or patient's own words |
| **Metadata** | the platform and the admin (ids, versions, expert profile, vignette design, `expected_types`) | versioned | header facts (role, case type) |
| **Derived by code** | deterministic code (spans from sentence numbers, checks on keywords, grouping, counts, embeddings) | recomputed when the code version changes | counts ("2 of 2 clinicians") |
| **Derived by the LLM** | the extraction model, then checked; optionally confirmed or edited by the expert | re-extractable until confirmed; frozen once confirmed or edited | the atom's summary line, labelled as a reading, never as a quote |

Field by field:

| Field | Filled by | Kind | Checked by | Why it exists |
|---|---|---|---|---|
| `atom_id`, `session_id`, `expert_id` | platform | metadata | - | identity, retraction |
| `type` | LLM | LLM-derived | second extraction run; expert | question-independent structure |
| `scope` (`case` / `pattern` / `rule`) | LLM | LLM-derived | code + LLM: `pattern`/`rule` need a `scope_evidence` phrase | stops a remark about one case becoming a general rule |
| `scope_evidence` | LLM picks a sentence; code stores the span | source data (verbatim) | code: the span exists | proof that the expert generalised |
| `cues[]` (span, role `cue`/`context`) | expert highlights first, then quotes in the answers (code), then vignette sentence numbers chosen by the LLM | source data (offsets into the vignette) | code: offsets valid | ties the atom to the patient's words; `context` keeps cue combinations |
| `reading` | LLM | LLM-derived | blind entailment check; second run; expert | the searchable, self-contained statement |
| `alternatives[]`, `discriminator` | LLM | LLM-derived | entailment check against the evidence | the two things a clinician most needs, as separate fields so they cannot silently drop |
| `condition` | LLM, must cite a sentence number | LLM-derived + source span | code: conditional words in the evidence but no condition → flag; blind LLM search for a missed condition | omission was the silver failure (33%) |
| `direction` | LLM | LLM-derived | blind LLM re-classification from the evidence only; code: negation near the cue; code: consistency with the expert's rating; expert toggle | flips were the silver failure (7.7%) |
| `certainty` + `certainty_evidence` | LLM picks the hedge sentence; level only if a hedge or emphasis phrase exists | LLM-derived + source span | code: the phrase exists | keeps "I cannot tell either way" from becoming a firm rule |
| `evidence[]` (question@version, span) | LLM chooses answer sentence numbers; code turns them into spans | source data (verbatim, by offsets) | code: offsets valid | the citation; the only text shown under the expert's name |
| `status` | checks, then the expert | metadata | - | `unverified` / `verified` / `confirmed` / `edited` / `rejected` |
| `checks` | code and checker calls | derived by code | - | which checks passed, extraction agreement (e.g. `2/2`) |
| `extractor` | platform | metadata | - | model, prompt version, for re-extraction and audit |
| `point_id` | code (overlapping cues + same type + same direction) | derived by code | - | grouping across experts |

## Flow

```
ADMIN     1 author vignette (text, design, version) and its questions (text, version, expected_types)
            │
EXPERT    2 session: read the vignette, highlight passages, answer the questions, rate
            │                                         → stored as source data, never edited
LLM       3 extract candidate atoms (JSON): evidence, cues, condition, scope evidence given as
            │ SENTENCE NUMBERS, not copied text; input = numbered vignette + highlights +
            │ questions at their version + all answers of this expert to this vignette (1-2k tokens)
CODE      4 resolve sentence numbers to character spans; snap cues to the expert's highlights
            │
CODE+LLM  5 checks per field (see below) + a second extraction run; disagreement → field flagged,
            │ atom `unverified`; nothing is auto-corrected
EXPERT    6 confirmation right after each vignette: atoms shown next to the highlighted source;
            │ accept / edit / reject; flagged fields highlighted ("Did you mean lowers?")
CODE      7 group into points across experts; compute panel counts from the responses
            │
CODE      8 index: embed atoms (dense + BM25) and cue keys (vignette spans, patient wording)
            │
QUERY     9 retrieve (clinician question → atoms; patient text → cue keys → atoms)
            │
CODE     10 pack the prompt: atom summary + verbatim evidence + caveat + panel line
```

Steps 3 to 5 can rerun when the extractor improves; atoms the expert confirmed or edited are kept as
they are. Deleting an expert cascades to their sessions, atoms and evidence; points and panel counts
are recomputed.

## Checks

Checks lower and measure the error rate; they do not remove it. LLM checks are made as independent
as possible: a different model family where available, **blind** (the checker sees only the evidence,
never the atom, so it cannot simply agree), and a different task (classify, not write). Code checks are
crude but share no failure mode with the LLM. The expert's confirmation is the only ground truth.

| Field | Code checks | LLM checks | Human |
|---|---|---|---|
| `reading` | evidence spans exist | entailment: evidence ⊨ reading | confirm / edit |
| `direction` | negation near the cue ("not", "rather than", "would not assign") against `raises`; rating consistency (a `raises` atom from an "insufficient information" response is flagged, not rejected) | blind re-classification from the evidence | raises / lowers / neutral toggle |
| `condition` | conditional words in the evidence ("unless", "if", "only when", "except", "without that", "before") but `condition` empty → flag | blind "does the expert say when this would change? give the sentence number" | confirm / edit |
| `scope` | `pattern` / `rule` without `scope_evidence` → downgraded to `case` | blind "does the expert generalise beyond this case?" | confirm / edit |
| `certainty` | the hedge phrase exists | - | confirm / edit |
| all | - | second extraction run; atoms matched by cue overlap | missing-something box (coverage) |

## Storage (Postgres)

```sql
-- admin-defined questions, versioned (replaces the fixed Q1-Q6 set)
CREATE TABLE questions (
    id text, version integer, text text NOT NULL, kind text NOT NULL,     -- open | rating_1_5 | shift
    expected_types text[] NOT NULL DEFAULT '{}',
    PRIMARY KEY (id, version)
);

CREATE TABLE atoms (
    id text PRIMARY KEY,
    session_id text NOT NULL REFERENCES elicitation_sessions ON DELETE CASCADE,
    expert_id text NOT NULL,
    vignette_id text NOT NULL, vignette_version integer NOT NULL,
    type text NOT NULL, scope text NOT NULL,
    reading text NOT NULL, alternatives text[] NOT NULL DEFAULT '{}', discriminator text,
    condition text, direction text NOT NULL, certainty text,
    status text NOT NULL, checks jsonb NOT NULL, extractor jsonb NOT NULL,
    point_id text,
    population text NOT NULL, track text NOT NULL, framing text NOT NULL, is_synthetic boolean NOT NULL,
    embed_text text NOT NULL, embedding vector(1024) NOT NULL, sparse sparsevec(1048576)
);

-- verbatim spans of the expert's answers (evidence, condition, certainty, scope evidence)
CREATE TABLE atom_evidence (
    atom_id text REFERENCES atoms ON DELETE CASCADE,
    role text NOT NULL,                       -- evidence | condition | certainty | scope
    question_id text NOT NULL, question_version integer NOT NULL,
    span int4range NOT NULL
);

-- vignette spans the atom is about
CREATE TABLE atom_cues (
    atom_id text REFERENCES atoms ON DELETE CASCADE,
    cue_key_id bigint NOT NULL REFERENCES cue_keys,
    role text NOT NULL                        -- cue | context
);

-- one row per cited vignette span, shared by every atom (of every expert) that cites it;
-- searched by patient text, like with like
CREATE TABLE cue_keys (
    id bigserial PRIMARY KEY,
    vignette_id text NOT NULL, vignette_version integer NOT NULL, span int4range NOT NULL,
    text text NOT NULL,
    embedding vector(1024) NOT NULL, sparse sparsevec(1048576),
    UNIQUE (vignette_id, vignette_version, span)
);
```

Experts, vignettes, sessions and responses are as in the relational layout already discussed (pseudonymous
`experts`, versioned `vignettes`, `elicitation_sessions` holding the raw `ElicitationDocument`,
`expert_responses` for the "n of N answered" counts). BM25 is fitted separately for `atoms` and for
`cue_keys`, never together with literature `chunks`.

`embed_text` is built by code from the fields:

```
<type> · <population>'s <framing> · <direction> · about this case|as a pattern|as a rule
<reading>
Tell apart by: <discriminator>. <condition>
```

## Retrieval

Two ways in, one output.

| Mode | Query | Search | Then |
|---|---|---|---|
| clinician question | "How do I tell grief-related procrastination from distractibility?" | dense + BM25 over `atoms` (filter: `status IN (confirmed, edited, verified)`, population), RRF | roll up to `point_id`, MMR, fill the expert token budget |
| patient text | a new patient's text | split into sentences; dense + BM25 over `cue_keys`, RRF per sentence | `atom_cues` → atoms; bonus when an atom's `cue` and `context` both match; roll up and fill as above |

A final query fetches each chosen point's members, their verbatim evidence (sliced from the stored
answers by offset) and the panel counts.

## In the prompt

System prompt rule: *Expert readings are clinician opinions on teaching cases. Rank them below
guidelines, never state them as diagnostic criteria, and keep their scope and certainty when you cite
[E#].* The judge rubric already scores attribution and fidelity; stating an atom as a rule fails
attribution.

Each point is packed as one block: case line (code, from metadata), the patient's words (source),
the reading (LLM-derived, labelled with scope, direction and certainty), the expert's verbatim
evidence and caveat (source), and the panel line (code). See the example below.

## Worked example (hand-written illustration)

Real silver data: vignette V003 (an adult's forum post about a tax return) and the answers of
`SYN-001` (consultant psychiatrist, session `DOC-SYN-0001`). The atoms were written by hand following
this design; no extractor produced them.

Vignette excerpt (offsets are into the full text):

> …**I spent twenty minutes staring at a spreadsheet for 'Q3 Income' then decided to reorganize my
> entire desktop by icon color instead** [115–245]… (Also, **lost mom last spring and things are just
> heavy right now** [295–351]…) …I need to **stop scrolling Pinterest for wallpaper ideas** [593–637]…

Answers (excerpts):

- Q1: *…two things look like ADHD: "…reorganize my entire desktop…" and "stop scrolling Pinterest…" -
  **but that is what everyone does with a tax return, and the writer says** [260–308] "lost mom last
  spring…"*
- Q2: *"**All of it would sit with grief or just a dreaded task** [0–53]… **What would separate: how
  paperwork went before spring.** [146–200]"*
- Q5: *"**Under: assuming grief explains everything when an older pattern may sit under it - I cannot
  tell either way.** [135–243]"*

The point is spread over three answers, so it can only be captured by extracting from the whole
response, not answer by answer.

### All atoms from this response

| Atom | Type | Direction | Scope | Draws on |
|---|---|---|---|---|
| 01 | `null_finding`: drifting to other screen tasks during a tax return is ordinary | lowers | pattern ("that is what everyone does with a tax return") | Q1 |
| 02 | `reading`: "usually hate paperwork" next to "so hard" is contradictory; baseline unclear | neutral | case | Q1 |
| 03 | `alternative`: the drifting fits grief or task dread better than attention; baseline separates them | lowers | case | Q1, Q2, Q5 |
| 04 | `info_need`: anything written before the bereavement; ask about the "numbers might run away" line | neutral | case | Q3 |
| 05 | `sensitivity`: without the bereavement, slightly more interesting, still one post, still needs a baseline | raises (low certainty) | case | Q4 |
| 06 | `pitfall`: over-reading desktop, Pinterest and the tax-form muddle (unfamiliar form, not attention) | lowers | case | Q5 |
| 07 | `pitfall`: under-reading: grief may hide an older pattern | raises (low certainty) | case | Q5 |
| 08 | `overall`: one short, self-aware vent with no history; no traits assigned; rated insufficient information | neutral | case | Q1, rating |

One sentence can support several atoms (the Q5 "Under" sentence is atom 07 and the condition of atom 03).

### Atom 03 in full

```json
{
  "atom_id": "AT-DOC-SYN-0001-V003-03",
  "type": "alternative",
  "scope": "case",
  "scope_evidence": null,
  "cues": [
    {"vignette": "V003@v1", "span": [115, 245], "role": "cue"},
    {"vignette": "V003@v1", "span": [593, 637], "role": "cue"},
    {"vignette": "V003@v1", "span": [295, 351], "role": "context"}
  ],
  "reading": "Switching from a tax spreadsheet to reorganising the desktop and scrolling Pinterest is better explained by grief after a recent bereavement, or by ordinary dread of a tedious task, than by an attention problem.",
  "alternatives": ["grief after bereavement", "dread of a tedious task"],
  "discriminator": "how paperwork went before the bereavement",
  "condition": "unless an older pattern predates the bereavement",
  "direction": "lowers",
  "certainty": "moderate",
  "certainty_evidence": {"question": "Q5@v1", "span": [135, 243]},
  "evidence": [
    {"question": "Q1@v1", "span": [260, 308]},
    {"question": "Q2@v1", "span": [0, 53]},
    {"question": "Q2@v1", "span": [146, 200]},
    {"question": "Q5@v1", "span": [135, 243]}
  ],
  "session_id": "DOC-SYN-0001",
  "expert_id": "SYN-001",
  "status": "confirmed",
  "checks": {"reading": "entailed", "direction": "ok", "condition": "ok", "scope": "ok", "agreement": "2/2"},
  "extractor": {"model": "…", "prompt": "Expert_atoms.v1"},
  "point_id": "V003v1:p02"
}
```

Where each part came from:

| Part | Kind | How |
|---|---|---|
| ids, `Q1@v1`, `V003@v1` | metadata | platform |
| `cues` spans | source data | 115–245 and 295–351 are the expert's own highlights (`quoted_fragments`), also quoted in Q1; 593–637 is a quote in Q1 matched by code. The LLM chose the roles (295–351 as `context`) |
| `type`, `scope`, `reading`, `alternatives`, `discriminator`, `condition`, `direction`, `certainty` | LLM-derived | extraction, then checks; confirmed by the expert |
| `evidence`, `certainty_evidence` spans | source data | LLM chose sentence numbers; code made the spans |
| `checks`, `point_id` | derived by code | checks and grouping |
| `status: confirmed` | human | expert accepted it after the vignette |

Checks this atom passes: entailment of the reading by Q2 [0–53]; blind direction from the evidence
alone gives `lowers`; the conditional "Under: assuming… may sit under it" is covered by `condition`;
no generalising phrase, so `scope: case`; the rating ("insufficient information") is consistent with
`lowers`.

### Stored for search

`atoms.embed_text`:

```
alternative · adult's forum post · lowers · about this case
Switching from a tax spreadsheet to reorganising the desktop and scrolling Pinterest is better explained by
grief after a recent bereavement, or by ordinary dread of a tedious task, than by an attention problem.
Tell apart by: how paperwork went before the bereavement. Unless an older pattern predates the bereavement.
```

`cue_keys` rows (patient wording; shared with every atom citing the same span, from any expert):
`V003@v1 [115,245]` "I spent twenty minutes staring at a spreadsheet… reorganize my entire desktop by
icon color instead", `[593,637]`, `[295,351]`.

### Retrieved

- **Clinician question** "How do I tell grief-related procrastination from ADHD distractibility in what
  a patient writes?" → BM25 and dense match "grief", "procrastination", "distractibility" in the
  atom → point `V003v1:p02`.
- **Patient text** "Spent the whole evening rearranging my bookshelf instead of filling in the benefits
  form. Dad's funeral was in March." → sentence 1 matches cue key [115–245], sentence 2 matches the
  context key [295–351] → atom 03, with the cue-plus-context bonus.

### Packed into the prompt (about 180 tokens)

```
[E1] Teaching case V003: an adult's forum post about a tax return, recent bereavement
  Patient's words: "…reorganize my entire desktop by icon color instead…" · "…stop scrolling Pinterest…"
  Reading (about this case · lowers · moderate certainty):
    The switching is better explained by grief or dread of a tedious task than by an attention problem.
    Tell apart by: how paperwork went before the bereavement.
  Clinician 1 (consultant psychiatrist): "All of it would sit with grief or just a dreaded task …
    What would separate: how paperwork went before spring."
    Caveat: "assuming grief explains everything when an older pattern may sit under it - I cannot tell either way."
  Panel: 2 of 2 clinicians who answered read it this way. Clinician 2 (clinical psychologist): "did she do
    paperwork on time before last spring, and does the desktop tidying happen when she is not sad?"
    Also noted it is "the classic shape".
```

| Line | Kind |
|---|---|
| case line | metadata, rendered by code |
| patient's words | source data (vignette spans) |
| reading, tell apart by | LLM-derived (confirmed), labelled with scope, direction, certainty |
| clinician quotes, caveat | source data (verbatim evidence spans) |
| panel line | derived by code; Clinician 2's quotes are source data from their own Q2 and Q1 |

Clinician 2 (`DOC-SYN-0002`) really makes the same point in their Q2, so the panel count is real; their
"classic shape" remark is kept so the agreement is not overstated. A good answer then reads like: *in
a similar teaching case, two clinicians read this switching as grief or task dread rather than
distractibility, and both said only the pre-bereavement baseline separates them [E1].*

## Problems to keep in mind

1. **Over-generalising** a remark about one case into a rule. Addressed by `scope` with required
   evidence; the most important check.
2. **Flattened hedges and dropped conditions.** Separate fields, omission checks, the verbatim caveat in
   the prompt.
3. **Cue combinations and whole-case judgements.** Several cues per atom, `context` role, the `overall`
   type.
4. **Skipped "not evidence" statements.** The `null_finding` type; check coverage on control vignettes.
5. **Unclear atom size.** Needs a written guideline with 2-3 examples per type; measure whether two
   people splitting the same answers agree.
6. **Correlated LLM errors.** Blind checks, a different model family, code checks, expert confirmation.
7. **Rubber-stamping.** Track edit and reject rates per expert; near zero edits is a warning.
8. **Consensus made up by normalising.** Panel lines quote each expert verbatim; only same cue, type and
   direction count as the same point.
9. **Short atoms retrieve less precisely** (rules alone had a lower nDCG than verbatim units). The atom
   always comes back with its verbatim evidence and case line.
10. **The 9B generator is the current limit** (oracle context passes no more often than retrieved
    units). Structured fields may help a two-step answer (list the readings, then summarise); that is a
    hypothesis to test, not a reason to build atoms.

## Code that has to change

- `QuestionId` is a fixed set of literals in [schema.py](../scripts/elicitation/elicitation_schema.py) and
  `QUESTIONS` a fixed tuple in [questions.py](../backend/app/vignettes/questions.py): questions need
  to become versioned rows, and a response must record the version it answered.
- `QUESTION_GIST` is hard-coded in [units.py](../scripts/elicitation/elicitation_units.py); the header must come
  from the question row.
- `Response.quoted_fragments` (the expert's highlights) is not used by `units.py`; atoms use it as the
  first source of cues.
- New: an extraction prompt (`prompts/Expert_atoms.v1.md`), the checks, the confirmation step on the
  platform, the tables above and an atom retriever beside `retrieve` in `rag_common.py`.

## Decision rule and evaluation

Silver cannot decide this: Claude wrote the answers, the reference claims and the questions. Use
answers written by people (a pilot with 2-3 clinicians, 5 or so vignettes, before gold).

1. Write the atom guideline (definition, the 7 types, 2-3 examples each; atom 03 can be the
   `alternative` example). Two people split 10-15 answers by hand: their agreement shows whether the
   definition works, and the result is the gold set for steps 2 and 3.
2. Atom-level: precision (the evidence supports the atom), coverage (share of expert sentences that end
   up in some atom), scope errors, direction flips and condition omissions, with and without each
   check, against silver's 7.7% and 33%.
3. Against B1 on the existing harness: retrieval (pooled labels, recall@4, nDCG@10) and generation
   (key points, fidelity, attribution, pass rate; two judge passes). Atoms replace B1 only if they are
   not worse on retrieval and better on generation pass rate or attribution; otherwise B1 stays and
   atoms can still serve as metadata (type, direction, cues) on the units.

## References

- Dense X Retrieval, propositions as retrieval units: https://arxiv.org/abs/2312.06648
- Claimify, staged claim extraction and ambiguity handling: https://arxiv.org/abs/2502.10855v1
- MiniCheck, checking claims against grounding documents: https://arxiv.org/html/2404.10774v1
- FActBench, NLI plus chain-of-thought verification: https://arxiv.org/html/2509.02198v1
- Annotator rationales (highlight the evidence for a judgement): https://preview.aclanthology.org/fix_video/N07-1033.pdf
- LLM-in-the-loop thematic analysis (codebook with a human): https://arxiv.org/abs/2310.15100v1
- Script concordance tests, scoring against an expert panel: https://pmc.ncbi.nlm.nih.gov/articles/PMC4989333
- Structured expert elicitation and aggregation: https://eprints.whiterose.ac.uk/id/eprint/220470/1/PIIS1098301524028432.pdf
- Case-based reasoning RAG: https://arxiv.org/abs/2404.04302v1

## Atoms or verbatim units? (review, 2026-11-02)

A second look at whether the checks and processing above are worth it, or whether verbatim units
(processed, but still the expert's own words) are enough. This section does not pick one; it records
the trade-offs and the tests that would decide.

### What the data says so far (silver)

Silver is development data (Claude wrote the answers, the claims and the questions), so these are
indications, not results.

| | nDCG@10 | hit@4 | tokens / item | generation pass rate | attribution | fidelity |
|---|---|---|---|---|---|---|
| B. verbatim units | **0.590** | **1.00** | 138 | - | - | - |
| B1. lean units (shipped) | 0.574 | 0.95 | 123 | **0.45 / 0.38** | **3.98 / 3.90** | **3.83 / 3.70** |
| D. units + LLM keys | 0.536 | 1.00 | 138 | - | - | - |
| C. LLM rules only | 0.513 | 0.90 | 39 | 0.25 / 0.17 | 3.75 / 3.62 | 3.58 / 3.50 |
| A. raw answers | 0.490 | 0.98 | 83 | - | - | - |

- **In practice the verbatim units were best**: top rank quality, a relevant unit in the top 4 for
  every question, and about 0.20 higher pass rate than LLM rules. Keys, leaner units and diversity
  re-ranking added nothing measurable.
- LLM-written text lost every comparison so far (rules flipped direction in 7.7% and dropped the
  condition in 33%, word-overlap heuristic).
- The 9B generator is the limit, not retrieval: perfect (oracle) context does no better, and 55% of
  failed answers distort their notes at generation time.
- **Atoms have never been extracted or tested.** Everything said for them is reasoning from the
  literature and from these failures.

### Verbatim processed units

For:

- Measured, and it won on ranking and on generation.
- Cannot distort at ingest: nothing the expert did not write is stored as their knowledge, so no checks
  and no member check are needed for safety.
- Cheap and deterministic: no LLM calls at ingest, reproducible, re-runs in seconds, retraction is a
  delete.
- No extra expert time.
- Easy to defend in the thesis: the system retrieves what clinicians wrote.

Against:

- The segmentation rules are tuned to Claude's writing (quote marks, `(a)` labels, clean
  punctuation); how they hold on real experts is unknown.
- A point spread over several answers is split (V003: Q1, Q2 and Q5). Retrieval may return one piece
  without the condition, which sits in another unit.
- Interpretation happens at query time, every time, unchecked: the 9B model turns "here, given the
  bereavement…" into advice, which is where the fidelity failures happen.
- No structure: no filtering by type or direction, and no "2 of 3 agree", because overlapping quotes
  only show that experts discussed the same passage, not that they agreed.
- Patient-text mode is weak (0.00 to 0.12): patient prose is matched against clinician commentary.

### Atoms with checks

For:

- Interpretation is done once, at ingest, where it can be checked (and ideally confirmed), instead of
  unchecked at every query.
- Points spread across answers can be captured, since extraction sees all of an expert's answers to
  a vignette.
- Structure: panels with agreement and disagreement, filtering, SCT-style counts, a knowledge base an
  admin can browse, and analysis for the thesis (what kinds of knowledge experts give).
- Robust to writing style and probably to language, since an LLM reads the answers, not regex rules.

Against:

- Unproven, and its closest tested relatives (C, D) lost.
- Distortion risk moves rather than disappearing: checks catch part of it, LLM checkers make correlated
  mistakes, and over-generalising from one case is the hardest error to catch.
- Not cheaper in the prompt: an atom with its verbatim evidence is about 180 tokens against about 123
  for a unit. The evidence that makes atoms safe also makes them bigger.
- Much more to build and maintain: extraction prompt, checks, confirmation UI, frozen versus
  re-extractable versions, more tables.
- Expert time: confirming about 8 atoms per vignette at 15 to 20 seconds each adds a few minutes per
  vignette (estimate). Rubber-stamping can make that time worthless.
- Cannot be evaluated without human annotation: a guideline, two people splitting answers, a gold set.

### Benefits that do not need atoms

| Benefit | Needs LLM-written atoms? |
|---|---|
| Patient-text mode via a cue index (vignette span → expert text) | no: units have `quote_spans`, highlights give more |
| Grouping experts by the passage they discuss | no: overlapping spans |
| Admin-editable, versioned questions | no: a schema change either way |
| Robust segmentation for real experts | not fully: an LLM can choose sentence boundaries while the text stays verbatim |
| Points spread across answers | partly: link units across answers (LLM chooses links), keep the text verbatim |
| Agree / disagree panels, filtering by type or direction | yes, or at least LLM labels |
| Interpretation checked once instead of at every query | yes |

So the real question is narrower than "atoms or units": whether **labels and checked interpretation**
are needed, which only an LLM-derived layer gives.

### A range of options

Each level keeps the verbatim text of the one before, so stopping at any level wastes nothing.
Effort and timing are rough estimates.

| Level | What it is | Ingest LLM calls per response | Expert time | Build effort | Main risk |
|---|---|---|---|---|---|
| 1. B1 as is | rule-cut verbatim units | 0 | 0 | done | rules break on real experts |
| 2. Robust verbatim | 1 + LLM chooses boundaries and cross-answer links + cue index + span grouping | about 1 to 2 | 0 | small to medium | boundary errors (cost: recall only) |
| 3. Verbatim + labels | 2 + LLM labels (type, direction, trait) for grouping, filtering and panels; never shown as text | about 2 to 3 | 0 | medium | wrong labels mislead panels |
| 4. Atoms, checked | the extraction and checks in this doc, no confirmation | about 30+ (2 runs + about 4 checks × 8 atoms) | 0 | large | over-generalising that slips past the checks |
| 5. Atoms, confirmed | 4 + expert confirmation | about 30+ | a few minutes per vignette | largest (needs a UI) | rubber-stamping; fewer vignettes per session |

At level 4, silver's 24 responses would be roughly 800 local calls, hours on a GPU: affordable
offline. The real costs are build effort, expert time and evaluation, not compute.

### Tests that decide

1. **Do the rules survive real writing?** On human-written pilot answers, compare B1's segmentation
   with a human one (Pk / WindowDiff). If they hold, level 1 is enough for segmentation; if not, level 2.
2. **How often is a point spread across answers?** Count how many hand-labelled points draw on more than
   one answer. If rare, cross-answer links are not worth building.
3. **Does structured context help the 9B generator?** Before building any extraction: in the existing
   generation harness, compare units against units plus hand-written labels or atoms on about 15
   questions. If pass rate and fidelity do not move, atoms have no answer-quality case and are justified
   only by panels, analysis or browsing.
4. **Are panels or a browsable knowledge base needed?** A product and thesis decision, not an empirical
   one. If yes, level 3 is the minimum.

All "no": stay at levels 1 to 2. A "yes" to 3 or 4: level 3 or 4, with expert confirmation (level 5)
only if pilot error rates show it is needed.
