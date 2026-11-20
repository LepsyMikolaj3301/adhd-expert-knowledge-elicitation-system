---
title: Powłoka aplikacji frontendowej
diataxis: reference
---

# Powłoka aplikacji frontendowej (`frontend/src`)

Język: **Polski** · [English](../../reference/frontend-app.md)

Frontend to jednostronicowa aplikacja Vue 3 (Pinia, Vue Router, `openapi-fetch`) budowana przez Vite. Ta strona opisuje jej powłokę: start aplikacji, trasy, strażnika tras, obsługę sesji, klienta API, store'y, listy nawigacji, widoki, stałe, eksporty `copy.ts`, pomocniki formularza winiety oraz konfigurację Vite, Vitest i ESLint. Komponenty i pomocniki odpowiadania opisuje [frontend-components.md](frontend-components.md); endpointy wywoływane przez klienta opisuje [backend-core-api.md](backend-core-api.md); sposób połączenia elementów opisuje [architecture](../explanation/architecture.md).

## Start aplikacji

`main.ts` wykonuje kroki w tej kolejności:

1. Ustawia `document.title` na `SITE_NAME`.
2. Tworzy aplikację z `App.vue`, który renderuje wyłącznie `RouterView`.
3. Instaluje Pinię, a następnie router.
4. Wywołuje `installSessionHandler(router)`.
5. Montuje aplikację w `#app`.

Importuje też zmienne kroje pisma Instrument Sans i Newsreader oraz `assets/main.css`.

`site.ts` eksportuje `SITE_NAME = 'PsyKnowHow'`. Czytają go `AppLayout.vue`, `AuthLayout.vue`, `HomeView.vue` i `AboutView.vue`.

## Trasy

`router/index.ts` tworzy router przez `createWebHistory(import.meta.env.BASE_URL)`. Zachowanie przewijania przywraca zapisaną pozycję, w przeciwnym razie przewija do celu z hasha (odsunięcie 72), a w przeciwnym razie na górę strony.

Dwie trasy leżą poza layoutem. Wszystkie pozostałe są dziećmi trasy `/`, która renderuje `AppLayout` i ma `requiresAuth: true`; dzieci dziedziczą tę wartość. `AppLayout` i `HomeView` są importowane od razu (`router/index.ts:3,5`); każdy inny widok jest ładowany leniwie.

| Ścieżka | Nazwa | Widok | Meta |
|---|---|---|---|
| `/login` | `login` | `LoginView` | `guestOnly` |
| `/invite/:token` | `invite` | `AcceptInviteView` | brak |
| `/` | `home` | `HomeView` | `wide` |
| `/assignments` | `assignments` | `AssignmentsView` | brak |
| `/assignments/:id` | `assignment` | `AnswerView` (propsy) | `wide`, `roles: ['expert']`, `keepOnExpiry`, `needsIntro` |
| `/about` | `about` | `AboutView` | `title: 'About'` |
| `/instructions` | `instructions` | `IntroView` | `roles: ['expert']`, `title: 'Instructions'` |
| `/reviews` | `reviews` | `ReviewsView` | brak |
| `/reviews/:id` | `review` | `ReviewView` (propsy) | `wide`, `keepOnExpiry` |
| `/vignettes` | `vignettes` | `AdminVignettesView` | `roles: ['admin']` |
| `/vignettes/new` | `vignette-new` | `VignetteEditView` | `roles: ['admin']` |
| `/vignettes/:id` | `vignette` | `VignetteEditView` (propsy) | `roles: ['admin']` |
| `/experts` | `experts` | `ExpertsView` | `roles: ['admin']` |
| `/knowledge` | `knowledge` | `KnowledgeView` | `roles: ['admin']` |
| `/account` | `account` | `AccountView` | brak |
| `/:pathMatch(.*)*` | `not-found` | `NotFoundView` | brak |

`router.beforeEach` wywołuje `auth.load()`. Jeśli wywołanie zgłosi wyjątek, nawigacja trwa jako wylogowana, a kolejna nawigacja pyta ponownie. Następnie zwraca `guardRoute(to, auth.user)`.

### Meta trasy

`router/guard.ts` rozszerza `RouteMeta`:

| Klucz | Typ | Znaczenie |
|---|---|---|
| `requiresAuth` | `boolean` | Wylogowany odwiedzający trafia na logowanie. |
| `roles` | `User['role'][]` | Dozwolone role. |
| `guestOnly` | `boolean` | Zalogowany użytkownik trafia na stronę główną. |
| `title` | `string` | Zadeklarowany jako nagłówek sekcji; ustawiony w `about` i `instructions`. `guardRoute` go nie używa. |
| `wide` | `boolean` | `AppLayout` używa pełnej szerokości strony. |
| `keepOnExpiry` | `boolean` | Po wygaśnięciu sesji strona zostaje, a nad nią otwiera się okno ponownego logowania. |
| `needsIntro` | `boolean` | Ekspert, który nie potwierdził instrukcji, trafia najpierw do nich. |

### `guardRoute(to, user) -> true | RouteLocationRaw`

Sprawdzenia przebiegają w tej kolejności; rozstrzyga pierwsze, które pasuje.

| Warunek | Wynik |
|---|---|
| `requiresAuth` i brak użytkownika | `{ name: 'login', query: { next: to.fullPath } }` |
| ustawione `roles`, a użytkownika brak lub ma inną rolę | `{ name: 'home' }` |
| `guestOnly` i użytkownik | `{ name: 'home' }` |
| `needsIntro`, użytkownik i `introNeeded(user.id)` | `{ name: 'instructions', query: { next: to.fullPath } }` |
| w pozostałych przypadkach | `true` |

Strażnik służy wygodzie nawigacji; jego komentarz stwierdza, że API wymusza każde uprawnienie.

### `safeNextPath(next: unknown) -> string`

Zwraca `next`, gdy jest napisem zaczynającym się od `/`, a nie od `//`; w przeciwnym razie `'/'`. Używają go `LoginView` i `IntroView` dla parametru zapytania `next`.

### Flaga instrukcji (`intro.ts`)

| Funkcja | Zachowanie |
|---|---|
| `introNeeded(userId)` | `true`, chyba że klucz `intro-seen:<userId>` równa się `'1'` w `localStorage` lub w `sessionStorage`. Błąd storage jest odczytywany jako „nie widziano". |
| `acknowledgeIntro(userId, forever)` | Zapisuje klucz w `sessionStorage`; także w `localStorage`, gdy `forever` jest prawdą. Błędy storage są ignorowane. |

## Obsługa sesji (`session.ts`)

`installSessionHandler(router)` rejestruje callback, który klient API uruchamia przy każdej odpowiedzi 401:

- Jeśli bieżąca trasa ma `keepOnExpiry` i użytkownik jest ustawiony, wywołuje `auth.endSession()`, które ustawia `sessionEnded`. `AppLayout` pokazuje wtedy `SignInAgainDialog`.
- W przeciwnym razie wywołuje `auth.clear()`, a jeśli bieżąca trasa ma `requiresAuth`, przechodzi na trasę logowania z `next` ustawionym na bieżący `fullPath`.

## Klient API (`api/client.ts`)

`api` to klient `openapi-fetch` nad wygenerowanym typem `paths` (`api/schema.d.ts`, generowany i nieopisany tutaj). Jego ustawienia: `baseUrl` to `window.location.origin`, `credentials` to `'same-origin'`, a `fetch` wywołuje `globalThis.fetch` przy każdym żądaniu. Middleware `throwOnError` obsługuje każdą odpowiedź inną niż OK.

| Eksport | Opis |
|---|---|
| `api` | Typowany klient. |
| `ApiError` | Podklasa `Error` z polami `status: number`, `code: string`, `details`; `message` pochodzi z treści odpowiedzi. |
| `setUnauthorizedHandler(handler)` | Ustawia funkcję wywoływaną przy odpowiedzi 401 przed zgłoszeniem `ApiError`. Domyślna nic nie robi. |
| Aliasy typów | Nazwy typów ze schematu, na przykład `User` (`UserView`), `HomeData` (`HomeView`), `Citation` (`Highlight`), `UserAdmin` (`UserAdminView`), `State` (stan przydziału), `QuestionId`, `Direction`. |

