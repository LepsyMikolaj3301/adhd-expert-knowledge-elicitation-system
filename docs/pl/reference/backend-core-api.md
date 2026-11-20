---
title: Rdzeń backendu i powierzchnia API
diataxis: reference
---

# Rdzeń backendu: fabryka aplikacji, ustawienia, uwierzytelnianie, użytkownicy, strona główna, audyt

Język: **Polski** · [English](../../reference/backend-core-api.md)

Najwyższy poziom `backend/app` oraz pakiety `core`, `auth`, `users`, `home` i `audit` dostarczają aplikację FastAPI pod `/api/v1`, obiekt `Settings`, obsługę bazy danych i błędów, obsługę haseł i sesji, sondę gotowości maszyny, na której działają Ollama i LanguageTool, klientów czatu i embeddingów Ollamy, loader promptów, ślad audytu oraz CLI operatora.

Trasy pozostałych routerów (`vignettes`, `assignments`, `reviews`, `knowledge`) opisują strony [backend-vignettes-knowledge.md](backend-vignettes-knowledge.md), [backend-assignments-jobs.md](backend-assignments-jobs.md) i [backend-reviews.md](backend-reviews.md). Konfiguracja indeksowania i korekta są w [backend-indexing-proofread.md](backend-indexing-proofread.md). Wdrożenie i połączenia w czasie działania opisuje [runtime-and-deploy.md](runtime-and-deploy.md); widok komponentów jest w [architecture](../explanation/architecture.md). Lista stron jest w [docs/index.md](../index.md).

## Aplikacja (`app.main`)

`create_app()` zwraca aplikację `FastAPI` o tytule `ADHD Expert Knowledge RAG Backend`. `app.main:app` jest instancją `create_app()` na poziomie modułu.

| Element | Wartość |
|---|---|
| `API_PREFIX` | `/api/v1` |
| Swagger UI | `/api/v1/docs` |
| Dokument OpenAPI | `/api/v1/openapi.json` |
| ReDoc | wyłączony (`redoc_url=None`) |
| Domyślny model błędu dla 4XX | `ErrorResponse` |
| Routery dołączone pod prefiksem | `auth`, `users`, `vignettes`, `assignments`, `reviews`, `knowledge`, `home` (w tej kolejności), oraz `GET /health` |

Handler lifespan nic nie robi, gdy `settings.require_compute` jest fałszem. Gdy jest prawdą, uruchamia `compute.watch()` jako zadanie w tle i anuluje je przy zamknięciu.

## Trasy HTTP

Ścieżki są względne wobec `/api/v1`. Sesją jest ciasteczko `session`. „Administrator” oznacza `AdminUser`: zalogowanego użytkownika z rolą `admin`, w przeciwnym razie 403 `forbidden`. „Zalogowany” oznacza `CurrentUser`: ważną, niewygasłą sesję aktywnego użytkownika, w przeciwnym razie 401 `not_authenticated`.

| Metoda i ścieżka | Dostęp | Treść żądania | Odpowiedź w przypadku powodzenia |
|---|---|---|---|
| `GET /health` | brak | brak | 200 `{"status": "ok"}` |
| `POST /auth/login` | brak | `LoginRequest` | 200 `UserView`, ustawia ciasteczko |
| `POST /auth/logout` | brak | brak | 204, usuwa ciasteczko |
| `POST /auth/check-invite` | brak | `CheckInviteRequest` | 204 |
| `POST /auth/accept-invite` | brak | `AcceptInviteRequest` | 200 `UserView`, ustawia ciasteczko |
| `GET /me` | zalogowany | brak | 200 `UserView` |
| `GET /users` | administrator | brak | 200 lista `UserAdminView`, uporządkowana według `created_at` |
| `GET /users/by-pseudonym/{pseudonym}` | zalogowany | brak | 200 `PersonAdminCard` dla przeglądającego administratora, w pozostałych przypadkach `PersonCard` |
| `POST /users` | administrator | `UserCreate` | 201 `InvitedUser` |
| `PATCH /users/{user_id}` | administrator | `UserUpdate` | 200 `UserAdminView` |
| `POST /users/{user_id}/invite` | administrator | brak | 200 `InviteIssued` |
| `GET /me/home` | zalogowany | brak | 200 `HomeView` |
| `POST /me/activity/seen` | zalogowany | opcjonalnie `ActivitySeen` | 204 |

### Trasy uwierzytelniania

