---
title: Backend przydziałów i zadań
diataxis: reference
---

# Backend: `app.assignments` i `app.jobs`

Język: **Polski** · [English](../../eng/reference/backend-assignments-jobs.md)

`app.assignments` zawiera przepływ pracy pojedynczego eksperta nad jedną opublikowaną wersją winiety: endpointy HTTP, maszynę stanów, w której jedynym zapisującym `Assignment.state` jest `transition()`, modele payloadu odpowiedzi oraz tabele `assignments`, `answer_drafts` i `submissions`. `app.jobs` to kolejka zadań oparta na Postgresie z dzierżawami, handlery każdego rodzaju zadania oraz proces workera (`python -m app.jobs.worker`), który ją opróżnia. Endpointy recenzji koleżeńskiej opisuje [backend-reviews.md](backend-reviews.md); sposób współpracy tych elementów opisuje [assignment-lifecycle.md](../explanation/assignment-lifecycle.md).

Wszystkie endpointy są zamontowane pod `/api/v1` (`API_PREFIX`) z tagiem `assignments`. Błędy mają kształt `{code, message, details}`; `DomainError` domyślnie zwraca HTTP 409, `not_found` to 404, `invalid` to 422, a `forbidden` to 403.

## Endpointy HTTP

Kolumna „Kto” wskazuje aktora: `admin`, `assignee` (ekspert, do którego należy przydział) albo dowolnego użytkownika, który może zobaczyć przydział. Użytkownik niezwiązany z przydziałem dostaje 404 `not_found`, a nie 403.

| Endpoint | Kto | Zachowanie |
|---|---|---|
| `POST /vignette-versions/{version_id}/assignments` | administrator | Body `{expert_ids: UUID[1..500]}`. Zwraca 201 z listą widoków administratora. Błędy: `version_not_published` (409), `invalid_assignee` (422, nie jest aktywnym ekspertem), `reviewer_contaminated` (409, ekspert otworzył recenzję tej winiety), `already_assigned` (409, istnieje nieanulowany przydział tej samej wersji). |
| `GET /assignments` | dowolny | Query `state`, `vignette_version_id`, `limit` (1..500, domyślnie 100), `offset` (>= 0, domyślnie 0). Administrator widzi wszystkie przydziały, od najnowszego `updated_at`. Ekspert widzi własne, w stabilnej pseudolosowej kolejności (`md5(expert_id \|\| vignette_id)`, potem wersja). Każde podsumowanie zawiera `allowed_actions` i `job_running`. |
| `GET /assignments/{assignment_id}` | dowolny | Jeden widok dla każdej grupy odbiorców (zob. Widoki). |
| `GET /assignments/{assignment_id}/events` | assignee, administrator | Oś czasu audytu. Recenzenci dostają 404. Przypisany ekspert nie widzi zdarzeń `REVIEW_CHATTER`, a każdego aktora widzi jako `you`, `admin`, `reviewer` albo `system`. |
| `GET /assignments/{assignment_id}/submission` | assignee, administrator | Zamrożone zgłoszenie. Recenzenci oraz brak zgłoszenia dają 404. |
| `POST /assignments/{assignment_id}/start` | assignee | `assigned -> in_progress`. Ustawia `started_at` i wstawia `AnswerDraft` z pustym payloadem. |
| `POST /assignments/{assignment_id}/cancel` | administrator | Dozwolone ze stanów `assigned`, `in_progress`, `proofread_check` i `peer_review`; z pozostałych stanów zwraca 409 `illegal_transition`. |
| `PUT /assignments/{assignment_id}/draft` | assignee | Body `{version, payload}`. Tylko w stanie `in_progress` (w przeciwnym razie 409 `not_editable`). `version` różna od zapisanej daje 409 `draft_conflict` z `details.current_version`. Zwraca `{version, updated_at}` i zwiększa zapisaną wersję. |
| `POST /assignments/{assignment_id}/submit` | assignee | Tylko w stanie `in_progress`. Waliduje szkic przez `clean_submission`, wstawia wiersz `Submission` i przechodzi do `proofreading`, co kolejkuje zadanie `proofread`. |
| `GET /assignments/{assignment_id}/findings` | administrator | Jak zatwierdzone odpowiedzi zostały sklasyfikowane: wyróżnienia, zdania, flagi i `check_outcome`. Pozostali użytkownicy oraz brak rekordu dają 404 `not_found`. |
| `GET /assignments/{assignment_id}/proofread` | assignee, administrator | Query `review_round`. Deleguje do `app.proofread.service.view`. |
| `PUT /assignments/{assignment_id}/proofread` | assignee | Blokuje wiersz przydziału, a następnie deleguje do `app.proofread.service.save`. |
| `POST /assignments/{assignment_id}/submit-for-review` | assignee | Deleguje do `app.proofread.service.submit_for_review`: `proofread_check -> peer_review`. |
| `POST /assignments/{assignment_id}/retry` | administrator | Uruchamia ponownie rodzaj ostatniego zadania przydziału o statusie `failed`. Bez zadania w statusie failed: 409 `illegal_transition`. |