Obsługa treści błędu: gdy treść odpowiedzi to JSON z napisowymi polami `code` i `message`, `ApiError` je przenosi. Każda inna treść (FastAPI `{"detail": ...}`, nie-JSON, 502 z proxy) staje się `code: 'unavailable'` z komunikatem `The server is not responding. Please try again.`.

## Store'y

### `useAuthStore` (`stores/auth.ts`)

| Składnik | Opis |
|---|---|
| `user` | `User` albo `null`. |
| `loaded` | `true` po pierwszej odpowiedzi z `/api/v1/me`. |
| `sessionEnded` | `true`, gdy serwer zakończył sesję na stronie z `keepOnExpiry`. |
| `isLoggedIn` | `user !== null`. |
| `role` | `'admin'` dla administratora; `'expert'` dla eksperta i dla wylogowanego odwiedzającego. |
| `load()` | Wraca od razu, jeśli `loaded`. W przeciwnym razie `GET /api/v1/me`; 401 ustawia `user` na `null`; inne błędy są zgłaszane ponownie i zostawiają `loaded` jako fałsz. |
| `login(email, password)` | `POST /api/v1/auth/login`; ustawia `user`, `loaded`, czyści `sessionEnded`. |
| `acceptInvite(token, password)` | `POST /api/v1/auth/accept-invite`; ustawia `user` i `loaded`. |
| `checkInvite(token)` | `POST /api/v1/auth/check-invite`; zgłasza `invalid_invite` dla nieważnego linku. |
| `logout()` | `POST /api/v1/auth/logout`; czyści `user` i `sessionEnded`. |
| `clear()` | Czyści `user` i `sessionEnded`, ustawia `loaded`. |
| `endSession()` | Ustawia `sessionEnded`. |

### `useHomeStore` (`stores/home.ts`)

| Składnik | Opis |
|---|---|
| `data` | `HomeData` albo `null`. |
| `failed` | `true` po nieudanym `load()`. |
| `load()` | `GET /api/v1/me/home`; zamiast zgłaszać wyjątek, ustawia `failed`. |
| `markSeen()` | Gdy `unread_activity` jest niezerowe, `POST /api/v1/me/activity/seen` z `until` ustawionym na najpóźniejsze `at` w `activity`, a następnie ustawia `unread_activity` na 0. Niepowodzenie jest ignorowane. |

## Nawigacja (`navigation.ts`)

`navFor(role) -> NavItem[]` zwraca listę administratora dla `'admin'` i listę eksperta dla każdej innej roli. `NavItem` ma `label`, `to` i `blurb` (wiersz, który pokazuje `HomeView`). `AppLayout` renderuje listę w panelu bocznym; `HomeView` wypisuje pozycje inne niż `/`, `/assignments` i `/reviews` jako karty sekcji.

| Rola | Pozycje (etykieta: ścieżka) |
|---|---|
| expert | Home: `/`; My cases: `/assignments`; Reviews: `/reviews` |
| admin | Home: `/`; All cases: `/vignettes`; Reviews: `/reviews`; Assignments: `/assignments`; Experts: `/experts`; Knowledge base: `/knowledge` |

## Layouty

| Plik | Opis |
|---|---|
| `layouts/AppLayout.vue` | Panel boczny (nazwa serwisu, link do konta `/account`, lista z `navFor`) i `RouterView`. Pokazuje plakietki: kropkę przy Home, gdy `unread_activity` jest niezerowe, oraz licznik `reviews_waiting_total` przy Reviews. Administratorom pokazuje baner z `SYSTEM.problems(home.data?.system)` prowadzący do `/#system`. Renderuje `SignInAgainDialog`, gdy `auth.sessionEnded`. Zeruje `home.data` przy zmianie id użytkownika. |
| `layouts/AuthLayout.vue` | Pasek z nazwą serwisu i wyśrodkowany slot, używany przez `LoginView` i `AcceptInviteView`. |

## Widoki

