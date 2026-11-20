---
title: Frontend app shell
diataxis: reference
---

# Frontend app shell (`frontend/src`)

The frontend is a Vue 3 single-page app (Pinia, Vue Router, `openapi-fetch`) built with Vite. This page covers its shell: bootstrap, routes, route guard, session handler, API client, stores, navigation lists, views, constants, the `copy.ts` exports, the vignette form helpers and the Vite, Vitest and ESLint configuration. Components and the answering helpers are in [frontend-components.md](frontend-components.md); the endpoints the client calls are in [backend-core-api.md](backend-core-api.md); how the pieces fit together is in [architecture](../explanation/architecture.md).

## Bootstrap

`main.ts` runs in this order:

1. Sets `document.title` to `SITE_NAME`.
2. Creates the app from `App.vue`, which renders only a `RouterView`.
3. Installs Pinia, then the router.
4. Calls `installSessionHandler(router)`.
5. Mounts on `#app`.

It also imports the variable fonts Instrument Sans and Newsreader and `assets/main.css`.

`site.ts` exports `SITE_NAME = 'PsyKnowHow'`. `AppLayout.vue`, `AuthLayout.vue`, `HomeView.vue` and `AboutView.vue` read it.

## Routes

`router/index.ts` creates the router with `createWebHistory(import.meta.env.BASE_URL)`. The scroll behaviour restores the saved position, otherwise scrolls to the hash target (offset 72), otherwise to the top.

Two routes sit outside the layout. All others are children of `/`, which renders `AppLayout` and has `requiresAuth: true`; children inherit it. `AppLayout` and `HomeView` are imported eagerly (`router/index.ts:3,5`); every other view is loaded lazily.

| Path | Name | View | Meta |
|---|---|---|---|
| `/login` | `login` | `LoginView` | `guestOnly` |
| `/invite/:token` | `invite` | `AcceptInviteView` | none |
| `/` | `home` | `HomeView` | `wide` |
| `/assignments` | `assignments` | `AssignmentsView` | none |
| `/assignments/:id` | `assignment` | `AnswerView` (props) | `wide`, `roles: ['expert']`, `keepOnExpiry`, `needsIntro` |
| `/about` | `about` | `AboutView` | `title: 'About'` |
| `/instructions` | `instructions` | `IntroView` | `roles: ['expert']`, `title: 'Instructions'` |
| `/reviews` | `reviews` | `ReviewsView` | none |
| `/reviews/:id` | `review` | `ReviewView` (props) | `wide`, `keepOnExpiry` |
| `/vignettes` | `vignettes` | `AdminVignettesView` | `roles: ['admin']` |
| `/vignettes/new` | `vignette-new` | `VignetteEditView` | `roles: ['admin']` |
| `/vignettes/:id` | `vignette` | `VignetteEditView` (props) | `roles: ['admin']` |
| `/experts` | `experts` | `ExpertsView` | `roles: ['admin']` |
| `/knowledge` | `knowledge` | `KnowledgeView` | `roles: ['admin']` |
| `/account` | `account` | `AccountView` | none |
| `/:pathMatch(.*)*` | `not-found` | `NotFoundView` | none |

`router.beforeEach` calls `auth.load()`. If the call throws, the navigation continues as logged out, and the next navigation asks again. It then returns `guardRoute(to, auth.user)`.

### Route meta

`router/guard.ts` augments `RouteMeta`:

| Key | Type | Meaning |
|---|---|---|
| `requiresAuth` | `boolean` | A logged-out visitor is sent to login. |
| `roles` | `User['role'][]` | Allowed roles. |
| `guestOnly` | `boolean` | A logged-in user is sent home. |
| `title` | `string` | Declared as the heading of a section; set on `about` and `instructions`. `guardRoute` does not use it. |
| `wide` | `boolean` | `AppLayout` uses the full width of the page. |
| `keepOnExpiry` | `boolean` | On session expiry the page stays and the sign-in dialog opens over it. |
| `needsIntro` | `boolean` | An expert who has not acknowledged the instructions is sent to them first. |

