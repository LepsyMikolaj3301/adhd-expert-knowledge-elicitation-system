---
id: persona_claude
version: 1
target: Claude (Sonnet/Opus) via API or Claude Code
use: controllable first-person texts — when a specific trait mix, confounder, or A/B variant is needed
output: JSON (schema at the end)
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
Where it was written: {{SOURCE_TYPE}}   (forum_post | personal_journal | email)
Writing habits: {{STYLE}}   (e.g. long run-on sentences, returns to the point late; or terse, lowercase)
</persona>

<hidden_traits>
Let these show only through concrete, mundane detail. Never name them.
{{TRAITS}}   (e.g. task_initiation: moderate; time_estimation: weak; novelty_seeking: weak)
</hidden_traits>

<confounders>
Include these as plausible alternative explanations, mentioned in passing:
{{CONFOUNDERS}}   (e.g. moved flats two months ago and sleeping badly)
</confounders>

Constraints:
- 120–250 words. One continuous text, no title, no sign-off.
- The text is about the topic. At most {{MAX_CUES}} moments where a trait shows. Many real
  people with these traits write texts where they barely show; err on the side of subtle.
- Never use: ADHD, attention deficit, executive function, dopamine, hyperfocus, neurodivergent,
  diagnosed, medication names, "my brain is wired", "my therapist says", or any self-diagnosis.
- No list of symptoms. If a reader could tick off DSM criteria line by line, rewrite it.
- No moral, no self-insight paragraph at the end, no "anyway, sorry for the rant" unless the
  style calls for it.
- Real people are inconsistent: allow one small contradiction or unfinished thought.

{{IF_VARIANT}}
This is variant B of the text below. Change ONLY this: {{VARIANT_CHANGE}}.
Keep every other sentence identical, character for character.
<variant_a>{{VARIANT_A_TEXT}}</variant_a>
{{END_IF}}

Return only JSON:
{
  "text": "...",
  "planted_cues": [{"quote": "<exact substring of text>", "trait": "...", "strength": "weak|moderate|strong"}],
  "confounders": [{"quote": "<exact substring of text>", "alternative_explanation": "..."}]
}