- `POST /auth/login` zamienia email na małe litery i sprawdza hasło. Nieznany email, błędne hasło, nieaktywne konto, konto bez hasła (zaproszenie nieprzyjęte) i konto zablokowane zwracają 401 `invalid_credentials` z tym samym komunikatem. Hash hasła jest weryfikowany w puli wątków także wtedy, gdy konto nie może się zalogować. Pięć nieudanych prób zeruje `failed_logins` do 0 i ustawia `locked_until` na 15 minut do przodu. Udane logowanie czyści `failed_logins` i `locked_until`, podmienia zapisany hash, gdy `needs_rehash` jest prawdą, usuwa wygasłe sesje użytkownika i tworzy sesję. `login` sam zatwierdza transakcję, żeby nieudana próba została policzona.
- `POST /auth/logout` usuwa wiersz `auth_sessions` odpowiadający tokenowi z ciasteczka, jeśli ciasteczko jest obecne, i usuwa ciasteczko (ścieżka `/`). Status to 204 z ciasteczkiem i bez niego.
- `POST /auth/check-invite` zwraca 204, gdy zaproszenie istnieje, jest niewykorzystane, nie wygasło i należy do aktywnego użytkownika. W przeciwnym razie zwraca 400 `invalid_invite`. To POST, żeby token nie trafiał do logów dostępu.
- `POST /auth/accept-invite` hashuje hasło, następnie blokuje wiersz zaproszenia i waliduje je jak wyżej (400 `invalid_invite`). Ustawia `used_at`, zapisuje hash hasła, czyści `failed_logins` i `locked_until`, usuwa wszystkie sesje użytkownika, tworzy sesję i zapisuje zdarzenie audytu `invite_accepted`.
- `GET /me` zwraca bieżącego użytkownika.

Ciasteczko sesji jest ustawiane z `httponly`, `samesite="lax"`, ścieżką `/`, `max_age` równym `session_ttl_hours * 3600` sekund oraz `secure`, gdy `settings.cookie_secure` jest prawdą lub `settings.environment` ma wartość `production`.

### Trasy użytkowników

- `POST /users` tworzy użytkownika bez hasła, wystawia zaproszenie i zwraca `InvitedUser`. Zduplikowany email zwraca 409 `email_taken`.
- `PATCH /users/{user_id}` modyfikuje `display_name` i `is_active`, jeśli zostały podane. Ustawienie `is_active` na fałsz dla konta samego administratora wykonującego żądanie zwraca 409 `cannot_deactivate_self`. Dezaktywacja innego użytkownika usuwa jego sesje. Modyfikacja `is_active` zapisuje `user_activated` lub `user_deactivated`. Nieznany `user_id` zwraca 404 `not_found`.
- `POST /users/{user_id}/invite` usuwa niewykorzystane zaproszenia użytkownika, tworzy nowe i zapisuje `invite_issued`. Przyjęcie zaproszenia ustawia nowe hasło, więc trasa służy także do resetu hasła.
- `GET /users/by-pseudonym/{pseudonym}` zwraca 404 `not_found` dla nieznanego pseudonimu. `PersonAdminCard.cases` zlicza przydziały osoby według stanu: `open` (ASSIGNED, IN_PROGRESS, PROOFREADING, PROOFREAD_CHECK), `in_review` (PEER_REVIEW), `done` (PROCESSING, PROCESSING_FAILED, INGESTING, INGESTION_FAILED, INGESTED) i `stopped` (CANCELLED, REJECTED).

Ścieżka zaproszenia ma postać `/invite/<token>`; token jest zwracany jeden raz, a zapisywany jest tylko jego hash SHA-256.

### Trasy strony głównej

`GET /me/home` zwraca `HomeView`, obliczany z tabel przepływu pracy przy każdym wywołaniu:

