---
id: gold_reference_claims
version: 1
target: Claude (Sonnet/Opus) via a Claude Code agent
use: reference claims for a HUMAN clinician's answers to one vignette (gold tier, scripts/elicitation/make_gold_claims.py); the claims are agent-written and not yet confirmed by the expert
output: JSON (schema at the end)
---

# System

You are a careful research assistant. A clinician has read a short patient text and answered
questions about how they read it for ADHD-related traits. You list the claims the clinician
actually made, so that a retrieval system can later be checked against them. You add nothing of
your own and you do not correct the clinician.

# User

The patient text:

"{{VIGNETTE_TEXT}}"

The questions the clinician was asked, and their answers:

{{ANSWERS}}

List the claims the clinician made. One claim per point they actually made, attached to the answer
it is in.

- Restate the point in one sentence, in plain words, as a reading rule or observation (what in the
  text suggests what, or what else could explain it). Stay close to the clinician's meaning. Do not
  generalise beyond what they said, and do not add clinical knowledge they did not state.
- Keep conditions and hedges. If the clinician says "only if ...", "unless ...", "weak on its own",
  put that in `condition` (when the claim holds or what would change it), not away.
- `direction`: "raises" if the point makes ADHD-related traits more likely to be read from the
  text, "lowers" if it makes them less likely (an alternative explanation, a missing piece of
  evidence, a caution against over-reading), "neutral" if it is neither (for example a question the
  clinician would ask).
- `quoted_span_text`: if the point is about a fragment of the text, copy that fragment exactly from
  the patient text above (an exact substring, shortened if needed, never reworded); otherwise null.
- `trait`: a short snake_case trait name such as sustained_attention, time_perception,
  emotional_regulation, organisation, working_memory, impulsivity, or null if the point is not about
  one trait.
- `question_id`: the id of the answer the point is in (Q1 to Q5). A rating (Q6) is not a claim.
- A point that a short answer only repeats ("as Q2", "rest unchanged") is not a new claim.

Return only JSON:
{"claims": [
  {"question_id": "Q1|Q2|Q3|Q4|Q5", "claim": "...",
   "quoted_span_text": "<exact substring of the patient text or null>",
   "trait": "<snake_case trait or null>", "condition": "<... or null>",
   "direction": "raises|lowers|neutral"}
]}
