package StrukturaElicytacji {
    doc /*
     * Struktura systemu elicytacji (BDD + IBD): gdzie leży logika przepływu.
     *   - API (BackendApi) wykonuje akcje osób; każda zmiana stanu przydziału idzie przez
     *     state_machine.transition(), który w jednej transakcji zapisuje stan, zdarzenie
     *     audytowe i zadanie nowego stanu (JOB_ON_ENTRY).
     *   - Kolejką zadań jest tabela `jobs` w bazie; worker pobiera z niej zadania (next_job),
     *     wykonuje je (handlers: proofread, process, ingest, refit) i sam woła transition()
     *     z aktorem `system`.
     *   - Etapy nie przekazują sobie danych w pamięci: wszystko idzie przez bazę (schemat app),
     *     a wynik końcowy do bazy wiedzy (schemat chips, KontekstElicytacji::BazaWiedzyEksperckiej).
     *   - Compute (bramka mocy) pilnuje, by nic nie czekało na wyłączony komputer z modelami.
     *
     * Nazwy bloków, części i atrybutów są jak w kodzie (backend/app/<moduł>), opisy po polsku.
     */

    private import ScalarValues::*;
    private import ISQ::DurationValue;
    private import SI::*;
    private import BibliotekaElicytacji::*;
    private import StanyElicytacji::*;

    // =================================================================== data (ORM classes)
    package Data {
        doc /* Klasy ORM schematu app (backend/app/<moduł>/models.py); tylko pola potrzebne na diagramach. */

        enum def VersionStatus {
            doc /* Status wersji winiety; przydzielić można tylko wersję published. */
            @OdwolanieDoKodu { sciezka = "backend/app/vignettes/models.py"; }
            enum draft;
            enum published;
            enum retired;
        }
        item def Vignette {
            doc /* Winieta (kod, np. V900); jej treść jest w wersjach. */
            @OdwolanieDoKodu { sciezka = "backend/app/vignettes/models.py"; }
            attribute code : String;
            ref item versions : VignetteVersion[1..*];
        }
        item def VignetteVersion {
            doc /*
             * Wersja winiety: tekst pacjenta, streszczenie i zadane pytania (Q1-Q6). Pole design
             * (zaplanowane wskazówki, notatki punktacji; JSONB) nigdy nie trafia do ekspertów.
             */
            @OdwolanieDoKodu { sciezka = "backend/app/vignettes/models.py"; }
            ref item vignette : Vignette;
            attribute version : Integer;
            attribute status : VersionStatus;
            attribute text : String;
            attribute content_hash : String;
            attribute framing : String;
            attribute question_ids : String[1..6];
            attribute q4_whatif : String[0..1];
            attribute patient_summary : String;
            attribute 'variant' : String[0..1]; // JSONB
            attribute design : String;          // JSONB
        }
        item def Assignment {
            doc /* Przydział: jeden ekspert na jednej wersji winiety; nośnik stanu przepływu. */
            @OdwolanieDoKodu { sciezka = "backend/app/assignments/models.py"; }
            ref item vignette_version : VignetteVersion;
            attribute 'state' : State;
            attribute review_round : Integer;
        }
        item def Submission {
            doc /* Niezmienne zgłoszenie odpowiedzi (wyzwalacz w bazie), ze skrótem winiety. */
            @OdwolanieDoKodu { sciezka = "backend/app/assignments/models.py"; }
            ref item assignment : Assignment;
            attribute vignette_hash : String;
        }
        item def ProofreadRound {
            doc /* Runda korekty (jedna na rundę recenzji): podświetlenia, flagi, przebiegi korekty. */
            @OdwolanieDoKodu { sciezka = "backend/app/proofread/models.py"; }
            ref item assignment : Assignment;
            attribute review_round : Integer;
        }
        item def AnswerRevision {
            doc /* Tekst odpowiedzi na pytanie: original, proposed (korekta), final (po sprawdzeniu autora), lines. */
            @OdwolanieDoKodu { sciezka = "backend/app/proofread/models.py"; }
            ref item round : ProofreadRound;
            attribute question_id : String;
        }
        item def AnswerDecision {
            doc /* Decyzja inżyniera wiedzy o odpowiedzi na pytanie: approve / reject / request_changes. */
            @OdwolanieDoKodu { sciezka = "backend/app/reviews/models.py"; }
            ref item assignment : Assignment;
            attribute question_id : String;
            attribute decision : String;
        }
        item def AnswerFindings {
            doc /* Rekord ustaleń: zdania odpowiedzi przypisane do cytatów; wejście do cięcia na jednostki. */
            @OdwolanieDoKodu { sciezka = "backend/app/knowledge/models.py"; }
            ref item assignment : Assignment;
            attribute findings_version : Integer;
        }
        item def KnowledgeUnit {
            doc /* Jednostka wiedzy: słowa eksperta przy cytacie (`fragment`) albo cały przypadek (`case`). */
            @OdwolanieDoKodu { sciezka = "backend/app/knowledge/models.py"; }
            ref item assignment : Assignment;
            ref item submission : Submission;
            attribute kind : String;
            attribute text : String;
            attribute content_hash : String;
            attribute status : String;
        }
        item def Job {
            doc /* Zadanie w tle: wiersz tabeli jobs (kolejka w Postgresie). */
            @OdwolanieDoKodu { sciezka = "backend/app/jobs/models.py"; }
            ref item assignment : Assignment[0..1]; // brak dla zadania korpusu (refit)
            attribute kind : JobKind;
            attribute status : JobStatus;
            attribute attempts : Integer;
            attribute last_error : String[0..1];
        }
        item def AuditEvent {
            doc /* Zdarzenie audytowe zapisywane przy każdym przejściu stanu. */
            @OdwolanieDoKodu { sciezka = "backend/app/audit/models.py"; }
            attribute 'action' : String;
            attribute from_state : String[0..1];
            attribute to_state : String[0..1];
        }
    }

    // =================================================================== ports
    package Ports {
        doc /*
         * Port opisuje stronę serwera (in = żądanie, out = odpowiedź); klient używa portu
         * sprzężonego (~), w którym kierunki są odwrócone. Te same komunikaty niesie diagram
         * sekwencji (05_Sekwencja).
         */

        // ---------------------------------------------------- komunikaty
        item def HttpRequest {
            doc /* Żądanie przeglądarki do API (REST /api/v1, JSON, ciasteczko sesji). */
        }
        item def HttpResponse {
            doc /* Odpowiedź API; widok przydziału zawiera stan i allowed_actions. */
        }
        item def ModelRequest {
            doc /* Wywołanie lokalnych modeli: LanguageTool /v2/check, Ollama /api/chat, /api/embed. */
        }
        item def ModelResponse {
            doc /* Wynik modelu: poprawki pisowni, tekst redakcji, klasyfikacja zdań albo wektory. */
        }
        item def SqlStatement {
            doc /* Instrukcja SQL (zapis albo zapytanie). */
        }
        item def SqlRows {
            doc /* Wiersze wyniku zapytania SQL. */
        }

        // ---------------------------------------------------- porty
        port def HttpPort {
            doc /* REST /api/v1, JSON, ciasteczko sesji. */
            in item request : HttpRequest;
            out item response : HttpResponse;
        }
        port def SqlPort {
            doc /* PostgreSQL (asyncpg w aplikacji, psycopg w expert-knowledge-rag). */
            in item statement : SqlStatement;
            out item rows : SqlRows;
        }
        port def OllamaPort {
            doc /* Ollama: /api/chat (redakcja, klasyfikator), /api/embed (bge-m3), /api/tags (sonda). */
            in item request : ModelRequest;
            out item response : ModelResponse;
        }
        port def LanguageToolPort {
            doc /* LanguageTool: /v2/check (pisownia, gramatyka), /v2/languages (sonda). */
            in item request : ModelRequest;
            out item response : ModelResponse;
        }
    }

    private import Ports::*;

    // =================================================================== API modules
    part def Auth {
        doc /* Logowanie, sesje (SESSION_TTL_HOURS), zaproszenia, blokada konta; require_role w każdym routerze. */
        @OdwolanieDoKodu { sciezka = "backend/app/auth/service.py"; }
        attribute MAX_FAILED_LOGINS : Integer = 5;
        attribute LOCKOUT : DurationValue = 15 [min];
        attribute INVITE_TTL : DurationValue = 7 [d];
    }

    part def Users {
        doc /* Eksperci i zaproszenia (inżynier wiedzy). */
        @OdwolanieDoKodu { sciezka = "backend/app/users"; }
    }

    part def Vignettes {
        doc /* Winiety i wersje (draft -> published -> retired), pytania Q1-Q6; pole design nie trafia do ekspertów. */
        @OdwolanieDoKodu { sciezka = "backend/app/vignettes"; }
    }

    part def StateMachine {
        doc /*
         * transition(): jedyne miejsce zmiany Assignment.state. Sprawdza regułę TRANSITIONS
         * (stan, akcja -> nowy stan, dozwoleni aktorzy); gdy osoba (nie system) wprowadza przydział
         * w stan zadania, najpierw require_compute(kind) - 503 compute_unavailable zostawia stan bez
         * zmian. Potem w jednej transakcji: nowy stan, AuditEvent (record_event) i Job nowego stanu
         * (JOB_ON_ENTRY). Wołający trzyma blokadę wiersza (lock_assignment) i zatwierdza transakcję.
         * Ten sam kod działa w API (akcje osób) i w workerze (akcje systemu).
         */
        @OdwolanieDoKodu { sciezka = "backend/app/assignments/state_machine.py"; }
        exhibit state assignmentLifecycle : AssignmentLifecycle;
    }

    part def Assignments {
        doc /*
         * Przydziały, szkice (draft z numerem wersji), zgłoszenia (answers.py: check_draft,
         * clean_submission), widoki z allowed_actions, start, cancel, retry. Każda akcja przepływu
         * przechodzi przez state_machine.transition().
         */
        @OdwolanieDoKodu { sciezka = "backend/app/assignments"; }
        part state_machine : StateMachine;
    }

    part def Proofread {
        doc /*
         * Sprawdzenie korekty przez autora (stan proofread_check): GET/PUT .../proofread, relink()
         * bez modelu, flagi liczone od nowa, 409 proofread_conflict; submit-for-review wymaga
         * powiązania każdej linii. Sam potok korekty wykonuje worker (ProofreadJob).
         */
        @OdwolanieDoKodu { sciezka = "backend/app/proofread/service.py"; }
    }

    part def Reviews {
        doc /*
         * Otwarta recenzja: dostęp (access.py), review/open (ReviewParticipant), komentarze, głosy,
         * answer-decisions: request_changes -> nowa runda (proofread_check); approve -> approve_answers;
         * brak zatwierdzonych odpowiedzi -> reject_all_answers.
         */
        @OdwolanieDoKodu { sciezka = "backend/app/reviews"; }
    }

    part def Knowledge {
        doc /*
         * Podgląd bazy wiedzy dla inżyniera wiedzy: lista i wyszukiwanie jednostek (retrievery
         * expert-knowledge-rag, osadzenie zapytania bge-m3), usuwanie jednostki albo wiedzy
         * eksperta (removal.py) i zadanie refit.
         */
        @OdwolanieDoKodu { sciezka = "backend/app/knowledge/router.py"; }
        port ollama : ~OllamaPort;
        port chips : ~SqlPort;
    }

    part def Compute {
        doc /*
         * Bramka mocy (REQUIRE_COMPUTE: produkcja true, dev i testy false). Sonda (probe): GET
         * /api/tags (Ollama) i GET /v2/languages (LanguageTool) równolegle. API: watch() sonduje
         * w tle; require_compute(kind) czyta ostatnią sondę i zwraca 503 compute_unavailable
         * z details.missing. Worker: ready_kinds() - pobiera tylko zadania, których maszyna działa;
         * is_down_for(kind) po błędzie zadania. FOLLOWED_BY: po process następuje ingest, więc
         * zatwierdzenie odpowiedzi sprawdza też model osadzeń.
         */
        @OdwolanieDoKodu { sciezka = "backend/app/compute.py"; }
        attribute REQUIRE_COMPUTE : Boolean;
        attribute TIMEOUT : DurationValue = 3 [s];
        attribute WATCH_EVERY : DurationValue = 10 [s];
        attribute API_TRUSTS : DurationValue = 30 [s];
        attribute WORKER_TRUSTS : DurationValue = 15 [s];
        port ollama : ~OllamaPort;
        port languagetool : ~LanguageToolPort;
    }

    // =================================================================== worker parts
    part def JobQueue {
        doc /*
         * next_job(kinds): najstarsze zadanie queued albo running z wygasłą dzierżawą (padnięty
         * worker), tylko z gotowych rodzajów, FOR UPDATE SKIP LOCKED - wiele workerów nie pobierze
         * tego samego zadania. Indeks uq_jobs_active: najwyżej jedno żywe zadanie danego rodzaju
         * na przydział. last_error zapisuje tylko nazwę klasy wyjątku.
         */
        @OdwolanieDoKodu { sciezka = "backend/app/jobs/queue.py"; }
        attribute MAX_ATTEMPTS : Integer = 3;
        attribute LEASE : DurationValue = 5 [min];
    }

    part def ProofreadJob {
        doc /*
         * Zadanie proofread (stan proofreading). PREPARE (bez transakcji i blokady): dla każdej
         * odpowiedzi śmieci -> LanguageTool -> redakcja LLM (Answer_enhance.v1, ENHANCE_MODEL;
         * pusty = wyłączona) -> LanguageTool ponownie -> jedno zdanie na linię; potem wiązanie
         * linii z cytatami: warstwa 1 chip [n], warstwa 2 cytowane słowa, warstwa 3 klasyfikator
         * LLM (Expert_sentence_targets.v1, num_ctx 8192); flagi findings.check().
         * HANDLERS (pod blokadą przydziału): ProofreadRound + AnswerRevision.
         * Bez REQUIRE_COMPUTE niedostępna usługa jest pomijana ("unavailable"); z REQUIRE_COMPUTE
         * zadanie kończy się błędem i czeka na komputer z modelami.
         */
        @OdwolanieDoKodu { sciezka = "backend/app/proofread/pipeline.py"; }
        port ollama : ~OllamaPort;
        port languagetool : ~LanguageToolPort;
    }

    part def ProcessJob {
        doc /*
         * Zadanie process (stan processing), bez PREPARE i bez modeli: odpowiedzi zatwierdzone
         * w bieżącej rundzie, z liniami powiązanymi przez autora -> AnswerFindings ->
         * build_units(): jednostka `fragment` na każde podświetlenie ze zdaniami i jedna `case`
         * -> KnowledgeUnit (approved). Brak ustaleń lub jednostek -> błąd trwały (NoFindings, NoUnits).
         */
        @OdwolanieDoKodu { sciezka = "backend/app/jobs/handlers.py"; }
    }

    part def IngestJob {
        doc /*
         * Zadanie ingest (stan ingesting). PREPARE: ingest.load (odmowy: NoUnits,
         * UnitsNotEmbeddable, NoFindings) i osadzenie bge-m3 w jednym wywołaniu: I1 tekst jednostki,
         * I2 słowa pacjenta cytatów, I3 = I1 + słowa pacjenta. HANDLERS (pod blokadą przydziału,
         * w transakcji przejścia): pg_advisory_xact_lock (jedna ingestia naraz), zastąpienie wierszy
         * sesji w chips, przeliczenie BM25 (refresh_sparse) dla całego schematu, jednostki -> ingested.
         */
        @OdwolanieDoKodu { sciezka = "backend/app/knowledge/ingest.py"; }
        port ollama : ~OllamaPort;
        port chips : ~SqlPort;
    }

    part def RefitJob {
        doc /* Zadanie refit (CORPUS_HANDLERS, bez przydziału): po usunięciu wiedzy przelicza BM25 całej bazy wiedzy. */
        @OdwolanieDoKodu { sciezka = "backend/app/jobs/handlers.py"; }
        port chips : ~SqlPort;
    }

    part def JobHandlers {
        doc /*
         * handlers.py: PREPARE[kind] - wolna część (modele), bez transakcji i blokady;
         * HANDLERS[kind] - zapis wyniku pod blokadą wiersza przydziału, w tej samej transakcji
         * co przejście stanu; CORPUS_HANDLERS - zadania bez przydziału (refit).
         */
        @OdwolanieDoKodu { sciezka = "backend/app/jobs/handlers.py"; }
        part proofread : ProofreadJob;
        part process : ProcessJob;
        part ingest : IngestJob;
        part refit : RefitJob;
    }

    // =================================================================== containers
    part def Frontend {
        doc /*
         * Vue 3 SPA serwowana przez nginx; nginx przekazuje /api/ do API (ciasteczko first-party).
         * Reguł przepływu nie powiela: pokazuje akcje z allowed_actions; w stanach zadań odpytuje API.
         */
        @OdwolanieDoKodu { sciezka = "frontend/src"; }
        port web : HttpPort;
        port api_client : ~HttpPort;
    }

    part def BackendApi {
        doc /* FastAPI (uvicorn), prefiks /api/v1, kontrola zdrowia /api/v1/health. Moduł = router + service + models + schemas. */
        @OdwolanieDoKodu { sciezka = "backend/app/main.py"; }

        port http : HttpPort;
        port sql : ~SqlPort;
        port chips : ~SqlPort;
        port ollama : ~OllamaPort;
        port languagetool : ~LanguageToolPort;

        part auth : Auth;
        part users : Users;
        part vignettes : Vignettes;
        part assignments : Assignments;
        part proofread : Proofread;
        part reviews : Reviews;
        part knowledge : Knowledge;
        part compute : Compute;      // watch() startuje z aplikacją

        connect knowledge.ollama to ollama;
        connect knowledge.chips to chips;
        connect compute.ollama to ollama;
        connect compute.languagetool to languagetool;
    }

    part def Worker {
        doc /*
         * python -m app.jobs.worker; można uruchomić wiele instancji. main() woła run_once() w pętli
         * (POLL_SECONDS przerwy, gdy nie ma pracy). run_once: ready_kinds() -> next_job() (running,
         * attempts + 1, dzierżawa) -> PREPARE z odnawianiem dzierżawy (_heartbeat) -> lock_assignment
         * i sprawdzenie, że dzierżawa nadal jest tego workera -> HANDLERS -> done ->
         * transition(*_succeeded, system). Błędy: JobLifecycle. _alive() dotyka ALIVE_FILE co
         * ALIVE_SECONDS (healthcheck kontenera).
         */
        @OdwolanieDoKodu { sciezka = "backend/app/jobs/worker.py"; }
        attribute POLL_SECONDS : Real = 2.0;
        attribute ALIVE_SECONDS : Real = 10.0;
        attribute ALIVE_FILE : String = "/tmp/worker-alive";

        port sql : ~SqlPort;
        port chips : ~SqlPort;
        port ollama : ~OllamaPort;
        port languagetool : ~LanguageToolPort;

        part queue : JobQueue;
        part handlers : JobHandlers;
        part state_machine : StateMachine;   // ten sam kod co w API, aktor system
        part compute : Compute;

        exhibit state jobLifecycle : JobLifecycle;

        connect handlers.proofread.ollama to ollama;
        connect handlers.proofread.languagetool to languagetool;
        connect handlers.ingest.ollama to ollama;
        connect handlers.ingest.chips to chips;
        connect handlers.refit.chips to chips;
        connect compute.ollama to ollama;
        connect compute.languagetool to languagetool;
    }

    part def AppDatabase {
        doc /*
         * PostgreSQL 16 z pgvector, schemat app (migracje Alembic). Fizycznie ta sama instancja co
         * baza wiedzy (schemat chips), która jest osobnym elementem kontekstu.
         */
        @OdwolanieDoKodu { sciezka = "backend/migrations/versions"; }
        port sql : SqlPort;

        part jobs {
            doc /* Tabela jobs: kolejka zadań (Job). */
        }
        part workflow {
            doc /*
             * Stan i wyniki przepływu: assignments, answer_drafts, submissions, proofread_rounds,
             * answer_revisions, review_participants, answer_comments, answer_votes, answer_decisions,
             * answer_findings, knowledge_units, audit_events.
             */
        }
    }

    // =================================================================== system of interest
    part def SystemElicytacji {
        doc /*
         * System elicytacji wiedzy eksperckiej (ADHD): sesje z winietami, korekta, recenzja
         * koleżeńska, budowa jednostek wiedzy i ich zapis do bazy wiedzy. Granica systemu = ten blok.
         */

        // porty brzegowe
        port web : HttpPort;                    // przeglądarki ekspertów i inżyniera wiedzy
        port wiedza : ~SqlPort;                 // baza wiedzy (chips): zapis, usuwanie, podgląd
        port ollama : ~OllamaPort;              // lokalne modele (Tailscale)
        port languagetool : ~LanguageToolPort;

        part frontend : Frontend;
        part api : BackendApi;
        part worker : Worker[0..*];
        part db : AppDatabase;

        // ---------------------------------------------------- IBD: kontenery
        // przepływ = połączenie z tym, co nim płynie (kierunek żądania; odpowiedź wraca tą samą drogą)
        bind web = frontend.web;
        flow of HttpRequest from frontend.api_client.request to api.http.request;
        flow of SqlStatement from api.sql.statement to db.sql.statement;
        flow of SqlStatement from worker.sql.statement to db.sql.statement;

        // ---------------------------------------------------- IBD: przepływ przez bazę
        connection api_transition connect api.assignments.state_machine to db.workflow {
            doc /* Akcje osób (submit, submit_for_review, decyzje, retry, cancel): Assignment.state + AuditEvent. */
        }
        connection api_enqueue connect api.assignments.state_machine to db.jobs {
            doc /* JOB_ON_ENTRY: wejście w proofreading / processing / ingesting tworzy Job w tej samej transakcji. */
        }
        connection next_job connect db.jobs to worker.queue {
            doc /* Worker pobiera Job (SKIP LOCKED, tylko rodzaje z ready_kinds()). */
        }
        connection handlers_write connect worker.handlers to db.workflow {
            doc /* HANDLERS: ProofreadRound, AnswerRevision, AnswerFindings, KnowledgeUnit - pod blokadą przydziału. */
        }
        connection worker_transition connect worker.state_machine to db.workflow {
            doc /* Akcje systemu (*_succeeded / *_failed): Assignment.state + AuditEvent. */
        }
        connection worker_enqueue connect worker.state_machine to db.jobs {
            doc /* processing_succeeded -> ingesting: następne zadanie (ingest) bez udziału osoby. */
        }

        // ---------------------------------------------------- IBD: wyjścia poza system
        // delegacja do portów brzegowych: ten sam kierunek po obu stronach
        flow of SqlStatement from api.chips.statement to wiedza.statement;           // podgląd, usuwanie
        flow of SqlStatement from worker.chips.statement to wiedza.statement;        // ingest, refit
        flow of ModelRequest from api.ollama.request to ollama.request;              // osadzenie zapytania, sonda
        flow of ModelRequest from api.languagetool.request to languagetool.request;  // sonda
        flow of ModelRequest from worker.ollama.request to ollama.request;
        flow of ModelRequest from worker.languagetool.request to languagetool.request;
    }
}