- `next_up` zawiera co najwyżej `NEXT_UP` przydziałów, od najnowszego `updated_at`, a `next_up_total` to pełna liczba. Ekspert widzi swoje przydziały w stanach ASSIGNED (akcja `start`), IN_PROGRESS (`continue`) i PROOFREAD_CHECK (`check`). Administrator widzi wszystkie przydziały w stanie PROCESSING_FAILED lub INGESTION_FAILED (akcja `retry`), a `expert_pseudonym` jest wypełniony tylko dla administratora.
- `reviews_waiting` zawiera co najwyżej `WAITING` otwartych recenzji. Dla administratora są to wszystkie otwarte recenzje; dla eksperta recenzje, w których `relation` to `reviewer` i `my_votes < answer_count`. `reviews_waiting_total` to pełna liczba. `recent_reviews` zawiera co najwyżej `RECENT` recenzji przeglądającego.
- `activity` zawiera co najwyżej `ACTIVITY` pozycji, od najnowszych, z dwóch źródeł. Zdarzenia przepływu pracy to `audit_events` z typem encji `assignment`, których przeglądający nie wywołał. Pozycje komentarzy to komentarze innych osób do własnych przydziałów przeglądającego (`comment_on_mine`) lub w wątkach, w których przeglądający uczestniczył (`reply`); `excerpt` to treść komentarza przycięta do `EXCERPT` znaków z `…` na końcu.
- Pozycja jest `unread`, gdy `activity_seen_at` jest puste lub `at` pozycji jest późniejsze. `unread_activity` je zlicza.
- `system` jest wypełnione dla administratorów i ma wartość null dla ekspertów.

Zdarzenia przepływu pracy według przeglądającego:

| Przeglądający | Pokazywane zdarzenia |
|---|---|
| Administrator | akcje `REVIEW_OPENED`, `REVIEW_CLOSED` i `JOB_FAILED` |
| Ekspert | akcje `assigned` i `CHECK_READY` dla własnych przydziałów; `REVIEW_OPENED` dla własnych przydziałów lub winiet, których `access.blocked_vignettes` nie wymienia; `REVIEW_CLOSED` dla własnych przydziałów lub recenzji, w których ekspert uczestniczył |

`POST /me/activity/seen` ustawia `activity_seen_at` na `until` albo na bieżący czas, gdy brakuje treści żądania lub `until`. Wartość jest ograniczona do bieżącego czasu i nigdy nie cofa się poniżej zapisanej wartości. `until` musi mieć strefę czasową (`AwareDatetime`), a treść żądania zabrania dodatkowych pól.

## Modele żądań i odpowiedzi

| Model | Pola |
|---|---|
| `LoginRequest` | `email: EmailStr`, `password` (maks. 1024 znaki); dodatkowe pola zabronione |
| `AcceptInviteRequest` | `token` (maks. 256), `password` (od 12 do 1024 znaków); dodatkowe pola zabronione |
| `CheckInviteRequest` | `token` (maks. 256); dodatkowe pola zabronione |
| `UserView` | `id`, `email`, `display_name`, `role`, `pseudonym`, `is_active`, `created_at` |
| `UserAdminView` | `UserView` oraz `invite_pending` (prawda, dopóki `password_hash` jest null) |
| `UserCreate` | `email: EmailStr`, `display_name` (od 1 do 200), `role`; dodatkowe pola zabronione |
| `UserUpdate` | `display_name` (opcjonalne, od 1 do 200), `is_active` (opcjonalne); dodatkowe pola zabronione |
| `InvitedUser` | `user: UserAdminView`, `invite_path` |
| `InviteIssued` | `invite_path` |
| `PersonCard` | `audience="peer"`, `pseudonym`, `role` |
| `PersonAdminCard` | `audience="admin"`, `pseudonym`, `role`, `display_name`, `email`, `is_active`, `cases: CaseCounts` |
| `CaseCounts` | `open`, `in_review`, `done`, `stopped` |
| `PersonView` | `PersonAdminCard` lub `PersonCard`, rozróżniane przez `audience` |
| `HomeView` | `next_up`, `next_up_total`, `reviews_waiting`, `reviews_waiting_total`, `recent_reviews`, `activity`, `unread_activity`, `system` |
| `NextUpItem` | `assignment_id`, `vignette_code`, `vignette_version`, `state`, `action`, `expert_pseudonym`, `updated_at` |
| `ActivityItem` | `kind`, `assignment_id`, `vignette_code`, `at`, `unread`; opcjonalne `question_id`, `comment_id`, `speaker`, `excerpt`, `outcome` |
| `SystemStatus` | `compute` (`ComputeStatus` lub null), `waiting`, `waiting_for_pc`, `oldest_waiting_minutes` (lub null), `stuck`, `failed_last_day` |
| `ComputeStatus` | `missing: list[str]`, `checked_seconds_ago` |
| `ActivitySeen` | `until: AwareDatetime` lub null; dodatkowe pola zabronione |

Literały w `app.home.schemas`: `NextAction` to `start`, `continue`, `check`, `retry`. `ActivityKind` to `case_assigned`, `check_ready`, `review_opened`, `review_closed`, `comment_on_mine`, `reply`, `job_failed`. `Outcome` to `accepted`, `rejected`, `sent_back`.