| Widok | Opis |
|---|---|
| `LoginView` | Formularz e-maila i hasła; wywołuje `auth.login`, a następnie przechodzi do `safeNextPath(route.query.next)`. |
| `AcceptInviteView` | Sprawdza token zaproszenia po zamontowaniu, nie pokazuje formularza dla nieważnego linku i ustawia hasło przez `auth.acceptInvite`, a następnie przechodzi na stronę główną. |
| `HomeView` | Najbliższe przypadki, oczekujące recenzje, ostatnie recenzje i strumień aktywności z `useHomeStore`; przycisk ponowienia dla nieudanych zadań; panel stanu systemu dla administratora; karty sekcji. |
| `AssignmentsView` | Lista przydziałów z filtrami po statusie, ekspercie i przypadku; akcje administratora: ponowienie i anulowanie; okno tworzenia przydziału; etykiety akcji eksperta. |
| `AnswerView` | Ekran odpowiadania dla jednego przydziału: kroki, cytaty z kierunkami, krok korekty, wysłanie. Używa `useAnswerDraft`; ostrzega przy `beforeunload`, dopóki szkic nie jest zapisany. |
| `IntroView` | Strona instrukcji; „continue" wywołuje `acknowledgeIntro` i przechodzi do `next` albo `/assignments`. |
| `AboutView` | Strona About zbudowana z `HOME`, `INTRO`, `CASES_INTRO` i `REVIEWS_INTRO`; ekspert i administrator widzą różne sekcje. |
| `ReviewsView` | Lista recenzji z przełącznikiem Open/Closed i filtrami po przypadku i autorze. Eksperci widzą grupy (czekające na głos, z oddanym głosem, własne zgłoszenia); administratorzy widzą jedną listę, od najstarszej. |
| `ReviewView` | Jedna recenzja: odpowiedzi, cytaty, dyskusja, głosy, decyzje; pokazuje bramkę, gdy serwer odpowiada `review_not_opened`. |
| `AdminVignettesView` | Tabela winiet dla administratora z ostatnią wersją, statusem i liczbą słów. |
| `VignetteEditView` | Formularz administratora do tworzenia winiety albo edycji wersji roboczej; tylko do odczytu dla wersji, która nie jest robocza; używa `admin/vignetteForm.ts`. |
| `ExpertsView` | Lista użytkowników dla administratora; zaproszenie, ponowne zaproszenie, zmiana nazwy, aktywacja i dezaktywacja. Link zaproszenia jest pokazywany jeden raz; opuszczenie strony prosi o potwierdzenie. |
| `KnowledgeView` | Dwie karty, Units i Test search, wybierane parametrem zapytania `tab` (`search`, w przeciwnym razie units). |
| `AccountView` | Imię i nazwisko, e-mail, rola i pseudonim; przycisk wylogowania. |
| `NotFoundView` | „We can't find that page." z linkiem do strony głównej. |

## Stałe

| Nazwa | Wartość | Plik | Zastosowanie |
|---|---|---|---|
| `REFRESH_MS` | 60 000 | `layouts/AppLayout.vue` | Interwał dla `home.load()`; tyknięcie jest pomijane, gdy karta jest ukryta lub brak użytkownika. |
| `REFRESH_MS` | 30 000 | `views/ReviewView.vue` | Interwał cichego przeładowania recenzji; pomijany, gdy karta jest ukryta, widoczna jest bramka lub trwa ładowanie. |
| `POLL_MS` | 4 000 | `views/AnswerView.vue` | Interwał przeładowania, gdy stan przydziału to `proofreading`; kończy się po zmianie stanu. |
| `POLL_MS` | 10 000 | `views/AssignmentsView.vue` | Opóźnienie przeładowania, gdy odświeżenie się nie powiodło albo istnieje przydział z `job_running`. |
| `MIN_PASSWORD_LENGTH` | 12 | `views/AcceptInviteView.vue` | Najkrótsze akceptowane hasło; ustawiane też jako `minlength` pola. |
| `MIN_WORDS` | 120 | `admin/vignetteForm.ts` | Dolny limit słów tekstu winiety, pokazywany w `VignetteEditView`. |
| `MAX_WORDS` | 250 | `admin/vignetteForm.ts` | Górny limit słów tekstu winiety. |
| `NEWS_STEP` | 5 | `views/HomeView.vue` | Liczba pozycji strumienia pokazywanych na początku i dokładanych przy każdym „Show more". |
| `SHOWN` | 3 | `views/HomeView.vue` | Liczba pozycji w listach najbliższych przypadków, oczekujących recenzji i ostatnich recenzji. |

