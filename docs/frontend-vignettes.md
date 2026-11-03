# Vignettes in the frontend

How the web elicitation platform should show a vignette and collect a clinician's answers. It
covers structure and behaviour, not a framework. The reference implementations are the notebook
`notebooks/answer_vignettes.ipynb` and the terminal app `scripts/elicitation/answer_vignettes.py`.
The data contract is [elicitation-document.md](elicitation-document.md), and the JSON Schema is
`data/schemas/elicitation_document.schema.json` (schema version 1.1).

## 1. What the frontend gets

| From | What | Notes |
|---|---|---|
| `Vignette.expert_view()` | `id`, `version`, `text`, `framing`, `question_ids`, `q4_whatif`, `variant`, `content_hash` | Never the hidden `design` block: it holds the planted cues and is what the answers are scored against. |
| `questions.QUESTIONS` | `id`, `kind`, `text` per question | `kind` is `open`, `shift` (Q4) or `rating_1_5` (Q6). |
| `questions.render_question(q, vignette.q4_whatif)` | The question text as shown | Fills Q4's `{whatif}`. |
| `questions.GATE` | `("Q1", "Q2", "Q3")` | The questions that must be answered before anything else is shown. |
| `questions.Q4_HYPOTHESIS`, `SHIFT_LEAD`, `SHIFT_LABELS`, `TOWARD_LABELS`, `Q4_TOWARD`, `Q4_WHY` | The wording of the Q4 step | Use these strings rather than rewording them, so all answers are given to the same item. |

The questions per vignette are `question_ids`, in that order. A vignette without a `q4_whatif` is
asked without Q4.

## 2. Screen layout

```
┌───────────────────────────────────────────────────────────────────────┐
│ E01 · ▓▓▓▓░░░░ 4 done · 1 skipped · 7 to go                           │
│ [V003][V007][V001]…   chips: current / done / skipped, click to open   │
├───────────────────────────────────────────────────────────────────────┤
│ V001 · personal journal · 212 words                                   │
│ ┌───────────────────────────────────────────────────────────────────┐ │
│ │ vignette text, always visible; fragments the expert has quoted    │ │
│ │ are ▒highlighted▒                                                 │ │
│ └───────────────────────────────────────────────────────────────────┘ │
├───────────────────────────────────────────────────────────────────────┤
│ Q2 · Which of those fragments could equally reflect something else…   │
│ question 2 of 6                                                       │
│ ┌───────────────────────────────────────────────────────────────────┐ │
│ │ answer                                                            │ │
│ └───────────────────────────────────────────────────────────────────┘ │
│ 54 words · ✓ 2 quotes match the text · ⚠ "…" is not in the text      │
├───────────────────────────────────────────────────────────────────────┤
│ [Back] [Next] [Skip vignette] [Save draft] [Finish & write document]  │
└───────────────────────────────────────────────────────────────────────┘
```

- **The vignette text stays on screen for every question.** Text the expert puts in double quotes
  that exactly matches the vignette is highlighted there. A quote that doesn't match is flagged
  under the answer, but this is not an error.
- Optionally, the expert can select text in the vignette to insert it as a quote. That gives exact
  matches. The matched fragments become `quoted_fragments` (see `answer_vignettes.quoted_fragments`).
  A quote shortened with `…` is matched piece by piece.
- One question at a time. A long single page makes it too easy to read ahead, and Q4–Q6 must not be
  seen early (see §3).

## 3. The question flow per vignette

```mermaid
stateDiagram-v2
    [*] --> Phase1
    state Phase1 {
        Q1 --> Q2: non-blank
        Q2 --> Q3: non-blank
    }
    Phase1 --> Gate: Q3 non-blank
    Gate --> Q4: Q1–Q3 locked
    state Q4 {
        Hypothesis --> Scale
        Scale --> Next0: 0
        Scale --> Why: −2 / −1
        Scale --> Towards: +1 / +2
        Towards --> Why
    }
    Q4 --> Q5
    Q5 --> Q6
    Q6 --> Review
    Review --> [*]: Accept & next vignette
```

### Phase 1: Q1–Q3, the gate

- Q1, Q2 and Q3 are open questions. **Each needs a non-blank answer** before Next moves on. If an
  answer is blank, show: "Q2 needs an answer before the next questions."
- **Q4–Q6 are not rendered, and not even sent to the client, until all three are answered.** The
  answers to Q1–Q3 are the expert's reading of the text before they see the what-if or the rating.
- **Passing the gate locks Q1–Q3.** The moment the expert moves from Q3 to the next question, Q1–Q3
  become read-only for this vignette: Back still shows them, but disabled, with a note "locked: you
  have seen the questions after this one". Record the time (`gate_passed_at` in the draft).