`SystemStatus` oblicza `home.service.system_status(db)`: `waiting` zlicza zadania w stanie QUEUED lub RUNNING z wygasłym `locked_until`; `waiting_for_pc` zlicza te, które ostatnia sonda zasobów obliczeniowych oznacza jako zablokowane; `stuck` jest prawdą, gdy oczekujące zadanie, które nie jest zablokowane, czeka dłużej niż `STUCK_MINUTES`; `failed_last_day` zlicza zadania FAILED utworzone w ciągu ostatnich 24 godzin. `compute` ma wartość null, gdy `REQUIRE_COMPUTE` jest wyłączone.

## Koperta błędu (`app.core.errors`)

Każde ciało błędu to `ErrorResponse`: `code: str`, `message: str`, `details: dict | None`.

| Zgłaszane przez | Status | `code` | `details` |
|---|---|---|---|
| `DomainError(code, message, status_code=409, details=None)` | `status_code` | podany kod | podany słownik |
| `not_found(what="Resource")` | 404 | `not_found` | `{"resource": what}` |
| `invalid(code, message, details=None)` | 422 | podany kod | podany słownik |
| `forbidden(message="You may not do this.")` | 403 | `forbidden` | brak |
| `RequestValidationError` | 422 | `validation_error` | `{"errors": [{loc, type, msg}]}` (bez `input`) |
| Starlette `HTTPException` | jego status | `http_error` | brak |
| Każdy inny wyjątek | 500 | `internal_error` | brak |

`SafeErrorMiddleware` odpowiada na nieobsłużone wyjątki i loguje `safe_traceback(exc)`: ramki stosu i nazwy typów wyjątków wzdłuż łańcucha przyczyn i kontekstu, bez komunikatów. Odpowiedź 500 wysyła tylko wtedy, gdy odpowiedź jeszcze się nie rozpoczęła.

Kody zgłaszane w omawianych tu plikach:

| `code` | Status | Źródło błędu |
|---|---|---|
| `invalid_credentials` | 401 | `auth.service.login` |
| `not_authenticated` | 401 | `auth.dependencies.current_user` |
| `invalid_invite` | 400 | `auth.service` (sprawdzenie i przyjęcie zaproszenia) |
| `email_taken` | 409 | `users.service.create_user` |
| `cannot_deactivate_self` | 409 | `users.service.update_user` |
| `compute_unavailable` | 503 | `compute.require_compute` |
| `not_an_admin` | 422 | `app.cli` import-vignettes (wypisywany, nie jest odpowiedzią HTTP) |

## Ustawienia (`app.settings`)

`settings` jest instancją `Settings(BaseSettings)`. Klasa nie ustawia prefiksu zmiennych środowiskowych, aliasu ani pliku env, więc każde pole jest czytane ze zmiennej środowiskowej o nazwie takiej jak pole, zapisanej wielkimi literami: `.env.example` wymienia nazwy `DATABASE_URL`, `ENVIRONMENT`, `COOKIE_SECURE`, `REQUIRE_COMPUTE`, `SESSION_TTL_HOURS`, `OLLAMA_BASE_URL`, `CLASSIFIER_MODEL`, `ENHANCE_MODEL`, `LANGUAGETOOL_URL` i `LANGUAGETOOL_LANGUAGE`. Pozostałe pola podlegają tej samej regule (`OLLAMA_REQUEST_TIMEOUT`, `LANGUAGETOOL_TIMEOUT`, `PROJECT_ROOT`).

