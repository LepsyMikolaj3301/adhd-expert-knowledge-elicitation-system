---
title: Frontend components and answering helpers
diataxis: reference
---

# Frontend components and answering helpers

Language: **English** · [Polski](../../pl/reference/frontend-components.md)

`frontend/src/components` holds the Vue single-file components that the views mount: shared widgets at the top level, and the folders `answering/`, `knowledge/` and `admin/`. `frontend/src/answering` holds the TypeScript modules behind the answering and review screens: citation model, step rules, draft saving, word diff and quote focus. Neither folder has an entry point of its own; the views in `frontend/src/views` and `frontend/src/layouts/AppLayout.vue` import the components. For the app shell, see [frontend-app.md](frontend-app.md); for the place of the frontend in the system, see [architecture.md](../explanation/architecture.md). The documentation index is [index.md](../index.md).

Props are declared with `defineProps`, events with `defineEmits`, and `defineExpose` marks methods a parent calls through a template ref. Text labels that components do not spell out come from `frontend/src/copy.ts`.

## Components in `components/`

| Component | Props | Emits / slots | Purpose |
|---|---|---|---|
| `SectionCard` | `title`, `text`, `to`, `action`, `testid?` | default slot | Home-page card: heading, text, optional slot content and a router link button labelled `action`. |
| `LoadingSpinner` | `size?` (20), `label?` | none | Spinning SVG. With `label` it has role `img` and an `aria-label`, without it the SVG is hidden from assistive technology. |
| `InfoPopover` | `mode`: `'hover'` or `'click'` | emits `open`; slot `trigger` (receives `open`, `toggle`, `panelId`); default slot is the panel | Popover base. Hover mode opens on mouse enter and focus in. The panel closes on a mouse press outside it and on Escape. |
| `CaseCard` | `code`, `version?`, `patientSummary`, `framing`, `wordCount`, `opening` | default slot replaces the trigger text | Button that opens a click popover with the framing label, word count, patient summary (when not empty) and opening words. The default trigger text is `Case {code} v{version}`. |
| `TermGrid` | `items`: `readonly { term: string; text: string }[]` | none | Definition list, two columns from the `sm` breakpoint. |
| `SegmentedToggle` | `options`: `readonly { value: T; label: string }[]`, `label`, `disabled?`; `v-model` | none | Generic (`T extends string`) button group in which one option is pressed. |
| `StepFlow` | `steps: readonly string[]`, `current?: string`, `testid?: string` | none | Ordered list of step labels with arrows; the `current` label is outlined. |
| `PseudonymChip` | `pseudonym` | none | Button that opens a click popover with the person behind a pseudonym. Looks the person up on first open and keeps the result in a module-level `Map`, so a pseudonym is fetched once per page load. An admin sees name, email, role, deactivation and case counts (open, in review, done, stopped); other users see the pseudonym and a privacy note. A failed lookup shows "Could not load this expert." |
| `HeroBanner` | `title`, `tagline` | none | Sticky home header that folds into a slim bar while the page scrolls. Sets `scroll-padding-top` on the document element while mounted and clears it on unmount. |
| `SignInAgainDialog` | none | none | Modal `<dialog>` opened with `showModal()`; `@cancel.prevent` keeps it open. Asks for the password of the signed-in account and calls `auth.login(auth.user.email, password)`. Shows the `ApiError` message on failure. |
| `PageIntro` | `lead: string | readonly string[]`, `moreTo?`, `testid?`, `center?` | none | Lead paragraphs. With `moreTo` it adds a router link labelled `HOME.learnMore`. |
| `AboutSection` | `id`, `heading`, `accent?`, `testid?` | default slot | Section card with an anchor `id` and an `h2` heading. |

## Components in `components/answering/`

