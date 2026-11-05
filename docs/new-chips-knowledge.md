# Expert findings: free text with citation chips

How expert answers to vignettes become retrievable knowledge when the expert writes free text but links
each point to the fragments it is about. The expert's input (step 1 of the flow below) is built, see
[frontend-vignettes.md](frontend-vignettes.md); the rest is a design, not code. It replaces
the regex segmentation of B1 ([expert-knowledge.md](expert-knowledge.md)) and is a lighter alternative
to LLM-extracted atoms ([expert-atoms.md](expert-atoms.md)). B1 stays shipped until this wins on the
same harness (see *Decision rule*).

The principle: **enforce the links, not the shape.** The expert decides how to write; the platform
makes sure each point is tied to the patient's words and has a direction. Everything stored as the
expert's knowledge is their own verbatim text.

Constraints this design keeps:

- **Elicitation stays vignette-based**, with admin-defined, versioned questions answered in free text.
  The instrument is not restructured into forms or cards.
- **Retrieval stays Postgres hybrid:** pgvector dense (bge-m3) + BM25 `sparsevec`, fused with RRF, in a
  separate lane from the literature `chunks`.
- **Models are local** (qwen3.5:9b class). The only LLM call at ingest is a classifier; it never writes
  text that is stored or shown.

## Why this and not the alternatives

| | Segmentation | Who decides what a sentence is about | Who decides direction | LLM writes stored text? |
|---|---|---|---|---|
| B1 (shipped) | regex rules tuned to Claude's writing | rules + quote matching | nobody | no |
| Atoms ([expert-atoms.md](expert-atoms.md)) | LLM extraction | LLM | LLM, then checks | yes (readings, conditions) |
| Cards (considered) | the form | the expert | the expert | no |
| **Chips (this doc)** | sentences | **the expert (chips), then code, then an LLM classifier** | **the expert (one toggle per highlight)** | **no** |

- B1's rules break on real writing, split points spread across answers (V003: Q1, Q2, Q5) and give no
  direction. Patient-text mode is weak (0.00 to 0.12) because patient prose is matched against
  clinician commentary.
- Atoms move interpretation to an LLM. On silver, LLM paraphrase flipped direction in 7.7% of rules and
  dropped the condition in 33%. Direction is a single click for the expert and a hard judgement for an
  LLM.
- Cards would capture the same links, but they change the elicitation instrument, add burden, and lose
  what the form discourages the expert from saying, which cannot be recovered later. Free text can
  always be reprocessed.
- Silver supports the per-fragment grouping: by count, 10 of 13 Q2 answers and 12 of 13 Q5 answers in
  `DOC-SYN-0002` go back to specific Q1 fragments, so one fragment's reading, alternative and pitfall
  end up in three answers.

What this does **not** fix: the 9B generator is still the limit (oracle context does no better than
retrieved units). The hypothesis is that whole per-fragment units with an explicit direction are harder
to distort at generation time; the evaluation tests it.

## Terms

| Term | Meaning |
|---|---|
| **highlight** | a span of the vignette the expert marked; shown as a numbered chip [1], [2], … |
| **chip** | a highlight reference the expert inserts into an answer by clicking; stored as `⟦hN⟧` |
| **toggle** | the direction the expert sets once per highlight: `toward` / `away` / `neutral` / `unclear` |
| **sentence** | one sentence of one answer; the unit of assignment |
| **target** | what a sentence is about: one or more highlights, or `case` |
| **fragment unit** | all sentences (from all answers) targeting one highlight, plus that highlight |
| **case unit** | all sentences targeting `case`, plus the rating |
| **cue key** | the patient's words of a highlight, indexed for patient-text search; shared across experts |
| **implicit highlight** | a quote in an answer that matches the vignette but no highlight; no toggle |

## Who fills what

| Content | Written by | Changed later? | Shown in the prompt as |
|---|---|---|---|
| Vignette text, question text | admin | never; versioned | patient's words, Q label |
| Highlights, toggles, answers with chips, rating | expert | never after submission, except toggles and grouping on the review screen (logged) | the expert's own words; direction label |
| Sentence split, chip and quote assignment, units, checks | code | recomputed when the code version changes | - |
| Assignment of chip-less sentences | LLM classifier, ids only | re-runnable until the expert's review | - (only decides grouping) |
| Grouping corrections | expert, on the review screen | frozen once made | - |