| Pole | Typ | Wartość domyślna | Opis |
|---|---|---|---|
| `database_url` | `str` | `postgresql://rag:rag@localhost:5432/rag` | URL PostgreSQL; `to_async_url` zamienia pierwsze `postgresql://` na `postgresql+asyncpg://` |
| `ollama_base_url` | `str` | `http://localhost:11434` | Serwer Ollama dla czatu, embeddingów i sond |
| `require_compute` | `bool` | `False` | Włącza sprawdzenie gotowości i sondę w tle (zob. Compute) |
| `classifier_model` | `str` | `qwen3.5:9b` | Model, który przypisuje zdania bez cytatu |
| `ollama_request_timeout` | `float` | `600` | Limit czasu `chat_json` w sekundach |
| `languagetool_url` | `str` | `http://localhost:8010` | Serwer LanguageTool |
| `languagetool_language` | `str` | `en-US` | Język LanguageTool |
| `languagetool_timeout` | `float` | `60` | Limit czasu klienta LanguageTool w sekundach; czyta go `backend/app/proofread/grammar.py:93` |
| `enhance_model` | `str` | `qwen3.5:9b` | Model, który zamienia fragmenty w zdania; pusty łańcuch wyłącza ulepszanie |
| `project_root` | `Path` | `Path(__file__).resolve().parents[2]` z `settings.py` (folder zawierający `backend/`) | Folder z `prompts/` i `config/` |
| `environment` | `"development"` lub `"production"` | `development` | Każda inna wartość zatrzymuje aplikację przy starcie; `production` wymusza bezpieczne ciasteczko |
| `cookie_secure` | `bool` | `False` | Oznacza ciasteczko sesji jako tylko dla HTTPS |
| `session_ttl_hours` | `int` | `12` | Czas życia wiersza sesji i ciasteczka |

## Gotowość zasobów obliczeniowych (`app.compute`)

Moduł sonduje maszynę, na której działają Ollama i LanguageTool. Jest nieaktywny, dopóki `settings.require_compute` nie jest prawdą.

| Funkcja | Zachowanie |
|---|---|
| `probe() -> Probe` | Współbieżnie wywołuje `GET /api/tags` w Ollamie i `GET /v2/languages` w LanguageTool (limit czasu `TIMEOUT`) i zapisuje wynik jako ostatnią sondę. `Probe.models` jest null, gdy Ollama jest nieosiągalna. |
| `watch() -> None` | Pętla: `probe()`, potem uśpienie na `WATCH_EVERY`. Wyjątek jest logowany przez `safe_traceback`, a pętla trwa dalej. |
| `require_compute(kind: JobKind) -> None` | Wraca, gdy sprawdzenie jest wyłączone lub ani `kind`, ani jego rodzaj `FOLLOWED_BY` nie wymaga zasobów obliczeniowych. W przeciwnym razie używa ostatniej sondy, powtarzanej, gdy jest starsza niż `API_TRUSTS`, i zgłasza `DomainError` 503 `compute_unavailable` z `details={"missing": [...]}`, gdy czegoś brakuje. |
| `ready_kinds() -> set[JobKind] or None` | Rodzaje zadań, którym niczego nie brakuje, na podstawie sondy starej co najwyżej `WORKER_TRUSTS`; `None`, gdy sprawdzenie jest wyłączone. |
| `is_down_for(kind) -> bool` | Sonduje ponownie i zwraca, czy `kind` jest zablokowany; `False`, gdy sprawdzenie jest wyłączone lub `kind` nie wymaga zasobów obliczeniowych. |
| `latest() -> Probe or None` | Ostatnia sonda (powtarzana po `API_TRUSTS`); `None`, gdy sprawdzenie jest wyłączone. |
| `missing_now(seen)` i `blocked(seen, kind)` | Brakujące elementy dla wszystkich wartości `JobKind` oraz informacja, czy jeden rodzaj jest zablokowany przez sondę. |
| `forget()` | Odrzuca ostatnią sondę. |
| `client(base_url)` | Buduje `httpx.AsyncClient` używany do sond; źródło oznacza go jako punkt podmiany w testach. |

Czego wymaga każdy rodzaj (`_models`, `needs_compute`):

| Rodzaj | Wymaga |
|---|---|
| `PROOFREAD` | `classifier_model` i `enhance_model` (pusta nazwa jest pomijana) w Ollamie oraz LanguageTool |
| `INGEST` | modelu embeddingów nazwanego w `config/indexing.yaml` (`embeddings.model`) |
| `PROCESS` | sam niczego; `FOLLOWED_BY` odwzorowuje go na `INGEST`, więc `require_compute(PROCESS)` sprawdza model embeddingów |

Wpisy w `missing` to `ollama`, `model <name>` i `languagetool`. Nazwa modelu bez tagu pasuje do `<name>:latest` na liście Ollamy.

| Stała | Wartość |
|---|---|
| `TIMEOUT` | `3.0` sekundy, na jedno żądanie sondy |
| `WATCH_EVERY` | `10.0` sekund |
| `API_TRUSTS` | `30.0` sekund |
| `WORKER_TRUSTS` | `15.0` sekund |
| `FOLLOWED_BY` | `{JobKind.PROCESS: JobKind.INGEST}` |

