---
id: persona_base_fewshot
version: 1
target: local BASE model (not instruct/chat), raw completion endpoint
use: realistic first-person texts (ADHD-like and controls) for vignettes and fixtures
endpoint: Ollama /api/generate with "raw": true, or llama.cpp /completion
sampling: {temperature: 0.95, top_p: 0.95, repeat_penalty: 1.1, max_tokens: 380, stop: ["\n=== ENTRY"]}
---

# How this works

A base model has no "assistant" layer. It does not explain, summarise or list symptoms;
it continues a document. So this is not an instruction prompt, it is the **start of a
document** whose most likely continuation is one more entry of the same kind.

Rules for filling the template:
- `{{EXAMPLES}}`: 3–4 entries. Use **leak-stripped** posts (ADHD, medication names,
  "diagnosed", "my psychiatrist", subreddit names removed or rewritten). For ADHD-like
  output take them from r/ADHD; for controls take them from a control subreddit. Same template
  for both, so the template itself is never the signal.
- Rotate examples on every call (random sample from a pool of ≥30) — fixed examples get copied.
- `{{TOPIC}}`: the surface topic of the entry (work report, flatmate, sister's birthday,
  moving out). The text should be *about* this, traits appear only incidentally.
- `{{AGE}}`, `{{SITUATION}}`: light persona anchor.
- After generation, run: leak-term scan, word count 120–250, and an n-gram overlap check
  against the examples (reject if any 8-gram is copied — the model regurgitated).

# Template (send everything below this line, filled in, as the raw prompt)

Personal notes — anonymous journal entries shared for a writing study.
Participants wrote freely about whatever was on their mind that day. Entries are
unedited: spelling, run-on sentences and topic changes are kept as written.

{{EXAMPLES}}

=== ENTRY {{N}} ===
Age: {{AGE}}
Situation: {{SITUATION}}
On my mind today: {{TOPIC}}