## Input: what the expert does

1. Reads the vignette and highlights fragments. Each highlight becomes a chip with a number.
2. Sets one **required** toggle per highlight: `toward` / `away` / `neutral` / `unclear`. `unclear` must
   exist, or the expert is forced into a polarity they do not hold.
3. Answers the questions in free text, per question, as before. While writing, clicks a chip to insert
   it, like a citation: *"[2] could just as easily be burnout; what separates them is…"*. Chips can go
   anywhere, in any answer, several per sentence.
4. Rates the case.

Soft checks while writing (code, never blocking):

- a highlight never cited in any answer → *"You highlighted this but didn't discuss it."*
- a Q1 answer over about 60 words with no chips → *"Which fragments is this about?"*

Wording: Q1 should ask which fragments **matter for your reading, in either direction**, not which
"could be ADHD". The second invites only positive readings and suppresses null findings.

## Flow

```
EXPERT    1 highlight fragments, set toggles, answer with chips, rate        → source data, versioned
            │
CODE      2 split answers into sentences; assign by chip; match quoted text to highlights
            │ (exact, then fuzzy word window ≥ 0.6); unmatched quotes that hit the vignette
            │ become implicit highlights
LLM       3 classify the remaining sentences: highlight ids | case | continues previous
            │ (ids only, validated by code; retry on invalid output)
CODE      4 checks: coverage, direction vs text
            │
EXPERT    5 review screen: sentences grouped per highlight + case; flags shown; drag to regroup,
            │ change a toggle (both logged); optional, skippable
CODE      6 build fragment units and the case unit; link co-cited highlights as context
            │
CODE      7 render embed text (chips → inline short quotes), embed I1 / I2 / I3
            │
QUERY     8 retrieve (clinician question → I1; patient text → I2 → units)
            │
CODE      9 pack: merge units of one session that share sentences; case line + patient's words
              + verbatim sentences + direction label
```

Steps 2 to 4 rerun when the code or the classifier improves; groupings the expert edited are kept.
Deleting an expert cascades to sessions, highlights, sentences and units; cue keys stay if another
expert cites the same span.

### Step 2: sentence assignment rules

| Order | Rule | `assigned_by` |
|---|---|---|
| 1 | the sentence contains chips → targets = those highlights | `chip` |
| 2 | the sentence contains quoted text matching a highlight (exact, then difflib word window ≥ 0.6) | `quote` |
| 3 | quoted text matches the vignette but no highlight → implicit highlight, target = it | `quote` |
| 4 | otherwise → the LLM classifier | `llm` |
| 5 | changed on the review screen | `expert` |

A sentence can have several targets. Sentences under about 4 words (fragments like "Hard to say.") are
joined to the previous sentence before assignment.

### Step 3: the classifier contract

Input: the numbered vignette, the highlights with ids and text, all of this expert's sentences to this
vignette (numbered, with their question labels and already-known targets), the list of unresolved ids.
About 1 to 2k tokens, one call per response.

Output, nothing else:

```json
{"Q1.3": ["h3", "h4"], "Q2.3": ["case"], "Q3.1": ["case"], "Q3.3": ["prev"]}
```

`prev` means the sentence continues the previous one and inherits its targets. Code rejects unknown
ids and missing sentences. The worst error is a sentence filed under the wrong fragment: it costs
recall and puts the wrong patient words next to it, but never changes what the expert said.

### Step 4: checks

Checks only flag; nothing is changed automatically. Flags are shown on the review screen.

| Check | Rule | Flag text |
|---|---|---|
| coverage | a highlight has no targeted sentence | "You highlighted [n] but didn't say anything about it." |
| direction vs text | toggle `toward`, but a targeted sentence matches a lowering pattern ("more likely … than", "rather than", "better explained by", "not", "unlikely") | "You marked [n] as pointing toward ADHD, but in Q2 you wrote … Keep, change, or mark unclear?" |
| direction vs text | toggle `away`, but a targeted sentence matches a raising pattern ("suggests", "points to", "consistent with", "typical of") | same, reversed |
| rating | a `toward` highlight in a case rated insufficient information | info only, not shown |

## Storage (Postgres)