Endpointy zmieniające przydział blokują jego wiersz (`lock_assignment`, `SELECT ... FOR UPDATE`) przed działaniem, a po nim zatwierdzają transakcję.

### Reguły dostępu

`actor_for` odwzorowuje użytkownika na `Actor`: administrator to `admin`, właściciel przydziału to `assignee`, ekspert, dla którego `reviews.access.may_review` zwraca prawdę, to `reviewer`; każdy inny dostaje 404. Recenzent, który nie otworzył recenzji, dostaje 409 `review_not_opened` z `load` i `lock`, z wyjątkiem `POST .../review/open`.

### `allowed_actions`

`allowed_actions(state, actor)` zwraca posortowaną listę zbudowaną z tabeli przejść (`USER_ACTION_NAMES`) oraz czterech dodatkowych nazw:

| Nazwa | Dodawana, gdy |
|---|---|
| `save_draft` | stan `in_progress` i aktor `assignee` |
| `edit_proofread` | stan `proofread_check` i aktor `assignee` |
| `comment` | stan `peer_review`, dowolny aktor |
| `vote` | stan `peer_review` i aktor `reviewer` |

`USER_ACTION_NAMES` odwzorowuje `start`, `cancel`, `submit` i `submit_for_review` na siebie, trzy akcje `retry_*` na `retry`, a `approve_answers`, `reject_all_answers` i `request_changes` na `decide_answers`.

### Widoki

`AssignmentView` to unia rozróżniana przez `audience`, więc ukryte dane nie mają pola, którym mogłyby wyciec.

| `audience` | Model | Zawartość poza `id`, `state`, `review_round`, `allowed_actions`, `updated_at` |
|---|---|---|
| `expert` | `ExpertAssignment` | `vignette` (`ExpertVignette`, z `content_hash` i widocznymi `questions`), `draft`, `started_at`, `submitted_at` |
| `peer` | `PeerAssignment` | `vignette` (`PeerVignette`: kod, wersja, tekst, framing, streszczenie pacjenta, liczba słów); bez tożsamości autora |
| `admin` | `AdminAssignment` | `expert_id`, `expert_pseudonym`, kod i wersja winiety, `vignette_version_id`, `vignette`, `started_at`, `submitted_at` |

`AssignmentSummary` (elementy listy) ma `job_running`, prawdziwe, gdy stan należy do `JOB_STATES`. Modele zdarzeń to `EventAdminView` (`actor_id`, `meta`) i `EventAuthorView` (`actor` sprowadzony do roli).

## Maszyna stanów

Stany, akcje i aktorzy są typami `StrEnum` w `states.py`; reguły są w `state_machine.py`.

| `State` | Wartość | Klasa |
|---|---|---|
| `ASSIGNED` | `assigned` | |
| `IN_PROGRESS` | `in_progress` | |
| `PROOFREADING` | `proofreading` | stan zadania |
| `PROOFREAD_CHECK` | `proofread_check` | |
| `PEER_REVIEW` | `peer_review` | |
| `PROCESSING` | `processing` | stan zadania |
| `PROCESSING_FAILED` | `processing_failed` | |
| `INGESTING` | `ingesting` | stan zadania |
| `INGESTION_FAILED` | `ingestion_failed` | |
| `INGESTED` | `ingested` | końcowy |
| `REJECTED` | `rejected` | końcowy |
| `CANCELLED` | `cancelled` | końcowy |