`Probe` jest zamrożoną dataclass: `at` (czas monotoniczny), `models` (`frozenset[str]` lub `None`), `languagetool` (`bool`).

## Klienci Ollamy i embeddingów

| Sygnatura | Zachowanie |
|---|---|
| `ollama.chat_json(model: str, system: str or None, user: str, options: dict) -> str` | `POST /api/chat` z `stream=False`, `think=False`, `format="json"` i podanymi `options`. Komunikat systemowy jest wysyłany, gdy `system` nie jest puste. Zwraca `message.content`. Zgłasza wyjątek przy statusie błędu HTTP. |
| `ollama.parse_json_object(raw: str) -> dict or None` | Odcina otaczający blok kodu i parsuje JSON. Zwraca `None` dla niepoprawnego JSON lub wartości, która nie jest obiektem. |
| `embeddings.Embedder` | `Protocol` z `embed(texts: list[str]) -> np.ndarray`, jeden wiersz znormalizowany w normie L2 na tekst. |
| `embeddings.OllamaEmbedder(model, batch_size=64, truncate=True, base_url=None)` | Klient synchroniczny (limit czasu 300 sekund, `base_url` domyślnie `settings.ollama_base_url`). `embed(texts)` wysyła partie do `/api/embed` z `model`, `input` i `truncate` i zwraca tablicę `float32` z wierszami podzielonymi przez ich normę (dolna granica normy `1e-12`). Odpowiedź 404 zgłasza `RuntimeError` z nazwą `ollama pull <model>`. Inne błędy HTTP zgłaszają wyjątek. |

## Loader promptów (`app.prompts`)

`PROMPTS_DIR` to `settings.project_root / "prompts"`. `PromptError` jest `ValueError`. `Prompt` jest zamrożoną dataclass: `id`, `version` (int), `meta` (dict), `system` (str lub None), `user` (str).

- `load_prompt(name: str, prompts_dir: Path = PROMPTS_DIR) -> Prompt` czyta `<name>.md`. Plik musi zaczynać się od `---\n` i bloku front matter zawierającego `id` i `version`. Sekcja `# Template` daje `user` z `system=None`. W przeciwnym razie wymagana jest sekcja `# User`, a sekcja `# System` jest opcjonalna; bez żadnej z nich zgłaszany jest `PromptError`. Front matter jest parsowany jako `key: value` w wierszu, dzielone na pierwszym dwukropku; wiersz bez dwukropka zgłasza `PromptError`; wartość zaczynająca się od `{` lub `[` jest parsowana jako YAML, a przy niepowodzeniu pozostaje łańcuchem.
- `Prompt.fill(**variables) -> Prompt` zastępuje `{{NAME}}` (wielkie litery, cyfry, podkreślenie) w `system` i `user` i obcina białe znaki z wyniku. Placeholder bez wartości lub zmienna, która nie występuje w żadnej z sekcji, zgłasza `PromptError`. Wskazówka po placeholderze (dwie lub więcej spacji albo tabulatorów, potem tekst w nawiasach) jest odrzucana. Blok `{{IF_VARIANT}} ... {{END_IF}}` jest zachowywany, gdy `IF_VARIANT` ma wartość prawdziwą, a w przeciwnym razie usuwany.

## Warstwa bazy danych (`app.core.db`)

| Nazwa | Opis |
|---|---|
| `APP_SCHEMA` | `app`, schemat każdej tabeli zadeklarowanej na `Base` |
| `NAMING_CONVENTION` | wzorce nazw dla ograniczeń `ix`, `uq`, `ck`, `fk` i `pk` |
| `Base` | `DeclarativeBase` z `MetaData(schema="app", naming_convention=...)` |
| `utcnow() -> datetime` | bieżący czas w UTC |
| `enum_column(enum_class, name)` | kolumna enum bez natywnego typu enum w bazie, o długości 32, z ograniczeniem CHECK, zapisywana według wartości składowej |
| `to_async_url(url)` | dodaje do URL sterownik `+asyncpg` |
| `configure_engine(url=None, **engine_options)` | tworzy asynchroniczny silnik (`hide_parameters=True`) i fabrykę sesji z `expire_on_commit=False`; `url` domyślnie `settings.database_url` |
| `session_factory()` | fabryka sesji; wywołuje najpierw `configure_engine()`, gdy żadna nie istnieje |
| `database_url()` | URL, z którym skonfigurowano silnik, lub `settings.database_url` |
| `get_session()` i `DbSession` | zależność sesji w zakresie żądania; routery zatwierdzają transakcję jawnie |