- If a vignette asks only some of Q1–Q3, the gate is the ones it asks.

### Phase 2: Q4, Q5, Q6

**Q4: the what-if (a short Script Concordance item).** Its heading is the rendered question, with
the what-if emphasised:

> Given your hypothesis about this person so far: how would it change if **the writer had an exam
> earlier that day**?

The step has four parts, in this order:

1. **Your working hypothesis, in one sentence (required).** A one-line text field. A classic SCT
   item states the hypothesis; here the expert formed their own in Q1–Q3, and this line names it, so
   a shift has something to point at.
2. **The scale (required).** A slider with 5 stops, headed **"With this, my hypothesis…"**:

   | value | label (`SHIFT_LABELS`) |
   |---|---|
   | −2 | is strongly reinforced |
   | −1 | is somewhat reinforced |
   | 0 | is unchanged |
   | +1 | partly changes |
   | +2 | changes completely |

   **The slider has no default position: no thumb until the expert places it.** A slider that starts
   at 0 records "no change" for anyone who skips past it, and in SCTs answering 0 by default is a
   known way to inflate scores. Next is disabled, or warns "Pick a point on the scale", until a stop
   is chosen. Show the label of the chosen stop next to the slider, and show all five labels under
   the stops on wide screens.
3. **Towards… (required, only for +1 and +2).** Three choices: *more ADHD-like* / *less ADHD-like* /
   *another explanation*. Choosing "another explanation" shows a required one-line field "Which
   explanation?".
4. **Why? (required, only when the value is not 0).** A multi-line answer, like the open questions.

Next stays on Q4 until every part that is shown has an answer, and it warns about the first one
missing (`answer_vignettes.q4_incomplete` has the messages). **At 0, only the hypothesis line and
the scale are shown, and Next goes straight on.** If the
expert moves the slider from +2 to 0, hide "Towards…" and "Why?". Their contents may stay in the
draft, but they aren't submitted (see §5).

**Q5** is an open question. **Q6** is a choice of 1–5 or *insufficient information*; the two are
exclusive, and an answer is required.

### Review

After the last question, review lists every answer. Q4–Q6 have an Edit button; Q1–Q3 are shown
with "locked" and no Edit button. Q4 is shown in one line, e.g. *hypothesis: tired, not trait-like
· +1 partly changes, towards less ADHD-like · why: …* (`answer_vignettes.q4_summary`). **Accept &
next vignette** marks the vignette done. A vignette with nothing written should be skipped, not
accepted.

## 4. Skip, pause, resume

- **Order:** the vignettes come in a random order that is fixed per expert (seeded by the expert
  id), so a resumed session shows the same sequence.
- **Skip vignette** sets it aside (orange chip); the expert can come back to it by clicking its chip.
- **Autosave:** save the draft on every Next/Back and every few seconds while typing. Reopening a
  vignette goes to its first unanswered step. A gate question counts as unanswered while it is
  blank, Q4 until a stop is chosen, and Q6 until it is rated.
- **Finish** asks for confirmation, then submits one document with the vignettes that are done.
  Skipped and unfinished ones are left out.

## 5. From UI controls to the payload

One `Response` per finished vignette:

| UI control | `Response` field | Rule |
|---|---|---|
| Q1, Q2, Q3, Q5 text | `answers["Q1"]` … | Trimmed. A blank Q5 is left out; Q1–Q3 can't be blank. |
| Quotes matched in the answers | `quoted_fragments` | Exact substrings of `text`. |
| Q4 hypothesis line | `q4.hypothesis` | Trimmed; required by the UI. |
| Q4 slider | `q4.shift` | Integer −2…2. Required whenever Q4 was asked and the vignette is submitted. |
| Q4 towards | `q4.toward` | `more_adhd` / `less_adhd` / `other`; required with shift +1/+2, else `null`. |
| Q4 "which explanation" | `q4.other_explanation` | Required with `toward = "other"`, else `null`. |
| Q4 why | `answers["Q4"]` | Required with shift ≠ 0; dropped at 0. |
| Q6 | `rating` (1–5) or `insufficient_information: true` | Exclusive. |
| Vignette opened / accepted | `started_at`, `submitted_at` | ISO 8601 with a timezone. |
| The vignette as shown | `vignette_id`, `vignette_version`, `vignette_hash` | Must match the vignette in the document. |

