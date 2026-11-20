---
title: Backend peer reviews
diataxis: reference
---

# Backend: `app.reviews`

`app.reviews` implements the peer review of a submitted assignment: reviewers open a review, comment and vote on each answer, and the admin's decision per answer closes the review. The module provides the routes below, the access rules that tell who may read a submission, and the tables `review_participants`, `answer_comments`, `answer_votes` and `answer_decisions`. The states and transitions the review moves through are in [backend-assignments-jobs.md](backend-assignments-jobs.md); the context is in [assignment-lifecycle.md](../explanation/assignment-lifecycle.md).

The routes are mounted under `/api/v1` with the tag `reviews`. Errors use `{code, message, details}`; `DomainError` defaults to HTTP 409, `not_found` is 404, `invalid` is 422 and `forbidden` is 403.

## HTTP routes

In the routes that take `assignment_id`, the viewer is mapped to an actor by `assignments.service.actor_for`: `admin`, `assignee` (the author) or `reviewer`; an unrelated viewer gets 404 `not_found`. A reviewer who has not opened the review gets 409 `review_not_opened` from every route below except `POST .../review/open`.

| Route | Who | Behaviour |
|---|---|---|
| `GET /reviews` | any | Query `status` (`open` or `closed`, default both) and `limit` (1..500, default 100). Returns a list of `ReviewItem`. |
| `POST /assignments/{assignment_id}/review/open` | reviewer | 204. Inserts a `ReviewParticipant` row and records a `review_opened` audit event. Idempotent. No effect for the author and the admin. |
| `GET /assignments/{assignment_id}/answers` | admin, assignee, reviewer | Query `review_round`. Returns `ReviewAnswersView`. |
| `POST /assignments/{assignment_id}/answers/{question_id}/comments` | admin, assignee, reviewer | Body `CommentCreate`. 201 with a `CommentView`. |
| `PUT /assignments/{assignment_id}/answers/{question_id}/vote` | reviewer | Body `VoteInput`. Returns `ReviewAnswersView` for the current round. |
| `POST /assignments/{assignment_id}/answer-decisions` | admin | Body `AnswerDecisionsRequest`. Returns the admin `AssignmentView`. |

### `GET /reviews`

The state filter comes from `access`: `open` is `OPEN_REVIEW_STATES`, `closed` is `CLOSED_REVIEW_STATES`, no filter is `REVIEW_VISIBLE_STATES`. Only assignments with a submitted round (`was_submitted`) appear. The list is ordered by `updated_at` descending, then `id`.

- Admin: every matching assignment.
- Other viewers: assignments the viewer authored, assignments whose review the viewer opened, and assignments of vignettes that are not in `blocked_vignettes(viewer)`.

For each item, `relation` is `admin`, `author` or `reviewer`; `opened` is true unless the relation is `reviewer` and the viewer has not opened the review; `author_pseudonym` is set only for the admin. The counts (`answer_count`, `approvals`, `disapprovals`, `comment_count`, `my_votes`) refer to the assignment's current `review_round`.

### `POST .../review/open`

The assignment is locked without the "opened" requirement. An unrelated viewer, a review that has no submitted round, an assignment outside `REVIEW_VISIBLE_STATES`, or a viewer who still has to answer the vignette gets 404 `not_found` from `actor_for` (see `may_review` below).

### `GET .../answers`

Returns the answers of one round. Rounds are the `review_round` values of `ProofreadRound` rows with `submitted_at` set. The admin and the author may pass `review_round` for an earlier round; for a reviewer the parameter is ignored and the latest round is returned. 404 `not_found` when no round was submitted or the requested round is not among them.

`ReviewAnswersView` contains `review_round`, `rounds`, the assignment `state`, `highlights` and `answers`. Each `ReviewAnswer` has `question_id`, `question`, `text` (the author's final text), `lines`, `comments`, `approvals`, `disapprovals`, `my_vote`, `votes` and `decision` (the admin's decision for that answer, when present).

### `POST .../comments`

Checks in order: the assignment is in `peer_review` (else 409 `review_closed`); a `stance` is given only by a reviewer (else 422 `stance_not_allowed`); the answer for `question_id` exists in the current round (else 404 `not_found`); a `parent_id` points at a top-level comment of the same assignment, round and question (else 422 `invalid_parent`). Records a `comment_added` audit event with `question_id`, `comment_id` and `stance`.

### `PUT .../vote`

Only a reviewer may vote (else 403 `forbidden`). The assignment must be in `peer_review` (409 `review_closed`) and `review_round` in the body must equal the assignment's current round (409 `stale_round`, `details.current_round`). The answer must exist (404 `not_found`). One vote exists per (assignment, round, question, voter); a second request replaces the vote and sets `updated_at`. Records a `vote_cast` audit event. Votes are advisory.

### `POST .../answer-decisions`

1. `check_transition(state, approve_answers, actor)`: 409 `illegal_transition` outside `peer_review`, 403 `forbidden` for a non-admin.
2. Every `request_changes` decision needs a non-blank `comment` (422 `comment_required`).
3. The set of `question_id`s must equal the set of answers of the current round, each once (422 `decisions_incomplete`).
4. One `AnswerDecision` row per answer is inserted, with `content_hash = proofread.answer_hash(...)` of the reviewed text and links.
5. The outcome follows from the decisions:

| Decisions | Effect |
|---|---|
| at least one `request_changes` | `review_round` is incremented; `transition` with `request_changes` moves to `proofread_check` (meta: counts per decision value and the new round); `proofread.open_next_round` creates the next round from the previous round's text, links, flags and passes, with the comments as `feedback`. |
| no `request_changes`, at least one `approve` on a filed answer | `transition` with `approve_answers` moves to `processing`. |
| otherwise | `transition` with `reject_all_answers` moves to `rejected`. |

An answer is filed when `findings.is_filed(question_id)` is true: an open question other than Q4 (Q4's why and the rating are not cut into units).

## Access rules (`access.py`)

| Name | Value / meaning |
|---|---|
| `PRE_SUBMISSION_STATES` | `assigned`, `in_progress`, `proofreading`, `proofread_check` |
| `OPEN_REVIEW_STATES` | `peer_review` |
| `CLOSED_REVIEW_STATES` | `processing`, `processing_failed`, `ingesting`, `ingestion_failed`, `ingested`, `rejected` |
| `REVIEW_VISIBLE_STATES` | union of the open and closed sets |

| Function | Description |
|---|---|
| `was_submitted()` | SQL condition: the assignment has a `ProofreadRound` with `submitted_at` set. It separates `processing_failed` after a review from `processing_failed` after a failed proofread. |
| `blocked_vignettes(db, expert_id) -> set[UUID]` | Vignette ids (any version) for which the expert has an assignment in `PRE_SUBMISSION_STATES`. |
| `vignette_id_of(db, assignment) -> UUID` | The vignette of the assignment's version. |
| `has_opened(db, assignment_id, expert_id) -> bool` | A `ReviewParticipant` row exists. |
| `may_review(db, assignment, viewer) -> bool` | False unless the viewer is an active expert. True when the viewer has opened the review. Otherwise true when the assignment is in `REVIEW_VISIBLE_STATES`, has a submitted round and its vignette is not in `blocked_vignettes(viewer)`. |

The module docstring states that the rule is evaluated on each request, not once at submission, and that reading is explicit: the text is sent only after the review is opened.

## Speakers

`speaker_for(assignment, actor, user_id, role, pseudonym)` returns `Speaker(kind, pseudonym)`. `kind` is `author` when the user owns the assignment, otherwise `admin` for an admin user, otherwise `reviewer`. `pseudonym` is set for a reviewer, or for any speaker when the viewer acts as `admin`; it is `None` otherwise.

## Tables

| Table (`Model`) | Key | Columns |
|---|---|---|
| `review_participants` (`ReviewParticipant`) | `assignment_id`, `expert_id` | `opened_at` |
| `answer_comments` (`AnswerComment`) | `id` | `assignment_id`, `review_round`, `question_id` (8 chars), `author_id`, `parent_id` (self reference, one level), `stance`, `body`, `created_at` |
| `answer_votes` (`AnswerVote`) | `assignment_id`, `review_round`, `question_id`, `voter_id` | `vote`, `created_at`, `updated_at` |
| `answer_decisions` (`AnswerDecision`) | `assignment_id`, `review_round`, `question_id` | `reviewer_id` (the deciding admin), `decision`, `comment`, `content_hash` (64 chars), `decided_at` |

`answer_comments` has the index `ix_answer_comments_answer` on (`assignment_id`, `review_round`). The model docstring says comments are never edited.

Enums: `DecisionValue` (`approve`, `reject`, `request_changes`), `Stance` (`support`, `challenge`, `question`), `AnswerVoteValue` (`approve`, `disapprove`).

## Request and response models (`schemas.py`)

| Model | Fields and limits |
|---|---|
| `CommentCreate` | `body` (stripped, 1..5000 chars), `stance` (optional), `parent_id` (optional) |
| `VoteInput` | `vote`, `review_round` (>= 1) |
| `AnswerDecisionInput` | `question_id`, `decision`, `comment` (optional, max 5000 chars) |
| `AnswerDecisionsRequest` | `decisions` (max 20 items) |
| `CommentView` | `id`, `question_id`, `parent_id`, `stance`, `body`, `created_at`, `speaker`, `is_mine` |
| `VoteEntry` | `speaker`, `vote`, `at` |
| `DecisionView` | `decision`, `comment`, `decided_at` |
| `Speaker` | `kind` (`author`, `reviewer`, `admin`), `pseudonym` |
| `ReviewItem` | `assignment_id`, `vignette_code`, `vignette_version`, `review_round`, `state`, `relation`, `opened`, `answer_count`, `approvals`, `disapprovals`, `comment_count`, `my_votes`, `updated_at`, `author_pseudonym` |

All request models forbid extra fields.

## Sources in code

- `backend/app/reviews/router.py` - routes and the locking pattern
- `backend/app/reviews/service.py` - list_reviews, list_answers, open_review, add_comment, cast_vote, submit_decisions, speaker_for
- `backend/app/reviews/access.py` - state groupings, may_review, blocked_vignettes, was_submitted
- `backend/app/reviews/models.py` - tables and enums
- `backend/app/reviews/schemas.py` - request and response models
- `backend/app/assignments/service.py:68-107` - actor_for, load and lock, which map viewers to actors and enforce review_not_opened
- `backend/app/knowledge/findings.py:76-79` - is_filed
- `backend/app/proofread/service.py:65-69,247-286` - answer_hash and open_next_round, called by the decision step