### `guardRoute(to, user) -> true | RouteLocationRaw`

Checks run in this order; the first that matches decides.

| Condition | Result |
|---|---|
| `requiresAuth` and no user | `{ name: 'login', query: { next: to.fullPath } }` |
| `roles` set and the user is missing or has another role | `{ name: 'home' }` |
| `guestOnly` and a user | `{ name: 'home' }` |
| `needsIntro`, a user, and `introNeeded(user.id)` | `{ name: 'instructions', query: { next: to.fullPath } }` |
| otherwise | `true` |

The guard serves navigation convenience; its comment states that the API enforces every permission.

### `safeNextPath(next: unknown) -> string`

Returns `next` when it is a string that starts with `/` and not `//`; otherwise `'/'`. `LoginView` and `IntroView` use it for the `next` query parameter.

### Instructions flag (`intro.ts`)

| Function | Behaviour |
|---|---|
| `introNeeded(userId)` | `true` unless the key `intro-seen:<userId>` equals `'1'` in `localStorage` or in `sessionStorage`. A storage error reads as not seen. |
| `acknowledgeIntro(userId, forever)` | Writes the key to `sessionStorage`; also to `localStorage` when `forever` is true. Storage errors are ignored. |

## Session handler (`session.ts`)

`installSessionHandler(router)` registers the callback that the API client runs on every 401 response:

- If the current route has `keepOnExpiry` and a user is set, it calls `auth.endSession()`, which sets `sessionEnded`. `AppLayout` then shows `SignInAgainDialog`.
- Otherwise it calls `auth.clear()`, and if the current route has `requiresAuth` it pushes the login route with `next` set to the current `fullPath`.

## API client (`api/client.ts`)

`api` is an `openapi-fetch` client over the generated `paths` type (`api/schema.d.ts`, generated and not covered here). Its settings: `baseUrl` is `window.location.origin`, `credentials` is `'same-origin'`, and `fetch` calls `globalThis.fetch` on each request. The `throwOnError` middleware handles every non-OK response.

| Export | Description |
|---|---|
| `api` | The typed client. |
| `ApiError` | `Error` subclass with `status: number`, `code: string`, `details`; `message` comes from the response body. |
| `setUnauthorizedHandler(handler)` | Sets the function called on a 401 response before `ApiError` is thrown. The default does nothing. |
| Type aliases | Names for schema types, for example `User` (`UserView`), `HomeData` (`HomeView`), `Citation` (`Highlight`), `UserAdmin` (`UserAdminView`), `State` (the assignment state), `QuestionId`, `Direction`. |

Error body handling: when the response body is JSON with string `code` and `message`, `ApiError` carries them. Any other body (a FastAPI `{"detail": ...}`, non-JSON, a proxy 502) becomes `code: 'unavailable'` with the message `The server is not responding. Please try again.`.

## Stores

### `useAuthStore` (`stores/auth.ts`)

| Member | Description |
|---|---|
| `user` | `User` or `null`. |
| `loaded` | `true` after the first answer from `/api/v1/me`. |
| `sessionEnded` | `true` when the server ended the session on a `keepOnExpiry` page. |
| `isLoggedIn` | `user !== null`. |
| `role` | `'admin'` for an admin; `'expert'` for an expert and for a logged-out visitor. |
| `load()` | Returns at once if `loaded`. Otherwise `GET /api/v1/me`; a 401 sets `user` to `null`; other errors are rethrown and leave `loaded` false. |
| `login(email, password)` | `POST /api/v1/auth/login`; sets `user`, `loaded`, clears `sessionEnded`. |
| `acceptInvite(token, password)` | `POST /api/v1/auth/accept-invite`; sets `user` and `loaded`. |
| `checkInvite(token)` | `POST /api/v1/auth/check-invite`; throws `invalid_invite` for a dead link. |
| `logout()` | `POST /api/v1/auth/logout`; clears `user` and `sessionEnded`. |
| `clear()` | Clears `user` and `sessionEnded`, sets `loaded`. |
| `endSession()` | Sets `sessionEnded`. |