```json
{
  "vignette_id": "V001", "vignette_version": 1, "vignette_hash": "bfcf…",
  "expert_id": "E01", "is_synthetic": false,
  "answers": {"Q1": "…", "Q2": "…", "Q3": "…", "Q4": "An exam would explain the rush.", "Q5": "…"},
  "quoted_fragments": ["I haven't slept well since moving into this new flat two months ago"],
  "q4": {"hypothesis": "sleep loss after the move, not clearly more",
         "shift": 1, "toward": "less_adhd", "other_explanation": null},
  "rating": 2, "insufficient_information": false,
  "started_at": "2026-11-03T10:02:00Z", "submitted_at": "2026-11-03T10:21:00Z"
}
```

The backend schema still accepts a missing hypothesis, direction or why (synthetic answers and
older drafts don't always have them); requiring them is the UI's job.

## 6. Backend validation codes and what to show

The backend validates every document; each error message starts with a stable code. The UI should
prevent these errors, so if one does come back, it means a bug. Show the message and keep the draft.

| Code | Meaning | UI message |
|---|---|---|
| `gate_not_passed` | Q4–Q6 answered while a Q1–Q3 answer is missing | "Q1–Q3 need answers first." |
| `q4_why_without_shift` | A Q4 why with shift 0 or no shift | Drop the why at 0. |
| `toward_without_change` | A direction with shift ≤ 0 | Clear `toward` when the slider goes ≤ 0. |
| `other_without_name` | `toward = other` without a name, or a name without `other` | Name it, or clear it. |
| `empty_answer` | A blank answer, hypothesis or quoted fragment | Trim; send `null` or omit. |
| `quote_not_in_vignette` | A `quoted_fragments` entry is not in the text | Send only exact matches. |
| `question_not_asked` | An answer to a question the vignette didn't ask | — |
| `rating_conflict` | Both a rating and "insufficient information" | — |
| `vignette_hash_mismatch` / `vignette_version_mismatch` | The text changed under the expert | Reload the vignette. |

## 7. Writing vignettes (admin side)

- **Text:** 120–250 words, first person, with a `framing` of `forum_post`, `personal_journal` or
  `email`. No words that name the construct (ADHD, attention deficit, medication names); the leak
  check in `scripts/elicitation/leak_terms.py` lists them.
- **The hidden `design` block:**
  - `purpose`;
  - `planted_cues` and `confounders`, each with an exact quote from the text;
  - `is_control`;
  - `track` (`general` / `text_analysis`, the latter with a `knowledge_target`).

  It is never shown to the expert.
- **`question_ids`:** normally all of Q1–Q6, in order. Q4 only when there is a what-if.
- **The what-if (`q4_whatif`)** is a clause that completes *"…how would it change if ___?"*. It names
  one fact the text doesn't state, so that an expert's reading should move (or deliberately not move).
  It should:
  - be **one concrete fact**: *the writer had an exam earlier that day*;
  - be **plausible for this writer and this text**: *the writer has two small children at home*;
  - **target a cue or a confounder**: if the text leans on poor sleep, *the writer has slept well for
    weeks*;
  - **not be a diagnosis or a conclusion.** *The writer has ADHD* asks the expert to agree, not to
    weigh a fact.
  - **not be several facts at once.** *The writer had an exam and also broke up last week* can't be
    weighed as one change.
  - **not be a rewording of the text.** *The writer was stressed* when the text already says so.

  Good what-ifs vary in which way they push. Some should reinforce a careful reading (−1/−2), some
  should move it (+1/+2), and some should be irrelevant (0). If every what-if pushes the same way,
  experts learn the pattern.

## 8. Background and open points

- **Why this shape for Q4.** A Script Concordance Test (SCT) item gives a hypothesis ("if you were
  thinking of…"), adds one new piece of information ("and then you find…"), and asks how the
  hypothesis changes on a −2…+2 scale. The scale reflects script theory's view of clinical
  reasoning as a series of qualitative judgments
  ([Fournier et al., guidelines for construction](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC2427021/)).
  - **The why box.** A plain SCT records only the point on the scale, not the reasoning behind it,
    and asking for a justification is the usual proposal to make the reasoning visible
    ([Wan, Tor & Hudson, think-aloud](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7870454/);
    ["an adequate tool to assess clinical reasoning?"](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6002295/)).
  - **No default on the slider.** Answering 0 everywhere can inflate SCT scores
    ([gaming and guessing](https://link.springer.com/article/10.1007/s40037-018-0435-8)).
  - **Labelled stops and a separate direction field.** Test-takers interpret an SCT scale
    inconsistently (Gawad et al., *Medical Education*, 2020), so each stop has a label in words and
    the direction is asked for separately.
- **Open:** more than one what-if per vignette (a full SCT case has 3–5), each its own Q4-style
  step.
- **Open:** whether the submitted document should record when the gate was passed. Today it is
  only in the draft.
- **Considered, not built:** linking the what-if to text fragments ("which parts does this change
  how you read?"), and a "can't judge this what-if" option next to the scale.
