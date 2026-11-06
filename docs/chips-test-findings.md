# Chip units test: findings

Run on 2026-11-04. Tests the design in [new-chips-knowledge.md](new-chips-knowledge.md) (free text with
citation chips) against the shipped B1 baseline ([expert-knowledge.md](expert-knowledge.md)), on new synthetic
vignettes. Q4 was out of scope. All numbers are **silver**: synthetic vignettes, answers written by Claude
Sonnet agents, judged by Claude Sonnet agents. They are development numbers, not results to report.

## Summary

- **Question-mode retrieval:** chip units retrieve better than B1 under the pooled labels (recall@4 +0.14,
  nDCG@10 +0.12, intervals exclude 0). Under the original labels the unmerged gain is within noise
  (+0.08, interval −0.003 to +0.18). Merging units that share sentences adds recall (+0.11) but not nDCG.
- **Patient-text retrieval:** no clear gain. The I3 text is within noise of B1; the cue-key path (I2) is
  worse than B1 on recall.
- **Generation with qwen3.5:9b:** chips and B1 are within noise on pass rate, key points, fidelity and
  attribution. Even perfect retrieval (oracle) passes only about 30%, so the 9B generator is the limit,
  as the doc predicted.
- **Generation with qwen3.6:35b-a3b:** clearly higher fidelity (+0.5) and attribution (+0.3 to +0.4) than
  the 9B, and an oracle pass rate of 0.57 to 0.65 against 0.30. With real retrieval its pass rate is not
  clearly higher than the 9B's.
- **Decision rule of the doc** (not worse on question retrieval, and better on patient retrieval or
  generation pass rate or fidelity): the first part holds, the second does not. **Chips are not shown to be
  better on this test.**

## What was run

| Step | What |
|---|---|
| Vignettes | 14 texts (13 scenarios, S05 as an A/B pair), written by 4 Sonnet agents with `Persona_claude.v2`; shared by bronze and silver |
| Silver answers | 2 simulated experts x 14 = 28 responses, written by Sonnet agents with `Synthetic_expert_answer.v4` (highlights, toggles, `⟦hN⟧` chips, free text). Arm B of the pair was answered by separate agents |
| Bronze answers | 37 of 42 responses from qwen3.6:35b-a3b (plumbing only, no accuracy numbers) |
| Steps 2 to 7 | `chip_findings.py` (sentence split, chip and quote assignment, checks, units, I1/I3 text); `classify_sentence_targets.py` for the sentences without a chip |
| Embedding | bge-m3, in the order I1, I2, I3; units also loaded into a separate Postgres schema (`chips` then; `chips_eval` now) |
| Evaluation | 40 clinician questions and pooled relevance labels by Sonnet agents; chips vs B1 on the same questions and the same 253 reference claims; two independent Sonnet judge passes |

B1 was run on the same sessions with the chips rendered back as full quotes, so it gets the best input its
regex rules can use.

## The data

| | Silver | Bronze |
|---|---|---|
| Responses | 28 | 37 (5 of 42 never passed the format checks) |
| Highlights per response | 5.9 | n/a |
| Toggles (silver) | away 51, neutral 49, unclear 41, toward 25 | |
| Sentences | 411 | 646 |
| Assigned by chip / quote / classifier | 191 / 13 / 207 (46% / 3% / 50%) | 185 / 98 / 363 |
| Implicit highlights (quote matches the text, no highlight) | 5 | 33 |
| Chip units (incl. case units) | 198 (28 case) | 176 (37 case) |
| B1 units, same silver sessions | 246 (8.8 per response vs 7.1) | |
| Reference claims | 253 | |
| Direction flags / coverage flags | 13 / 1 | 46 / 9 |

Half of the silver sentences carry no chip, so the classifier has real work. Bronze answers quote the text
far more than silver ones.

## The sentence classifier

Step 3 files the sentences without a chip or matching quote under a highlight, or `case`.

| | qwen3.5:9b | qwen3.6:35b-a3b |
|---|---|---|
| Silver: sentences filed / fallbacks to `case` / responses retried | 207 / 0 / 0 | 207 / 1 / 1 |
| Masked-chip check (n=191): exact set match | 0.61 | 0.63 |
| overlap with the true targets | 0.77 | 0.79 |
| filed as `case` only | 0.14 | 0.12 |
| extra wrong highlight | 0.16 | 0.19 |
| Bronze: sentences filed / fallbacks | 363 / 3 | not run |

