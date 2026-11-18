package SledzenieElicytacji {
    doc /*
     * Śledzenie: wymaganie --satisfy--> element struktury, przypadek weryfikacji --verify--> wymaganie.
     * Przypadki weryfikacji = istniejące testy: pytest (tests/unit, tests/api, tests/integration,
     * tests/scripts, tests/test_*.py, packages/<pakiet>/tests) i vitest (frontend/src/__tests__),
     * oraz test dymny wdrożenia. Gdzie który poziom działa: PlatformaElicytacji::SrodowiskoTestowe.
     * Mapowanie test -> wymaganie wyprowadzono z nazw i treści testów; do potwierdzenia.
     */

    private import ScalarValues::*;
    private import BibliotekaElicytacji::*;
    private import StrukturaElicytacji::SystemElicytacji;
    private import KontekstElicytacji::kontekstElicytacji;
    private import PlatformaElicytacji::platformaProd;
    private import WymaganiaElicytacji::Funkcjonalne::*;
    private import WymaganiaElicytacji::Niefunkcjonalne::*;

    // =================================================================== satisfy
    package Spelnianie {
        satisfy dostepWgRol by kontekstElicytacji.system.backend.uwierzytelnianie;
        satisfy kontaTylkoZZaproszen by kontekstElicytacji.system.backend.uwierzytelnianie;
        satisfy wersjonowanieWiniet by kontekstElicytacji.system.backend.winiety;
        satisfy przydzialTylkoOpublikowanych by kontekstElicytacji.system.backend.przydzialy;
        satisfy ukrytyProjektWiniety by kontekstElicytacji.system.backend.przydzialy;
        satisfy wszystkiePytaniaWidoczne by kontekstElicytacji.system.backend.przydzialy;
        satisfy cytatyZgodneZWinieta by kontekstElicytacji.system.backend.przydzialy.walidacjaOdpowiedzi;
        satisfy kierunekCytatu by kontekstElicytacji.system.backend.przydzialy.walidacjaOdpowiedzi;
        satisfy kompletneZgloszenie by kontekstElicytacji.system.backend.przydzialy.walidacjaOdpowiedzi;
        satisfy autozapisSzkicu by kontekstElicytacji.system.backend.przydzialy;
        satisfy niezmienneZgloszenie by kontekstElicytacji.system.baza.schematApp;
        satisfy jedenPunktPrzejsc by kontekstElicytacji.system.backend.przydzialy.maszynaStanow;
        satisfy dozwoloneAkcje by kontekstElicytacji.system.backend.przydzialy;
        satisfy automatycznaKorekta by kontekstElicytacji.system.worker.korekta;
        satisfy autorSprawdzaKorekte by kontekstElicytacji.system.backend.korekta;
        satisfy otwartaRecenzja by kontekstElicytacji.system.backend.recenzje.dostep;
        satisfy administratorDecyduje by kontekstElicytacji.system.backend.recenzje;
        satisfy budowaJednostek by kontekstElicytacji.system.worker.wiedza.ustalenia;
        satisfy ingestiaJednostek by kontekstElicytacji.system.worker.wiedza.ingestia;
        satisfy ponawianieNieudanychZadan by kontekstElicytacji.system.backend.przydzialy;
        satisfy sladAudytowy by kontekstElicytacji.system.backend.audyt;
        satisfy wyszukiwanieWiedzy by kontekstElicytacji.system.backend.wiedza.wyszukiwanie;
        satisfy usuwanieWiedzy by kontekstElicytacji.system.backend.wiedza.usuwanie;
        satisfy odpowiedziRag by kontekstElicytacji.system.badania.rag;     // @Planowane w aplikacji

        satisfy modeleLokalne by kontekstElicytacji.ollama;
        satisfy budzetKontekstu by kontekstElicytacji.system.worker.wiedza.klasyfikator;
        satisfy ograniczonePonawianieZadan by kontekstElicytacji.system.worker;
        satisfy ochronaLogowania by kontekstElicytacji.system.backend.uwierzytelnianie;
        satisfy czasZyciaSesji by kontekstElicytacji.system.backend.uwierzytelnianie;
        satisfy pseudonimizacja by kontekstElicytacji.system.backend.przydzialy;
        satisfy skalowalneWorkery by kontekstElicytacji.system.backend.zadania.kolejka;
        satisfy bezpieczneMigracje by kontekstElicytacji.system.baza;
        satisfy bezpieczneMigracje by platformaProd.vm.migracja;
        satisfy tanieHostowanie by platformaProd.vm;
        satisfy gotowoscMocyPrzedZadaniem by kontekstElicytacji.system.backend.mocObliczeniowa;
        satisfy zadaniaCzekajaNaMoc by kontekstElicytacji.system.worker.mocObliczeniowa;
        satisfy kontrolaZdrowiaUslug by platformaProd.vm;
        satisfy kopieZapasoweBazy by platformaProd.vm.kopiaZapasowa;
        satisfy ograniczonaEkspozycjaSieci by platformaProd;
        // nieweryfikowane testem: budzetKontekstu, skalowalneWorkery, pseudonimizacja, kopieZapasoweBazy,
        //   ograniczonaEkspozycjaSieci, tanieHostowanie - do uzupełnienia
        // brak elementu spełniającego: usuwanieDanychRodo, dostepnosc, szybkoscDzialania,
        //   jakoscOdpowiedzi, dostepnoscInterfejsu - do uzupełnienia
    }

    // =================================================================== verification cases
    package Weryfikacja {

        enum def PoziomTestu {
            doc /* Katalog / znacznik testu. */
            enum jednostkowy;     // tests/unit, tests/test_*.py, testy pakietów bez bazy
            enum skryptow;        // tests/scripts - skrypty badawcze
            enum api;             // tests/api - FastAPI + własna baza rag_<pid>_test (znacznik integration)
            enum integracyjny;    // tests/integration, packages/*/tests/integration (znacznik integration)
            enum regresyjny;      // znacznik regression: jakość wyszukiwania na migawce silver
            enum frontendowy;     // vitest
            enum wdrozeniowy;     // test dymny po wdrożeniu
        }

        verification def PrzypadekTestowy {
            doc /* Wspólna definicja: podmiot, poziom i to, czy działa w CI (bez bazy). */
            subject system : SystemElicytacji;
            attribute poziom : PoziomTestu;
            attribute wCi : Boolean;
        }

        // ---------------------------------------------------- przepływ i stany
        verification def TestStanowPrzeplywu :> PrzypadekTestowy {
            doc /* Tablica przejść, aktorzy, allowed_actions. */
            @OdwolanieDoKodu { sciezka = "tests/test_workflow_states.py"; }
            attribute :>> poziom = PoziomTestu::jednostkowy;
            attribute :>> wCi = true;
            objective {
                verify jedenPunktPrzejsc;
                verify dozwoloneAkcje;
            }
        }

        verification def TestApiPrzeplywu :> PrzypadekTestowy {
            @OdwolanieDoKodu { sciezka = "tests/api/test_api_workflow.py"; }
            attribute :>> poziom = PoziomTestu::api;
            attribute :>> wCi = false;
            objective {
                verify jedenPunktPrzejsc;
                verify sladAudytowy;
                verify ponawianieNieudanychZadan;
                verify przydzialTylkoOpublikowanych;
            }
        }

        verification def TestApiOdpowiedzi :> PrzypadekTestowy {
            @OdwolanieDoKodu { sciezka = "tests/api/test_api_answers.py"; }
            attribute :>> poziom = PoziomTestu::api;
            attribute :>> wCi = false;
            objective {
                verify wszystkiePytaniaWidoczne;
                verify cytatyZgodneZWinieta;
                verify kierunekCytatu;
                verify kompletneZgloszenie;
                verify autozapisSzkicu;
            }
        }

        verification def TestRegulOdpowiedzi :> PrzypadekTestowy {
            doc /* Reguły treści odpowiedzi (chipy, Q4, Q6) bez bazy. */
            @OdwolanieDoKodu { sciezka = "tests/unit/test_answers_rules.py"; }
            attribute :>> poziom = PoziomTestu::jednostkowy;
            attribute :>> wCi = true;
            objective {
                verify cytatyZgodneZWinieta;
                verify kompletneZgloszenie;
            }
        }

        verification def TestApiPodstaw :> PrzypadekTestowy {
            doc /* Podstawy API i bazy, m.in. wyzwalacz niezmienności zgłoszenia. */
            @OdwolanieDoKodu { sciezka = "tests/api/test_api_foundation.py"; }
            attribute :>> poziom = PoziomTestu::api;
            attribute :>> wCi = false;
            objective {
                verify niezmienneZgloszenie;
            }
        }

        verification def TestApiSchematu :> PrzypadekTestowy {
            doc /* Co zostawia migracja 0003: tabele RAG w `chips` i tabele ścieżki przetwarzania. */
            @OdwolanieDoKodu { sciezka = "tests/api/test_api_schema.py"; }
            attribute :>> poziom = PoziomTestu::api;
            attribute :>> wCi = false;
            objective {
                verify bezpieczneMigracje;
            }
        }

        // ---------------------------------------------------- dostęp
        verification def TestApiUwierzytelniania :> PrzypadekTestowy {
            doc /* Sprawdzenie, że hashowanie hasła nie blokuje pętli zdarzeń (5 taktów). */
            @OdwolanieDoKodu { sciezka = "tests/api/test_api_auth.py"; }
            attribute :>> poziom = PoziomTestu::api;
            attribute :>> wCi = false;
            objective {
                verify dostepWgRol;
                verify kontaTylkoZZaproszen;
                verify ochronaLogowania;
                verify czasZyciaSesji;
            }
        }

        verification def TestApiLuk :> PrzypadekTestowy {
            doc /* Trasy tylko dla administratora, 404, 422, konta, odświeżanie skrótu hasła. */
            @OdwolanieDoKodu { sciezka = "tests/api/test_api_gaps.py"; }
            attribute :>> poziom = PoziomTestu::api;
            attribute :>> wCi = false;
            objective {
                verify dostepWgRol;
                verify wersjonowanieWiniet;
            }
        }

        verification def TestApiWiniet :> PrzypadekTestowy {
            @OdwolanieDoKodu { sciezka = "tests/api/test_api_vignettes.py"; }
            attribute :>> poziom = PoziomTestu::api;
            attribute :>> wCi = false;
            objective {
                verify wersjonowanieWiniet;
                verify ukrytyProjektWiniety;
            }
        }

        // ---------------------------------------------------- ścieżka przetwarzania
        verification def TestKorekty :> PrzypadekTestowy {
            doc /* Poprawki LanguageTool, śmieci przed gramatyką, układ, redakcja zachowuje chipy. */
            @OdwolanieDoKodu { sciezka = "tests/test_proofread.py"; }
            attribute :>> poziom = PoziomTestu::jednostkowy;
            attribute :>> wCi = true;
            objective {
                verify automatycznaKorekta;
            }
        }

        verification def TestPowiazanLinii :> PrzypadekTestowy {
            doc /* Warstwy powiązań linii z cytatami i cięcie powiązanych linii na jednostki. */
            @OdwolanieDoKodu { sciezka = "tests/test_links.py"; }
            attribute :>> poziom = PoziomTestu::jednostkowy;
            attribute :>> wCi = true;
            objective {
                verify automatycznaKorekta;
                verify autorSprawdzaKorekte;
                verify budowaJednostek;
            }
        }

        verification def TestKlasyfikatora :> PrzypadekTestowy {
            @OdwolanieDoKodu { sciezka = "tests/test_classifier.py"; }
            attribute :>> poziom = PoziomTestu::jednostkowy;
            attribute :>> wCi = true;
            objective {
                verify automatycznaKorekta;
            }
        }

        verification def TestApiRewizji :> PrzypadekTestowy {
            @OdwolanieDoKodu { sciezka = "tests/api/test_api_revisions.py"; }
            attribute :>> poziom = PoziomTestu::api;
            attribute :>> wCi = false;
            objective {
                verify autorSprawdzaKorekte;
            }
        }

        verification def TestApiRecenzji :> PrzypadekTestowy {
            @OdwolanieDoKodu { sciezka = "tests/api/test_api_reviews.py"; }
            attribute :>> poziom = PoziomTestu::api;
            attribute :>> wCi = false;
            objective {
                verify otwartaRecenzja;
                verify administratorDecyduje;
            }
        }

        verification def TestApiPotoku :> PrzypadekTestowy {
            doc /*
             * Cała ścieżka z atrapami modeli: korekta i powiązania, sprawdzenie autora, recenzja,
             * decyzja, cięcie, ingestia (jedna kopia przy ponowieniu, chips bez zmian po błędzie).
             */
            @OdwolanieDoKodu { sciezka = "tests/api/test_api_pipeline.py"; }
            attribute :>> poziom = PoziomTestu::api;
            attribute :>> wCi = false;
            objective {
                verify automatycznaKorekta;
                verify autorSprawdzaKorekte;
                verify otwartaRecenzja;
                verify administratorDecyduje;
                verify budowaJednostek;
                verify ingestiaJednostek;
                verify ponawianieNieudanychZadan;
            }
        }

        verification def TestApiSrebrnegoPrzeplywu :> PrzypadekTestowy {
            doc /*
             * Odpowiedzi silver przez całą platformę (seed_silver_reviews na zatwierdzonej kopii
             * fikstur): zgłoszenie, recenzja, decyzja, ingestia, wyszukiwanie, usunięcie wiedzy eksperta.
             */
            @OdwolanieDoKodu { sciezka = "tests/api/test_api_silver_workflow.py"; }
            attribute :>> poziom = PoziomTestu::api;
            attribute :>> wCi = false;
            objective {
                verify kompletneZgloszenie;
                verify ingestiaJednostek;
                verify wyszukiwanieWiedzy;
                verify usuwanieWiedzy;
            }
        }

        verification def TestUstalen :> PrzypadekTestowy {
            @OdwolanieDoKodu { sciezka = "tests/test_findings.py"; }
            attribute :>> poziom = PoziomTestu::jednostkowy;
            attribute :>> wCi = true;
            objective {
                verify budowaJednostek;
            }
        }

        verification def TestStrazyLadowaniaChips :> PrzypadekTestowy {
            doc /* Ładowarka fikstur nigdy nie pisze do schematu `chips` (bazy wiedzy aplikacji). */
            @OdwolanieDoKodu { sciezka = "tests/test_load_chips_guard.py"; }
            @DoUzupelnienia;    // wymaganie weryfikowane przez ten test
            attribute :>> poziom = PoziomTestu::jednostkowy;
            attribute :>> wCi = true;
        }

        // ---------------------------------------------------- worker i moc obliczeniowa
        verification def TestApiWorkera :> PrzypadekTestowy {
            doc /* Wolne PREPARE nie trzyma blokady przydziału; puls (dzierżawa 1,5 s w teście) chroni długie zadanie. */
            @OdwolanieDoKodu { sciezka = "tests/api/test_api_worker.py"; }
            attribute :>> poziom = PoziomTestu::api;
            attribute :>> wCi = false;
            objective {
                verify ograniczonePonawianieZadan;
            }
        }

        verification def TestTabelZadan :> PrzypadekTestowy {
            doc /* Każdy rodzaj zadania ma handler, PREPARE tylko z wolną częścią, akcje sukcesu i porażki; skrót jednostki obejmuje I1 i I3. */
            @OdwolanieDoKodu { sciezka = "tests/unit/test_jobs_unit.py"; }
            attribute :>> poziom = PoziomTestu::jednostkowy;
            attribute :>> wCi = true;
            objective {
                verify jedenPunktPrzejsc;
            }
        }

        verification def TestMocyObliczeniowej :> PrzypadekTestowy {
            doc /* compute.py bez sieci (transport atrapowy httpx): sonda, braki, gotowe rodzaje, wiek sondy. */
            @OdwolanieDoKodu { sciezka = "tests/unit/test_compute.py"; }
            attribute :>> poziom = PoziomTestu::jednostkowy;
            attribute :>> wCi = true;
            objective {
                verify gotowoscMocyPrzedZadaniem;
                verify zadaniaCzekajaNaMoc;
            }
        }

        verification def TestApiMocy :> PrzypadekTestowy {
            doc /*
             * End to end z REQUIRE_COMPUTE: zgłoszenie przy wyłączonym PC -> 503 i brak zmian; po
             * włączeniu przechodzi; PC wyłączony po zgłoszeniu -> zadanie czeka bez zużycia prób.
             */
            @OdwolanieDoKodu { sciezka = "tests/api/test_api_compute.py"; }
            attribute :>> poziom = PoziomTestu::api;
            attribute :>> wCi = false;
            objective {
                verify gotowoscMocyPrzedZadaniem;
                verify zadaniaCzekajaNaMoc;
            }
        }

        // ---------------------------------------------------- baza wiedzy i RAG
        verification def TestApiWiedzy :> PrzypadekTestowy {
            @OdwolanieDoKodu { sciezka = "tests/api/test_api_knowledge.py"; }
            attribute :>> poziom = PoziomTestu::api;
            attribute :>> wCi = false;
            objective {
                verify wyszukiwanieWiedzy;
            }
        }

        verification def TestApiUsuwaniaWiedzy :> PrzypadekTestowy {
            @OdwolanieDoKodu { sciezka = "tests/api/test_api_knowledge_removal.py"; }
            attribute :>> poziom = PoziomTestu::api;
            attribute :>> wCi = false;
            objective {
                verify usuwanieWiedzy;
            }
        }

        verification def TestApiRagEksperckiego :> PrzypadekTestowy {
            doc /* Po prawdziwej ingestii rekord jest czytelny dla expert-knowledge-rag, a retriever zwraca zatwierdzone notatki. */
            @OdwolanieDoKodu { sciezka = "tests/api/test_api_expert_rag.py"; }
            attribute :>> poziom = PoziomTestu::api;
            attribute :>> wCi = false;
            objective {
                verify ingestiaJednostek;
                verify wyszukiwanieWiedzy;
            }
        }

        verification def TestKontraktuRagEksperckiego :> PrzypadekTestowy {
            doc /* Kontrakt: rekord ustaleń budowany przez backend jest czytelny dla expert-knowledge-rag. */
            @OdwolanieDoKodu { sciezka = "tests/test_expert_rag_contract.py"; }
            attribute :>> poziom = PoziomTestu::jednostkowy;
            attribute :>> wCi = true;
            objective {
                verify budowaJednostek;
                verify odpowiedziRag;
            }
        }

        verification def TestRankingu :> PrzypadekTestowy {
            @OdwolanieDoKodu { sciezka = "packages/expert-knowledge-rag/tests/test_ranking.py"; }
            attribute :>> poziom = PoziomTestu::jednostkowy;
            attribute :>> wCi = true;
            objective {
                verify wyszukiwanieWiedzy;
            }
        }

        verification def TestSrebrnejBazy :> PrzypadekTestowy {
            doc /* Retrievery pakietu na bazie silver, w tym filtr ekspertów (ExpertFilter.experts). */
            @OdwolanieDoKodu { sciezka = "packages/expert-knowledge-rag/tests/integration/test_silver_database.py"; }
            attribute :>> poziom = PoziomTestu::integracyjny;
            attribute :>> wCi = false;
            objective {
                verify wyszukiwanieWiedzy;
            }
        }

        verification def TestZatloczonejWiniety :> PrzypadekTestowy {
            doc /*
             * Wielu ekspertów na jedną winietę (kopie `crowded` z migawki silver): co zostaje w top k
             * i jak działa obniżanie duplikatów przypadków. Nie mierzy jakości.
             */
            @OdwolanieDoKodu { sciezka = "packages/expert-knowledge-rag/tests/integration/test_crowded_vignette.py"; }
            attribute :>> poziom = PoziomTestu::integracyjny;
            attribute :>> wCi = false;
            objective {
                verify wyszukiwanieWiedzy;
            }
        }

        verification def TestRegresjiWyszukiwania :> PrzypadekTestowy {
            doc /*
             * Regresja jakości wyszukiwania na zamrożonej migawce silver (zamrożone wektory zapytań
             * bge-m3, deterministyczny BM25): żadna metryka nie spada poniżej linii bazowej o więcej niż
             * tolerancja; progi bezwzględne niezależne od linii bazowej. Wartości poniżej to progi
             * testu (kod), nie wartości wymagania WYM-N-13 - te pozostają do ustalenia.
             */
            @OdwolanieDoKodu { sciezka = "tests/integration/test_retrieval_regression.py"; }
            attribute :>> poziom = PoziomTestu::regresyjny;
            attribute :>> wCi = false;
            attribute tolerancja : Real = 0.02;
            attribute progTrafienieAt4 : Real = 0.8;     // question/hybrid/no-merge, tezy łączone
            attribute progMrr : Real = 0.5;
            attribute progNdcgAt10 : Real = 0.4;
            attribute progTrafienieAt4Pacjent : Real = 0.1;   // patient/cues
            objective {
                verify jakoscWyszukiwania;
            }
        }

        verification def UruchomienieEwaluacjiRag :> PrzypadekTestowy {
            doc /* Ewaluacja RAG (AnalizaElicytacji::EwaluacjaRag) - progi do uzupełnienia. */
            @OdwolanieDoKodu { sciezka = "scripts/rag/eval_expert_units.py"; }
            @DoUzupelnienia;
            attribute :>> poziom = PoziomTestu::regresyjny;
            attribute :>> wCi = false;
            objective {
                verify jakoscWyszukiwania;
                verify jakoscOdpowiedzi;
            }
        }

        // ---------------------------------------------------- frontend (vitest)
        verification def TestyFrontenduPrzeplywu :> PrzypadekTestowy {
            doc /* answerDraft, answerView, proofreadStep, failedActions, reviewDecisions, reviews. */
            @OdwolanieDoKodu { sciezka = "frontend/src/__tests__"; }
            attribute :>> poziom = PoziomTestu::frontendowy;
            attribute :>> wCi = true;
            objective {
                verify autozapisSzkicu;
                verify autorSprawdzaKorekte;
                verify ponawianieNieudanychZadan;
                verify administratorDecyduje;
                verify dozwoloneAkcje;
            }
        }

        verification def TestyFrontenduDostepu :> PrzypadekTestowy {
            doc /* guard, router, session, acceptInvite, experts. */
            @OdwolanieDoKodu { sciezka = "frontend/src/__tests__"; }
            attribute :>> poziom = PoziomTestu::frontendowy;
            attribute :>> wCi = true;
            objective {
                verify dostepWgRol;
                verify kontaTylkoZZaproszen;
            }
        }

        verification def TestyFrontenduWiedzy :> PrzypadekTestowy {
            doc /* knowledge.spec: lista, wyszukiwanie i usuwanie jednostek. */
            @OdwolanieDoKodu { sciezka = "frontend/src/__tests__/knowledge.spec.ts"; }
            attribute :>> poziom = PoziomTestu::frontendowy;
            attribute :>> wCi = true;
            objective {
                verify wyszukiwanieWiedzy;
                verify usuwanieWiedzy;
            }
        }

        // ---------------------------------------------------- wdrożenie
        verification def TestDymnyWdrozenia :> PrzypadekTestowy {
            doc /* deploy.sh czeka na healthy (API, worker, frontend); workflow sprawdza /api/v1/health i /. */
            @OdwolanieDoKodu { sciezka = ".github/workflows/deploy.yml"; }
            attribute :>> poziom = PoziomTestu::wdrozeniowy;
            attribute :>> wCi = true;
            objective {
                verify kontrolaZdrowiaUslug;
                verify bezpieczneMigracje;
            }
        }
    }

    // =================================================================== verification plan
    package PlanWeryfikacji {
        private import Weryfikacja::*;

        verification stanyPrzeplywu : TestStanowPrzeplywu;
        verification apiPrzeplyw : TestApiPrzeplywu;
        verification apiOdpowiedzi : TestApiOdpowiedzi;
        verification regulyOdpowiedzi : TestRegulOdpowiedzi;
        verification apiPodstawy : TestApiPodstaw;
        verification apiSchemat : TestApiSchematu;
        verification apiUwierzytelnianie : TestApiUwierzytelniania;
        verification apiLuki : TestApiLuk;
        verification apiWiniety : TestApiWiniet;
        verification korekta : TestKorekty;
        verification powiazaniaLinii : TestPowiazanLinii;
        verification klasyfikator : TestKlasyfikatora;
        verification apiRewizje : TestApiRewizji;
        verification apiRecenzje : TestApiRecenzji;
        verification apiPotok : TestApiPotoku;
        verification apiSrebrnyPrzeplyw : TestApiSrebrnegoPrzeplywu;
        verification ustalenia : TestUstalen;
        verification strazLadowaniaChips : TestStrazyLadowaniaChips;
        verification apiWorker : TestApiWorkera;
        verification tabeleZadan : TestTabelZadan;
        verification mocObliczeniowa : TestMocyObliczeniowej;
        verification apiMoc : TestApiMocy;
        verification apiWiedza : TestApiWiedzy;
        verification apiUsuwanieWiedzy : TestApiUsuwaniaWiedzy;
        verification apiRagEksperckie : TestApiRagEksperckiego;
        verification kontraktRagEksperckiego : TestKontraktuRagEksperckiego;
        verification ranking : TestRankingu;
        verification srebrnaBaza : TestSrebrnejBazy;
        verification zatloczonaWinieta : TestZatloczonejWiniety;
        verification regresjaWyszukiwania : TestRegresjiWyszukiwania;
        verification ewaluacjaRag : UruchomienieEwaluacjiRag;
        verification frontendPrzeplyw : TestyFrontenduPrzeplywu;
        verification frontendDostep : TestyFrontenduDostepu;
        verification frontendWiedza : TestyFrontenduWiedzy;
        verification dymnyWdrozenia : TestDymnyWdrozenia;
    }
}