| Component | Props | Emits / slots / exposed | Purpose |
|---|---|---|---|
| `AnswerThread` | `assignmentId`, `questionId`, `questionName`, `comments`, `highlights`, `canComment`, `canStance`, `startOpen?` | emits `posted`; exposes `addQuote(target)` | Folded discussion under one answer: comments with replies one level deep, an optional stance (sent only when `canStance`), and a comment box. While open and `canComment`, it registers its box as the page's comment sink. `addQuote` opens the thread and inserts a chip, or the quoted passage for a highlight without a chip. Posts the comment; on failure the text stays in the box. |
| `CasePanel` | `summary?`, `framing`, `lead`, `textClass?` | default slot holds the text | Two sections: the patient summary (rendered when `summary` is set) and the case-text box with the text type and a lead line. |
| `ChipEditor` | `modelValue`, `label`, `compact?` | emits `update:modelValue`, `active(chip or null)`, `focus`; exposes `insertChip(n)`, `insertText(text)`, `focusEnd()` | TipTap editor over the stored text. A chip is an inline atom node; list lines are indented and Enter continues the list (Enter on an empty item ends it). A `modelValue` change from outside replaces the content without a history entry. `compact` sets `min-h-24`. |
| `ChipText` | `text` | emits `active(chip or null)` | Read-only renderer of stored text: chips, list lines, line breaks. Pointing at a chip sets the quote focus; clicking pins it when a pin is provided. |
| `CitationTable` | `citations`, `editable`, `canInsert`, `counts`, `pulseChip`, `marked?`, `flashKey?`, `insertInto?` (`'answer'`), `pinnedChip?` | emits `active`, `direction(chip, direction)`, `insert(chip)`, `remove(chip)`, `pin(chip)` | Table of quotes with a direction select, a remove button, a help popover and per-quote reference counts. A row click emits `insert` when `canInsert`, otherwise `active` and `pin`. Hovering or focusing a row emits `active`. |
| `CiteHelp` | none | none | "How to add a quote" hover popover (`InfoPopover`, hover mode) with a CSS-animated demo. |
| `ConfirmDialog` | `title`, `confirmLabel`, `cancelLabel`, `danger?` | emits `confirm`, `cancel`; default slot is the body | Modal `<dialog>` opened with `showModal()` and closed on unmount. Escape emits `cancel`. `danger` selects the `btn-danger` style for the confirm button. |
| `DecisionButtons` | `questionId` | `v-model:decision` (`'approve'`, `'reject'`, `'request_changes'` or `''`), `v-model:comment` | The admin's three-way decision on one answer, with a comment box under the choice. |
| `DiffText` | `before`, `after` | none | Redline of `wordDiff(before, after)`: unchanged parts as `ChipText`, added parts in `<ins>`, removed parts in `<del>`, each with a screen-reader prefix. |
| `ProofreadStep` | `id` (assignment id) | emits `submitted`, `missing`, `highlights(highlights)`; exposes `flush()` | Proofread check. Per answer it shows the diff and an editable text, with sentence lines tagged by quotes (`QuoteTag` toggles) and an autosave status. Submit for review runs through a `ConfirmDialog`. Emits `missing` when loading the proofread returns 404, and `submitted` after the submit call. See [Proofread save and submit](#proofread-save-and-submit). |
| `Q4Step` | `question`, `q4`, `why` | emits `update:q4`, `update:why`, `active`; exposes `insertChip`, `focusEnd` | Q4 inputs: a hypothesis text field (`maxlength` 2000), a scale radio group with stops -2 to 2, direction radios (shown when the scale is above 0), an "other explanation" field (when direction is `other`) and a "why" `ChipEditor` with a word count (shown when the scale is not 0). |
| `QuestionBlock` | `question`, `payload`, `problem?`, `flashKey?` | emits `answer(text)`, `q4(Q4Answer)`, `rate(n)`, `insufficient`, `active`; exposes `insertChip`, `focusEnd` | Question heading plus the input for its kind: `Q4Step` for a shift question, `RatingStep` for a rating, a `ChipEditor` with word count otherwise. The Q4 heading bolds the part after "change if ". A hint appears when the Q1 answer has more than 60 words and no chip. |
| `QuoteTag` | `target`, `highlights`, `pressed?`, `toggle?`, `disabled?` | emits `toggle` | Tag for a quote or for `case`. With `toggle` it is a toggle button; otherwise it is a pin button when a pin is provided and the target is not `case`, or a static span. Hover and focus set the quote focus (not for `case`). |
| `RatingStep` | `rating`, `insufficient` | emits `rate(n)`, `insufficient` | Radios 1 to 5 and an option for insufficient information. |
| `ReviewAnswerCard` | `answer`, `highlights`, `assignmentId`, `authorName`, `canVote`, `canComment`, `showVoters`, `startOpen` | emits `vote(AnswerVote)`, `posted`; slot `decide` | One answer under review: question, vote tally (voter names for admins when `showVoters`), approve and disapprove buttons, the decision label, the sentences with quote tags, and an `AnswerThread`. |
| `ReviewStep` | `questions`, `payload`, `editable` | emits `edit(id)`, `active(chip or null)` | Read-only summary of the answers, with an Edit button per answer while `editable`; shows the Q4 scale line. |
| `StepRail` | `steps: RailStep[]`, `current`, `flashKey?` | emits `go(id)` | Question navigation strip. A step with a `problem` gets the `flag-shake` class and re-flashes when `flashKey` changes. |
| `UnsavedText` | `text` | none | Copy button (`navigator.clipboard.writeText`) and a `<details>` box with a read-only textarea. When copying fails, the box opens. |
| `VignetteText` | `text`, `active`, `canCite`, `citeLabel?` (`CITE.add`) | emits `cite(start, end)` | Case text with the `active` span marked. With `canCite`, a text selection shows a "+ label" button teleported to `body`; pressing it emits `cite` with browser (UTF-16) offsets and clears the selection. The mark is not drawn during a selection. |

`RailStep` is exported from `StepRail.vue`: `{id, label, reachable, problem?}`. `Decision` is exported from `DecisionButtons.vue`.

## Components in `components/knowledge/` and `components/admin/`

| Component | Props | Emits | Purpose |
|---|---|---|---|
| `KnowledgeSearch` | none | none | Search over knowledge units. Two modes (`question`, `patient_text`) through `SegmentedToggle`; the query field has `maxlength` 4000. Switching mode clears results and errors. Results render as `UnitCard` with `showCase`. |
| `KnowledgeUnits` | none | none | Knowledge base list grouped by case, then by expert answer; the units of an answer are folded until opened. Shows the search-index state, polls it while it is queued or running, and removes one unit or all units of an expert after a `ConfirmDialog`. Removal sets the index state to `queued` and reloads it. |
| `UnitCard` | `unit`, `showCase?`, `removable?` | `remove` | One knowledge unit: kind ("Whole case" or `Quote {highlight_id}`), direction label, and, with `showCase`, the case code and version. |
| `CreateAssignmentDialog` (admin) | `assignments` | `done`, `cancel` | `ConfirmDialog` that assigns the latest published version of a vignette to one active expert. A version the chosen expert already holds in a state other than `cancelled` is disabled and marked "already assigned". Errors from the API are explained with the names of the experts concerned. |

`KnowledgeUnits` calls `GET /api/v1/knowledge-units` with `status: 'ingested'` and `limit: 500`. The source comment states that more than 500 units need paging or a filter.

## HTTP calls made by components and helpers

| Source | Calls |
|---|---|
| `useAnswerDraft` | `GET /api/v1/assignments/{assignment_id}`; `POST .../start`; `GET .../submission`; `PUT .../draft`; `POST .../submit` |
| `ProofreadStep` | `GET` and `PUT /api/v1/assignments/{assignment_id}/proofread`; `POST .../submit-for-review` |
| `AnswerThread` | `POST /api/v1/assignments/{assignment_id}/answers/{question_id}/comments` |
| `KnowledgeSearch` | `POST /api/v1/knowledge-units/search` with `{query, mode, k}` |
| `KnowledgeUnits` | `GET /api/v1/knowledge-units`; `GET /api/v1/knowledge-units/index`; `POST /api/v1/knowledge-units/index/refit`; `DELETE /api/v1/knowledge-units/{unit_id}`; `DELETE /api/v1/knowledge-units/by-expert/{expert_id}` |
| `CreateAssignmentDialog` | `GET /api/v1/users`; `GET /api/v1/vignettes`; `POST /api/v1/vignette-versions/{version_id}/assignments` with `{expert_ids}` |
| `PseudonymChip` | `GET /api/v1/users/by-pseudonym/{pseudonym}` |
| `SignInAgainDialog` | `auth.login` from `@/stores/auth` |

## Helpers in `frontend/src/answering`

### `highlights.ts`: citations

A citation is stored in the answer text as the token `⟦hN⟧`. The API counts spans in code points; the browser counts UTF-16 units. The module converts between them and does not touch the DOM.

| Name | Description |
|---|---|
| `CHIP_RE` | `/⟦h(\d+)⟧/g`, the chip token. |
| `INK_COUNT` | 8, number of ink colours. |
| `Answers` | `Record<string, string or undefined>`, answer text by question id. |
| `utf16ToCodePoint(text, index)`, `codePointToUtf16(text, index)` | Offset conversion. |
| `snapToWords(text, start, end)` | Trims spaces at the edges, extends the range to whole words, returns `[from, to]` or `null` when nothing is left. A word is letters, digits, marks and `_`, joined by `'`, `’` or `-`. |
| `addCitation(citations, text, start, end)` | Snaps a browser selection and returns `{kind: 'added', citations}` (chip number is count + 1, `direction: null`), `{kind: 'duplicate', chip}` for an identical span, `{kind: 'too_long'}` above 2000 code points, or `{kind: 'empty'}`. |
| `removeCitation(citations, answers, chip)` | Removes the chip token from every answer (with adjacent spaces, depending on neighbours) and renumbers later chips in citations and answers. Returns `{citations, answers}`. |
| `countWords(text)` | Counts words, ignoring list markers and chips. The source comment states that the server's `count_words` counts differently. |
| `citationCounts(citations, answers)` | References per chip number across answers. |
| `citedChips(answers)` | `Set` of chip numbers that appear in answers. |
| `uncitedChips(citations, answers)` | Chip numbers of citations that no answer refers to. |
| `inkFor(chip)` | `var(--ink-1)` to `var(--ink-8)`, repeating after 8. |
| `segmentsFor(text, active)` | Splits text into `before`, `marked`, `after` using the span of `active`, converted to UTF-16. |

`AddResult` is the union returned by `addCitation`. The limit 2000 is the module-private constant `MAX_CITATION_LENGTH`.

### Text format helpers

| Module and function | Description |
|---|---|
| `chipDoc.ts`: `textToDoc(text)`, `docToText(doc)` | Exact conversion between stored text and the TipTap document: one paragraph per line, `chip` nodes with attribute `n`. |
| `listLines.ts`: `listMarker(line)` | The list marker with surrounding spaces, or `null`. A marker is a number followed by `.` or `)`, or one of `-`, `–`, `•`, `*`, then a space (`^\s*(?:\d+[.)]\|[-–•*])\s`). |
| `listLines.ts`: `nextMarker(marker)` | The marker with its number increased by one. |
| `plainText.ts`: `readable(text)` | Replaces each `⟦hN⟧` with `[N]`. |
| `plainText.ts`: `plainText(payload, questions)` | Plain text of the answers in question order. Each block starts with the question id; shift questions add `Hypothesis:`, `Other explanation:` (when direction is `other`) and `Why:`; rating questions give `Insufficient information` or `Rating: n of 5`. Questions without content are skipped. |
| `wordDiff.ts`: `tokens(text)` | Words with trailing spaces; each line break is its own token. |
| `wordDiff.ts`: `wordDiff(before, after)` | Longest common subsequence over tokens, compared without trailing spaces. Returns `DiffPart[]` of kind `same`, `added` or `removed`. The cost is quadratic. |
| `wordDiff.ts`: `changed(before, after)` | `true` when the words differ after whitespace normalisation. |

### `steps.ts`: step rules

| Name | Description |
|---|---|
| `StepId`, `REVIEW` | A question id, or `'review'` for the last page. |
| `Q4Wording` | `{hypothesis, shift_lead, shift_labels, toward, toward_labels, why}`; typed by hand because the API types `wording` as a dictionary. |
| `q4Wording(question)` | Casts `question.wording` to `Q4Wording`. |
| `wordCountLabel(words)` | `"1 word"` or `"n words"`. |
| `stepProblem(question, payload)` | First missing item for a question, or `null`. Shift: hypothesis, scale point, direction (when scale above 0), other explanation (when direction is `other`), then the "why" text (unless scale is 0). Rating: a rating or insufficient information. Otherwise: a non-empty answer. Length never counts. |
| `firstProblem(questions, payload)` | First problem in question order, or `null`. |
| `firstOpenStep(questions, payload)` | Id of the first question with a problem, else `REVIEW`. |
| `forSaving(payload)` | Payload for the server: drops `toward` unless scale is above 0, `other_explanation` unless `toward` is `other`, and the `Q4` answer when scale is 0. |

### `useAnswerDraft.ts`: draft loading and saving

`useAnswerDraft(id)` manages one expert's draft of one assignment. It returns `view`, `payload`, `status`, `saveProblem`, `editable`, `load`, `changed`, `flush`, `resume`, `submit` and `stop`.

| Member | Behaviour |
|---|---|
| `load()` | Fetches the assignment (a non-expert view raises a 404 `ApiError`). When `allowed_actions` contains `start`, posts start and fetches again. Loads the submission payload when `submitted_at` is set, otherwise the draft payload. |
| `editable` | `true` when `allowed_actions` contains `save_draft`. |
| `changed()` | Marks the draft dirty and schedules a save after `SAVE_AFTER_MS`. Status becomes `unsaved` unless a save is running. Has no effect on status in `conflict` and `signin`. |
| `flush()` | Resolves when everything is saved. Saves run one at a time and send the version returned by the last save. Rejects with `draft_conflict` (409) in status `conflict` and with `not_authenticated` (401) in status `signin`. |
| `resume()` | After signing in again: leaves `signin` and flushes. |
| `submit()` | Flushes, then posts the submission and applies the returned assignment. |
| `stop()` | Cancels the timer and disables retries. |

Save outcome in `saveOnce`: error code `draft_conflict` gives `conflict`; HTTP 401 gives `signin`; other 4xx except 408 and 429 give `rejected` (the error is kept in `saveProblem`); everything else gives `failed` and a retry after `RETRY_AFTER_MS` unless stopped. `SaveStatus` is `saved`, `unsaved`, `saving`, `failed`, `rejected`, `signin` or `conflict`. `EMPTY_PAYLOAD` is `{answers: {}, highlights: [], insufficient_information: false}`.

### Proofread save and submit

`ProofreadStep` keeps its own save loop with the same shape: `SAVE_AFTER_MS` after an edit or a tag change, one save at a time using the version from the view, status `saved`, `unsaved`, `saving`, `failed`, `conflict` or `rejected`. Error code `proofread_conflict` gives `conflict`; any other 4xx gives `rejected`; other errors give `failed` and a retry after `RETRY_AFTER_MS`. A sentence keeps at least one quote target: removing the last one is ignored. The submit button is blocked (and marks the problems) while an answer is empty or a sentence of a linked answer has no target; the `links_missing` error from the server also marks them.

### Quote focus and comment sink

| Module | Names | Description |
|---|---|---|
| `quoteFocus.ts` | `provideQuoteFocus()`, `useQuoteFocus()` | Provide and inject a `Ref<QuoteId or null>` for the quote being pointed at. Without a provider, `useQuoteFocus` returns a private ref. |
| `quoteFocus.ts` | `provideQuotePin()`, `useQuotePin()`, `togglePin(pin, id)` | Pin for the clicked quote. `useQuotePin` returns `null` without a provider. `togglePin` pins the id, or clears it when already pinned. |
| `quoteFocus.ts` | `chipFocus(focus)` | Writable computed between `h<N>` ids and chip numbers. |
| `quoteFocus.ts` | `markFor(id, highlights)`, `inkOf(chip)` | The `Mark` (`{span, chip}`) of a highlight, and its colour (`var(--ink-0)` for no chip). |
| `commentSink.ts` | `provideCommentSink()`, `useCommentSink()` | Provide and inject a `ShallowRef<CommentSink or null>`; `CommentSink` is `{questionId, insertChip, insertText}`. |
| `commentSink.ts` | `quoted(words)` | Passage in curly quotes with collapsed whitespace and a trailing space. |

`QuoteId` is a string: `h3` for the expert's quote 3, `i1` for words quoted without a chip.

## Constants

| Name | Value | Where | Meaning |
|---|---|---|---|
| `SAVE_AFTER_MS` | 2000 | `useAnswerDraft.ts` | Autosave delay of a draft. |
| `RETRY_AFTER_MS` | 5000 | `useAnswerDraft.ts` | Retry delay after a failed draft save. |
| `SAVE_AFTER_MS` | 1500 | `ProofreadStep.vue` | Autosave delay of the proofread. |
| `RETRY_AFTER_MS` | 5000 | `ProofreadStep.vue` | Retry delay after a failed proofread save. |
| `Q1_NUDGE_WORDS` | 60 | `QuestionBlock.vue` | Q1 words without a chip before the hint appears. |
| `HITS` | 8 | `KnowledgeSearch.vue` | `k` sent with a knowledge search. |
| `PAGE` | 500 | `KnowledgeUnits.vue` | `limit` of the unit list request. |
| `POLL_MS` | 2000 | `KnowledgeUnits.vue` | Poll interval of the index state while `queued` or `running`. |
| `FULL`, `COMPACT` | 176, 56 (px) | `HeroBanner.vue` | Banner height and folded height; the fold distance is 120 px. |
| `MAX_CITATION_LENGTH` | 2000 | `highlights.ts` | Longest citation in code points. |
| `INK_COUNT` | 8 | `highlights.ts` | Ink colours cycled by chip number. |
| `STOPS`, `TOWARD` | -2 to 2; `more_adhd`, `less_adhd`, `other` | `Q4Step.vue` | Scale points and direction options. |
| `RATINGS` | 1 to 5 | `RatingStep.vue` | Rating options. |

## Sources in code

- `frontend/src/answering/chipDoc.ts` - text and TipTap document conversion
- `frontend/src/answering/commentSink.ts` - comment sink provide/inject, quoted
- `frontend/src/answering/highlights.ts` - citation model, offsets, counts, ink colours
- `frontend/src/answering/listLines.ts` - list marker detection
- `frontend/src/answering/plainText.ts` - plain text export, readable
- `frontend/src/answering/quoteFocus.ts` - quote focus and pin, Mark
- `frontend/src/answering/steps.ts` - step rules, Q4 wording, forSaving
- `frontend/src/answering/useAnswerDraft.ts` - draft load and save loop, status, delays
- `frontend/src/answering/wordDiff.ts` - word diff and changed check
- `frontend/src/components/AboutSection.vue` - props
- `frontend/src/components/CaseCard.vue` - props, popover content
- `frontend/src/components/HeroBanner.vue` - fold constants and scroll padding
- `frontend/src/components/InfoPopover.vue` - modes, slots, open event
- `frontend/src/components/LoadingSpinner.vue` - props
- `frontend/src/components/PageIntro.vue` - props, learn-more link
- `frontend/src/components/PseudonymChip.vue` - lookup and cache
- `frontend/src/components/SectionCard.vue` - props
- `frontend/src/components/SegmentedToggle.vue` - generic options and v-model
- `frontend/src/components/SignInAgainDialog.vue` - non-dismissable login dialog
- `frontend/src/components/StepFlow.vue` - props
- `frontend/src/components/TermGrid.vue` - props
- `frontend/src/components/admin/CreateAssignmentDialog.vue` - assignment dialog and calls
- `frontend/src/components/answering/AnswerThread.vue` - discussion props, emits, addQuote
- `frontend/src/components/answering/CasePanel.vue` - props and slot
- `frontend/src/components/answering/ChipEditor.vue` - TipTap editor, extensions, exposed methods
- `frontend/src/components/answering/ChipText.vue` - read-only chip renderer
- `frontend/src/components/answering/CitationTable.vue` - quote table props and emits
- `frontend/src/components/answering/CiteHelp.vue` - help popover
- `frontend/src/components/answering/ConfirmDialog.vue` - modal dialog
- `frontend/src/components/answering/DecisionButtons.vue` - decision model
- `frontend/src/components/answering/DiffText.vue` - redline rendering
- `frontend/src/components/answering/ProofreadStep.vue` - proofread save loop, blocker, constants
- `frontend/src/components/answering/Q4Step.vue` - Q4 inputs, STOPS, TOWARD
- `frontend/src/components/answering/QuestionBlock.vue` - question input by kind, nudge
- `frontend/src/components/answering/QuoteTag.vue` - tag variants
- `frontend/src/components/answering/RatingStep.vue` - rating radios
- `frontend/src/components/answering/ReviewAnswerCard.vue` - review card props, emits, slot
- `frontend/src/components/answering/ReviewStep.vue` - summary props, emits
- `frontend/src/components/answering/StepRail.vue` - RailStep and navigation
- `frontend/src/components/answering/UnsavedText.vue` - copy fallback
- `frontend/src/components/answering/VignetteText.vue` - selection to cite
- `frontend/src/components/knowledge/KnowledgeSearch.vue` - search modes, HITS
- `frontend/src/components/knowledge/KnowledgeUnits.vue` - unit list, index polling, removal
- `frontend/src/components/knowledge/UnitCard.vue` - unit card props