The masked-chip check hides the chips (replaced by "that") and asks the classifier to find the targets the
chips gave for free. It is a **proxy**: sentences that carry chips may differ from those that do not. The
hand-labelled accuracy the doc asks for was not done. The two models are equal within noise, and their units
retrieve the same (`@35b` rows below).

## Retrieval

40 questions. Pooled labels: every system's top 8 judged by a Claude agent, which confirmed 154 of 157
original labels and added 6.1 per question.

**Question mode, pooled labels** (95% bootstrap intervals; tokens = mean size of the top 4 items)

| Experiment | recall@4 | nDCG@10 | hit@4 | recall@500t | tokens/item |
|---|---|---|---|---|---|
| B1 | 0.265 [0.21, 0.31] | 0.540 [0.47, 0.60] | 0.90 | 0.227 | 156 |
| I1 | 0.409 [0.35, 0.49] | 0.662 [0.61, 0.73] | 0.98 | 0.276 | 187 |
| I1 + merge | 0.519 [0.44, 0.59] | 0.655 [0.60, 0.72] | 0.98 | 0.313 | 221 |
| I3 | 0.397 [0.34, 0.47] | 0.650 [0.59, 0.72] | 0.98 | 0.264 | 187 |
| I3 + merge | 0.513 [0.45, 0.58] | 0.651 [0.58, 0.72] | 1.00 | 0.304 | 220 |
| I1 or I3 (better text) | 0.387 [0.33, 0.46] | 0.665 [0.60, 0.73] | 1.00 | 0.264 | 185 |
| I1 + dw | identical to I1 on every metric | | | | |
| I1@35b (35b classifier) | 0.417 [0.36, 0.48] | 0.665 [0.61, 0.73] | 1.00 | 0.281 | 185 |
| I1@35b + merge | 0.500 [0.43, 0.57] | 0.652 [0.59, 0.71] | 1.00 | 0.313 | 212 |

Paired differences (a − b, `+` = interval excludes 0):

| a − b | recall@4 | nDCG@10 |
|---|---|---|
| I1 − B1 | +0.144 [+0.084, +0.207] + | +0.123 [+0.076, +0.173] + |
| I1 + merge − B1 | +0.254 [+0.190, +0.316] + | +0.115 [+0.060, +0.173] + |
| I1 + merge − I1 | +0.110 [+0.067, +0.153] + | −0.007 within noise |
| I3 − I1, I1 or I3 − I1 | within noise | within noise |
| I1@35b − I1 | +0.008 within noise | +0.003 within noise |

**How far to trust the retrieval gain**
- Under the *original* labels (the claims one agent listed per question) the unmerged gain is within noise:
  I1 − B1 recall@4 +0.083 [−0.003, +0.176]. Only the merged variants are clearly better there
  (+0.205 [+0.112, +0.293]).
- Part of the recall gain is structural. A fragment unit gathers a highlight's sentences from all answers, so
  one hit can hold claims from several answers. A merged item also counts all its units toward the top 4.
  That is the "metrics need a rule" problem the doc lists; here both versions are reported.
- The down-weighting of near-duplicate case units (`dw`) changed nothing.

**Patient-text mode** (weak labels: claims that share a planted trait; 9 queries)

| | recall@4 | nDCG@10 | hit@4 |
|---|---|---|---|
| B1 | 0.036 [0.01, 0.06] | 0.138 [0.05, 0.23] | 0.44 |
| I3 | 0.059 [0.03, 0.08] | 0.191 [0.09, 0.32] | 0.78 |
| I2 (cue keys → units, with co-citation bonus) | 0.004 [0.00, 0.01] | 0.098 [0.05, 0.16] | 0.11 |

I3 − B1 is within noise (recall@4 +0.022 [−0.009, +0.053]); I2 − B1 is −0.032 [−0.057, −0.009]. The doc's
hypothesis that patient mode improves is not supported here, and the cue-key route is the weak part.
With 9 queries and weak labels this is a thin test.

## Generation

