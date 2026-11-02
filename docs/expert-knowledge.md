# Expert answers as retrievable knowledge

How the answers in an `ElicitationDocument` become something the RAG can retrieve, and the
experiment that decides it. This replaces the "LLM extracts claims → expert member-checks → only
approved claims reach the knowledge base" plan in [elicitation-document.md](elicitation-document.md)
as the working proposal. That doc and `lifecycle.py` change only once the results below confirm
the choice.

There is no production yet, so synthetic data is treated like real data here. `assert_ingestible`
stays as it is but is not called with `production=True`; `is_synthetic` is kept as metadata.

Constraints:

- Generation is small and local: qwen3.5:9b or gemma4:e4b with `num_ctx 8192`.
- Two kinds of query: a clinician's question ("how do I tell goal-loss digression from
  rumination?") and a new patient text that needs relevant expert readings pulled in.

## What the answers look like (silver)

- Q1 is the long answer (median about 145 words) made of several points, each tied to a quote.
  C1 enumerates ("(a) … (b) … HOW: …"); C2 writes prose in which each quote opens a point.
- Q2 to Q5 are short (Q3 can be one line). They cross-refer ("see Q2", "rest unchanged") and use
  shorthand ("hx", "->", "?means").
- General knowledge is woven into case talk ("a phone note at the end of a twelve hour night shift
  looks like…"), and names from the vignette appear.
- Most of the context a point needs is already structured data: the question, the vignette sentence
  around each quote, the framing, the population, the expert's role and the Q6 rating. Literature
  chunks are different: their context has to be inferred.

## Options

| | What reaches the generator | What is embedded | Risk | Expert burden |
|---|---|---|---|---|
| A. Raw answers | each Q answer verbatim | the same | coarse units, unresolved "see Q2", the small model must generalise | none |
| B. Deterministic units | verbatim point + header from metadata + the vignette sentence it quotes | the same | rule-based segmentation can miss implicit points; no generalised phrasing for question-mode search | none |
| C. LLM claims as the knowledge | an LLM paraphrase ("reading rule") | the paraphrase | a small model distorts the expert's meaning and it still reads as expert knowledge | high: about 80 claims per session to check |
| D. B + LLM retrieval keys | verbatim point (as B) | the point **and** an LLM reading rule + 2–3 questions | an LLM error only costs recall; nothing it wrote is shown as expert knowledge | none required |

D keeps the expert's own words as the cited unit and moves generalisation into the search keys, the
same multi-representation idea `contextual_text` applies to literature chunks. The member check is
no longer needed for safety; it can come back as an optional "is this rule what you meant?" step.

## What is built

- [units.py](../backend/app/elicitation/units.py) (no model calls, tested in
  [test_units.py](../tests/test_units.py)): `build_units(doc, role)` returns `ExpertUnit`s.
  - **Segment.** Split at enumerators and labels (`(a)`, `HOW:`, `Over:`, `Under:`, `1.`, `-`);
    otherwise a sentence with a quote not seen before starts a new point (Q1 always, other answers
    over 120 words). Segments under 8 words join their neighbour.
  - **Anchor the quotes** to vignette character spans: exact match, then a difflib word-window
    match for near-misses. Quotes that match nothing are listed in `unanchored_quotes`.
  - **Vignette context:** the whole vignette sentence around each quote (clipped to 60 words for
    run-ons).
  - **Cross-references:** "see/as Qn" link to that question's units; "above"/"unchanged" link to
    Q1. `render_unit` appends the first referenced unit, truncated.
  - **Shorthand** (`hx`, `ddx`, `r/o`, `->`) is spelled out in `text_expanded`; `text` stays verbatim.
  - **Header** from metadata, for example `Clinician (consultant psychiatrist, 18 years in an adult
    ADHD and neurodevelopmental service) on an adult's email · Q2 "what else could explain those
    fragments" · overall 3/5`. The full question text is not repeated: it cost about 40 tokens per
    unit and added the same words to every embedding.
- [Expert_unit_keys.v1.md](../prompts/Expert_unit_keys.v1.md) and
  [make_unit_keys.py](../scripts/elicitation/make_unit_keys.py): one qwen3.5:9b call per unit returns
  `{reading_rule, questions, traits, direction}`. A reply that is invalid JSON or carries a name from
  the vignette is retried with a new seed. Output: `data/expert_units/<tier>/<session>.json`.
- [eval_expert_units.py](../scripts/rag/eval_expert_units.py), [eval_expert_generation.py](../scripts/rag/eval_expert_generation.py): the experiments (see below).
- `VignetteDesign.population` (default `"adult"`, filled from the scenario age in `make_fixtures.py`).

## The experiment

Two scripts, run in this order (embedding and generation never run at the same time: they share an
8 GB GPU and stall each other).

1. `python scripts/rag/eval_expert_units.py --tier silver` compares ways to index the answers, in
   memory. Building blocks are in `expert_retrieval.py`, metrics in `expert_metrics.py` (tested in
   [test_expert_eval.py](../tests/test_expert_eval.py)).
2. `python scripts/rag/eval_expert_generation.py --tier silver` answers the 40 questions with
   qwen3.5:9b from the selected representation; `scripts/rag/judge_generations.py` exports the
   answers blind to Haiku subagents (clinician rubric `EXPERT_JUDGE_RUBRIC` in `rag_common.py`) and
   `eval_expert_generation.py --report <run dir>` summarises.

**Retrieval.** Dense bge-m3 plus BM25 fused with RRF k=60, like the literature chunks; an item is
scored by its best representation. Representations: A answer-level; B header + two vignette sentences +
the point; B1 the same with one short vignette sentence; Bs searched as B1 but shown as B; C the LLM
reading rule alone; D / D1 = B / B1 also searched through the rule and 2 to 3 generated questions.
Variants: dense only, BM25 only, `+cap` (one result per vignette and question first), `+mmr`.

**Ground truth** is the silver reference claims. A unit holds a claim if their quote spans overlap;
otherwise the unit of the same answer closest to the claim text holds it. Question labels come in two
sets: the claims the question-writing agent listed (*original*), and those plus every claim a second
agent (Haiku) marked relevant among all claims any variant returned in its top 8 (*pooled*).

**Metrics:** claim recall@4 units, that recall as a share of `ceiling@4` (the most 4 units could hold),
hit@4, MRR, nDCG@10, and recall within a 500-token budget. Intervals are 95% bootstrap over questions;
differences between variants are paired.

**Generation.** Each question is answered under: `units` (selected representation, 500 tokens),
`rules` (C's rules, same budget), `oracle` (the units holding the labelled claims), `none` (no notes,
general knowledge, said so) and `shuffled` (another question's notes, 10 questions; a control). The
generator is told to report the notes as what clinicians said, keep conditions, and cite `[E#]`. The
judge sees the question, the labelled main key points with their direction and condition, the exact
notes, and the answer, and scores key points, fidelity (direction and conditions kept), attribution
(opinion not criterion, no invented quotes), usefulness and citations, plus unsupported-claim and
abstention flags. `pass` = fidelity ≥ 4, attribution ≥ 4, key points ≥ 3, no unsupported claim.
Every answer is judged twice by independent Haiku passes, to measure agreement.

## Results (silver; synthetic experts and Claude-written questions, so a development result)

### Retrieval

Labels matter first. Haiku confirmed 189 of 197 original labels (96%) but added 8.4 relevant claims per
question: the original lists had about 5 relevant claims, the pooled ones about 13. Against the first
labels recall looked poor partly because relevant claims were missing from the list, and partly
because 4 units can hold at most 42% of 13 claims (`ceiling@4`).

Pooled labels, question mode (40 questions; 95% interval in brackets):

| | recall@4 | recall@4 / ceiling | hit@4 | MRR | nDCG@10 | tokens / item |
|---|---|---|---|---|---|---|
| A. raw answers | 0.291 [0.24, 0.34] | 0.78 | 0.98 | 0.83 | 0.490 [0.43, 0.55] | 83 |
| B. units | 0.218 [0.18, 0.26] | 0.54 | 1.00 | 0.85 | 0.590 [0.53, 0.65] | 138 |
| B1. lean units | 0.211 [0.17, 0.26] | 0.53 | 0.95 | 0.81 | 0.574 [0.51, 0.64] | 123 |
| C. rules only | 0.197 [0.16, 0.23] | 0.50 | 0.90 | 0.72 | 0.513 [0.45, 0.58] | 39 |
| D. units + keys | 0.201 [0.17, 0.23] | 0.51 | 1.00 | 0.83 | 0.536 [0.48, 0.59] | 138 |
| D1. lean + keys | 0.199 [0.17, 0.23] | 0.51 | 1.00 | 0.84 | 0.538 [0.48, 0.59] | 123 |

(A's items hold several units each, so its recall@4 is not comparable.)

- Retrieval works: a relevant unit is in the top 4 for every question with B (hit@4 1.00) and the first
  relevant unit is usually at rank 1 or 2 (MRR 0.85). What is left is spread across many claims, which
  a 500-token budget cannot carry.
- **Nothing beats B by more than noise.** Paired differences: B1 − B recall −0.006 [−0.03, +0.01]
  (nDCG −0.017, just below zero); D − B recall −0.017 [−0.05, +0.02]; D1 − B1 −0.012 [−0.05, +0.02];
  `cap` and `mmr` lower nDCG (−0.07 and −0.02, intervals below zero) and leave recall unchanged.
  The generated keys do not help, and neither does a leaner unit or diversity re-ranking.
- Hybrid and dense only are within noise of each other (B/dense recall 0.232 against 0.218); BM25 alone is
  worse. The lean unit saves only 15 tokens per item: the header and the point dominate its size.
- Selected for generation: B1 (not significantly worse than B, no LLM keys, shorter).

### Generation (qwen3.5:9b, 500-token budget, 40 questions)

Two independent Haiku passes (j1 / j2). Means with a 95% interval for pass rate:

| context | key points (1-5) | fidelity | attribution | pass rate | unsupported claims |
|---|---|---|---|---|---|
| units | 2.58 / 2.60 | 3.83 / 3.70 | 3.98 / 3.90 | 0.45 / 0.38 | 5% / 7% |
| rules | 2.62 / 2.40 | 3.58 / 3.50 | 3.75 / 3.62 | 0.25 / 0.17 | 5% / 3% |
| oracle | 2.62 / 2.65 | 3.30 / 3.23 | 3.67 / 3.52 | 0.25 / 0.30 | 10% / 12% |
| none | 1.32 / 1.27 | - | 2.38 / 2.88 | 0.00 / 0.00 | 88% / 90% |
| shuffled (10) | 1.10 / 1.30 | 4.10 / 4.00 | 4.10 / 4.20 | 0.00 / 0.10 | 10% / 10% |

- **Units are at least as good as rules, probably better.** Pass rate +0.20 for units over rules in
  both passes ([−0.03, +0.40] and [0.00, +0.38]); attribution +0.23 and +0.28 (the second interval
  excludes zero); key points equal. By the decision rule (rules must beat units to be used) the rules are out.
- **The 9B model, not retrieval, is the limit.** The oracle context (perfect retrieval) does not do
  better than retrieved units. With the right notes the answers cover only about half of the main key
  points (2.6 of 5), and 40% pass. Of the failed units answers (both passes
  together, a failure can have several causes): 74% have key points below 3 (the answer covers one or
  two of 4 to 6 points), 55% fidelity below 4 (real distortions, for example an added "uncontrolled
  attention deficit" that is not in the notes), 26% attribution below 4.
- Without notes the model gives general knowledge and passes nothing (88 to 90% unsupported claims); its
  key points score 1.3. The notes add real content.
- **Judge checks.** Agreement between the two Haiku passes: pass 0.84; weighted kappa 0.82 key points,
  0.81 usefulness, 0.70 fidelity, 0.63 attribution, 0.60 citations. Controls: oracle − none key points
  +1.3 / +1.4; oracle − shuffled +1.7 / +1.1; shuffled passes 0 and 1 of 10. Fidelity cannot be a
  control: it measures faithfulness to the notes the answer saw, and answers faithful to irrelevant notes
  score high; key points and usefulness do the discriminating. Haiku wrote `key_points: 0` for 19
  answers that cover nothing; these count as 1 rather than being dropped (dropping them would remove the
  worst answers). Haiku and the silver data are both Claude, so a shared blind spot is possible: a hand
  check of 10 items is in `data/eval/expert_runs/main/human_check.md`, agreement still to be filled
  in with `judge_generations.py --sheet-agreement`.

### What this means

1. Ship B1 (or B): verbatim units with a short header and one vignette sentence. No LLM at ingest, no
   expert member check needed for safety.
2. Rules (C) and keys (D) are not justified by this data.
3. To raise answer quality, work on the generation side, not on retrieval: give the model fewer, fuller
   units or a two-step answer (list the readings, then summarise), and test a larger budget. Retrieval
   already finds a relevant unit every time.
4. Open: the hand check, gold data from real clinicians, and the patient-text mode (weak labels,
   `--patient`).

## Literature check

The silver `knowledge_target`s run through the existing hybrid retrieval over the 400 literature
chunks (top 3 each). This closes the open item in [fixtures.md](fixtures.md).

- V006 (goal-loss digression vs rumination): children's pragmatics review, a discourse-genre table
  from the lifespan review, the consensus statement's general text. Nothing on telling rumination
  from digression.
- V007 (time language): discourse-review passages on task structure; nothing on time estimation in
  text.
- V008 (help-seeking message): the genre table again, NICE's right to be involved, the consensus on
  collateral informants. Closest hit, but about taking history, not reading a message.
- V009 (fragmentation from fatigue): lifespan review framework, ICD-11 definitional requirements.
- V010 (emotional reactivity vs low mood): the ICD-11 boundary with mood and anxiety disorders and
  the consensus on emotional dysregulation are relevant background, not reading guidance.
- V011 (retrospective childhood accounts): consensus passages on late-onset and onset in adults.
  Background only.
- V012 (hard negative): children's pragmatics meta-analysis and ICD-11 subtype definitions.

So the corpus gives the criteria and general background; none of it covers how to read a patient's
free text. That is the gap the expert lane fills. All scores are close (0.027 to 0.033 RRF), so
there is no confident literature hit to compete with.

## Decisions kept

- **A separate lane.** Expert units never go into `chunks`: BM25 idf would be refit across both
  kinds of text and shift the literature eval numbers, RRF scores across sources are not comparable,
  and citations differ (`[1]` literature, `[E1]` experts). Fusion uses fixed quotas, for example 4
  literature chunks and 4 expert units, about 2.5k tokens of context.
- The DB table (`expert_units` plus key vectors) and a `retrieve_expert` in `rag_common.py` come
  after the experiment picks a representation.

## Other things to consider (mostly deferred)

1. **One case, one expert.** Show "1 clinician"; later cluster near-duplicate units across experts
   and show disagreement instead of averaging.
2. **Evidence level.** The generator prompt must rank expert units below guidelines and never state
   them as criteria. Add an "attribution" criterion to the judge rubric.
3. **Population.** Every writer is an adult; units carry `population` from the vignette design.
4. **Expert profile.** Specialty and years exist only in `PERSONAS`; the header takes a `role` string
   today. A pseudonymous `ExpertProfile` on the session is the proper home.
5. **Retraction and consent.** Deleting an expert must cascade to their units; record a consent
   version on the session.
6. **Quotes from real text.** For `real_text` (Reddit) vignettes `vignette_context` puts third-party
   text into the knowledge base. Units keep `origin` so it can be filtered; decide before gold.
7. **Versioning.** Units carry `segmenter_version`; the keys file records the prompt and model. Add
   the vignette hash and embedding model when units are stored.
8. **Q6 ratings and controls** go in the header and metadata, not in separate units. A control rated
   1 makes its "lowers" readings useful base-rate knowledge.
