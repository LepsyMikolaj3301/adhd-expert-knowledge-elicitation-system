package StrukturaElicytacji {
    doc /*
     * Struktura systemu (BDD + IBD).
     *   SystemElicytacji  - system będący przedmiotem modelu (granica systemu)
     *   BackendApi        - moduły backend/app/* jako części
     *   FrontendWebowy    - aplikacja Vue + nginx, części wg grup widoków
     *   WorkerZadan       - proces python -m app.jobs.worker
     *   BazaPostgres      - schematy app i chips
     *   Biblioteki        - pakiety packages/expert-knowledge-*
     * Struktura techniczna ścieżki przetwarzania (od zgłoszenia do chips): 13_SciezkaPrzetwarzania.
     * Połączenia wewnętrzne (IBD) są w SystemElicytacji; zależności między modułami backendu
     * w pakiecie ZaleznosciModulow (odpowiednik diagramu pakietów).
     */

    private import ScalarValues::*;
    private import BibliotekaElicytacji::*;
    private import InterfejsyElicytacji::Porty::*;
    private import InterfejsyElicytacji::DefinicjeInterfejsow::*;

    // =================================================================== libraries
    package Biblioteki {
        part def RdzenWiedzyEksperckiej {
            doc /* Rdzeń bez zależności od LangChain: rekordy, notatki, BM25, prompty. */
            @OdwolanieDoKodu { sciezka = "packages/expert-knowledge-core/src/expert_knowledge_core"; }
            part rekordy;     // records.py - Record, Unit, Sentence, Highlight
            part notatki;       // notes.py   - nagłówki, cytaty, podział na zdania
            part bm25;        // bm25.py    - wektory rzadkie, Bm25Config
            part prompty;     // prompts.py - prompty ekspert / pacjent
        }

        part def RagWiedzyEksperckiej {
            doc /* Warstwa RAG na LangChain: retrievery, ranking (RRF), łańcuchy odpowiedzi. */
            @OdwolanieDoKodu { sciezka = "packages/expert-knowledge-rag/src/expert_knowledge_rag"; }
            part magazyn;                      // store.py - ExpertKnowledgeStore
            part wyszukiwaczPytan;          // retrievers.py - ExpertQuestionRetriever
            part wyszukiwaczTekstuPacjenta;       // retrievers.py - PatientTextRetriever
            part ranking;                    // ranking.py - cue_scores (RRF), downweight_duplicate_cases
            part filtry;                     // filters.py - ExpertFilter: winiety, eksperci (experts)
            part budowniczySql;                 // sql.py - units_search, cues_search
            part lancuchy;                     // chains.py - expert_answer_chain, patient_answer_chain
            part rdzen : RdzenWiedzyEksperckiej;
            port bd : ~PortSql;
            port llm : ~PortOllama;
        }
    }

    private import Biblioteki::*;

    // =================================================================== backend modules
    package ModulyBackendu {
        doc /* Moduły FastAPI (backend/app/<moduł>): router + service + models + schemas. */

        part def ModulRdzenia {
            doc /*
             * Połączenie z bazą (SQLAlchemy + asyncpg; DATABASE_URL dostaje tylko nazwę sterownika),
             * błędy domenowe, bezpieczeństwo (hasła, tokeny, content_hash).
             */
            @OdwolanieDoKodu { sciezka = "backend/app/core"; }
        }
        part def ModulUwierzytelniania {
            doc /* Logowanie, wylogowanie, akceptacja zaproszeń; blokada po 5 nieudanych próbach. */
            @OdwolanieDoKodu { sciezka = "backend/app/auth"; }
            attribute maksymalnaLiczbaNieudanychLogowan : Integer = 5;
        }
        part def ModulUzytkownikow {
            doc /* Zarządzanie ekspertami i zaproszeniami (admin). */
            @OdwolanieDoKodu { sciezka = "backend/app/users"; }
        }
        part def ModulWiniet {
            doc /* Winiety i wersje: draft -> published -> retired; pytania Q1-Q6. */
            @OdwolanieDoKodu { sciezka = "backend/app/vignettes"; }
            exhibit state cyklZyciaWersji : StanyElicytacji::CyklZyciaWersjiWiniety;
        }
        part def MaszynaStanowPrzeplywu {
            doc /* TRANSITIONS + transition(): jedyne miejsce zmiany stanu przydziału. */
            @OdwolanieDoKodu { sciezka = "backend/app/assignments/state_machine.py"; }
            exhibit state cyklZyciaPrzydzialu : StanyElicytacji::CyklZyciaPrzydzialu;
        }
        part def ModulPrzydzialow {
            doc /* Przydziały, szkice, zgłoszenia, widoki z allowed_actions, ponawianie zadań. */
            @OdwolanieDoKodu { sciezka = "backend/app/assignments"; }
            part maszynaStanow : MaszynaStanowPrzeplywu;
            part walidacjaOdpowiedzi;   // answers.py - check_draft, clean_submission
        }
        part def ModulKorekty {
            doc /* Korekta: LanguageTool, poprawa LLM, odrzucanie śmieci, łączenie linii z cytatami. */
            @OdwolanieDoKodu { sciezka = "backend/app/proofread"; }
            part potok;   // pipeline.py
            part gramatyka;    // grammar.py  - LanguageTool
            part redakcja;    // enhance.py  - LLM, prompt Answer_enhance.v1
            part smieci;    // garbage.py
            part powiazania;      // links.py
        }
        part def ModulRecenzji {
            doc /* Otwarta recenzja: dostęp, komentarze, głosy, decyzje administratora. */
            @OdwolanieDoKodu { sciezka = "backend/app/reviews"; }
            part dostep;     // access.py - kto może czytać zgłoszenie
        }
        part def ModulWiedzy {
            doc /* Ustalenia, jednostki wiedzy, osadzanie, ingestia do chips, wyszukiwanie, usuwanie. */
            @OdwolanieDoKodu { sciezka = "backend/app/knowledge"; }
            part klasyfikator;  // classifier.py - prompt Expert_sentence_targets.v1
            part ustalenia;    // findings.py   - build_units
            part osadzenie;   // embedding.py  - bge-m3
            part ingestia;      // ingest.py     - zapis do chips, refresh_sparse
            part wyszukiwanie;      // search.py     - wyszukiwanie hybrydowe
            part usuwanie;     // removal.py    - usuwanie jednostek, refit BM25
        }
        part def ModulZadan {
            doc /* Kolejka zadań w Postgresie (SKIP LOCKED, dzierżawa 5 min, max 3 próby) i handlery. */
            @OdwolanieDoKodu { sciezka = "backend/app/jobs"; }
            part kolejka;       // queue.py    - next_job
            part handlery;    // handlers.py - PREPARE, HANDLERS, CORPUS_HANDLERS
            exhibit state cyklZyciaZadania : StanyElicytacji::CyklZyciaZadania;
        }
        part def ModulMocyObliczeniowej {
            doc /*
             * Sprawdza, czy komputer z modelami (Ollama, LanguageTool) jest gotowy; włączany
             * REQUIRE_COMPUTE. API: 503 compute_unavailable przed zakolejkowaniem zadania.
             * Worker: nie pobiera zadań, których maszyna nie działa. Szczegóły:
             * SciezkaPrzetwarzania::Komponenty::BramkaMocyObliczeniowej.
             */
            @OdwolanieDoKodu { sciezka = "backend/app/compute.py"; }
            port ollama : ~PortOllama;
            port languageTool : ~PortLanguageTool;
        }
        part def ModulAudytu {
            @OdwolanieDoKodu { sciezka = "backend/app/audit"; }
        }
        part def ModulStronyGlownej {
            doc /* Strona domowa i aktywność użytkownika. */
            @OdwolanieDoKodu { sciezka = "backend/app/home"; }
        }
    }

    private import ModulyBackendu::*;

    // =================================================================== module dependencies (package view)
    package ZaleznosciModulow {
        doc /* Zależności między modułami backendu (kto importuje kogo). */
        dependency przydzialyUzywajaWiniet from ModulPrzydzialow to ModulWiniet;
        dependency przydzialyUzywajaAudytu from ModulPrzydzialow to ModulAudytu;
        dependency przydzialyUzywajaZadan from ModulPrzydzialow to ModulZadan;
        dependency przydzialyUzywajaKorekty from ModulPrzydzialow to ModulKorekty;
        dependency recenzjeUzywajaPrzydzialow from ModulRecenzji to ModulPrzydzialow;
        dependency zadaniaUzywajaPrzydzialow from ModulZadan to ModulPrzydzialow;
        dependency zadaniaUzywajaKorekty from ModulZadan to ModulKorekty;
        dependency zadaniaUzywajaWiedzy from ModulZadan to ModulWiedzy;
        dependency zadaniaUzywajaRecenzji from ModulZadan to ModulRecenzji;
        dependency wiedzaUzywaRag from ModulWiedzy to RagWiedzyEksperckiej;
        dependency wiedzaUzywaRdzenia from ModulWiedzy to RdzenWiedzyEksperckiej;
        dependency uwierzytelnianieUzywaUzytkownikow from ModulUwierzytelniania to ModulUzytkownikow;
        dependency stronaGlownaUzywaPrzydzialow from ModulStronyGlownej to ModulPrzydzialow;
        dependency stronaGlownaUzywaRecenzji from ModulStronyGlownej to ModulRecenzji;
        dependency przydzialyUzywajaMocy from ModulPrzydzialow to ModulMocyObliczeniowej;   // transition() -> require_compute
        dependency zadaniaUzywajaMocy from ModulZadan to ModulMocyObliczeniowej;           // worker -> ready_kinds, is_down_for
        dependency mocUzywaZadan from ModulMocyObliczeniowej to ModulZadan;                // JobKind
    }

    // =================================================================== containers
    part def BackendApi {
        doc /* Aplikacja FastAPI (uvicorn), prefiks /api/v1, kontrola zdrowia /api/v1/health. */
        @OdwolanieDoKodu { sciezka = "backend/app/main.py"; }

        port api : PortHttp;
        port bd : ~PortSql;
        port llm : ~PortOllama;          // wyszukiwanie: osadzanie zapytania; sonda mocy
        port gramatyka : ~PortLanguageTool;   // tylko sonda mocy (GET /v2/languages)

        part rdzen : ModulRdzenia;
        part uwierzytelnianie : ModulUwierzytelniania;
        part uzytkownicy : ModulUzytkownikow;
        part winiety : ModulWiniet;
        part przydzialy : ModulPrzydzialow;
        part korekta : ModulKorekty;
        part recenzje : ModulRecenzji;
        part wiedza : ModulWiedzy;
        part zadania : ModulZadan;
        part audyt : ModulAudytu;
        part stronaGlowna : ModulStronyGlownej;
        part mocObliczeniowa : ModulMocyObliczeniowej;   // obserwator (watch) startuje z aplikacją
        part rag : RagWiedzyEksperckiej;
    }

    part def WorkerZadan {
        doc /*
         * Proces zadań w tle; można uruchomić wiele instancji. Wolna część (PREPARE) bez transakcji,
         * zapis wyniku pod blokadą przydziału, potem przejście stanu. Z REQUIRE_COMPUTE pobiera tylko
         * zadania, których maszyna działa. Co 10 s dotyka /tmp/worker-alive (healthcheck kontenera).
         * Struktura techniczna: SciezkaPrzetwarzania::Komponenty::PetlaWorkera.
         */
        @OdwolanieDoKodu { sciezka = "backend/app/jobs/worker.py"; }

        port bd : ~PortSql;
        port llm : ~PortOllama;
        port gramatyka : ~PortLanguageTool;

        attribute odpytywanieSekundy : Real = 2.0;
        attribute maksymalnaLiczbaProb : Integer = 3;
        attribute dzierzawaMinuty : Integer = 5;
        attribute sygnalZyciaSekundy : Real = 10.0;
        attribute plikZycia : String = "/tmp/worker-alive";

        // worker uruchamia ten sam kod modułów co API
        part zadania : ModulZadan;
        part korekta : ModulKorekty;
        part wiedza : ModulWiedzy;
        part przydzialy : ModulPrzydzialow;
        part mocObliczeniowa : ModulMocyObliczeniowej;

        perform action wykonanieZadania : CzynnosciElicytacji::WykonanieZadania;
        perform action zadanieKorekty : CzynnosciElicytacji::PotokKorekty;
        perform action zadaniePrzetwarzania : CzynnosciElicytacji::ZbudujJednostki;
        perform action zadanieIngestii : CzynnosciElicytacji::IngestujJednostki;
    }

    part def FrontendWebowy {
        doc /* Vue 3 SPA serwowana przez nginx; nginx przekazuje /api/ do backendu (ciasteczko first-party). */
        @OdwolanieDoKodu { sciezka = "frontend/src"; }

        port web : PortHttp;             // przeglądarka -> nginx
        port klientApi : ~PortHttp;      // nginx -> backend

        part widokiLogowania {
            doc /* LoginView, AcceptInviteView, AccountView */
        }
        part widokiEksperta {
            doc /* HomeView, AssignmentsView, AnswerView, IntroView, AboutView */
        }
        part widokiRecenzji {
            doc /* ReviewsView, ReviewView */
        }
        part widokiAdministratora {
            doc /* AdminVignettesView, VignetteEditView, ExpertsView */
        }
        part widokWiedzy {
            doc /* KnowledgeView - przegląd i wyszukiwanie jednostek wiedzy */
        }
        part modulKlientaApi {
            doc /* frontend/src/api - klient generowany z openapi.json */
        }
    }

    part def BazaPostgres {
        doc /*
         * PostgreSQL 16 z pgvector. Produkcja: kontener na maszynie wirtualnej Azure (niepublikowany).
         * Testy API tworzą własną bazę na przebieg: rag_<pid>_test (PlatformaElicytacji).
         */
        @OdwolanieDoKodu { sciezka = "backend/migrations/versions"; }
        port sql : PortSql;
        part schematApp {
            doc /* DziedzinaElicytacji::SchematApp - migracje Alembic */
        }
        part schematChips {
            doc /* DziedzinaElicytacji::SchematChips - wektory jednostek wiedzy */
        }
    }

    // =================================================================== system of interest
    part def SystemElicytacji {
        doc /*
         * System zarządzania wiedzą ekspercką (ADHD): elicytacja winietami, korekta, recenzja
         * koleżeńska, budowa jednostek wiedzy i baza RAG. Granica systemu = ten blok.
         */

        // porty brzegowe
        port web : PortHttp;                 // dla przeglądarek administratorów i ekspertów
        port ollama : ~PortOllama;           // usługa zewnętrzna: lokalne LLM i osadzanie
        port languageTool : ~PortLanguageTool;

        part frontend : FrontendWebowy;
        part backend : BackendApi;
        part worker : WorkerZadan[0..*];
        part baza : BazaPostgres;

        // ---------------------------------------------------- IBD: delegacje portów brzegowych
        bind web = frontend.web;

        // ---------------------------------------------------- IBD: połączenia wewnętrzne
        interface nginxDoApi : ApiRest connect
            klient ::> frontend.klientApi to
            serwer ::> backend.api;

        interface apiDoBd : PolaczenieSql connect
            klient ::> backend.bd to
            serwer ::> baza.sql;

        interface workerDoBd : PolaczenieSql connect
            klient ::> worker.bd to
            serwer ::> baza.sql;

        // ---------------------------------------------------- IBD: wyjście do usług zewnętrznych
        connect backend.llm to ollama;
        connect worker.llm to ollama;
        connect worker.gramatyka to languageTool;
        connect backend.gramatyka to languageTool;     // sonda mocy obliczeniowej
    }
}