Questions, experts, vignettes and sessions as in [expert-atoms.md](expert-atoms.md) (versioned
`questions`, pseudonymous `experts`, `elicitation_sessions` holding the raw `ElicitationDocument`).
`cue_keys` is the same table as there.

```sql
-- the expert's highlights; one cue key per distinct vignette span
CREATE TABLE highlights (
    id text PRIMARY KEY,                       -- <session>-<vignette>-h<chip>
    session_id text NOT NULL REFERENCES elicitation_sessions ON DELETE CASCADE,
    vignette_id text NOT NULL, vignette_version integer NOT NULL,
    chip smallint,                             -- number shown to the expert; NULL for implicit
    span int4range NOT NULL,
    origin text NOT NULL,                      -- expert | implicit
    direction text,                            -- toward | away | neutral | unclear; NULL for implicit
    direction_changed_after_flag boolean NOT NULL DEFAULT false,
    cue_key_id bigint NOT NULL REFERENCES cue_keys
);

-- every sentence of every answer, with what it is about
CREATE TABLE answer_sentences (
    id text PRIMARY KEY,                       -- <session>-<vignette>-Q2.1
    session_id text NOT NULL REFERENCES elicitation_sessions ON DELETE CASCADE,
    vignette_id text NOT NULL, vignette_version integer NOT NULL,
    question_id text NOT NULL, question_version integer NOT NULL,
    idx smallint NOT NULL,
    span int4range NOT NULL,                   -- offsets into the stored answer, chip tokens included
    targets text[] NOT NULL,                   -- highlight ids and/or 'case'
    assigned_by text NOT NULL                  -- chip | quote | llm | expert
);

-- fragment units and case units
CREATE TABLE finding_units (
    id text PRIMARY KEY,
    session_id text NOT NULL REFERENCES elicitation_sessions ON DELETE CASCADE,
    expert_id text NOT NULL,
    vignette_id text NOT NULL, vignette_version integer NOT NULL,
    kind text NOT NULL,                        -- fragment | case
    highlight_id text REFERENCES highlights,   -- NULL for case units
    direction text,                            -- copied from the highlight
    population text NOT NULL, track text NOT NULL, framing text NOT NULL, is_synthetic boolean NOT NULL,
    segmenter jsonb NOT NULL,                  -- code version, classifier model + prompt version
    embed_text text NOT NULL,                  -- I1
    embedding vector(1024) NOT NULL, sparse sparsevec(1048576),
    embed_text_combined text,                  -- I3 (test variant)
    embedding_combined vector(1024), sparse_combined sparsevec(1048576)
);

CREATE TABLE finding_unit_sentences (
    unit_id text REFERENCES finding_units ON DELETE CASCADE,
    sentence_id text REFERENCES answer_sentences ON DELETE CASCADE,
    ord smallint NOT NULL,
    PRIMARY KEY (unit_id, sentence_id)
);

-- the unit's own highlight (cue) and co-cited highlights (context)
CREATE TABLE unit_cues (
    unit_id text REFERENCES finding_units ON DELETE CASCADE,
    cue_key_id bigint NOT NULL REFERENCES cue_keys,
    role text NOT NULL                         -- cue | context
);

-- what happened on the review screen and in the checks; evaluation data
CREATE TABLE review_events (
    session_id text REFERENCES elicitation_sessions ON DELETE CASCADE,
    vignette_id text NOT NULL,
    kind text NOT NULL,                        -- flag_shown | toggle_changed | sentence_moved | skipped
    payload jsonb NOT NULL,
    at timestamptz NOT NULL
);
```

**Co-citation as context:** when a sentence cites several highlights, each of those units gets the
others as `context` in `unit_cues`. This records cue combinations ("sleep + the shaking") from what the
expert wrote, without a role the expert has to pick.

**Legacy data:** answers without chips (current silver, any free-text import) run through the same
pipeline: `quoted_fragments` become highlights with `direction NULL`, and every sentence goes through
quote matching and the classifier. So silver can be tested before the frontend exists.

## What is embedded

| Index | Text | Used for |
|---|---|---|
| **I1** `finding_units.embed_text` | header (role · population · framing · direction · rating) + the unit's sentences, verbatim, each prefixed with its question label; chips rendered as «short quote» | clinician-question mode |
| **I2** `cue_keys` | the highlight's vignette span (patient's words only) | patient-text mode |
| **I3** `finding_units.embed_text_combined` | I1 with a `Patient: "…"` line after the header | test variant for both modes ("same chunk") |

