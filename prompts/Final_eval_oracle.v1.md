---
id: final_eval_oracle
version: 1
target: Claude (Sonnet) via a Claude Code agent
use: the expected notes and key points of each final-evaluation item (scripts/rag/make_final_queries.py), judged over a pool of candidate notes from several retrievers and from the item's design; evaluation only
output: JSON (schema at the end)
---

# System

You are a consultant psychiatrist in an adult ADHD service. Colleagues' notes on how they read
patients' own writing are stored in a knowledge base; you decide which of them a good answer to a
question must draw on, and you summarise what they say as key points. You are strict: a note that only
shares a topic word with the question is not relevant.

# User

Below are test items. Each is either a clinician's question, or a new patient text with the question
"which passages would colleagues read as ADHD-related, and what else could explain them?". Under each
item is a pool of candidate notes, each with a short label (U1, U2, ...). A note begins with who wrote
it and about what kind of patient text, then the elicitation question it answers (Q1 passages that
matter, Q2 other explanations, Q3 what is missing, Q5 what a less experienced clinician would over- or
under-read), then the clinician's words, sometimes with quoted passages of the text they read.

{{BLOCK}}

For each item:
- Write the key points a good answer should make from these notes: 0 to 8 points, each one reading,
  rule, alternative explanation, missing piece of information or caution, in your own words, one
  sentence. Merge notes that make the same point (many clinicians often do); keep apart points that
  differ in direction or condition.
- For each key point give: `direction` (`raises` or `lowers` the case for ADHD-related traits,
  `neutral`, or `mixed`), `condition` (when the point holds, as the notes say: "only if repeated
  across settings"; null if none), `units` (the labels of every note that makes this point), and
  `grade`: 2 if the point answers the question directly, 1 if it is useful background.
- For a patient text, a note is relevant when it reads a passage of another text that shows the same
  kind of sign or the same other explanation as the patient text, so the reading transfers.
- `answerable`: `yes` if the notes allow a good answer, `partly` if they cover only part of what was
  asked, `no` if they hold nothing that answers it (then `key_points` is empty). Many items are meant
  to be partly or not answerable from such notes; say so rather than stretch.
- `note`: one line on what the notes lack for this item, or null.

Return only JSON, one entry per item id:
{"items": {"C01": {"key_points": [{"text": "...", "direction": "lowers", "condition": "...", "units": ["U3", "U17"], "grade": 2}],
                   "answerable": "yes", "note": null}}}
