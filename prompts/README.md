# Prompts

Versioned prompt files. **Never edit a released prompt in place**: a change is a new file
(`name.v2.md`) so fixtures and manifests can say exactly which prompt produced them.
Each file starts with front-matter (`id`, `version`, `target`, ...); the loader is
`scripts/elicitation/prompt_loader.py` (`load_prompt(name).fill(VAR=...)`; a missing or unused
`{{VAR}}` is an error, trailing `(e.g. ...)` hints after a placeholder are dropped).

| File | id | v | Target model | Input variables | Output |
|---|---|---|---|---|---|
| `Persona_base_fewshot.v1.md` | `persona_base_fewshot` | 1 | local **base** model, raw completion (Ollama `/api/generate` with `raw`) | `EXAMPLES`, `N`, `AGE`, `SITUATION`, `TOPIC` | plain text (one journal entry), stops at `\n=== ENTRY` |
| `Persona_claude.v1.md` | `persona_claude` | 1 | Claude via a Claude Code agent; also works on local instruct models (e.g. qwen) | `AGE`, `SITUATION`, `TOPIC`, `SOURCE_TYPE`, `STYLE`, `TRAITS`, `CONFOUNDERS`, `MAX_CUES`, and for variant B `IF_VARIANT`, `VARIANT_CHANGE`, `VARIANT_A_TEXT` (pass `""` otherwise) | JSON: `text`, `planted_cues[{quote,trait,strength}]`, `confounders[{quote,alternative_explanation}]` |
| `Synthetic_expert_answer.v1.md` | `synthetic_expert_answer` | 1 | bronze: local instruct model (qwen) | `PERSONA`, `FIXTURE_KIND`, `FRAMING`, `VIGNETTE_TEXT`, `QUESTIONS` | JSON: `answers{Q1..}`, `overall_rating`, `insufficient_information`, `gold_claims[{claim,quoted_span_text,trait,condition,direction}]` |
| `Synthetic_expert_answer.v2.md` | `synthetic_expert_answer` | 2 | silver: Claude via a Claude Code agent | same as v1 | as v1, plus `question_id` on each claim; asks for reading the writing itself, a text-specific Q3, and a rating unless `insufficient_info` |
| `Synthetic_expert_answer.v3.md` | `synthetic_expert_answer` | 3 | silver: Claude via a Claude Code agent | same as v1 | as v2, plus `q4{hypothesis, shift -2..2, toward, other_explanation}` for the what-if question (Q4's why stays in `answers.Q4`, omitted at shift 0) |
| `Persona_claude.v2.md` | `persona_claude` | 2 | Claude (Sonnet) via a Claude Code agent | `AGE`, `SITUATION`, `TOPIC`, `SOURCE_TYPE`, `STYLE`, `TRAITS`, `CONFOUNDERS`, `MAX_CUES`, `MIN_WORDS` | JSON as v1; plain voice, several ordinary quotable moments (some pointing away from a trait), no variant block (variant B is derived in code); for the chip fixtures |
| `Synthetic_expert_answer.v4.md` | `synthetic_expert_answer` | 4 | silver: Claude (Sonnet) via a Claude Code agent; bronze: qwen3.6:35b-a3b | `PERSONA`, `STYLE_RULE`, `CHIP_HABIT`, `FRAMING`, `VIGNETTE_TEXT`, `QUESTIONS` | JSON: `highlights[{chip,text,direction}]`, `answers{Q1,Q2,Q3,Q5}` with `⟦hN⟧` chips, `overall_rating`, `insufficient_information`, `gold_claims`; no Q4 (notes/new-chips-knowledge.md) |
| `Synthetic_expert_answer.v5.md` | `synthetic_expert_answer` | 5 | local instruct models, one per expert (gpt-oss:20b, mistral-small3.2:24b, qwen3.8:27b); scale fixture | `PERSONA_SYSTEM`, `WRITING_STYLE`, `FRAMING`, `VIGNETTE_TEXT`, `QUESTIONS` | as v4; the expert's own system prompt and way of writing and citing replace `PERSONA`, `STYLE_RULE`, `CHIP_HABIT` and the shared register example, so experts differ in how they write, not in how well they read |
| `expert_personas/E21.v1.md` ... `E32.v1.md` | `expert_persona` | 1 | the model named in the file (`model`; `think: low` for gpt-oss) | none (loaded whole: `# System` -> `PERSONA_SYSTEM`, `# User` -> `WRITING_STYLE`) | one file per synthetic expert of the scale fixture: front-matter `expert`, `role`, `model`, `think`, `citation` (the one-line habit), then the expert's system prompt and their writing block with an example in their own register. Experts 21-25 gpt-oss, 26-30 mistral-small, 31-32 qwen3.8 |
| `Expert_unit_keys.v1.md` | `expert_unit_keys` | 1 | local instruct model (qwen3.5:9b), JSON mode | `VIGNETTE_TEXT`, `UNIT` (a rendered expert unit: header, quoted vignette sentences, the clinician's point) | JSON: `reading_rule`, `questions[2-3]`, `traits[]`, `direction`; search keys only, never shown to the answer generator |
| `Expert_unit_queries.v1.md` | `expert_unit_queries` | 1 | Claude via a Claude Code agent | `VIGNETTES` (texts, knowledge targets, reference claims with ids), `N` | JSON: `queries[{question, claim_ids[]}]`; evaluation only |
| `Expert_unit_pooling.v1.md` | `expert_unit_pooling` | 1 | Claude (Haiku/Sonnet) via a Claude Code agent | `BLOCK` (10 questions, each with the claims retrieved for it, with ids) | JSON: `labels{Q<n>: [claim ids]}`; evaluation only |
| `Expert_sentence_targets.v1.md` | `expert_sentence_targets` | 1 | local instruct model (qwen3.5:9b, qwen3.6:35b-a3b), JSON mode | `VIGNETTE`, `HIGHLIGHTS`, `SENTENCES`, `UNRESOLVED` | JSON: `{sentence id: [highlight ids \| case \| prev]}`, ids only, validated by code; step 3 of notes/new-chips-knowledge.md |
| `Answer_enhance.v1.md` | `answer_enhance` | 1 | local instruct model (qwen3.5:9b), JSON mode | `QUESTION`, `ANSWER`, `CITATIONS` (the cited passages) | JSON `{"answer"}`: the clinician's answer in fuller sentences; replaced by v2, which the proofread job uses (its replies copied the passages into the answer, often in the patient's first person) |
| `Answer_enhance.v2.md` | `answer_enhance` | 2 | local instruct model (qwen3.5:9b), JSON mode | `QUESTION`, `ANSWER` | as v1; not shown the passages, four worked examples in the system message, the clinician is always the speaker. Code refuses replies that change the chips, grow too long, copy passage words (`leak`) or tell the passage in the first person (`voice`), `backend/app/proofread/enhance.py` |
| `Enhance_fidelity_judge.v1.md` | `enhance_fidelity_judge` | 1 | Claude (Haiku/Sonnet) via a Claude Code agent | `PAIRS` (blinded pairs: question, original, passages, edited) | JSON `{pair id: {meaning same/added/removed/changed, voice_ok, fuller 1-3, note}}`; evaluation only (`scripts/elicitation/eval_enhance.py`) |

The `bad_quote` fixture kind listed in the expert-answer prompt is not sent to the model: the script asks
for a `clean` answer and breaks one quote itself.

A persona file is versioned like a prompt: changing an expert's way of writing is `E21.v2.md`, so a fixture's manifest can say which wording produced it.

Fixtures only: the expert-answer prompt writes test answers for the fixtures.
