package SciezkaPrzetwarzania {
    doc /*
     * Techniczna struktura ścieżki przetwarzania wypełnionej winiety (BDD + IBD): od zgłoszenia
     * odpowiedzi eksperta do wierszy w schemacie `chips`, z których czyta RAG.
     *
     * Ścieżka (stan przydziału -> zadanie -> co powstaje):
     *   1. zgłoszenie (API)            in_progress -> proofreading      Zgloszenie (niezmienne), Job proofread
     *   2. korekta (worker)            proofreading -> proofread_check  RundaKorekty + RewizjaOdpowiedzi
     *   3. sprawdzenie autora (API)    proofread_check -> peer_review   poprawione teksty i powiązania linii
     *   4. recenzja + decyzja (API)    peer_review -> processing        DecyzjaOOdpowiedzi, Job process
     *                                  (lub -> proofread_check: nowa runda, lub -> rejected)
     *   5. cięcie (worker)             processing -> ingesting          UstaleniaOdpowiedzi + JednostkaWiedzy, Job ingest
     *   6. ingestia (worker)           ingesting -> ingested            wiersze chips + przeliczony BM25
     *
     * Każde przekazanie między etapami to wiersz w Postgresie (schemat `app`) i zadanie w tabeli
     * `jobs`; etapy nie przekazują sobie danych w pamięci. IBD (`SciezkaPrzetwarzaniaWiniety`) pokazuje
     * to jawnie: artefakty płyną przez `magazynStanu`, a zadania przez `kolejka`.
     *
     * Każde zadanie ma dwie fazy (app/jobs/handlers.py):
     *   PREPARE  - wolna część (LanguageTool, modele), bez transakcji i bez blokady;
     *   HANDLERS - zapis wyniku pod blokadą wiersza przydziału, w tej samej transakcji co przejście stanu.
     *
     * Części logiczne są alokowane do modułów i kontenerów z 04_Struktura (pakiet AlokacjaSciezki).
     */

    private import ScalarValues::*;
    private import ISQ::DurationValue;
    private import SI::*;
    private import BibliotekaElicytacji::*;
    private import DziedzinaElicytacji::TypyWyliczeniowe::*;
    private import DziedzinaElicytacji::TrescOdpowiedzi::Cytat;
    private import DziedzinaElicytacji::SchematApp::*;
    private import InterfejsyElicytacji::Elementy::Osadzenie;
    private import InterfejsyElicytacji::Porty::*;
    private import StanyElicytacji::Sygnaly::SygnalPrzeplywu;
    private import KontekstElicytacji::kontekstElicytacji;

    // =================================================================== 1. artefakty
    package Artefakty {
        doc /* Dane przekazywane między częściami ścieżki (oprócz encji ze schematu app). */

        enum def ZrodloPowiazania {
            doc /* Kto przypisał linię odpowiedzi do cytatu (`assigned_by`). */
            @OdwolanieDoKodu { sciezka = "backend/app/proofread/links.py"; }
            enum chip;      // db: chip    - warstwa 1: chip [n] w linii
            enum cytat;     // db: quote   - warstwa 2: cytowane słowa pasują do podświetlenia lub winiety
            enum model;     // db: llm     - warstwa 3: klasyfikator LLM
            enum ekspert;   // db: expert  - autor przypisał ręcznie w sprawdzeniu korekty
        }

        item def TekstOdpowiedzi {
            doc /* Tekst odpowiedzi na jedno pytanie na danym etapie korekty. */
            attribute idPytania : IdPytania;
            attribute tresc : String;
        }

        item def WynikKorektyOdpowiedzi {
            doc /* `Proofread`: tekst po korekcie (jedno zdanie na linię), usunięte śmieci, przebiegi. */
            @OdwolanieDoKodu { sciezka = "backend/app/proofread/pipeline.py"; }
            attribute idPytania : IdPytania;
            attribute oryginal : String;
            attribute propozycja : String;
            attribute odrzucone : String[0..*];
            attribute przebiegi : Json;   // grammar, enhanced, grammar_after, dropped; "unavailable" przy pominięciu
        }

        item def LiniaOdpowiedzi {
            doc /* Linia odpowiedzi `{text, targets, assigned_by}`; cele: id podświetleń (h1, i1) i `case`. */
            @OdwolanieDoKodu { sciezka = "backend/app/proofread/links.py"; }
            attribute tekst : String;
            attribute cele : String[0..*];   // pusta lista = linia jeszcze niepowiązana
            attribute zrodlo : ZrodloPowiazania[0..1];
        }

        item def FlagaUstalen {
            doc /* Flaga pokazywana autorowi (findings.check), np. cytat bez zdania, kierunek sprzeczny z treścią. */
            @OdwolanieDoKodu { sciezka = "backend/app/knowledge/findings.py"; }
            attribute rodzaj : String;
            attribute idPodswietlenia : String;
            attribute idZdania : String[0..1];
        }

        item def PrzygotowanaKorekta {
            doc /* Wynik fazy PREPARE zadania `proofread` (słownik z proofread.service.prepare). */
            @OdwolanieDoKodu { sciezka = "backend/app/proofread/service.py"; }
            item pozycje : WynikKorektyOdpowiedzi[1..*];
            item linie : LiniaOdpowiedzi[0..*];
            item podswietlenia : Cytat[0..*];     // cytaty eksperta + niejawne (i1, i2...) z warstwy 2
            item flagi : FlagaUstalen[0..*];
            attribute przebiegi : Json;
            attribute klasyfikator : String[0..1];  // model, jeśli klasyfikator został użyty
            attribute prompt : String[0..1];
        }

        item def PakietIngestii {
            doc /*
             * `Ingestion`: zatwierdzone jednostki przydziału wycięte z rekordu ustaleń, z wektorami.
             * I1 - tekst jednostki (to, co zrecenzowano), I2 - słowa pacjenta każdego cytatu,
             * I3 - I1 ze słowami pacjenta. Jedno wywołanie osadzania: 2n + m tekstów.
             */
            @OdwolanieDoKodu { sciezka = "backend/app/knowledge/ingest.py"; }
            attribute idSesji : String;           // = id przydziału
            attribute idEksperta : String;
            attribute winieta : Json;             // kod, wersja, tekst, skrót, kontekstowanie, populacja
            attribute dokument : Json;            // rekord ustaleń przycięty do zatwierdzonych jednostek
            attribute zdarzenia : Json;           // co autor widział i zrobił (tylko id i rodzaje)
            attribute segmentator : Json;         // findings_version, klasyfikator, prompt
            attribute sciezkaBadawcza : String;   // track
            item i1 : Osadzenie[1..*];
            item i2 : Osadzenie[0..*];
            item i3 : Osadzenie[1..*];
        }

        item def WierszeChips {
            doc /* Wiersze jednej sesji w schemacie chips (zastępują poprzednie wiersze tej sesji). */
            @OdwolanieDoKodu { sciezka = "backend/app/knowledge/ingest.py"; }
            item sesja : DziedzinaElicytacji::SchematChips::SesjaElicytacji;
            item podswietlenia : DziedzinaElicytacji::SchematChips::Cytat[0..*];
            item zdania : DziedzinaElicytacji::SchematChips::ZdanieOdpowiedzi[0..*];
            item jednostki : DziedzinaElicytacji::SchematChips::JednostkaUstalen[1..*];
            item kluczeWskazowek : DziedzinaElicytacji::SchematChips::KluczWskazowki[0..*];
            item zdarzenia : DziedzinaElicytacji::SchematChips::ZdarzenieRecenzji[0..*];
        }

        item def ProbaMocy {
            doc /* `Probe`: wynik ostatniej sondy komputera z modelami. */
            @OdwolanieDoKodu { sciezka = "backend/app/compute.py"; }
            attribute chwila : Real;                  // time.monotonic()
            attribute ollamaOsiagalna : Boolean;
            attribute modele : String[0..*];          // co Ollama ma pobrane (/api/tags)
            attribute languageToolOsiagalny : Boolean;
        }
    }

    private import Artefakty::*;

    // =================================================================== 2. porty artefaktów
    package PortyArtefaktow {
        doc /* Porty strony nadawcy (out). Odbiorca używa portu sprzężonego (~). */

        port def PortSygnalu {
            doc /* Akcja przepływu z aktorem (np. Zglos, ZatwierdzOdpowiedzi, KorektaUdana). */
            out item sygnal : SygnalPrzeplywu;
        }
        port def PortZgloszenia {
            out item zgloszenie : Zgloszenie;
        }
        port def PortZadania {
            out item zadanie : Zadanie;
        }
        port def PortStanuMocy {
            out item proba : ProbaMocy;
        }
        port def PortTekstu {
            out item tekst : TekstOdpowiedzi;
        }
        port def PortCytatow {
            out item podswietlenia : Cytat[0..*];
        }
        port def PortWynikuKorekty {
            out item wynik : WynikKorektyOdpowiedzi;
        }
        port def PortLinii {
            out item linie : LiniaOdpowiedzi[0..*];
        }
        port def PortFlag {
            out item flagi : FlagaUstalen[0..*];
        }
        port def PortPrzygotowanejKorekty {
            out item korekta : PrzygotowanaKorekta;
        }
        port def PortRewizji {
            doc /* Poprawki autora: teksty końcowe i ręczne przypisania linii (PUT .../proofread). */
            out item rewizje : RewizjaOdpowiedzi[1..*];
        }
        port def PortRundy {
            out item runda : RundaKorekty;
            out item rewizje : RewizjaOdpowiedzi[1..*];
        }
        port def PortDecyzji {
            out item decyzje : DecyzjaOOdpowiedzi[1..*];
        }
        port def PortUstalen {
            out item ustalenia : UstaleniaOdpowiedzi;
            out item jednostki : JednostkaWiedzy[1..*];
        }
        port def PortPakietuIngestii {
            out item pakiet : PakietIngestii;
        }
        port def PortWierszyChips {
            out item wiersze : WierszeChips;
        }
        port def PortZdarzen {
            out item zdarzenie : ZdarzenieAudytowe;
        }
    }

    private import PortyArtefaktow::*;

    // =================================================================== 3. komponenty (BDD)
    package Komponenty {

        // ------------------------------------------------------------ sterowanie przepływem
        part def BramkaPrzejsc :> StrukturaElicytacji::ModulyBackendu::MaszynaStanowPrzeplywu {
            doc /*
             * transition(): jedyne miejsce zmiany stanu przydziału. Sprawdza regułę (TRANSITIONS,
             * aktor), a gdy osoba (nie system) wprowadza przydział w stan zadania, najpierw pyta
             * bramkę mocy (require_compute) - 503 zostawia przydział bez zmian. Potem w jednej
             * transakcji: nowy stan, zdarzenie audytowe, Job dla nowego stanu (JOB_ON_ENTRY).
             * Wywołujący trzyma blokadę wiersza przydziału (lock_assignment) i zatwierdza transakcję.
             */
            @OdwolanieDoKodu { sciezka = "backend/app/assignments/state_machine.py"; }
            port polecenia : ~PortSygnalu;
            port stanMocy : ~PortStanuMocy;
            port zadania : PortZadania;
            port zdarzenia : PortZdarzen;
        }

        part def BramkaMocyObliczeniowej {
            doc /*
             * app/compute.py, włączana REQUIRE_COMPUTE (produkcja: true; dev i testy: false).
             * Ollama i LanguageTool działają na komputerze właściciela, nie na serwerze aplikacji.
             * Sonda: GET /api/tags (Ollama) i GET /v2/languages (LanguageTool) równolegle.
             * Potrzeby rodzajów zadań:
             *   korekta       - model klasyfikatora, model redakcji (jeśli włączony), LanguageTool
             *   przetwarzanie - nic; ale po nim bez udziału osoby następuje ingestia (FOLLOWED_BY),
             *                   więc API sprawdza też model osadzeń
             *   ingestia      - model osadzeń z config/indexing.yaml (bge-m3)
             *   przeliczenie  - nic (BM25 bez modelu)
             */
            @OdwolanieDoKodu { sciezka = "backend/app/compute.py"; }
            attribute wymaganaMoc : Boolean;                              // REQUIRE_COMPUTE
            attribute limitCzasuSondy : DurationValue = 3 [s];
            attribute odstepSondowania : DurationValue = 10 [s];          // watch() w API
            attribute waznoscSondyDlaApi : DurationValue = 30 [s];        // starszą sondę żądanie ponawia
            attribute waznoscSondyDlaWorkera : DurationValue = 15 [s];

            port ollama : ~PortOllama;
            port languageTool : ~PortLanguageTool;
            port stanMocy : PortStanuMocy;

            part obserwator {
                doc /* watch(): zadanie tła API (lifespan), sonda co 10 s; nie ginie przy błędzie. */
            }
            part sprawdzenieDlaApi {
                doc /* require_compute(kind): 503 compute_unavailable, details.missing = ollama | languagetool | model <nazwa>. */
            }
            part gotoweRodzaje {
                doc /* ready_kinds(): rodzaje zadań, które worker może teraz pobrać (None = wszystkie). */
            }
            part awariaPoBledzie {
                doc /* is_down_for(kind): po błędzie zadania pyta komputer od razu, czy to jego awaria. */
            }
        }

        part def KolejkaZadan {
            doc /*
             * Tabela app.jobs + next_job(): najstarsze zadanie queued albo running z wygasłą
             * dzierżawą (padnięty worker), tylko z rodzajów gotowych (ready_kinds), FOR UPDATE
             * SKIP LOCKED - wiele workerów nie pobierze tego samego zadania. Indeks uq_jobs_active:
             * najwyżej jedno żywe (queued/running) zadanie danego rodzaju na przydział.
             * last_error zapisuje tylko nazwę klasy wyjątku (komunikat mógłby cytować eksperta).
             */
            @OdwolanieDoKodu { sciezka = "backend/app/jobs/queue.py"; }
            attribute maksymalnaLiczbaProb : Integer = 3;
            attribute dzierzawa : DurationValue = 5 [min];
            port wejscie : ~PortZadania;
            port wyjscie : PortZadania;
        }

        part def PetlaWorkera {
            doc /*
             * python -m app.jobs.worker: main() woła run_once() w pętli; gdy nie ma pracy, czeka 2 s.
             * run_once: gotowe rodzaje -> pobranie (running, attempts + 1, dzierżawa) -> PREPARE bez
             * transakcji (z odnawianiem dzierżawy) -> blokada przydziału, sprawdzenie, że dzierżawa
             * nadal należy do tego workera (_current) -> HANDLERS -> done -> transition(*_succeeded).
             * Polityka błędów: PermanentJobError -> failed od razu; komputer z modelami niedostępny ->
             * z powrotem queued, próba się nie liczy; inaczej queued aż do 3. próby, potem failed
             * i transition(*_failed).
             */
            @OdwolanieDoKodu { sciezka = "backend/app/jobs/worker.py"; }
            attribute odstepOdpytywania : DurationValue = 2 [s];
            attribute odnowienieDzierzawy : DurationValue = 100 [s];      // LEASE / 3
            attribute odstepSygnaluZycia : DurationValue = 10 [s];
            attribute plikZycia : String = "/tmp/worker-alive";           // czytany przez healthcheck (60 s)

            port zadania : ~PortZadania;
            port stanMocy : ~PortStanuMocy;
            port wynik : PortSygnalu;            // *_succeeded / *_failed (aktor: system)
            port doKorekty : PortZadania;
            port doCiecia : PortZadania;
            port doIngestii : PortZadania;

            part rozdzielacz {
                doc /* handlers.PREPARE, HANDLERS (proofread, process, ingest), CORPUS_HANDLERS (refit). */
                @OdwolanieDoKodu { sciezka = "backend/app/jobs/handlers.py"; }
            }
            part pulsDzierzawy {
                doc /* _heartbeat(): przedłuża locked_until co 1/3 dzierżawy, osobnym połączeniem. */
            }
            part sygnalZycia {
                doc /* _alive(): dotyka /tmp/worker-alive co 10 s, także w czasie długiego zadania. */
            }
            part politykaPonowien {
                doc /* PermanentJobError, compute.is_down_for, MAX_ATTEMPTS. */
                @OdwolanieDoKodu { sciezka = "backend/app/jobs/errors.py"; }
            }
        }

        // ------------------------------------------------------------ etapy po stronie API
        part def PrzyjecieZgloszenia {
            doc /*
             * POST /assignments/{id}/submit: blokada przydziału, clean_submission() (kompletność,
             * cytaty, kierunki, reguły Q4/Q6), zapis niezmiennego zgłoszenia (wyzwalacz w bazie),
             * transition(submit) -> proofreading + Job proofread.
             */
            @OdwolanieDoKodu { sciezka = "backend/app/assignments/service.py"; }
            port wejscie : ~PortZgloszenia;
            port zgloszenie : PortZgloszenia;
            port sygnal : PortSygnalu;
        }

        part def SprawdzenieAutora {
            doc /*
             * Stan proofread_check. PUT .../proofread: autor zmienia teksty i przypisania linii;
             * relink() bez modelu (ręczne przypisanie -> zrodlo = ekspert; linia bez zmian zachowuje
             * powiązanie; nowa linia - warstwy 1-2), flagi liczone od nowa, konflikt wersji ->
             * 409 proofread_conflict. Oddanie do recenzji wymaga niepustych odpowiedzi i powiązania
             * każdej linii (links_missing).
             */
            @OdwolanieDoKodu { sciezka = "backend/app/proofread/service.py"; }
            port wejscie : ~PortRewizji;
            port polecenie : ~PortSygnalu;  // autor: oddaj do recenzji
            port runda : ~PortRundy;
            port poprawki : PortRundy;
            port sygnal : PortSygnalu;      // OddajDoRecenzji, po sprawdzeniu powiązań
        }

        part def RozstrzygniecieAdministratora {
            doc /*
             * reviews.submit_decisions(): decyzja per pytanie (request_changes wymaga komentarza).
             * Choć jedno request_changes -> runda + 1, nowa runda korekty z ostatniego tekstu
             * (open_next_round), stan proofread_check. Inaczej: zatwierdzone pytanie otwarte (nie Q4)
             * -> approve_answers (processing + Job process; bramka mocy sprawdza też model osadzeń);
             * brak takich -> reject_all_answers (rejected).
             */
            @OdwolanieDoKodu { sciezka = "backend/app/reviews/service.py"; }
            port wejscie : ~PortDecyzji;
            port decyzje : PortDecyzji;
            port sygnal : PortSygnalu;
        }

        // ------------------------------------------------------------ etap: korekta (worker)
        part def FiltrSmieci {
            doc /* Usuwa ciągi bez sensu przed sprawdzaniem pisowni (inaczej "afdoafgja" stałby się słowem). */
            @OdwolanieDoKodu { sciezka = "backend/app/proofread/garbage.py"; }
            port wejscie : ~PortTekstu;
            port wyjscie : PortTekstu;
        }

        part def KorektorGramatyki {
            doc /* LanguageTool; słownictwo winiety i terminy kliniczne są chronione. Deterministyczny. */
            @OdwolanieDoKodu { sciezka = "backend/app/proofread/grammar.py"; }
            attribute jezyk : String = "en-US";
            attribute limitCzasu : DurationValue = 60 [s];
            port wejscie : ~PortTekstu;
            port wyjscie : PortTekstu;
            port languageTool : ~PortLanguageTool;
        }

        part def RedaktorLlm {
            doc /* Zamienia urywki na pełne zdania; ENHANCE_MODEL pusty = wyłączony. */
            @OdwolanieDoKodu { sciezka = "backend/app/proofread/enhance.py"; }
            attribute prompt : String = "Answer_enhance.v1";
            attribute model : String = "qwen3.5:9b";       // ENHANCE_MODEL
            attribute temperatura : Real = 0.2;
            attribute rozmiarKontekstu : Integer = 8192;
            attribute maksTokenow : Integer = 1200;
            port wejscie : ~PortTekstu;
            port wyjscie : PortTekstu;
            port ollama : ~PortOllama;
        }

        part def UkladZdan {
            doc /* layout(): jedno zdanie na linię (split_sentences z expert-knowledge-core). */
            @OdwolanieDoKodu { sciezka = "backend/app/proofread/pipeline.py"; }
            port wejscie : ~PortTekstu;
            port wynik : PortWynikuKorekty;
        }

        part def KorektaOdpowiedzi {
            doc /*
             * proofread_answer(): śmieci -> gramatyka -> redakcja LLM -> gramatyka ponownie -> układ.
             * Bez REQUIRE_COMPUTE niedostępna usługa jest pomijana i zapisana w przebiegach
             * ("unavailable"); z REQUIRE_COMPUTE błąd transportu kończy zadanie, a worker czeka
             * na komputer z modelami, zamiast oddać autorowi niesprawdzony tekst.
             */
            @OdwolanieDoKodu { sciezka = "backend/app/proofread/pipeline.py"; }
            attribute pomijaNiedostepneUslugi : Boolean;     // = not REQUIRE_COMPUTE

            port wejscie : ~PortTekstu;
            port wynik : PortWynikuKorekty;
            port ollama : ~PortOllama;
            port languageTool : ~PortLanguageTool;

            part filtrSmieci : FiltrSmieci;
            part gramatyka : KorektorGramatyki;
            part redakcja : RedaktorLlm;
            part gramatykaPonownie : KorektorGramatyki;
            part uklad : UkladZdan;

            flow of TekstOdpowiedzi from wejscie.tekst to filtrSmieci.wejscie.tekst;
            flow of TekstOdpowiedzi from filtrSmieci.wyjscie.tekst to gramatyka.wejscie.tekst;
            flow of TekstOdpowiedzi from gramatyka.wyjscie.tekst to redakcja.wejscie.tekst;
            flow of TekstOdpowiedzi from redakcja.wyjscie.tekst to gramatykaPonownie.wejscie.tekst;
            flow of TekstOdpowiedzi from gramatykaPonownie.wyjscie.tekst to uklad.wejscie.tekst;
            flow of WynikKorektyOdpowiedzi from uklad.wynik.wynik to wynik.wynik;

            connect gramatyka.languageTool to languageTool;
            connect gramatykaPonownie.languageTool to languageTool;
            connect redakcja.ollama to ollama;
        }

        part def RozbiorZgloszenia {
            doc /*
             * findings.response_from_submission + expert_highlights: teksty odpowiedzi na zadane
             * pytania i cytaty eksperta (chip -> słowa pacjenta).
             */
            @OdwolanieDoKodu { sciezka = "backend/app/knowledge/findings.py"; }
            port wejscie : ~PortZgloszenia;
            port teksty : PortTekstu;
            port podswietlenia : PortCytatow;
        }

        part def WiazanieLinii {
            doc /*
             * links.link_lines (warstwy 1-2): linia z chipem [n] -> ten cytat; inaczej cytowane
             * słowa dopasowane do podświetlenia (difflib >= 0.6, min. 2 słowa); dopasowane tylko do
             * winiety -> nowe podświetlenie niejawne i<n>. Tylko pytania otwarte poza Q4 (is_filed).
             */
            @OdwolanieDoKodu { sciezka = "backend/app/proofread/links.py"; }
            attribute minimalnePodobienstwoCytatu : Real = 0.6;    // QUOTE_RATIO
            attribute minimalnaLiczbaSlowCytatu : Integer = 2;
            port teksty : ~PortWynikuKorekty;
            port podswietlenia : ~PortCytatow;
            port linie : PortLinii;
        }

        part def KlasyfikatorZdan {
            doc /*
             * Warstwa 3 (links.classify_rest -> classifier.classify): lokalny LLM w trybie JSON
             * przypisuje linie bez powiązania do cytatów lub `case`; `prev` dziedziczy po poprzedniej
             * linii. Zachowuje najlepszą odpowiedź z prób; błędy nie cytują odpowiedzi.
             */
            @OdwolanieDoKodu { sciezka = "backend/app/knowledge/classifier.py"; }
            attribute prompt : String = "Expert_sentence_targets.v1";
            attribute model : String = "qwen3.5:9b";       // CLASSIFIER_MODEL
            attribute temperatura : Real = 0.2;
            attribute rozmiarKontekstu : Integer = 8192;
            attribute maksTokenow : Integer = 600;
            attribute liczbaProb : Integer = 3;
            port wejscie : ~PortLinii;
            port wyjscie : PortLinii;
            port ollama : ~PortOllama;
        }

        part def KontrolaUstalen {
            doc /* findings.check(): tylko flagi do pokazania autorowi; niczego nie zmienia. */
            @OdwolanieDoKodu { sciezka = "backend/app/knowledge/findings.py"; }
            port linie : ~PortLinii;
            port podswietlenia : ~PortCytatow;
            port flagi : PortFlag;
        }

        part def PrzygotowanieKorekty {
            doc /* Faza PREPARE zadania `proofread` (proofread.service.prepare): bez transakcji. */
            @OdwolanieDoKodu { sciezka = "backend/app/proofread/service.py"; }
            port zgloszenie : ~PortZgloszenia;
            port wynik : PortPrzygotowanejKorekty;
            port ollama : ~PortOllama;
            port languageTool : ~PortLanguageTool;

            part rozbior : RozbiorZgloszenia;
            part korektaOdpowiedzi : KorektaOdpowiedzi[1..*];   // jedna na zadane pytanie z odpowiedzią
            part wiazanieLinii : WiazanieLinii;
            part klasyfikator : KlasyfikatorZdan;
            part kontrolaUstalen : KontrolaUstalen;

            flow of Zgloszenie from zgloszenie.zgloszenie to rozbior.wejscie.zgloszenie;
            flow of TekstOdpowiedzi from rozbior.teksty.tekst to korektaOdpowiedzi.wejscie.tekst;
            flow of WynikKorektyOdpowiedzi from korektaOdpowiedzi.wynik.wynik to wiazanieLinii.teksty.wynik;
            flow of Cytat from rozbior.podswietlenia.podswietlenia to wiazanieLinii.podswietlenia.podswietlenia;
            flow of LiniaOdpowiedzi from wiazanieLinii.linie.linie to klasyfikator.wejscie.linie;
            flow of LiniaOdpowiedzi from klasyfikator.wyjscie.linie to kontrolaUstalen.linie.linie;
            flow of Cytat from rozbior.podswietlenia.podswietlenia to kontrolaUstalen.podswietlenia.podswietlenia;

            // składanie wyniku fazy PREPARE
            flow of WynikKorektyOdpowiedzi from korektaOdpowiedzi.wynik.wynik to wynik.korekta.pozycje;
            flow of LiniaOdpowiedzi from klasyfikator.wyjscie.linie to wynik.korekta.linie;
            flow of Cytat from rozbior.podswietlenia.podswietlenia to wynik.korekta.podswietlenia;
            flow of FlagaUstalen from kontrolaUstalen.flagi.flagi to wynik.korekta.flagi;

            connect korektaOdpowiedzi.ollama to ollama;
            connect korektaOdpowiedzi.languageTool to languageTool;
            connect klasyfikator.ollama to ollama;
        }

        part def ZapisRundy {
            doc /*
             * Faza HANDLERS (proofread.service.record), pod blokadą przydziału: usuwa rundę o tym
             * numerze (ponowienie ją zastępuje), zapisuje RundaKorekty i RewizjaOdpowiedzi z
             * final = proposed.
             */
            @OdwolanieDoKodu { sciezka = "backend/app/proofread/service.py"; }
            port wejscie : ~PortPrzygotowanejKorekty;
            port runda : PortRundy;
        }

        part def EtapKorekty {
            doc /* Zadanie `proofread`: PrzygotowanieKorekty (wolne) -> ZapisRundy (krótko, pod blokadą). */
            @OdwolanieDoKodu { sciezka = "backend/app/jobs/handlers.py"; }
            port zadanie : ~PortZadania;
            port zgloszenie : ~PortZgloszenia;
            port runda : PortRundy;
            port ollama : ~PortOllama;
            port languageTool : ~PortLanguageTool;

            part przygotowanie : PrzygotowanieKorekty;
            part zapis : ZapisRundy;

            flow of Zgloszenie from zgloszenie.zgloszenie to przygotowanie.zgloszenie.zgloszenie;
            flow of PrzygotowanaKorekta from przygotowanie.wynik.korekta to zapis.wejscie.korekta;
            flow of RundaKorekty from zapis.runda.runda to runda.runda;
            flow of RewizjaOdpowiedzi from zapis.runda.rewizje to runda.rewizje;

            connect przygotowanie.ollama to ollama;
            connect przygotowanie.languageTool to languageTool;
        }

        // ------------------------------------------------------------ etap: cięcie na jednostki (worker)
        part def WyborZatwierdzonych {
            doc /* Decyzje approve z bieżącej rundy  x  rewizje tej rundy (tekst końcowy i linie autora). */
            @OdwolanieDoKodu { sciezka = "backend/app/jobs/handlers.py"; }
            port decyzje : ~PortDecyzji;
            port runda : ~PortRundy;
            port rewizje : PortRewizji;
        }

        part def BudowaRekorduUstalen {
            doc /*
             * findings.response_from_submission + record_from_lines: rekord ustaleń z linii tak, jak je
             * powiązał autor, plus flags_shown, track, origin. Brak zgłoszenia lub rundy
             * -> NoFindings (błąd trwały).
             */
            @OdwolanieDoKodu { sciezka = "backend/app/knowledge/findings.py"; }
            port zgloszenie : ~PortZgloszenia;
            port rewizje : ~PortRewizji;
            port ustalenia : PortUstalen;
        }

        part def PodzialNaJednostki {
            doc /*
             * findings.build_units: jednostka `fragment` na każde podświetlenie ze zdaniami i jedna
             * `case`. I1 = nagłówek + treść jednostki; I3 = I1 ze słowami pacjenta. Cytaty użyte razem
             * są wzajemnym kontekstem. Brak jednostek -> NoUnits (błąd trwały).
             */
            @OdwolanieDoKodu { sciezka = "backend/app/knowledge/findings.py"; }
            port wejscie : ~PortUstalen;
            port wyjscie : PortUstalen;
        }

        part def ZapisJednostek {
            doc /*
             * Pod blokadą przydziału: AnswerFindings (rekord, klasyfikator, prompt, findings_version)
             * i KnowledgeUnit ze statusem approved oraz content_hash = sha256(I1 + "\n" + I3).
             */
            @OdwolanieDoKodu { sciezka = "backend/app/jobs/handlers.py"; }
            port wejscie : ~PortUstalen;
            port wyjscie : PortUstalen;
        }

        part def EtapCiecia {
            doc /* Zadanie `process` (handlers.process): bez modeli i bez fazy PREPARE. */
            @OdwolanieDoKodu { sciezka = "backend/app/jobs/handlers.py"; }
            attribute wymagaModelu : Boolean = false;
            port zadanie : ~PortZadania;
            port zgloszenie : ~PortZgloszenia;
            port runda : ~PortRundy;
            port decyzje : ~PortDecyzji;
            port ustalenia : PortUstalen;

            part wybor : WyborZatwierdzonych;
            part rekord : BudowaRekorduUstalen;
            part podzial : PodzialNaJednostki;
            part zapis : ZapisJednostek;

            flow of DecyzjaOOdpowiedzi from decyzje.decyzje to wybor.decyzje.decyzje;
            flow of RundaKorekty from runda.runda to wybor.runda.runda;
            flow of RewizjaOdpowiedzi from runda.rewizje to wybor.runda.rewizje;
            flow of RewizjaOdpowiedzi from wybor.rewizje.rewizje to rekord.rewizje.rewizje;
            flow of Zgloszenie from zgloszenie.zgloszenie to rekord.zgloszenie.zgloszenie;
            flow of UstaleniaOdpowiedzi from rekord.ustalenia.ustalenia to podzial.wejscie.ustalenia;
            flow of JednostkaWiedzy from podzial.wyjscie.jednostki to zapis.wejscie.jednostki;
            flow of UstaleniaOdpowiedzi from podzial.wyjscie.ustalenia to zapis.wejscie.ustalenia;
            flow of UstaleniaOdpowiedzi from zapis.wyjscie.ustalenia to ustalenia.ustalenia;
            flow of JednostkaWiedzy from zapis.wyjscie.jednostki to ustalenia.jednostki;
        }

        // ------------------------------------------------------------ etap: ingestia (worker)
        part def WczytanieDoIngestii {
            doc /*
             * ingest.load (PREPARE, bez transakcji): jednostki approved/ingested, rekord przycięty do
             * nich. Odmowy (błędy trwałe): brak jednostek -> NoUnits; jednostka bez I1/I3 -> UnitsNotEmbeddable; brak ustaleń -> NoFindings.
             */
            @OdwolanieDoKodu { sciezka = "backend/app/knowledge/ingest.py"; }
            port wejscie : ~PortUstalen;
            port pakiet : PortPakietuIngestii;
        }

        part def OsadzanieJednostek {
            doc /*
             * ingest.embed -> embedding.embed_texts (PREPARE): I1, I2, I3 w jednym wywołaniu, wektory
             * znormalizowane L2. Klient HTTP działa w wątku, więc puls dzierżawy działa dalej.
             */
            @OdwolanieDoKodu { sciezka = "backend/app/knowledge/embedding.py"; }
            attribute model : String = "bge-m3";      // config/indexing.yaml
            attribute wymiary : Integer = 1024;
            port wejscie : ~PortPakietuIngestii;
            port wyjscie : PortPakietuIngestii;
            port ollama : ~PortOllama;
        }

        part def ZapisChips {
            doc /*
             * ingest.write (HANDLERS, pod blokadą przydziału, w transakcji przejścia stanu):
             * pg_advisory_xact_lock(BM25_LOCK) - jedna ingestia naraz przelicza BM25; usuwa sesję,
             * wstawia experts, vignettes (tier `app`), elicitation_sessions, cue_keys, highlights,
             * answer_sentences, finding_units, finding_unit_sentences, unit_cues, review_events.
             * Wektory przez rzutowanie SQL (CAST(:v AS vector)). Potem jednostki -> ingested.
             */
            @OdwolanieDoKodu { sciezka = "backend/app/knowledge/ingest.py"; }
            attribute kluczBlokadyBm25 : Integer = 4715331001;
            attribute poziomWiniet : String = "app";
            port wejscie : ~PortPakietuIngestii;
            port wiersze : PortWierszyChips;
        }

        part def OdswiezenieBm25 {
            doc /*
             * refresh_sparse: BM25 (idf globalne) od nowa dla całego schematu chips - teksty I1, I3
             * jednostek i klucze wskazówek. Ta sama część obsługuje zadanie `refit` po usunięciu wiedzy.
             */
            @OdwolanieDoKodu { sciezka = "backend/app/knowledge/ingest.py"; }
            port wiersze : ~PortWierszyChips;
            port wyjscie : PortWierszyChips;
        }

        part def EtapIngestii {
            doc /* Zadanie `ingest`: wczytanie + osadzanie (PREPARE) -> zapis chips + BM25 (HANDLERS). */
            @OdwolanieDoKodu { sciezka = "backend/app/jobs/handlers.py"; }
            port zadanie : ~PortZadania;
            port ustalenia : ~PortUstalen;
            port wiersze : PortWierszyChips;
            port ollama : ~PortOllama;

            part wczytanie : WczytanieDoIngestii;
            part osadzanie : OsadzanieJednostek;
            part zapis : ZapisChips;
            part bm25 : OdswiezenieBm25;

            flow of UstaleniaOdpowiedzi from ustalenia.ustalenia to wczytanie.wejscie.ustalenia;
            flow of JednostkaWiedzy from ustalenia.jednostki to wczytanie.wejscie.jednostki;
            flow of PakietIngestii from wczytanie.pakiet.pakiet to osadzanie.wejscie.pakiet;
            flow of PakietIngestii from osadzanie.wyjscie.pakiet to zapis.wejscie.pakiet;
            flow of WierszeChips from zapis.wiersze.wiersze to bm25.wiersze.wiersze;
            flow of WierszeChips from bm25.wyjscie.wiersze to wiersze.wiersze;

            connect osadzanie.ollama to ollama;
        }

        // ------------------------------------------------------------ magazyny (Postgres)
        part def MagazynStanuPrzeplywu {
            doc /*
             * Tabele schematu `app` na ścieżce: submissions (niezmienne), proofread_rounds,
             * answer_revisions, answer_decisions, answer_findings, knowledge_units, audit_events.
             * Przez nie etapy przekazują sobie wyniki.
             */
            @OdwolanieDoKodu { sciezka = "backend/migrations/versions"; }
            port zgloszenieWe : ~PortZgloszenia;
            port zgloszenieWy : PortZgloszenia;
            port rundaWe : ~PortRundy;              // z zadania proofread i z poprawek autora
            port rundaWy : PortRundy;               // do sprawdzenia autora, widoku i cięcia
            port decyzjeWe : ~PortDecyzji;
            port decyzjeWy : PortDecyzji;
            port ustaleniaWe : ~PortUstalen;
            port ustaleniaWy : PortUstalen;
            port zdarzeniaWe : ~PortZdarzen;
        }

        part def MagazynWiedzyRag {
            doc /* Schemat `chips` (pgvector): czyta go wyszukiwanie w API i biblioteka expert-knowledge-rag. */
            @OdwolanieDoKodu { sciezka = "backend/migrations/versions/0003_pipeline.py"; }
            port wiersze : ~PortWierszyChips;
            port odczyt : PortSql;
        }
    }

    private import Komponenty::*;

    // =================================================================== 4. IBD ścieżki
    part def SciezkaPrzetwarzaniaWiniety {
        doc /*
         * IBD: części ścieżki, ich porty i przepływy artefaktów. Porty brzegowe to wejścia od
         * użytkowników przez API (autor, administrator), wyjście widoku korekty, usługi na
         * komputerze z modelami i odczyt bazy wiedzy.
         */

        // ---------------------------------------------------- porty brzegowe
        port zgloszenieAutora : ~PortZgloszenia;      // POST /assignments/{id}/submit
        port poprawkiAutora : ~PortRewizji;           // PUT  /assignments/{id}/proofread
        port oddanieDoRecenzji : ~PortSygnalu;        // POST /assignments/{id}/submit-for-review
        port decyzjeAdministratora : ~PortDecyzji;    // POST /assignments/{id}/answer-decisions
        port ponowienia : ~PortSygnalu;               // POST /assignments/{id}/retry, .../cancel (administrator)
        port widokKorekty : PortRundy;                // GET  .../proofread, recenzja
        port ollama : ~PortOllama;
        port languageTool : ~PortLanguageTool;
        port odczytWiedzy : PortSql;

        // ---------------------------------------------------- części
        part przyjecieZgloszenia : PrzyjecieZgloszenia;
        part sprawdzenieAutora : SprawdzenieAutora;
        part rozstrzygniecie : RozstrzygniecieAdministratora;
        part bramkaPrzejsc : BramkaPrzejsc;
        part bramkaMocy : BramkaMocyObliczeniowej;
        part kolejka : KolejkaZadan;
        part petla : PetlaWorkera;
        part etapKorekty : EtapKorekty;
        part etapCiecia : EtapCiecia;
        part etapIngestii : EtapIngestii;
        part magazynStanu : MagazynStanuPrzeplywu;
        part magazynWiedzy : MagazynWiedzyRag;

        // ---------------------------------------------------- delegacje portów brzegowych
        bind zgloszenieAutora = przyjecieZgloszenia.wejscie;
        bind poprawkiAutora = sprawdzenieAutora.wejscie;
        bind oddanieDoRecenzji = sprawdzenieAutora.polecenie;
        bind decyzjeAdministratora = rozstrzygniecie.wejscie;
        bind odczytWiedzy = magazynWiedzy.odczyt;
        flow of RundaKorekty from magazynStanu.rundaWy.runda to widokKorekty.runda;
        flow of RewizjaOdpowiedzi from magazynStanu.rundaWy.rewizje to widokKorekty.rewizje;

        // ---------------------------------------------------- sterowanie: sygnały -> bramka przejść
        flow of SygnalPrzeplywu from przyjecieZgloszenia.sygnal.sygnal to bramkaPrzejsc.polecenia.sygnal;
        flow of SygnalPrzeplywu from sprawdzenieAutora.sygnal.sygnal to bramkaPrzejsc.polecenia.sygnal;
        flow of SygnalPrzeplywu from rozstrzygniecie.sygnal.sygnal to bramkaPrzejsc.polecenia.sygnal;
        flow of SygnalPrzeplywu from ponowienia.sygnal to bramkaPrzejsc.polecenia.sygnal;
        flow of SygnalPrzeplywu from petla.wynik.sygnal to bramkaPrzejsc.polecenia.sygnal;

        flow of ProbaMocy from bramkaMocy.stanMocy.proba to bramkaPrzejsc.stanMocy.proba;
        flow of ProbaMocy from bramkaMocy.stanMocy.proba to petla.stanMocy.proba;
        flow of ZdarzenieAudytowe from bramkaPrzejsc.zdarzenia.zdarzenie to magazynStanu.zdarzeniaWe.zdarzenie;

        // ---------------------------------------------------- zadania: bramka -> kolejka -> worker -> etap
        flow of Zadanie from bramkaPrzejsc.zadania.zadanie to kolejka.wejscie.zadanie;
        flow of Zadanie from kolejka.wyjscie.zadanie to petla.zadania.zadanie;
        flow of Zadanie from petla.doKorekty.zadanie to etapKorekty.zadanie.zadanie;
        flow of Zadanie from petla.doCiecia.zadanie to etapCiecia.zadanie.zadanie;
        flow of Zadanie from petla.doIngestii.zadanie to etapIngestii.zadanie.zadanie;

        // ---------------------------------------------------- artefakty przez magazyn stanu
        flow of Zgloszenie from przyjecieZgloszenia.zgloszenie.zgloszenie to magazynStanu.zgloszenieWe.zgloszenie;
        flow of Zgloszenie from magazynStanu.zgloszenieWy.zgloszenie to etapKorekty.zgloszenie.zgloszenie;
        flow of RundaKorekty from etapKorekty.runda.runda to magazynStanu.rundaWe.runda;
        flow of RewizjaOdpowiedzi from etapKorekty.runda.rewizje to magazynStanu.rundaWe.rewizje;

        flow of RundaKorekty from magazynStanu.rundaWy.runda to sprawdzenieAutora.runda.runda;
        flow of RewizjaOdpowiedzi from magazynStanu.rundaWy.rewizje to sprawdzenieAutora.runda.rewizje;
        flow of RundaKorekty from sprawdzenieAutora.poprawki.runda to magazynStanu.rundaWe.runda;
        flow of RewizjaOdpowiedzi from sprawdzenieAutora.poprawki.rewizje to magazynStanu.rundaWe.rewizje;

        flow of DecyzjaOOdpowiedzi from rozstrzygniecie.decyzje.decyzje to magazynStanu.decyzjeWe.decyzje;

        flow of Zgloszenie from magazynStanu.zgloszenieWy.zgloszenie to etapCiecia.zgloszenie.zgloszenie;
        flow of RundaKorekty from magazynStanu.rundaWy.runda to etapCiecia.runda.runda;
        flow of RewizjaOdpowiedzi from magazynStanu.rundaWy.rewizje to etapCiecia.runda.rewizje;
        flow of DecyzjaOOdpowiedzi from magazynStanu.decyzjeWy.decyzje to etapCiecia.decyzje.decyzje;
        flow of UstaleniaOdpowiedzi from etapCiecia.ustalenia.ustalenia to magazynStanu.ustaleniaWe.ustalenia;
        flow of JednostkaWiedzy from etapCiecia.ustalenia.jednostki to magazynStanu.ustaleniaWe.jednostki;

        flow of UstaleniaOdpowiedzi from magazynStanu.ustaleniaWy.ustalenia to etapIngestii.ustalenia.ustalenia;
        flow of JednostkaWiedzy from magazynStanu.ustaleniaWy.jednostki to etapIngestii.ustalenia.jednostki;
        flow of WierszeChips from etapIngestii.wiersze.wiersze to magazynWiedzy.wiersze.wiersze;

        // ---------------------------------------------------- usługi na komputerze z modelami
        connect bramkaMocy.ollama to ollama;
        connect bramkaMocy.languageTool to languageTool;
        connect etapKorekty.ollama to ollama;
        connect etapKorekty.languageTool to languageTool;
        connect etapIngestii.ollama to ollama;
    }

    part sciezka : SciezkaPrzetwarzaniaWiniety;

    // =================================================================== 5. alokacja do kodu i kontenerów
    package AlokacjaSciezki {
        doc /*
         * Część logiczna ścieżki -> moduł / kontener z 04_Struktura. Bramka przejść i bramka mocy
         * działają w obu procesach (API i worker), bo oba wołają transition() i compute.
         */

        allocation def CzescSciezkiWModule {
            doc /* Część ścieżki realizowana przez moduł (kod) w kontenerze. */
        }

        // API
        allocation p01 : CzescSciezkiWModule allocate sciezka.przyjecieZgloszenia to kontekstElicytacji.system.backend.przydzialy;
        allocation p02 : CzescSciezkiWModule allocate sciezka.sprawdzenieAutora to kontekstElicytacji.system.backend.korekta;
        allocation p03 : CzescSciezkiWModule allocate sciezka.rozstrzygniecie to kontekstElicytacji.system.backend.recenzje;
        allocation p04 : CzescSciezkiWModule allocate sciezka.bramkaPrzejsc to kontekstElicytacji.system.backend.przydzialy.maszynaStanow;
        allocation p05 : CzescSciezkiWModule allocate sciezka.bramkaMocy to kontekstElicytacji.system.backend.mocObliczeniowa;

        // worker
        allocation p06 : CzescSciezkiWModule allocate sciezka.bramkaPrzejsc to kontekstElicytacji.system.worker.przydzialy.maszynaStanow;
        allocation p07 : CzescSciezkiWModule allocate sciezka.bramkaMocy to kontekstElicytacji.system.worker.mocObliczeniowa;
        allocation p08 : CzescSciezkiWModule allocate sciezka.petla to kontekstElicytacji.system.worker.zadania;
        allocation p09 : CzescSciezkiWModule allocate sciezka.etapKorekty.przygotowanie.korektaOdpowiedzi to kontekstElicytacji.system.worker.korekta.potok;
        allocation p10 : CzescSciezkiWModule allocate sciezka.etapKorekty.przygotowanie.wiazanieLinii to kontekstElicytacji.system.worker.korekta.powiazania;
        allocation p11 : CzescSciezkiWModule allocate sciezka.etapKorekty.przygotowanie.klasyfikator to kontekstElicytacji.system.worker.wiedza.klasyfikator;
        allocation p12 : CzescSciezkiWModule allocate sciezka.etapCiecia to kontekstElicytacji.system.worker.wiedza.ustalenia;
        allocation p13 : CzescSciezkiWModule allocate sciezka.etapIngestii.osadzanie to kontekstElicytacji.system.worker.wiedza.osadzenie;
        allocation p14 : CzescSciezkiWModule allocate sciezka.etapIngestii to kontekstElicytacji.system.worker.wiedza.ingestia;

        // Postgres
        allocation p15 : CzescSciezkiWModule allocate sciezka.kolejka to kontekstElicytacji.system.baza.schematApp;
        allocation p16 : CzescSciezkiWModule allocate sciezka.magazynStanu to kontekstElicytacji.system.baza.schematApp;
        allocation p17 : CzescSciezkiWModule allocate sciezka.magazynWiedzy to kontekstElicytacji.system.baza.schematChips;
    }
}