`TERMINAL_STATES` to `{ingested, rejected, cancelled}`. `JOB_STATES` to `{proofreading, processing, ingesting}`. `Actor` ma wartości `assignee`, `admin`, `reviewer` i `system`.

### Przejścia

`TRANSITIONS` odwzorowuje `(state, action)` na `Rule(to, actors)`. Zawiera 19 wpisów.

| Z | Akcja | Do | Aktor |
|---|---|---|---|
| `assigned` | `start` | `in_progress` | assignee |
| `assigned` | `cancel` | `cancelled` | administrator |
| `in_progress` | `cancel` | `cancelled` | administrator |
| `in_progress` | `submit` | `proofreading` | assignee |
| `proofreading` | `proofread_succeeded` | `proofread_check` | system |
| `proofreading` | `proofread_failed` | `processing_failed` | system |
| `proofread_check` | `cancel` | `cancelled` | administrator |
| `proofread_check` | `submit_for_review` | `peer_review` | assignee |
| `peer_review` | `cancel` | `cancelled` | administrator |
| `peer_review` | `approve_answers` | `processing` | administrator |
| `peer_review` | `reject_all_answers` | `rejected` | administrator |
| `peer_review` | `request_changes` | `proofread_check` | administrator |
| `processing` | `processing_succeeded` | `ingesting` | system |
| `processing` | `processing_failed` | `processing_failed` | system |
| `processing_failed` | `retry_proofread` | `proofreading` | administrator |
| `processing_failed` | `retry_processing` | `processing` | administrator |
| `ingesting` | `ingestion_succeeded` | `ingested` | system |
| `ingesting` | `ingestion_failed` | `ingestion_failed` | system |
| `ingestion_failed` | `retry_ingestion` | `ingesting` | administrator |

Do `processing_failed` prowadzi zarówno nieudane zadanie korekty, jak i nieudane zadanie process; `retry` wybiera akcję na podstawie rodzaju ostatniego nieudanego zadania (`RETRY_BY_JOB`).

### `transition(db, assignment, action, actor, actor_id, meta=None) -> None`

Jedyny zapisujący `Assignment.state`. Wywołujący trzyma blokadę wiersza i zatwierdza transakcję. Funkcja:

1. wywołuje `check_transition`, która zgłasza 409 `illegal_transition` (z `details.state` i `details.action`), gdy para nie ma reguły, albo 403 `forbidden`, gdy aktora nie ma w regule;
2. gdy stan docelowy ma zadanie (`JOB_ON_ENTRY`), a aktor nie jest `system`, oczekuje na `app.compute.require_compute(kind)`, która zgłasza 503 `compute_unavailable`, gdy `REQUIRE_COMPUTE` jest włączone, a potrzebna maszyna nie jest gotowa;
3. ustawia stan docelowy i zapisuje zdarzenie audytu (`record_event`) z nazwą akcji, `from_state`, `to_state` i `meta`;
4. dodaje wiersz `Job` dla stanu, do którego wchodzi przydział.

`JOB_ON_ENTRY`: `proofreading -> proofread`, `processing -> process`, `ingesting -> ingest`.

### Funkcje pomocnicze

| Funkcja | Opis |
|---|---|
| `check_transition(state, action, actor) -> Rule` | Sprawdza poprawność przejścia bez jego wykonania. |
| `user_actions(state, actor) -> set[str]` | Nazwy akcji użytkownika dostępnych aktorowi w danym stanie. |
| `lock_assignment(db, assignment_id) -> Assignment` | `SELECT ... FOR UPDATE` z `populate_existing`; 404 `not_found`, gdy brak przydziału. |

## Payload odpowiedzi (`answers.py`)

| Model | Pola |
|---|---|
| `Highlight` | `chip` (>= 1), `text` (1..2000 znaków), `span` (start, end; przesunięcia w punktach kodowych w tekście winiety), `direction` (`toward`, `away`, `neutral`, `unclear` albo `None` w trakcie szkicu) |
| `Q4Answer` | `hypothesis`, `shift` (-2..2, `None` oznacza brak odpowiedzi), `toward` (`more_adhd`, `less_adhd`, `other`), `other_explanation` |
| `AnswerPayload` | `answers` (na identyfikator pytania, maksymalnie 20 000 znaków każda), `highlights` (maksymalnie 200), `q4`, `rating` (1..5), `insufficient_information` (bool, domyślnie false) |