### `useHomeStore` (`stores/home.ts`)

| Member | Description |
|---|---|
| `data` | `HomeData` or `null`. |
| `failed` | `true` after a failed `load()`. |
| `load()` | `GET /api/v1/me/home`; sets `failed` instead of throwing. |
| `markSeen()` | When `unread_activity` is non-zero, `POST /api/v1/me/activity/seen` with `until` set to the latest `at` in `activity`, then sets `unread_activity` to 0. A failure is ignored. |

## Navigation (`navigation.ts`)

`navFor(role) -> NavItem[]` returns the admin list for `'admin'` and the expert list for any other role. `NavItem` has `label`, `to` and `blurb` (the line `HomeView` shows). `AppLayout` renders the list in the side panel; `HomeView` lists the items other than `/`, `/assignments` and `/reviews` as section cards.

| Role | Items (label: path) |
|---|---|
| expert | Home: `/`; My cases: `/assignments`; Reviews: `/reviews` |
| admin | Home: `/`; All cases: `/vignettes`; Reviews: `/reviews`; Assignments: `/assignments`; Experts: `/experts`; Knowledge base: `/knowledge` |

## Layouts

| File | Description |
|---|---|
| `layouts/AppLayout.vue` | Side panel (site name, account link to `/account`, the `navFor` list) and the `RouterView`. Shows the badges: a dot on Home when `unread_activity` is non-zero, the `reviews_waiting_total` count on Reviews. For admins, shows a banner from `SYSTEM.problems(home.data?.system)` linking to `/#system`. Renders `SignInAgainDialog` while `auth.sessionEnded`. Resets `home.data` when the user id changes. |
| `layouts/AuthLayout.vue` | Site name bar and a centered slot, used by `LoginView` and `AcceptInviteView`. |

## Views

| View | Description |
|---|---|
| `LoginView` | Email and password form; calls `auth.login`, then goes to `safeNextPath(route.query.next)`. |
| `AcceptInviteView` | Checks the invite token on mount, shows no form for a dead link, and sets the password through `auth.acceptInvite`, then goes home. |
| `HomeView` | Next cases, reviews waiting, recent reviews and the activity feed from `useHomeStore`; retry button for failed jobs; admin system status panel; section cards. |
| `AssignmentsView` | Assignment list with filters on status, expert and case; admin actions retry and cancel; create-assignment dialog; expert action labels. |
| `AnswerView` | The answering screen for one assignment: steps, quotes with directions, proofreading step, submit. Uses `useAnswerDraft`; warns on `beforeunload` while the draft is not saved. |
| `IntroView` | The instructions page; "continue" calls `acknowledgeIntro` and goes to `next` or `/assignments`. |
| `AboutView` | The About page built from `HOME`, `INTRO`, `CASES_INTRO` and `REVIEWS_INTRO`; expert and admin see different sections. |
| `ReviewsView` | Review list with an Open/Closed toggle and filters on case and author. Experts see groups (waiting for the vote, voted, own submissions); admins see one list, oldest first. |
| `ReviewView` | One review: answers, quotes, discussion, votes, decisions; shows a gate when the server answers `review_not_opened`. |
| `AdminVignettesView` | Admin table of vignettes with latest version, status and word count. |
| `VignetteEditView` | Admin form to create a vignette or edit a draft version; read-only for a version that is not a draft; uses `admin/vignetteForm.ts`. |
| `ExpertsView` | Admin user list; invite, re-invite, rename, activate and deactivate. The invite link is shown once; leaving the page asks for confirmation. |
| `KnowledgeView` | Two tabs, Units and Test search, selected by the `tab` query parameter (`search`, otherwise units). |
| `AccountView` | Name, email, role and pseudonym; sign-out button. |
| `NotFoundView` | "We can't find that page." with a link home. |

## Constants