Chip rendering: `⟦hN⟧` becomes «the fragment», truncated to its first 8 words with "…". This makes each
sentence readable on its own, in the index and in the prompt.

**Not embedded:** the full vignette, question texts (only the Q label stays), toggles, rating, flags and
review events (metadata, filters and header only). Case-unit sentences that are near-duplicates of
other sessions' generic answers (the "longitudinal history, childhood onset, other domains" Q3
pattern) are stored but down-weighted.

BM25 is fitted separately for `finding_units` and for `cue_keys`, never with literature `chunks`.

## Retrieval

| Mode | Query | Search | Then |
|---|---|---|---|
| clinician question | "How do I tell sleep deprivation from attention problems in what a patient writes?" | dense + BM25 over I1 (or I3), RRF; filter population | fill the expert token budget |
| patient text | a new patient's text | split into sentences; dense + BM25 over I2 per sentence, RRF | `unit_cues` → units; bonus when a unit's `cue` and a `context` both match |

Fusion with literature: fixed quotas (for example 4 literature chunks + 4 expert blocks), as in
[expert-knowledge.md](expert-knowledge.md).

## In the prompt

System prompt rule (unchanged): expert notes are clinician opinions on teaching cases; rank them below
guidelines, never state them as criteria, keep their direction and caveats when citing [E#].

Packing (code):

1. Retrieved units from the same session that share sentences are **merged into one block**; each
   sentence is printed once.
2. Each block: case line (metadata) → patient's words (highlight spans) → the expert's sentences
   (verbatim, in question order) → direction label per fragment (from the toggles).

## Worked example (hand-written illustration)

Vignette V001 (adult's journal, quarterly report, two months of poor sleep after a move). The answers
are `DOC-SYN-0002`'s content, rewritten with chips as an expert using this frontend would write them.
Offsets are real.

### Input

| Chip | Span | Fragment | Toggle |
|---|---|---|---|
| [1] | 73–137 | "numbers on screen keep looking like they are moving when I blink" | away |
| [2] | 167–234 | "I haven't slept well since moving into this new flat two months ago" | away |
| [3] | 239–305 | "every time I try to type a formula my hand starts shaking slightly" | unclear |
| [4] | 461–562 | "the whole thing falls apart again like last week when I forgot to file the forms until Monday morning" | toward |

- **Q1:** [3] could be read as motor restlessness under task difficulty, but it's shaky ground. [4]: the
  "again" suggests a repeated pattern of disorganisation. I'm hedging heavily on both: hand shaking is
  more often anxiety or physiology, and the forgetting could just as well be sleep deprivation.
- **Q2:** [2] explains most of this more parsimoniously: [1], [3], the gritty eyes, the fog. The
  'falling apart' at work is more likely acute burnout or situational overwhelm than chronic
  disorganisation. What would distinguish them: lapses that also occur when sleep is adequate and life
  is stable.
- **Q3:** I'm missing baseline functioning before the move and the sleep loss. Does [3] happen only when
  tired? Without knowing whether this is new, I can't rule out adjustment disorder or severe sleep debt.
- **Q5:** A less experienced clinician might take [3] and [1] as hyperactivity or sensory signs, missing
  that they follow directly from insomnia. They might also under-read [4] as a one-off and miss the
  "again".
- **Rating:** insufficient information.

### Steps 2 and 3: assignment

| Sentence | Chips | Quote match | Targets | By |
|---|---|---|---|---|
| Q1.1 | [3] | | h3 | chip |
| Q1.2 | [4] | | h4 | chip |
| Q1.3 | | | h3, h4 | llm |
| Q2.1 | [2] [1] [3] | | h2, h1, h3 | chip |
| Q2.2 | | 'falling apart' → h4 (0.67) | h4 | quote |
| Q2.3 | | | case | llm |
| Q3.1 | | | case | llm |
| Q3.2 | [3] | | h3 | chip |
| Q3.3 | | | case | llm |
| Q5.1 | [3] [1] | | h3, h1 | chip |
| Q5.2 | [4] | | h4 | chip |

Seven of eleven sentences are resolved by code. The classifier handles four, including Q1.3, which
refers to "hand shaking" and "the forgetting" without quoting them.

### Steps 4 and 5: checks and review

- Coverage: all four highlights are targeted.
- Direction vs text: [4] is `toward`, but Q2.2 matches "more likely … than". Flag on the review screen:
  *"You marked [4] as pointing toward ADHD, but in Q2 you wrote it's more likely burnout. Keep, change,
  or mark unclear?"* The expert sets `unclear` (`review_events`: `toggle_changed`). No sentence is moved.

### Step 6: units

| Unit | Patient's words | Sentences | Direction | Context (co-cited) |
|---|---|---|---|---|
| U-h1 | [1] | Q2.1, Q5.1 | away | h2, h3 |
| U-h2 | [2] | Q2.1 | away | h1, h3 |
| U-h3 | [3] | Q1.1, Q1.3, Q2.1, Q3.2, Q5.1 | unclear | h1, h2, h4 |
| U-h4 | [4] | Q1.2, Q1.3, Q2.2, Q5.2 | unclear (changed after flag) | h3 |
| U-case | - | Q2.3, Q3.1, Q3.3 + rating | - | - |

U-h4 now holds the Q1 reading, the Q2 counter-reading and the Q5 pitfall together; B1 split them into
three units.

### Step 7: embedded text

I1 for U-h3:

```
Clinician · adult's personal journal · fragment marked: unclear · case rated insufficient information
Q1: «my hand starts shaking slightly» could be read as motor restlessness under task difficulty, but it's
shaky ground. I'm hedging heavily on both: hand shaking is more often anxiety or physiology, and the
forgetting could just as well be sleep deprivation.
Q2: «haven't slept well since moving» explains most of this more parsimoniously: «numbers… moving when
I blink», «hand starts shaking», the gritty eyes, the fog.
Q3: Does «hand starts shaking» happen only when tired?
Q5: A less experienced clinician might take «hand starts shaking» and «numbers… moving» as
hyperactivity or sensory signs, missing that they follow directly from insomnia.
```

I2: four `cue_keys` rows, the patient's words of [1] to [4].
I3 for U-h3: the I1 text with `Patient: "every time I try to type a formula my hand starts shaking
slightly"` after the header.

### Step 8: retrieval

- **Clinician question** *"How do I tell sleep deprivation from attention problems in what a patient
  writes?"* → I1 matches "sleep deprivation", "insomnia", "parsimoniously" → U-h3, U-h1, U-h4.
- **Patient text** *"Night shifts all week. My hands won't stop trembling when I try to fill in the
  rota."* → sentence 2 matches the cue key of [3], sentence 1 the cue key of [2]; [2] is context of
  U-h3 → U-h3 with the combination bonus.

### Step 9: packed

U-h3 and U-h1 share Q2.1 and Q5.1, so they are merged:

```
[E1] Teaching case V001: an adult's journal entry, quarterly report, two months of poor sleep after a move
  Patient's words: «my hand starts shaking slightly» (marked: unclear) · «numbers… moving when I blink» (marked: away)
  Clinician (case rated insufficient information):
    "…could be read as motor restlessness under task difficulty, but it's shaky ground."
    "«haven't slept well since moving» explains most of this more parsimoniously…"
    "A less experienced clinician might take [these] as hyperactivity or sensory signs, missing that
     they follow directly from insomnia."
    Open question they raised: "Does it happen only when tired?"
```

| Line | Kind |
|---|---|
| case line | metadata, rendered by code |
| patient's words, direction labels | source data (expert's highlights and toggles) |
| clinician lines | source data (verbatim sentences) |

## Problems to keep in mind

1. **Shared sentences duplicate across units.** Q2.1 sits in three units. Right for patient mode (each
   fragment finds it); question mode may retrieve near-duplicates. Packing merges them; the metrics need
   a rule (count units of one session that share sentences as one hit, or not).
2. **Units are bigger than B1's** (U-h3 is about 170 tokens against 123). A 500-token budget holds
   about three blocks. Test a larger budget alongside.
3. **Hedging preambles survive** verbatim and dilute the embedding ("I'm hedging heavily on both"). The
   toggle already carries the uncertainty. Test removing pure-hedge sentences from I1 only, keeping them
   in the packed text.
4. **Generic case answers.** The Q3 "longitudinal history, childhood onset, other domains" pattern
   repeats across vignettes and floods generic questions. Down-weight near-duplicates; consider
   rewording the case question to *"What one piece of information would most change your reading of
   this case?"*
5. **Chip discipline is unknown.** If real experts ignore chips, everything runs through the
   classifier, which still works but is the measured weak point.
6. **Direction patterns are crude.** They will miss and over-flag. They only ask the expert; a false
   flag costs a click.
7. **Q1 wording primes positive readings.** "Which fragments could be ADHD" suppresses null findings;
   ask which fragments matter, in either direction.
8. **The 9B generator remains the limit.** Nothing here touches generation except the unit shape and
   the direction labels.

## Before testing: silver fixes

Found in `DOC-SYN-0002`:

- **V014 leaks the variant design.** Arm B removes the newborn, yet Q3 mentions "the newborn and the
  broken nights" (the `change` text). The answering agent must see only `text` and the questions;
  regenerate the S05 pair and check others.
- **V007 Q1 breaks character** ("the clinician in this persona hedges heavily"). Add a leakage filter
  (persona, "as an AI", third-person self-reference).
- **Highlights and answers disagree** (V007: "I cannot quote a fragment" with 4 `quoted_fragments`).
  Span-based labels are wrong for such responses.
- **V009 misreads the writer** as Mr. Henderson (the patient). Decide whether silver may carry such
  errors.

## Code that has to change

- `Response.quoted_fragments: list[str]` → `highlights: list[Highlight]` (span, chip, direction) in
  [schema.py](../backend/app/elicitation/schema.py); answers keep `⟦hN⟧` tokens. A legacy adapter turns
  `quoted_fragments` into highlights with `direction=None`.
- `QuestionId` literals and the `QUESTIONS` tuple → versioned question rows (as in
  [expert-atoms.md](expert-atoms.md)).
- New `findings.py` beside [units.py](../backend/app/elicitation/units.py): sentence split, chip and
  quote assignment (reusing the difflib anchoring from `units.py`), checks, unit building, chip
  rendering. No model calls; tested like `test_units.py`.
- New classifier prompt `prompts/Expert_sentence_targets.v1.md` and a script that runs it per response.
- Frontend: the review screen. Highlights, chips, toggles and soft checks are built.
- `retrieve_expert` in `rag_common.py` over I1 / I2 / I3, with the pack-time merge.

## Decision rule and evaluation

1. **Silver, free text (now, no frontend).** Run the fixed silver sessions through the legacy path
   (quote matching + classifier) and compare with B1 on the existing harness: question-mode retrieval
   (pooled labels, recall@4, nDCG@10), patient-mode retrieval, and generation (key points, fidelity,
   attribution, pass rate; two judge passes). Retrieval variants: I1, I3, max(I1, I3) for questions;
   I2, I3 for patient text.
2. **Classifier accuracy.** Hand-label targets for the chip-less sentences of 10 to 15 responses;
   report accuracy and per-class errors (highlight vs `case`). This is the only LLM error in the design.
3. **Silver, chips.** Regenerate silver with the agent writing chips and toggles (vignette text only).
   Compare with step 1: what grouping and direction add over free text on the same vignettes.
4. **Human pilot.** Share of sentences with a chip, flags shown and accepted, toggles changed, sentences
   moved on review, review skipped, time per vignette, and a short debrief ("anything you wanted to say
   but couldn't place?"). If possible, one vignette in plain free text first for comparison.

Chips replace B1 if they are not worse on question-mode retrieval and better on patient-mode retrieval
or generation pass rate or fidelity. If the pilot shows experts do not use chips, the legacy path
(free text + classifier) is the fallback and still replaces the regex rules.

## References

- Annotator rationales (highlight the evidence for a judgement): https://preview.aclanthology.org/fix_video/N07-1033.pdf
- Dense X Retrieval, self-contained retrieval units: https://arxiv.org/abs/2312.06648
- Script concordance tests, scoring against an expert panel: https://pmc.ncbi.nlm.nih.gov/articles/PMC4989333
- Structured expert elicitation and aggregation: https://eprints.whiterose.ac.uk/id/eprint/220470/1/PIIS1098301524028432.pdf
- Case-based reasoning RAG: https://arxiv.org/abs/2404.04302v1