Wszystkie trzy modele zabraniają dodatkowych pól. `PAYLOAD_FORMAT = 2` jest zapisywany w `Submission.payload_format`.

Kontrole szkicu (`check_draft`, łagodne wobec kompletności): `question_not_asked`, `answer_to_rating_question`, `chip_numbers` (cytaty są numerowane 1..n po kolei), `highlight_not_in_vignette` (422).

Kontrole zgłoszenia (`clean_submission`, zgłasza pierwszy znaleziony problem, wszystkie jako 422): `question_not_asked` i `answer_to_rating_question`; każde pytanie rodzaju `open` ma niepustą odpowiedź (`empty_answer`); `chip_numbers` i `highlight_not_in_vignette`; każdy chip `⟦hN⟧` w odpowiedzi wskazuje cytat (`unknown_chip`); każdy cytat ma kierunek (`highlight_no_direction`); ocena i `insufficient_information` wykluczają się (`rating_conflict`); gdy zadane jest Q6, wymagane jest jedno z nich (`submission_incomplete`). Dla Q4: `submission_incomplete` przy brakującym punkcie skali, hipotezie, kierunku lub wyjaśnieniu, a ponadto `q4_why_without_shift`, `toward_without_change` i `other_without_name`. Zwrócony payload ma przycięte odpowiedzi i tekst Q4.

Payload zgłoszenia zapisuje także `vignette_code`, `vignette_version`, `expert_pseudonym`, `started_at` i `submitted_at`; `Submission.vignette_hash` to `content_hash` wersji.

## Widok ustaleń (`check.py`)

`check.get` odczytuje wiersz `AnswerFindings` przydziału i zwraca `FindingsView`: `version`, `review_round`, `check_outcome` (`completed`, `skipped` albo `None`), `highlights` (`FindingHighlight`: `id`, `chip`, `text`, `origin` `expert` albo `implicit`, `direction`), `sentences` (`FindingSentence`: `id`, `question_id`, `text`, `targets`, `assigned_by` jedno z `chip`, `quote`, `llm`, `expert`) oraz `flags` (`FindingFlag`: `kind` `coverage` albo `direction`, `highlight`, `sentence`, `message`).

## Tabele

| Tabela (`Model`) | Kolumny |
|---|---|
| `assignments` (`Assignment`) | `id`, `vignette_version_id`, `expert_id`, `assigned_by`, `state`, `review_round` (domyślnie 1), `started_at`, `submitted_at`, `created_at`, `updated_at` |
| `answer_drafts` (`AnswerDraft`) | `assignment_id` (PK, kaskadowe usuwanie), `payload` JSONB, `version` (domyślnie 1), `updated_at` |
| `submissions` (`Submission`) | `assignment_id` (PK), `payload` JSONB, `payload_format`, `vignette_hash` (64 znaki), `submitted_at` |
| `jobs` (`Job`) | `id`, `kind`, `assignment_id` (nullable), `status`, `attempts` (domyślnie 0), `locked_until`, `last_error` (200 znaków), `created_at` |

Indeksy: `uq_assignments_active` jest unikalny na (`vignette_version_id`, `expert_id`) tam, gdzie `state <> 'cancelled'`. `uq_jobs_active` jest unikalny na (`assignment_id`, `kind`) tam, gdzie `status IN ('queued', 'running')`. `ix_jobs_claim` jest na (`status`, `created_at`). Docstring `Submission` stwierdza, że wyzwalacz bazy danych odrzuca UPDATE; wyzwalacz jest w migracji początkowej, której ta strona nie omawia.

## Kolejka zadań

`JobKind`: `proofread`, `process`, `ingest`, `refit` (dla całego korpusu, bez przydziału). `JobStatus`: `queued`, `running`, `done`, `failed`.

### `next_job(db, kinds=None) -> Job | None`

Zwraca najstarsze zadanie (według `created_at`), które jest `queued` albo `running` z `locked_until` w przeszłości. `kinds` ogranicza wynik do podanych rodzajów; `None` oznacza dowolny. Zapytanie używa `FOR UPDATE SKIP LOCKED`, więc kilka workerów nie bierze tego samego wiersza.

## Worker (`python -m app.jobs.worker`)