`app.models` importuje klasy ORM `AnswerComment`, `AnswerDecision`, `AnswerDraft`, `AnswerRevision`, `AnswerVote`, `AnswerFindings`, `Assignment`, `AuditEvent`, `AuthSession`, `Invite`, `Job`, `KnowledgeUnit`, `ProofreadRound`, `ReviewParticipant`, `Submission`, `User`, `Vignette` i `VignetteVersion`, tak aby `Base.metadata` zawierało każdą tabelę.

## Pomocniki bezpieczeństwa (`app.core.security`)

| Funkcja | Zachowanie |
|---|---|
| `hash_password(password) -> str` | Hash Argon2 z domyślnymi ustawieniami `argon2.PasswordHasher()` |
| `verify_password(password_hash or None, password) -> bool` | Weryfikuje względem atrapy hasha, gdy hash to `None`, i w tym przypadku zwraca `False`; `False` przy błędzie weryfikacji lub niepoprawnym hashu |
| `needs_rehash(password_hash) -> bool` | `check_needs_rehash` hashera |
| `run_hash(function, *args)` | Uruchamia funkcję hashującą w `ThreadPoolExecutor` z 4 wątkami roboczymi |
| `new_token() -> str` | `secrets.token_urlsafe(32)` |
| `hash_token(token) -> str` | skrót szesnastkowy SHA-256 |
| `content_hash(text) -> str` | skrót szesnastkowy SHA-256 tekstu w UTF-8 |

## Stałe i zależności uwierzytelniania

| Nazwa | Wartość |
|---|---|
| `SESSION_COOKIE` | `session` |
| `MAX_FAILED_LOGINS` | `5` |
| `LOCKOUT` | 15 minut |
| `INVITE_TTL` | 7 dni |
| `MIN_PASSWORD_LENGTH` / `MAX_PASSWORD_LENGTH` | `12` / `1024` |

`auth.dependencies` definiuje `current_user`, `CurrentUser`, `require_role(role)` i `AdminUser`. `auth.service` dostarcza także `create_session`, `set_session_cookie`, `end_all_sessions` i `issue_invite`.

## Tabele

| Klasa (tabela) | Kolumny |
|---|---|
| `User` (`users`) | `id` UUID; `email` String(320), unikalny, CHECK `email = lower(email)`; `display_name` String(200); `role` (`Role`); `pseudonym` String(32), unikalny; `password_hash` String(255), null do przyjęcia zaproszenia; `is_active` (domyślnie true); `failed_logins` (domyślnie 0); `locked_until`; `activity_seen_at`; `created_at` |
| `AuthSession` (`auth_sessions`) | `token_hash` String(64), klucz główny; `user_id` FK do `users` (kaskadowo); `expires_at`; `created_at` |
| `Invite` (`invites`) | `id`; `user_id` FK do `users` (kaskadowo); `token_hash` String(64), unikalny; `expires_at`; `used_at`, null do wykorzystania |
| `AuditEvent` (`audit_events`) | `id`; `actor_id` FK do `users`, null dla systemu; `entity_type` String(32); `entity_id`; `action` String(64); `from_state`, `to_state` String(32); `meta` JSONB w kolumnie `metadata`; `at`. Indeksy na (`entity_type`, `entity_id`, `at`) i (`action`, `at`) |

`Role` jest `StrEnum` z `ADMIN = "admin"` i `EXPERT = "expert"`. `PSEUDONYM_SEQUENCE` to sekwencja `user_pseudonym_seq`; pseudonim to `A` (administrator) lub `E` (ekspert), po którym następuje numer z sekwencji zapisany co najmniej dwiema cyframi. Docstring `AuditEvent` stwierdza, że wyzwalacz bazy danych odrzuca UPDATE oraz że tabela nie może zawierać tekstu odpowiedzi ani jednostek; wyzwalacz nie jest zdefiniowany w omawianych tu plikach.

`audit.service.record_event(db, *, actor_id, entity_type, entity_id, action, from_state=None, to_state=None, meta=None) -> None` dodaje `AuditEvent` do otwartej transakcji bez jej zatwierdzania. `meta` domyślnie ma wartość `{}`.

Akcje audytu zapisywane w omawianych tu plikach: `user_created` (meta `{"role": ...}`), `user_activated`, `user_deactivated`, `invite_issued`, `invite_accepted`.

