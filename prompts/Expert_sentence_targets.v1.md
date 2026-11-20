---
id: expert_sentence_targets
version: 1
target: local instruct model (qwen3.5:9b, qwen3.6:35b-a3b), JSON mode
use: step 3 of notes/new-chips-knowledge.md: assigns the sentences of a clinician's answers that carry no chip and no matching quote to the highlights they are about (ids only); the model never writes text that is stored or shown
output: JSON (schema at the end)
---

# System

You file the sentences of a clinician's written answers under the part of a patient's text they are
about. You only return ids. You never write, quote or rephrase anything.

# User

A clinician read a short text written by a patient and answered questions about it. They marked some
fragments of the text (highlights, each with an id). Decide which highlight each listed sentence is
about.

<patient_text>
{{VIGNETTE}}
</patient_text>

<highlights>
{{HIGHLIGHTS}}
</highlights>

<answers>
All sentences of this clinician's answers, in order. A sentence marked "-> h3" already has its
target; it is shown for context only.
{{SENTENCES}}
</answers>

Sentences to file: {{UNRESOLVED}}

For each sentence to file, return a list with one or more of:
- highlight ids (for example "h3", "i1") when the sentence is about those fragments, even if it does
  not quote them (a sentence about "the shaking" is about the highlight with the shaking hand);
- "case" when it is about the person or the text as a whole: history, what information is missing,
  the overall rating, general advice about reading texts like this;
- "prev" when it only continues the sentence just before it (an example, a caveat, a "because ..."
  or "so ...") and has no target of its own. "prev" must be the only item in its list and is not
  allowed for the first sentence of an answer.
Use only the ids listed under highlights. If you cannot decide between a highlight and "case",
choose "case".

Return only JSON with one entry per sentence to file, and nothing else:
{"Q1.3": ["h3", "h4"], "Q2.3": ["case"], "Q3.3": ["prev"]}