Contexts: `chips` (best experiment, I1 + merge, 500 tokens), `chips800`, `b1` (500 tokens), `oracle` (the
units that hold the labelled claims), `none`, `shuffled` (notes of another question, 10 questions). Two
Sonnet judge passes (`j1`, `j2`), blind, one reply per answer.

**qwen3.5:9b** (pass rate; key points / fidelity / attribution on a 1–5 scale; pass j1, j2 in order)

| Context | pass | key points | fidelity | attribution |
|---|---|---|---|---|
| b1 | 0.40, 0.33 | 2.77, 2.67 | 3.38, 3.23 | 3.65, 3.62 |
| chips | 0.30, 0.33 | 2.65, 2.62 | 3.20, 3.15 | 3.62, 3.55 |
| chips800 | 0.42, 0.35 | 2.95, 2.90 | 3.33, 3.30 | 3.70, 3.55 |
| oracle | 0.30, 0.30 | 2.85, 2.83 | 3.10, 3.20 | 3.48, 3.48 |
| none | 0.00, 0.00 | 1.50, 1.50 | n/a | 1.88, 2.00 |
| shuffled | 0.00, 0.00 | 1.10, 1.10 | 3.40, 3.40 | 3.50, 3.70 |

- chips − b1: pass −0.10 [−0.28, +0.10] (j1), 0.00 (j2); fidelity −0.17 and −0.07. Every difference is
  within noise.
- chips800 − chips: key points +0.30 [0.00, +0.55] (j1), +0.28 [−0.05, +0.57] (j2): a hint that a larger
  budget helps, not a result.
- **Controls work.** Oracle − none on key points is +1.35 / +1.32 and oracle − shuffled +1.80 / +1.70;
  shuffled never passes. (Shuffled answers score high on fidelity because they mostly say the notes do not
  cover the question.)
- Judge agreement: pass 0.94; weighted kappa 0.77 to 0.87 across the five fields.
- Automatic checks: answers to chips notes cite an [E#] that does not exist in 10% of cases (b1: 0%,
  chips800: 7%).

**qwen3.6:35b-a3b** (chips and oracle contexts only, same questions and notes)

| Context | pass | key points | fidelity | attribution | abstains |
|---|---|---|---|---|---|
| chips | 0.45, 0.40 | 2.73, 2.67 | 3.73, 3.70 | 3.98, 3.88 | 17% |
| oracle | 0.65, 0.57 | 3.08, 2.98 | 3.62, 3.55 | 3.95, 3.88 | 5% |

35b − 9b, same context (j1 / j2):

| | pass | fidelity | attribution |
|---|---|---|---|
| chips | +0.15 [0.00, +0.30] / +0.07, within noise | +0.53 [+0.17, +0.85] / +0.55 [+0.23, +0.90] | +0.35 [+0.12, +0.55] / +0.33 [+0.07, +0.57] |
| oracle | +0.35 [+0.17, +0.53] / +0.28 [+0.05, +0.47] | +0.53 [+0.23, +0.80] / +0.35, within noise (j2) | +0.47 [+0.23, +0.72] / +0.40 [+0.15, +0.68] |

- Fidelity and attribution rise clearly. Key points do not. The 35b abstains more (17% on chips notes).
- With the 9B, oracle and chips pass equally (0.30). With the 35b, oracle passes more than chips
  (+0.20 [0.00, +0.40] in j1, +0.17 [−0.05, +0.38] in j2, borderline): once the generator is strong
  enough, a retrieval gap becomes visible.
- Judge agreement: pass 0.91; weighted kappa 0.71 to 0.88.
- The 35b was **not** run on the B1 context, so there is no chips − B1 comparison with the stronger
  generator.

## The doc's open problems, as seen here

| Problem | What this test shows |
|---|---|
| 1. Shared sentences duplicate across units | Merge fixes it at pack time; it raises recall@4 but not nDCG, and part of that is mechanical (see above) |
| 2. Units are bigger than B1's | Items are ~187 vs 156 tokens; a larger budget (800) hints at more key points, not significantly |
| 3. Hedging preambles | Not tested |
| 4. Generic case answers | Down-weighting near-duplicate case units had no effect on this data |
| 5. Chip discipline is unknown | Not testable on synthetic data; half of the silver sentences have no chip by construction |
| 6. Direction patterns are crude | 13 direction flags on 28 responses; nobody checked them |
| 7. Q1 wording primes positive readings | Q1 was reworded for the chip answers (toward, away or ordinary); not compared with the old wording |
| 8. The 9B generator remains the limit | Confirmed: oracle passes only 30% with the 9B; the 35b reaches 57–65% |