`main()` wykonuje w pętli `run_once()` i czeka `POLL_SECONDS`, gdy funkcja zwróci False albo zgłosi wyjątek. Osobne zadanie asynchroniczne dotyka `ALIVE_FILE` co `ALIVE_SECONDS`. Moduł importuje `app.models`, aby każda tabela była znana bez `app.main`.

### `run_once() -> bool`

Pobiera i uruchamia jedno zadanie; zwraca False, gdy zadania nie było.

1. `compute.ready_kinds()` podaje rodzaje, które mogą działać (`None`, gdy `REQUIRE_COMPUTE` jest wyłączone); `next_job` pobiera jedno z nich.
2. Pobrane zadanie, którego `attempts` osiągnęło już `MAX_ATTEMPTS` (jego worker zginął), kończy się niepowodzeniem z `last_error = "LeaseExpired"`.
3. W przeciwnym razie zadanie przechodzi w `running`, `attempts` jest zwiększane, `locked_until = now + LEASE`, a pobranie jest zatwierdzane.
4. Zadanie heartbeat odnawia `locked_until` co `LEASE / 3`, dopóki zadanie działa; błąd odnowienia jest logowany i nie zatrzymuje zadania.
5. Zadanie korpusowe (`assignment_id` ma wartość None) uruchamia `CORPUS_HANDLERS[kind](db)` i jest oznaczane jako `done`.
6. Zadanie przydziału uruchamia `PREPARE[kind](assignment_id)` (jeśli rodzaj go ma) bez otwartej transakcji i blokady. Następnie w jednej transakcji blokuje przydział, odczytuje zadanie ponownie przez `_current` (które zwraca None, gdy dzierżawa wygasła i zadanie przejął inny worker), uruchamia `HANDLERS[kind]`, oznacza zadanie jako `done` i wywołuje `transition` z `SUCCESS_ACTION[kind]` jako `system`.
7. Przy wyjątku: nazwa klasy błędu jest logowana wraz ze śladem stosu bez komunikatów i zapisywana jako `last_error`.
   - Jeśli wyjątek nie jest `PermanentJobError`, a `compute.is_down_for(kind)` zwraca prawdę, zadanie wraca do `queued`, a próba nie jest liczona.
   - Jeśli jest to `PermanentJobError` albo `attempt >= MAX_ATTEMPTS`, `_fail` oznacza zadanie jako `failed`, czyści dzierżawę, a dla zadania przydziału przenosi przydział akcją `FAILURE_ACTION[kind]`.
   - W przeciwnym razie zadanie wraca do `queued`.

| `JobKind` | `SUCCESS_ACTION` | `FAILURE_ACTION` |
|---|---|---|
| `proofread` | `proofread_succeeded` | `proofread_failed` |
| `process` | `processing_succeeded` | `processing_failed` |
| `ingest` | `ingestion_succeeded` | `ingestion_failed` |

### Handlery (`handlers.py`)

| Rodzaj | `PREPARE` | Handler |
|---|---|---|
| `proofread` | `app.proofread.service.prepare` | `app.proofread.service.record` |
| `process` | brak | `process` |
| `ingest` | `prepare_ingest` | `ingest` |
| `refit` | brak | `refit` (w `CORPUS_HANDLERS`) |

- `process(db, assignment, prepared=None)` wczytuje zgłoszenie, rundę korekty i identyfikatory pytań, dla których `AnswerDecision` w bieżącej rundzie ma wartość `approve`, i buduje rekord `AnswerFindings` z ostatecznych linii autora (`findings.record_from_lines`). Zapisuje rekord w wierszu `AnswerFindings` (tworzonym z `version=1`, gdy go brak) z `check_outcome = "completed"` i wstawia po jednej `KnowledgeUnit` na jednostkę ze statusem `approved`. Zgłasza `NoFindings`, gdy brakuje zgłoszenia lub rundy, oraz `NoUnits`, gdy rekord nie ma jednostek.
- `prepare_ingest(assignment_id)` wczytuje to, co zatwierdzono (`ingest.load`), i tworzy embeddingi (`ingest.embed`), poza transakcją workera.
- `ingest(db, assignment, prepared)` zapisuje przygotowane jednostki przez `ingest.write` i ustawia jednostki `approved` danego przydziału na `ingested`.
- `refit(db)` bierze `pg_advisory_xact_lock(BM25_LOCK)` i wywołuje `ingest.refresh_sparse`. Komentarz w module mówi, że funkcja dopasowuje BM25 ponownie do całej bazy wiedzy; jako wyzwalacz komentarz wskazuje usunięcie jednostek.
- `unit_content_hash(embed_text, embed_text_combined) -> str` haszuje oba teksty połączone znakiem nowego wiersza.