`VignetteEditView` ustawia też atrybuty `maxlength` równe 32, 64, 600, 20000 i 1000 znaków na swoich polach (`VignetteEditView.vue:289-371`).

## Pomocniki formularza winiety (`admin/vignetteForm.ts`)

| Eksport | Opis |
|---|---|
| `FormField` | Unia: `code`, `text`, `q4_whatif`, `patient_summary`, `knowledge_target`, `quotes`. |
| `fieldForError(error: ApiError) -> FormField \| null` | Mapuje odmowę na pole formularza, do którego należy; `null` oznacza górę formularza. `construct_word_in_text` używa `details.field`, gdy jest to `text`, `q4_whatif` albo `patient_summary`. `validation_error` używa drugiego elementu `loc` pierwszego błędu, gdy wskazuje on jedno z pierwszych pięciu pól. Pozostałe kody mapują się jak niżej. |
| `nextCode(codes: string[]) -> string` | `V` plus najwyższa część liczbowa plus jeden, dopełnione do trzech cyfr (`V001` dla pustej listy). |
| `emptyDesign() -> VignetteDesign` | Puste `purpose` i `notes`, puste `planted_cues` i `confounders`, `is_control: false`, `track: 'general'`, `knowledge_target: null`, `origin: 'hand_written'`, `population: 'adult'`, `source_ref: null`. |
| `designForSaving(design) -> VignetteDesign` | Opróżnia `planted_cues` dla kontroli; zachowuje `knowledge_target` tylko dla ścieżki `text_analysis`; zachowuje `source_ref` tylko dla pochodzenia `real_text`. |
| `countTextWords(text) -> number` | Liczy słowa oddzielone białymi znakami. |
| `openingWords(text, count = 40) -> string` | Pierwsze `count` słów, z dopisanym `…`, gdy tekst jest dłuższy. |

Bezpośrednia mapa kod-pole: `vignette_code_taken` na `code`; `word_count_out_of_range` na `text`; `q4_without_whatif` na `q4_whatif`; `summary_missing` na `patient_summary`; `track_without_target` na `knowledge_target`; `span_not_in_text` i `control_with_cues` na `quotes`.

## Teksty interfejsu (`copy.ts`)

`copy.ts` zawiera teksty widoczne dla użytkownika. Jego komentarz nagłówkowy mówi, że używa słów „quote", „reference" i „case" zamiast terminów API oraz że same pytania pochodzą z API. Eksporty według grup:

| Grupa | Eksporty |
|---|---|
| Obiekty tekstów stron | `INTRO` (instrukcje), `HOME` (strona główna i About), `CASES_INTRO`, `REVIEWS_INTRO`, `INVITE`, `CASE_TEXT`, `CITE`, `SYSTEM` |
| Wspólne napisy i mapy etykiet | `TRUST_SENTENCE`, `DIRECTIONS`, `STANCES`, `FRAMING_LABELS`, `FILED_BY_LABELS`, `ASSIGNMENT_STATE_LABELS` |
| Teksty błędów | `describeError(error, { serverWording })`, `describeAdminError`, `saveRefusal` |
| Komunikaty o cytatach i odpowiedziach | `directionLabel`, `directionNeeded`, `notMentioned`, `quoteCount`, `citedTimes`, `removalNote`, `renumberNote`, `questionLabel`, `quoteTagLabel`, `proofreadPassNote` |
| Teksty recenzji i strumienia | `tallyLabel`, `speakerLabel`, `reviewOutcome`, `activityText`, `postedAt`, `commentExcerpt` |

