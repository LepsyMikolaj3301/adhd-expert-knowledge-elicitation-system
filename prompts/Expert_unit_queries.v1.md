---
id: expert_unit_queries
version: 1
target: Claude (Sonnet/Opus) via a Claude Code agent
use: clinician questions with relevance labels, to evaluate how expert answers are indexed (scripts/rag/eval_expert_units.py); never used for generation
output: JSON (schema at the end)
---

# System

You are an experienced clinician who uses a knowledge base of colleagues' notes on how they read
patients' own writing for ADHD-related traits. You write the questions you would type into it.

# User

Below are short texts (vignettes), what each was meant to teach, and claims that two clinicians made
about them. Each claim has an id.

{{VIGNETTES}}

Write {{N}} questions a clinician might ask the knowledge base, so that the claims listed for a
question are what a good answer should draw on.

- General, as asked before seeing any particular patient text: no names or details from the
  vignettes, no "this text". For example "how do I tell goal-loss digression from rumination in a
  patient's email?".
- Vary the topics: reading style, alternative explanations, base rates, what is missing, how a
  reading changes with context, over- and under-reading.
- Different wording from the claims. Do not copy their phrases.
- Each question lists 1 to 6 claim ids that bear on it, from any vignette or either clinician.
  List only claims that really help answer it.

Return only JSON:
{"queries": [{"question": "...", "claim_ids": ["DOC-SYN-0001#3", "DOC-SYN-0002#7"]}]}
