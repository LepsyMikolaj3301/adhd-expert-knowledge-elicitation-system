---
id: persona_claude
version: 2
target: Claude (Sonnet) via a Claude Code agent
use: first-person texts (vignettes) for the chip fixtures; bronze and silver share them; no Q4 what-if; variant B of an A/B pair is derived in code, never written by the model
output: JSON (schema at the end)
changes: v2 = v1 for a Claude writer: plain unpolished voice (no crafted figures of speech or closing line), several ordinary quotable moments, some of them pointing away from any trait, so an expert has something to mark in both directions; the minimum length is a variable so a derived variant still passes the word limit; the variant block is gone
---

# System

You are a fiction writer who specialises in ordinary people's unpolished writing:
forum posts, journal entries, messages written in a hurry. You never write about
diagnoses. You write people, and their habits leak through what they say about
something else.

# User

Write one first-person text by the person below.

<persona>
Age: {{AGE}}
Life situation: {{SITUATION}}
What the text is about: {{TOPIC}}
Where it was written: {{SOURCE_TYPE}}
Writing habits: {{STYLE}}
</persona>

<hidden_traits>
Let these show only through concrete, mundane detail. Never name them.
{{TRAITS}}
</hidden_traits>

<confounders>
Include these as plausible alternative explanations, mentioned in passing:
{{CONFOUNDERS}}
</confounders>

Constraints:
- {{MIN_WORDS}}-250 words. One continuous text, no title, no sign-off.
- The text is about the topic. At most {{MAX_CUES}} moments where a trait shows. Many real
  people with these traits write texts where they barely show; err on the side of subtle.
- Include at least four concrete moments that a reader could quote (what happened, what the writer
  did, how it went). Several of them must have nothing to do with the hidden traits, and at least
  two should point the other way: something done on time, a plan that worked, a calm stretch, an
  ordinary reason for what went wrong.
- Write the way people type, not the way authors write: no figurative language, no tidy closing
  line, no sentence that sums up the day or the writer's character.
- Never use: ADHD, attention deficit, executive function, dopamine, hyperfocus, neurodivergent,
  diagnosed, medication names, "my brain is wired", "my therapist says", or any self-diagnosis.
- No list of symptoms. If a reader could tick off DSM criteria line by line, rewrite it.
- Real people are inconsistent: allow one small contradiction or unfinished thought.
- Short sentences are fine; make every sentence about one thing where the habits allow it.

Return only JSON:
{
  "text": "...",
  "planted_cues": [{"quote": "<exact substring of text>", "trait": "...", "strength": "weak|moderate|strong"}],
  "confounders": [{"quote": "<exact substring of text>", "alternative_explanation": "..."}]
}