`describeError` zwraca stały komunikat zastępczy („Something went wrong. Your text is safe. ...") dla wartości, która nie jest `ApiError`. Dla `ApiError` zwraca tekst napisany dla danego `code`; w gałęzi domyślnej zwraca komunikat błędu, gdy `serverWording` jest prawdą, a komunikat jest niepusty, w przeciwnym razie komunikat zastępczy. `describeAdminError` to `describeError` z `serverWording: true`. `SYSTEM.problems(status)` zwraca listę problemów pokazywanych w banerze administratora; `SYSTEM.rows(status)` zwraca trzy wiersze panelu stanu (komputer z modelami, worker, kolejka).

## Konfiguracja budowania i testów

| Plik | Zawartość |
|---|---|
| `vite.config.ts` | Wtyczki `vue()`, `vueDevTools()`, `tailwindcss()`. Alias `@` dla `src`. Serwer deweloperski: `host: true`, port 5173, `allowedHosts: ['frontend']`; `/api` jest przekazywane przez proxy do `VITE_API_PROXY_TARGET`, domyślnie `http://localhost:8000`, z `changeOrigin`. |
| `vitest.config.ts` | Scala konfigurację Vite. Środowisko `jsdom`; wyklucza `e2e/**` obok domyślnych wykluczeń; pokrycie z `v8` dla `src/**`, z wyłączeniem `src/api/schema.d.ts` i `src/__tests__/**`; reportery `text-summary` i `text`. |
| `eslint.config.ts` | Sprawdza lintem `**/*.{vue,ts,mts,tsx}` z presetami Vue essential i Vue TypeScript recommended, regułami Vitest recommended dla `src/**/__tests__/*`, regułami zbudowanymi z `.oxlintrc.json` i wyłączonymi regułami formatowania Prettier. Ignoruje `dist`, `dist-ssr`, `coverage` i `src/api/schema.d.ts`. |

## Źródła w kodzie

- `frontend/src/main.ts` - kolejność startu aplikacji
- `frontend/src/App.vue` - komponent główny
- `frontend/src/site.ts` - SITE_NAME
- `frontend/src/router/index.ts` - tabela tras, zachowanie przewijania, beforeEach
- `frontend/src/router/guard.ts` - RouteMeta, guardRoute, safeNextPath
- `frontend/src/intro.ts` - introNeeded, acknowledgeIntro
- `frontend/src/session.ts` - installSessionHandler
- `frontend/src/api/client.ts` - klient api, ApiError, aliasy typów, handler 401
- `frontend/src/stores/auth.ts` - store uwierzytelniania
- `frontend/src/stores/home.ts` - store strony głównej
- `frontend/src/navigation.ts` - NavItem, listy navFor
- `frontend/src/layouts/AppLayout.vue` - panel boczny, plakietki, interwał odświeżania
- `frontend/src/layouts/AuthLayout.vue` - layout uwierzytelniania
- `frontend/src/views/AboutView.vue` - opis widoku
- `frontend/src/views/AcceptInviteView.vue` - opis widoku, MIN_PASSWORD_LENGTH
- `frontend/src/views/AccountView.vue` - opis widoku
- `frontend/src/views/AdminVignettesView.vue` - opis widoku
- `frontend/src/views/AnswerView.vue` - opis widoku, POLL_MS
- `frontend/src/views/AssignmentsView.vue` - opis widoku, POLL_MS
- `frontend/src/views/ExpertsView.vue` - opis widoku
- `frontend/src/views/HomeView.vue` - opis widoku, SHOWN, NEWS_STEP
- `frontend/src/views/IntroView.vue` - opis widoku
- `frontend/src/views/KnowledgeView.vue` - karty
- `frontend/src/views/LoginView.vue` - opis widoku
- `frontend/src/views/NotFoundView.vue` - opis widoku
- `frontend/src/views/ReviewView.vue` - opis widoku, REFRESH_MS
- `frontend/src/views/ReviewsView.vue` - opis widoku
- `frontend/src/views/VignetteEditView.vue` - opis widoku, wartości maxlength
- `frontend/src/admin/vignetteForm.ts` - pomocniki formularza, MIN_WORDS, MAX_WORDS
- `frontend/src/copy.ts` - lista eksportów, describeError
- `frontend/vite.config.ts` - wtyczki Vite, alias, serwer deweloperski i proxy
- `frontend/vitest.config.ts` - środowisko Vitest i pokrycie
- `frontend/eslint.config.ts` - konfiguracja lintu