| Name | Value | File | Use |
|---|---|---|---|
| `REFRESH_MS` | 60 000 | `layouts/AppLayout.vue` | Interval for `home.load()`; the tick skips when the tab is hidden or no user is set. |
| `REFRESH_MS` | 30 000 | `views/ReviewView.vue` | Interval for a silent reload of the review; skipped while the tab is hidden, the gate is shown or a load runs. |
| `POLL_MS` | 4 000 | `views/AnswerView.vue` | Reload interval while the assignment state is `proofreading`; stops when the state changes. |
| `POLL_MS` | 10 000 | `views/AssignmentsView.vue` | Reload delay while a failed refresh or an assignment with `job_running` exists. |
| `MIN_PASSWORD_LENGTH` | 12 | `views/AcceptInviteView.vue` | Shortest accepted new password; also set as `minlength` on the input. |
| `MIN_WORDS` | 120 | `admin/vignetteForm.ts` | Lower word limit of a vignette text, shown in `VignetteEditView`. |
| `MAX_WORDS` | 250 | `admin/vignetteForm.ts` | Upper word limit of a vignette text. |
| `NEWS_STEP` | 5 | `views/HomeView.vue` | Feed items shown first and added per "Show more". |
| `SHOWN` | 3 | `views/HomeView.vue` | Items shown in the next-cases, reviews-waiting and recent-reviews lists. |

`VignetteEditView` also sets `maxlength` attributes of 32, 64, 600, 20000 and 1000 characters on its inputs (`VignetteEditView.vue:289-371`).

## Vignette form helpers (`admin/vignetteForm.ts`)

| Export | Description |
|---|---|
| `FormField` | Union: `code`, `text`, `q4_whatif`, `patient_summary`, `knowledge_target`, `quotes`. |
| `fieldForError(error: ApiError) -> FormField \| null` | Maps a refusal to the form field it belongs to; `null` means the top of the form. `construct_word_in_text` uses `details.field` when it is `text`, `q4_whatif` or `patient_summary`. `validation_error` uses the second `loc` element of the first error when it names one of the first five fields. Other codes map as below. |
| `nextCode(codes: string[]) -> string` | `V` plus the highest numeric part plus one, padded to three digits (`V001` for an empty list). |
| `emptyDesign() -> VignetteDesign` | Empty `purpose` and `notes`, empty `planted_cues` and `confounders`, `is_control: false`, `track: 'general'`, `knowledge_target: null`, `origin: 'hand_written'`, `population: 'adult'`, `source_ref: null`. |
| `designForSaving(design) -> VignetteDesign` | Empties `planted_cues` for a control; keeps `knowledge_target` only for track `text_analysis`; keeps `source_ref` only for origin `real_text`. |
| `countTextWords(text) -> number` | Counts whitespace-separated words. |
| `openingWords(text, count = 40) -> string` | First `count` words, with `…` appended when the text is longer. |

Direct code-to-field map: `vignette_code_taken` to `code`; `word_count_out_of_range` to `text`; `q4_without_whatif` to `q4_whatif`; `summary_missing` to `patient_summary`; `track_without_target` to `knowledge_target`; `span_not_in_text` and `control_with_cues` to `quotes`.

## Wording (`copy.ts`)

`copy.ts` holds the user-facing wording. Its header comment says it uses "quote", "reference" and "case" in place of the API's terms, and that the questions themselves come from the API. Exports by group:

| Group | Exports |
|---|---|
| Page text objects | `INTRO` (instructions), `HOME` (home and About), `CASES_INTRO`, `REVIEWS_INTRO`, `INVITE`, `CASE_TEXT`, `CITE`, `SYSTEM` |
| Shared strings and label maps | `TRUST_SENTENCE`, `DIRECTIONS`, `STANCES`, `FRAMING_LABELS`, `FILED_BY_LABELS`, `ASSIGNMENT_STATE_LABELS` |
| Error wording | `describeError(error, { serverWording })`, `describeAdminError`, `saveRefusal` |
| Quote and answer messages | `directionLabel`, `directionNeeded`, `notMentioned`, `quoteCount`, `citedTimes`, `removalNote`, `renumberNote`, `questionLabel`, `quoteTagLabel`, `proofreadPassNote` |
| Review and feed text | `tallyLabel`, `speakerLabel`, `reviewOutcome`, `activityText`, `postedAt`, `commentExcerpt` |

