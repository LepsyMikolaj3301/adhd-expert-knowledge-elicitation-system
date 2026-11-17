---
id: synthetic_expert_answer
version: 5
target: local instruct models, one per expert (gpt-oss:20b, mistral-small3.2:24b, qwen3.8:27b); the expert comes from prompts/expert_personas/
use: synthetic expert answers with highlights, direction toggles and citation chips for the scale fixture (is_synthetic=true, expert_id SYN-*); never ingested to prod
output: JSON (schema at the end), the same as v4
changes: v5 = v4 with the writing left to the expert. `PERSONA_SYSTEM` is the expert's own system prompt and `WRITING_STYLE` their way of writing and citing (both from prompts/expert_personas/E<nn>.v1.md), replacing `PERSONA`, `STYLE_RULE`, `CHIP_HABIT` and the shared register example, so experts differ in how they write, not in how well they read. The reading rules stay the same for everyone
---

# System

{{PERSONA_SYSTEM}}

The output is test data for a software pipeline and is never used as clinical knowledge.

# User

<your_writing>
{{WRITING_STYLE}}
Your way of writing changes how you put things, never how well you read the text.
</your_writing>

<vignette framing="{{FRAMING}}">
{{VIGNETTE_TEXT}}
</vignette>

Questions:
{{QUESTIONS}}

How the form works:

A. Highlights first. Mark 3 to 6 stretches of the text that matter for your reading, in either
   direction. Copy each one exactly, word for word, from the text (3 to 25 words). Number them 1, 2,
   ... in the order you mark them. Give each one a toggle, your own call on reading that fragment:
   "toward" (points toward ADHD-related traits), "away" (points away: an ordinary explanation, an
   organised habit), "neutral" (ordinary, tells you little) or "unclear" (you cannot tell). Use
   "unclear" when you truly cannot tell, not as a default.
B. Chips. In your answers you cite a highlight by writing its chip, ⟦h1⟧ for highlight 1, ⟦h2⟧ for
   highlight 2, and so on, anywhere in the text, as often as you like and several in one sentence
   if the sentence is about several. Cite only highlights you marked. How often and where you cite is part of your own way of writing (above). You may also
   quote a few words from the text in double quotes, with or without a chip. Do not write the
   highlight's full text again next to its chip.

How an experienced clinician answers this kind of form:

1. Read HOW it is written, not only WHAT happened. Look at structure (does the text get back to its
   point, does it answer its own opening question), self-corrections ("anyway"), where a digression
   goes (somewhere new versus back to the same worry), time words ("just", "a bit", "about", "soon"),
   hedging and apologising, register for the medium (phone note, formal email), whose opinion is
   being repeated, what the writer says is the problem versus what the text shows. Content alone
   ("I forgot", "I got distracted") is weak evidence: everybody writes that.
2. Keep track of who is who. The writer is the "I". Other people named in the text are not the
   person being assessed. You are the reader, not the writer.
3. Base rates. Ordinary stress, a new job, grief, poor sleep and a talkative personality explain a
   lot. Say so when they do. A control text with nothing in it deserves a low rating, not a
   search for something to find. Careful checking and list-keeping is usually just being organised.
4. Q3 is about THIS text: what would you want to see or ask next (another sample written on a calm
   day, the earlier message it refers to, a specific question to the writer). Do not recite the
   diagnostic criteria (onset age, 6 months, two settings, rule out thyroid): a colleague knows
   them. One short nod to "the usual history" is fine.
5. Plain clinical language. No neurotransmitters, hormones or theory names. Never write about
   yourself in the third person and never mention a persona, a questionnaire design, versions of the
   text or that this is a test. If a question has no real answer, say why in your own words instead
   of "N/A".
6. Answer lengths follow your own habits (above); real answers are uneven, and later answers may point
   back ("as Q2") when that is how you write.
7. Q6: always give a rating 1-5 in overall_rating, and always set insufficient_information to false.
   Uncertainty goes into the answers, not into withholding the rating. 1 = nothing beyond ordinary, 5 = strong and specific.

Then list, separately, the claims a careful reader should extract from your answers. One claim per
point you actually made, attached to the answer it is in. Write each claim so it makes sense on its
own: use the fragment's words, never a chip. A claim's quoted_span_text must be an exact substring
of the vignette (or null if the claim quotes nothing).

Return only JSON:
{
  "highlights": [{"chip": 1, "text": "<exact substring of the vignette>",
                  "direction": "toward|away|neutral|unclear"}],
  "answers": {"Q1": "...", "Q2": "...", "Q3": "...", "Q5": "..."},
  "overall_rating": 1-5 or null,
  "insufficient_information": false,
  "gold_claims": [
    {"question_id": "Q1|Q2|Q3|Q5", "claim": "...",
     "quoted_span_text": "<exact substring of vignette or null>",
     "trait": "<snake_case trait or null>", "condition": "... or null",
     "direction": "raises|lowers|neutral"}
  ]
}
