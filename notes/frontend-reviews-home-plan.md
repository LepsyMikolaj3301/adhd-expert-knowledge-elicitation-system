# Frontend plan: reviews, home page and account management

Not implemented yet. The backend these screens call is described in
[backend-workflow.md](backend-workflow.md).

## The API these screens call

All of it exists and is typed in `frontend/src/api/schema.d.ts`. Details in
[backend-workflow.md](backend-workflow.md), *Review* and *Home*.

| Screen | Calls |
|---|---|
| Experts (admin) | `GET /users` (each has `invite_pending`), `POST /users` (returns `invite_path`, once), `PATCH /users/{id}`, `POST /users/{id}/invite` |
| Reviews list | `GET /reviews?status=open\|closed`: per item `relation` (`reviewer`, `author`, `admin`), `opened`, `unit_count`, `accepts`, `declines`, `comment_count`, `my_vote`, `author_pseudonym` (admin only) |
| Review page | `POST /assignments/{id}/review/open` (204), `GET /assignments/{id}` (`allowed_actions` has `comment`, and `vote` for reviewers), `GET /assignments/{id}/units[?review_round=]` (each unit has `comments`), `POST .../units/{unit_id}/comments`, `GET .../votes`, `PUT .../vote`, and for the admin `POST .../unit-decisions` |
| Home | `GET /me/home`, `POST /me/activity/seen` (`{ "until": <at of the newest item shown> }`) |

Error codes the review screens must handle (`describeError` in `copy.ts`): `review_not_opened`
(409, show the first-open gate), `review_closed` (409, the admin has decided; keep the typed text),
`stale_round` (409, `details.current_round`; reload), `stance_not_allowed` and `invalid_parent`
(422, should not happen from the UI), `comment_required` (422, admin asking for changes),
`reviewer_contaminated` (409, on assigning, `details.expert_ids`).

Points that are easy to get wrong:

- A reviewer's `GET`s are refused until they have opened the review, so the review page opens with
  the gate and only then loads. The reviews list and the home page carry no unit text and need no
  opening.
- `speaker.pseudonym` is null for the author and the admin unless the viewer is the admin; show
  "Author" and "Admin".
- The tally is advice. Nothing the reviewers do moves a case on, so never word it as a verdict.
- `allowed_actions` decides what the page offers (comment box, vote bar, decision controls); do
  not infer it from the role or the state.
- `unread` on feed items is the server's: don't keep a second copy in the browser.

Follows the existing conventions: clinical wording through [copy.ts](../frontend/src/copy.ts), errors by stable `code` through `describeError`, actions driven by `allowed_actions`, Vitest specs, typed `api` client.

## F0. Expert-check screen (blocker, do first)

**Nothing can reach review through the UI today.** After processing, a submission waits in `expert_check` for the author, and no screen calls `findings` or `expert-check/complete`. Admins have no skip button either.

- In `/assignments/:id`, when the state is `expert_check`: show how sentences were filed, flags, and `feedback` from an earlier round, using `GET /findings`.
- Allow corrections (`PUT /findings`, handling `findings_conflict`), then Approve or Skip.
- Add "Ready to check" to `expertStatus` in [AssignmentsView.vue](../frontend/src/views/AssignmentsView.vue), which currently shows everything after submission as "Submitted".
- Add an admin Skip button, and Retry for failed jobs, to [AssignPanel.vue](../frontend/src/components/admin/AssignPanel.vue).

## F1. Admin: Experts screen (replaces the `/experts` placeholder)

- New `ExpertsView.vue`: table of name, email, pseudonym, role, status (Active, Invite not accepted, Deactivated) from `GET /users`.
- "Add account" form: email, display name, role. `POST /users` handles `email_taken`.
- **The invite link is shown once.** Show the full URL (`location.origin` + `invite_path`) with a copy button and a note that it can't be retrieved again, and warn before leaving the page.
- Row actions: new invite link (`POST /users/{id}/invite`, also how a password is reset), edit name, deactivate or reactivate with `ConfirmDialog` (`cannot_deactivate_self`).
- [AcceptInviteView.vue](../frontend/src/views/AcceptInviteView.vue) already handles the invited person's side. There's no public `/register` route.