`describeError` returns a fixed fallback ("Something went wrong. Your text is safe. ...") for a value that is not an `ApiError`. For an `ApiError` it returns the wording written for the `code`; in the default branch it returns the error's message when `serverWording` is true and the message is non-empty, otherwise the fallback. `describeAdminError` is `describeError` with `serverWording: true`. `SYSTEM.problems(status)` returns the list of problems shown in the admin banner; `SYSTEM.rows(status)` returns the three rows of the status panel (computer with the models, worker, queue).

## Build and test configuration

| File | Content |
|---|---|
| `vite.config.ts` | Plugins `vue()`, `vueDevTools()`, `tailwindcss()`. Alias `@` for `src`. Dev server: `host: true`, port 5173, `allowedHosts: ['frontend']`; `/api` is proxied to `VITE_API_PROXY_TARGET`, default `http://localhost:8000`, with `changeOrigin`. |
| `vitest.config.ts` | Merges the Vite config. Environment `jsdom`; excludes `e2e/**` besides the default excludes; coverage with `v8` over `src/**`, excluding `src/api/schema.d.ts` and `src/__tests__/**`; reporters `text-summary` and `text`. |
| `eslint.config.ts` | Lints `**/*.{vue,ts,mts,tsx}` with the Vue essential and Vue TypeScript recommended presets, the Vitest recommended rules on `src/**/__tests__/*`, rules built from `.oxlintrc.json`, and Prettier formatting rules switched off. Ignores `dist`, `dist-ssr`, `coverage` and `src/api/schema.d.ts`. |

## Sources in code

- `frontend/src/main.ts` - bootstrap order
- `frontend/src/App.vue` - root component
- `frontend/src/site.ts` - SITE_NAME
- `frontend/src/router/index.ts` - route table, scroll behaviour, beforeEach
- `frontend/src/router/guard.ts` - RouteMeta, guardRoute, safeNextPath
- `frontend/src/intro.ts` - introNeeded, acknowledgeIntro
- `frontend/src/session.ts` - installSessionHandler
- `frontend/src/api/client.ts` - api client, ApiError, type aliases, 401 handler
- `frontend/src/stores/auth.ts` - auth store
- `frontend/src/stores/home.ts` - home store
- `frontend/src/navigation.ts` - NavItem, navFor lists
- `frontend/src/layouts/AppLayout.vue` - side panel, badges, refresh interval
- `frontend/src/layouts/AuthLayout.vue` - auth layout
- `frontend/src/views/AboutView.vue` - view summary
- `frontend/src/views/AcceptInviteView.vue` - view summary, MIN_PASSWORD_LENGTH
- `frontend/src/views/AccountView.vue` - view summary
- `frontend/src/views/AdminVignettesView.vue` - view summary
- `frontend/src/views/AnswerView.vue` - view summary, POLL_MS
- `frontend/src/views/AssignmentsView.vue` - view summary, POLL_MS
- `frontend/src/views/ExpertsView.vue` - view summary
- `frontend/src/views/HomeView.vue` - view summary, SHOWN, NEWS_STEP
- `frontend/src/views/IntroView.vue` - view summary
- `frontend/src/views/KnowledgeView.vue` - tabs
- `frontend/src/views/LoginView.vue` - view summary
- `frontend/src/views/NotFoundView.vue` - view summary
- `frontend/src/views/ReviewView.vue` - view summary, REFRESH_MS
- `frontend/src/views/ReviewsView.vue` - view summary
- `frontend/src/views/VignetteEditView.vue` - view summary, maxlength values
- `frontend/src/admin/vignetteForm.ts` - form helpers, MIN_WORDS, MAX_WORDS
- `frontend/src/copy.ts` - export list, describeError
- `frontend/vite.config.ts` - Vite plugins, alias, dev server and proxy
- `frontend/vitest.config.ts` - Vitest environment and coverage
- `frontend/eslint.config.ts` - lint configuration
