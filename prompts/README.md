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
| `Expert_unit_keys.v1.md` | `expert_unit_keys` | 1 | local instruct model (qwen3.5:9b), JSON mode | `VIGNETTE_TEXT`, `UNIT` (a rendered expert unit: header, quoted vignette sentences, the clinician's point) | JSON: `reading_rule`, `questions[2-3]`, `traits[]`, `direction`; search keys only, never shown to the answer generator |
| `Expert_unit_queries.v1.md` | `expert_unit_queries` | 1 | Claude via a Claude Code agent | `VIGNETTES` (texts, knowledge targets, reference claims with ids), `N` | JSON: `queries[{question, claim_ids[]}]`; evaluation only |
| `Expert_unit_pooling.v1.md` | `expert_unit_pooling` | 1 | Claude (Haiku/Sonnet) via a Claude Code agent | `BLOCK` (10 questions, each with the claims retrieved for it, with ids) | JSON: `labels{Q<n>: [claim ids]}`; evaluation only |
| `Reddit_post_screen.v1.md` | `reddit_post_screen` | 1 | local instruct model (qwen3.5:9b), JSON mode | `POST_TEXT` (a cleaned r/ADHD post) | JSON: `kind`, `episodes`, `subtlety`, `trait`, `fit`, `reason`; selects candidate texts only, never reference answers |
| `Gold_reference_claims.v1.md` | `gold_reference_claims` | 1 | Claude (Sonnet/Opus) via a Claude Code agent | `VIGNETTE_TEXT`, `ANSWERS` (the human's answers with their questions, the Q4 scale answer and the Q6 rating) | JSON: `claims[{question_id, claim, quoted_span_text, trait, condition, direction}]`; gold tier, written from human answers, not yet confirmed by the expert |

The `bad_quote` fixture kind listed in the expert-answer prompt is not sent to the model: the script asks
for a `clean` answer and breaks one quote itself.

Fixtures only: the expert-answer prompt produces `is_synthetic=true` data that must never be ingested
into the production knowledge base.