## Stałe strony głównej (`app.home.service`)

| Nazwa | Wartość |
|---|---|
| `NEXT_UP` | `5` |
| `WAITING` | `5` |
| `RECENT` | `10` |
| `ACTIVITY` | `30` |
| `EXCERPT` | `140` |
| `STUCK_MINUTES` | `5` |
| `REVIEW_OPENED` | `submit_for_review`, `units_built`, `units_built_for_peers` |
| `REVIEW_CLOSED` | `approve_answers` i `approve_units` (accepted), `reject_all_answers` i `reject_all_units` (rejected), `request_changes` (sent_back) |
| `JOB_FAILED` | `proofread_failed`, `processing_failed`, `units_failed`, `ingestion_failed` |
| `CHECK_READY` | `proofread_succeeded` |

## CLI (`python -m app.cli`)

Docstring modułu podaje wywołanie `python -m app.cli <command>`. Opcje wymienione przy każdym poleceniu są wymagane. Błędy są wypisywane na stderr, a kod wyjścia to 1.

| Polecenie | Opcje | Zachowanie |
|---|---|---|
| `create-admin` | `--email`, `--name` | Waliduje email przez `EmailStr` (ta sama reguła co przy logowaniu, więc zarezerwowane domeny, takie jak `.local`, są odrzucane), prosi o hasło przez `getpass`, sprawdza, że ma od 12 do 1024 znaków, tworzy użytkownika z rolą `admin` i tym hasłem oraz wypisuje `Created admin <pseudonym>`. Zduplikowany email wypisuje komunikat błędu `email_taken`. |
| `export-openapi` | `--out PATH` | Zapisuje `create_app().openapi()` do `PATH` jako JSON z wcięciem 2 spacji i posortowanymi kluczami, zakończony znakiem nowego wiersza. |
| `import-vignettes` | `--dir DIR`, `--whatifs FILE`, `--admin-email EMAIL` | Czyta teksty what-if z `FILE`, znajduje użytkownika po emailu zapisanym małymi literami i wymaga aktywnego administratora (`not_an_admin`, 422, w przeciwnym razie), wywołuje `app.vignettes.importing.import_vignettes` i zatwierdza transakcję. Wypisuje utworzone kody oraz, gdy występują, pominięte kody. Docstring stwierdza, że `DIR` zawiera pliki `V*.json` ładowane jako wersje robocze, że `FILE` odwzorowuje kody na teksty (`{"V001": "..."}`), że import jest atomowy (wszystko albo nic) i że kody, które już istnieją, są pomijane. |

## Źródła w kodzie

- `backend/app/main.py` - fabryka aplikacji, prefiks, lista routerów, lifespan
- `backend/app/cli.py` - polecenia CLI i opcje
- `backend/app/settings.py` - pola Settings i wartości domyślne
- `.env.example` - nazwy zmiennych środowiskowych ustawianych dla backendu
- `backend/app/compute.py` - sonda, bramki, stałe
- `backend/app/ollama.py` - chat_json, parse_json_object
- `backend/app/embeddings.py` - Embedder, OllamaEmbedder
- `backend/app/prompts.py` - loader promptów i reguły fill
- `backend/app/models.py` - rejestr klas ORM
- `backend/app/core/db.py` - Base, silnik, zależność sesji
- `backend/app/core/errors.py` - koperta błędu, handlery, middleware
- `backend/app/core/security.py` - pomocniki hashowania i tokenów
- `backend/app/auth/router.py` - trasy uwierzytelniania i /me
- `backend/app/auth/service.py` - logowanie, blokada, zaproszenia, ciasteczko, stałe
- `backend/app/auth/schemas.py` - treści żądań i limity haseł
- `backend/app/auth/dependencies.py` - current_user i zależności ról
- `backend/app/auth/models.py` - tabele AuthSession i Invite
- `backend/app/users/router.py` - trasy użytkowników
- `backend/app/users/service.py` - tworzenie i modyfikacja użytkowników, karta osoby
- `backend/app/users/models.py` - tabela User, Role, sekwencja pseudonimów
- `backend/app/users/schemas.py` - modele widoków użytkowników i osób
- `backend/app/home/router.py` - trasy strony głównej
- `backend/app/home/schemas.py` - modele widoku strony głównej i literały
- `backend/app/home/service.py` - kanał strony głównej, status systemu, stałe
- `backend/app/audit/models.py` - tabela AuditEvent
- `backend/app/audit/service.py` - record_event
