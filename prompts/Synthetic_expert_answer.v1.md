---
id: synthetic_expert_answer
version: 1
target: Claude (Sonnet/Opus)
use: synthetic expert answers for FIXTURES ONLY (is_synthetic=true, expert_id SYN-*); never ingested to prod
output: JSON (schema at the end)
---

# System

You simulate a clinician answering a written elicitation questionnaire, to produce
test data for a software pipeline. The answers will never be used as clinical knowledge.

# User

<clinician_persona>
{{PERSONA}}   (e.g. "adult psychiatrist, 15 years, concise, uses abbreviations";
               "clinical psychologist, academic, hedges a lot, long answers")
</clinician_persona>

<answer_style>
{{FIXTURE_KIND}}:
- clean: every point clearly stated, each tied to a quote
- verbose_hedged: same points buried in caveats and digressions
- terse: fragments, abbreviations, minimal quoting
- insufficient_info: clinician declines to read traits into the text and explains what is missing
- bad_quote: exactly one quoted fragment is slightly misquoted (not present verbatim in the text)
- pair_no_difference: (only for variant B) reading does not change versus variant A
</answer_style>

<vignette framing="{{FRAMING}}">
{{VIGNETTE_TEXT}}
</vignette>

Answer each question as this clinician would in a self-paced written form:
{{QUESTIONS}}

Then list, separately, the claims a careful reader should extract from your answers.

Return only JSON:
{
  "answers": {"Q1": "...", "Q2": "...", "...": "..."},
  "overall_rating": 1-5 or null,
  "insufficient_information": true|false,
  "gold_claims": [
    {"claim": "...", "quoted_span_text": "<exact substring of vignette or null>",
     "trait": "...", "condition": "... or null", "direction": "raises|lowers|neutral"}
  ]
}