## Limits of this test

- Silver is synthetic: two simulated experts, 14 vignettes, one writer model. A Claude judge grading
  Claude-written answers may share blind spots.
- 40 questions; intervals are wide, and "within noise" does not mean "equal".
- Direction toggles were never reviewed, since there is no review screen. Step 5 is only logged
  (`flag_shown`, `skipped`).
- Classifier accuracy is a masked-chip proxy, not hand labels.
- The B1 header still carries the old Q1 wording ("fragments relevant to ADHD-related traits").
- The reference claims were written in the same call as the answers, so they are consistent with them by
  construction.
- Bronze (37 of 42 answers from the 35b model) was used for plumbing only: it ran through the classifier,
  the unit builder and Postgres, and nothing about accuracy is claimed from it.

## Things that went wrong, and what was done

- **Judge reply format.** The Sonnet judges dropped the outer system-label level (`{"A": {...}}`) in all 18
  first-round files, and one second-round file had misplaced brackets. These were repaired mechanically in
  copies under `fixed/` (originals kept); the grades themselves were not touched. Later judge prompts stated
  the shape explicitly.
- **Two answer checks were too strict** (the word "persona" matched "personality"; generic words such as
  "sleep" were counted as leaks of the A/B design). Two valid silver replies were rejected and restored after
  the checks were fixed. 26 of 28 silver replies passed on the first try.
- **The 35b model as answer writer.** It fails the format checks often (missing Q2, highlights with "..."
  that are not exact substrings, claim directions outside the vocabulary, no rating) and never sets
  "insufficient information" when told to decline, so bronze rotates three answer styles instead of four.
- **One silver writer** did not read the chip-habit text for V004 to V013 (it said so). Chip use came out the
  same either way (47–49% of sentences).
- **Load time.** The 35b model's cold load took about 13 minutes the first time and about 25 minutes after
  the 9B evicted it.

## Where things are

| What | Where |
|---|---|
| Old data (moved, sha256 manifest inside) | `data/backup/pre_chips_2026-11-04/` |
| New fixtures | `data/fixtures_chips/synthetic/{bronze,silver}/` |
| Built units and embeddings | `data/expert_units_chips/synthetic/<tier>/<classifier>/` |
| Retrieval report | `data/eval/chip_units/latest.json` |
| Generation runs, judgments | `data/eval/expert_runs/20261104-chips-silver/` and `…-silver-35b/` |
| Postgres | schema `chips` at the time, synthetic only, `public.chunks` untouched. On 2026-11-05 `chips` became the application's schema (migration `0003`) and these rows were taken out: a binary backup is in `data/backup/chips_synthetic_2026-11-05/` (`scripts/db/chips_backup.py restore`), and `scripts/db/load_chips_pg.py` now loads into `chips_eval`. The `.json` and `.npz` files under `data/expert_units_chips/` are the source and were not touched |
| Code | `scripts/elicitation/` (`chips_schema`, `make_chip_fixtures`, `classify_sentence_targets`, `chip_findings`, `build_chip_units`), `scripts/rag/` (`chip_retrieval`, `eval_chip_units`, `eval_chip_generation`), `scripts/db/` (`chips_schema.sql`, `load_chips_pg`) |
| Prompts | `Persona_claude.v2`, `Synthetic_expert_answer.v4`, `Expert_sentence_targets.v1` |

Restoring the old setup is a plain `mv` of the backup folders back to `data/`. Until then
`answer_vignettes.py`, `chat_expert.py` and `eval_expert_*.py` find no fixtures, and the real answers of E02
and the draft of E01 are in the backup.

## Possible next steps

1. Run the 35b generator on the B1 context too (about 15 minutes of GPU plus one judging round) to see
   whether the retrieval gain turns into a generation gain with a stronger generator.
2. Hand-label the chip-less sentences of 10 to 15 responses to get the classifier accuracy the doc asks for.
3. Fix or drop the cue-key route for patient mode before investing in a frontend for it.
4. Regenerate silver with the answering agent seeing the Q1 wording of the old design, to separate the effect
   of the wording from the effect of chips.