## F2. Reviews list (replaces the `/reviews` placeholder)

- `ReviewsView.vue` from `GET /reviews`. Tabs: Open and Closed.
- Experts see groups "Waiting for your vote", "You've voted", "Your submissions". Admins see one list sorted by oldest waiting, with tallies.
- Each row: case code, unit count, tally, comment count, relation.

## F3. Review page (new route `/reviews/:id`, both roles, `keepOnExpiry`)

- **First-open gate:** when `opened` is false, or on `review_not_opened`, explain: "Reading this means you can't be assigned this case later." Continue calls `POST .../review/open`, and only then loads the content. This must also catch links from the home feed.
- **Layout:** the case text in one column (reuse [VignetteText.vue](../frontend/src/components/answering/VignetteText.vue)), units with threads in the other (`wide` route). Stacked on narrow screens.
- **Unit card:** marked passage, direction via `directionLabel`, unit text, status.
- **Thread (`UnitThread.vue`):** comments with speaker labels, stance tags and one level of replies. A reply to a reply attaches to the top-level comment. Reviewers pick an optional stance; author and admin don't get the control.
- **Text safety:** keep the typed comment if posting fails, in line with the existing `UnsavedText` behaviour.
- **Vote bar (reviewers, `vote` in `allowed_actions`):** Accept, Decline, current choice and tally, changeable, with a note that the study team makes the final decision. `stale_round` reloads the page and says the units have changed.
- **Author:** "This is your submission. You can read and comment, but not vote." Shows tally and votes. For round 2 and later, links to the previous round's discussion.
- **Admin:** per-unit Approve, Reject, Request changes with the tally alongside, a required comment for changes (`comment_required`), and a `ConfirmDialog` stating the outcome before `POST /unit-decisions`. Also a round switcher through `?review_round=`.
- **Closed or sent back:** read-only with the outcome shown. Refresh every 30 s while the tab is visible, without disturbing a comment being typed. `review_closed` keeps the text and explains.

## F4. Home page ([HomeView.vue](../frontend/src/views/HomeView.vue))

Under the welcome, from `GET /me/home`:

1. **Next up:** cards with one button each from `action` (Start, Continue, Check), plus "See all N" linking to `/assignments`. Admins see failed jobs with Retry.
2. **Reviews waiting:** up to 5, with tally and comment count, linking to `/reviews/:id`.
3. **Recent reviews:** a horizontally scrolling strip of status cards that wraps on phones.
4. **What's new:** the activity feed with unread markers and sentence templates per `kind` in `copy.ts`. Links go to the exact thread (`/reviews/:id#unit-<id>`). Viewing the page calls `POST /me/activity/seen` after the items are rendered.

Each panel has its own empty state ("Nothing to do right now"), and a failed load shows an error without breaking the page. Keep the trust sentence. The current section list shrinks to quiet links at the bottom. Refresh every 60 s while the tab is visible.

## F5. Navigation

- Unread dot on Home and a waiting count on Reviews in [AppLayout.vue](../frontend/src/layouts/AppLayout.vue), from a small Pinia store shared with the home page.
- Update the Reviews blurbs in [navigation.ts](../frontend/src/navigation.ts).

## Later ideas (not in this work)

Admin dashboard counts per state; filtering the feed; admin knowledge base browser (`/knowledge` is still a placeholder); email notifications when email exists; live updates instead of polling.

## Order and testing

F0 first, since without it nothing reaches review. Then F1 (independent), F3, F2, F4, F5.

Each gets Vitest specs alongside [views.spec.ts](../frontend/src/__tests__/views.spec.ts). Add a Playwright walkthrough of the three-account scenario from Part A, at desktop and phone widths.

**Word to settle before F3:** `copy.ts` avoids engineering terms, and "unit" is one. Agree the word experts see, for example "statement".
