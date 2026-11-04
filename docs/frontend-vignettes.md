# Vignettes in the frontend

How the web elicitation platform should show a vignette and collect a clinician's answers. It
covers structure and behaviour, not a framework. The API and the workflow around it are in
[backend-workflow.md](backend-workflow.md). The API's types are generated into
`frontend/src/api/schema.d.ts`, so field names are not repeated here where they can be looked up.

## 1. What the frontend gets

`GET /api/v1/assignments/{id}` returns everything the answering screen needs:

| Field | What | Notes |
|---|---|---|
| `vignette` | `code`, `version`, `text`, `framing`, `word_count`, `content_hash` | Never the hidden `design` block: it holds the planted cues and is what the answers are scored against. A/B variant information isn't sent either. |
| `vignette.questions[]` | `id`, `kind`, `text`, `min_words` | Only the questions the expert may see now, in order, with the text as shown (Q4's what-if is filled in). `kind` is `open`, `shift` (Q4) or `rating_1_5` (Q6). `min_words` is the minimum of different words, for a counter. |
| `vignette.questions[].wording` | The wording of the Q4 step | Use these strings rather than rewording them, so all answers are given to the same item. |
| `draft` | `version`, `payload` | The saved answers. |
| `allowed_actions` | e.g. `save_draft`, `pass_gate`, `submit` | Show only these actions; the server owns the workflow rules. |

A vignette without a what-if is asked without Q4.

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
  matches. The matched fragments become `quoted_fragments`. A quote shortened with `…` is matched
  piece by piece.
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

- Q1, Q2 and Q3 are open questions. **Each needs an answer with at least `min_words` different words**
  before Next moves on. If an answer is blank, show: "Q2 needs an answer before the next questions."
  The check is here because these answers can't be corrected once the gate is passed.
- **Q4–Q6 are not rendered, and not even sent to the client, until all three are answered.** The
  answers to Q1–Q3 are the expert's reading of the text before they see the what-if or the rating.
- **Passing the gate locks Q1–Q3.** The moment the expert moves from Q3 to the next question, call
  `POST /assignments/{id}/pass-gate`. It records `gate_passed_at` and returns Q4–Q6, and from then on
  the server refuses changes to Q1–Q3 (`gate_locked`). They become read-only for this vignette: Back
  still shows them, but disabled, with a note "locked: you have seen the questions after this one".
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
missing. **At 0, only the hypothesis line and the scale are shown, and Next goes straight on.** If
the expert moves the slider from +2 to 0, hide "Towards…" and "Why?". The screen may remember their
contents in case the slider moves back, but they must be left out of what it saves: the server
submits the saved draft exactly as it is, and refuses leftovers (see §5 and §6).

**Q5** is an open question, and needs at least `min_words` different words. **Q6** is a choice of
1–5 or *insufficient information*; the two are exclusive, and an answer is required.

### Review

After the last question, review lists every answer. Q4–Q6 have an Edit button; Q1–Q3 are shown
with "locked" and no Edit button. Q4 is shown in one line, e.g. *hypothesis: tired, not trait-like
· +1 partly changes, towards less ADHD-like · why: …*. **Submit** freezes this vignette's answers
for good and moves to the next assignment. A vignette with nothing written should be left for later,
not submitted.

## 4. Skip, pause, resume

- **Order:** `GET /assignments` returns the expert's assignments in a random order that is fixed per
  expert, so a resumed session shows the same sequence.
- **Skip vignette** sets it aside (orange chip); the expert can come back to it by clicking its chip.
- **Autosave:** `PUT /assignments/{id}/draft` on every Next/Back and every few seconds while typing,
  sending the `version` of the last save. A `draft_conflict` means another tab has saved since, so
  reload the draft. Reopening a vignette goes to its first unanswered step. A gate question counts as
  unanswered while it is blank, Q4 until a stop is chosen, and Q6 until it is rated.
- **Submit** works per vignette, after a confirmation: `POST /assignments/{id}/submit`. Nothing is
  ever reopened afterwards. Other assignments stay as they are.

## 5. From UI controls to the payload

What the draft's `payload` holds when it is submitted:

| UI control | Field | Rule |
|---|---|---|
| Q1, Q2, Q3, Q5 text | `answers["Q1"]` … | The server trims them. All required, each with at least its `min_words`. |
| Quotes matched in the answers | `quoted_fragments` | Exact substrings of `text`. |
| Q4 hypothesis line | `q4.hypothesis` | Required, at least `wording.hypothesis_min_words` different words. |
| Q4 slider | `q4.shift` | Integer −2…2. Required whenever Q4 was asked and the vignette is submitted. |
| Q4 towards | `q4.toward` | `more_adhd` / `less_adhd` / `other`; required with shift +1/+2, else `null`. |
| Q4 "which explanation" | `q4.other_explanation` | Required with `toward = "other"`, else `null`. |
| Q4 why | `answers["Q4"]` | Required with shift ≠ 0, at least Q4's `min_words` different words; must be absent at 0. |
| Q6 | `rating` (1–5) or `insufficient_information: true` | Exclusive. |

The server adds the rest when it freezes the submission: the vignette's code, version and hash, the
expert's pseudonym, and the `started_at`, `gate_passed_at` and `submitted_at` times.

```json
{
  "answers": {"Q1": "…", "Q2": "…", "Q3": "…", "Q4": "An exam would explain the rush.", "Q5": "…"},
  "quoted_fragments": ["I haven't slept well since moving into this new flat two months ago"],
  "q4": {"hypothesis": "sleep loss after the move, not clearly more",
         "shift": 1, "toward": "less_adhd", "other_explanation": null},
  "rating": 2, "insufficient_information": false
}
```

The server requires the hypothesis, the direction and the why at submission, as well as the UI.

## 6. Backend validation codes and what to show

The backend validates every save and submission. Errors are `{code, message, details}`, with a
stable `code`. The UI should prevent these errors, so if one does come back, it means a bug. Show the
message and keep the draft.

| Code | Meaning | UI message |
|---|---|---|
| `gate_not_passed` | Q4–Q6 answered while a Q1–Q3 answer is missing | "Q1–Q3 need answers first." |
| `gate_locked` | A Q1–Q3 answer changed after the gate | Keep them read-only after the gate. |
| `submission_incomplete` | A required Q4 part or Q6 is missing | Name the missing part. |
| `answer_too_short` | Below the minimum of different words; `details.answers` lists which | Show a counter, and keep Next disabled until it is met. |
| `draft_conflict` | Another tab has saved since | Reload the draft. |
| `q4_why_without_shift` | A Q4 why with shift 0 or no shift | Drop the why at 0. |
| `toward_without_change` | A direction with shift ≤ 0 | Clear `toward` when the slider goes ≤ 0. |
| `other_without_name` | `toward = other` without a name, or a name without `other` | Name it, or clear it. |
| `empty_answer` | A blank required answer or quoted fragment | Ask for the answer. |
| `quote_not_in_vignette` | A `quoted_fragments` entry is not in the text | Send only exact matches. |
| `question_not_asked` | An answer to a question the vignette didn't ask | — |
| `rating_conflict` | Both a rating and "insufficient information" | — |

## 7. Writing vignettes (admin side)

- **Text:** 120–250 words (the server checks this at publishing), first person, with a `framing` of
  `forum_post`, `personal_journal` or `email`. No words that name the construct (ADHD, attention
  deficit, medication names). The backend doesn't check this yet.
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
- **Considered, not built:** linking the what-if to text fragments ("which parts does this change
  how you read?"), and a "can't judge this what-if" option next to the scale.