### Błędy (`errors.py`)

| Klasa | Znaczenie |
|---|---|
| `PermanentJobError` | Ponowienie nie pomoże: zadanie kończy się niepowodzeniem od razu. Klasa bazowa. |
| `NoFindings` | Podklasa: brak materiału, z którego można budować. |
| `NoUnits` | Podklasa: rekord nie ma jednostek. |
| `UnitsNotEmbeddable` | Podklasa: zapisane jednostki nie mają tekstu do osadzenia. |

## Stałe i konfiguracja

| Nazwa | Wartość | Znaczenie |
|---|---|---|
| `MAX_ATTEMPTS` | `3` | Liczba prób, po której zadanie kończy się niepowodzeniem. |
| `LEASE` | `timedelta(minutes=5)` | Długość dzierżawy; heartbeat odnawia ją co `LEASE / 3`. |
| `POLL_SECONDS` | `2.0` | Czas oczekiwania w stanie bezczynności między próbami pobrania. |
| `ALIVE_FILE` | `/tmp/worker-alive` | Plik, którego dotyka worker na potrzeby sprawdzenia stanu kontenera. |
| `ALIVE_SECONDS` | `10.0` | Odstęp między dotknięciami pliku. |
| `PAYLOAD_FORMAT` | `2` | Numer formatu zapisanego payloadu zgłoszenia. |
| `REVIEW_CHATTER` | `("review_opened", "comment_added", "vote_cast")` | Akcje audytu ukryte na osi czasu autora. |
| `LEGACY_PEER_ACTIONS` | `{"peers_approved", "peer_rejected"}` | Akcje zdarzeń pokazywane autorowi jako `reviewer`. |
| `REQUIRE_COMPUTE` | `false` | Ustawienie `require_compute`. Gdy jest włączone, `transition` zwraca 503 dla akcji użytkownika wchodzących w stan zadania, dopóki maszyna obliczeniowa nie jest gotowa, a worker wstrzymuje zadania, których maszyna nie działa. Wartość domyślna w `.env.example`. |

Pozostałe limity: `AnswerText` 20 000 znaków, `ShortText` 2 000 znaków, `highlights` 200 elementów, `AssignRequest.expert_ids` 1..500.

## Źródła w kodzie

- `backend/app/assignments/router.py` - endpointy oraz wzorzec blokowania i zatwierdzania transakcji
- `backend/app/assignments/service.py` - kontrole dostępu, widoki, przydzielanie, szkice, zgłoszenie, ponowienie, oś czasu, allowed_actions
- `backend/app/assignments/state_machine.py` - TRANSITIONS, JOB_ON_ENTRY, transition, lock_assignment
- `backend/app/assignments/states.py` - State, Action, Actor, TERMINAL_STATES, JOB_STATES
- `backend/app/assignments/models.py` - Assignment, AnswerDraft, Submission i częściowy indeks unikalny
- `backend/app/assignments/answers.py` - modele payloadu, kontrole szkicu i zgłoszenia, PAYLOAD_FORMAT
- `backend/app/assignments/check.py` - widok ustaleń
- `backend/app/assignments/schemas.py` - widoki dla grup odbiorców, modele żądań i zdarzeń
- `backend/app/jobs/models.py` - Job, JobKind, JobStatus, indeksy
- `backend/app/jobs/queue.py` - next_job, MAX_ATTEMPTS, LEASE
- `backend/app/jobs/worker.py` - run_once, heartbeat, obsługa niepowodzeń, stałe
- `backend/app/jobs/handlers.py` - PREPARE, HANDLERS, CORPUS_HANDLERS i handlery
- `backend/app/jobs/errors.py` - PermanentJobError i podklasy
- `backend/app/main.py:19,53-63` - API_PREFIX i montowanie routerów
- `backend/app/compute.py:138-170` - require_compute, ready_kinds, is_down_for
- `backend/app/core/errors.py:23-49` - DomainError i jego kody statusu
- `.env.example:20` - wartość domyślna REQUIRE_COMPUTE
