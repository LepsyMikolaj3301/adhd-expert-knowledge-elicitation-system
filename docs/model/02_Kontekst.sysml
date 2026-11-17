package KontekstElicytacji {
    doc /*
     * Kontekst systemu i przypadki użycia.
     *   Aktorzy            - osoby (role) i interesariusze
     *   SystemyZewnetrzne  - usługi spoza granicy systemu
     *   kontekstElicytacji - kontekst systemu (odpowiednik diagramu kontekstu / IBD kontekstu);
     *                        to jest korzeń drzewa części używany w śledzeniu (satisfy) i alokacji
     *   PrzypadkyUzycia    - przypadki użycia (podmiot: SystemElicytacji)
     */

    private import ScalarValues::*;
    private import BibliotekaElicytacji::*;
    private import InterfejsyElicytacji::Porty::*;
    private import InterfejsyElicytacji::DefinicjeInterfejsow::*;
    private import StrukturaElicytacji::SystemElicytacji;

    // =================================================================== actors & stakeholders
    package Aktorzy {
        part def Osoba {
            doc /* Osoba korzystająca z systemu przez przeglądarkę. */
        }

        part def Administrator :> Osoba {
            doc /*
             * Administrator - użytkownik aplikacji (nie programista): pisze winiety, zaprasza
             * i przydziela ekspertów, decyduje, co trafia do bazy wiedzy, ponawia nieudane zadania.
             */
            @OdwolanieDoKodu { sciezka = "backend/app/users/models.py"; }
        }

        part def Ekspert :> Osoba {
            doc /* Ekspert (psycholog/psychiatra): odpowiada na przydzielone winiety. */
            @OdwolanieDoKodu { sciezka = "backend/app/users/models.py"; }
        }

        part def Recenzent :> Ekspert {
            doc /*
             * Ekspert w roli recenzenta cudzej odpowiedzi (AktorPrzeplywu::recenzent): czyta,
             * komentuje i głosuje. Nie jest osobnym typem konta.
             */
            @OdwolanieDoKodu { sciezka = "backend/app/reviews/access.py"; }
        }

        part def InzynierWiedzy :> Osoba {
            doc /* Inżynier wiedzy (autor pracy): korpus, eksperymenty, ewaluacja RAG. */
        }

        part def OdbiorcaRag {
            doc /* Odbiorca bazy wiedzy - system AI/klinicysta zadający pytania do RAG. */
            @Planowane;
        }

        part def PodmiotDanych :> Osoba {
            doc /* Osoba, której dane dotyczą (ekspert) - interesariusz RODO. */
        }
    }

    private import Aktorzy::*;

    // =================================================================== external systems
    package SystemyZewnetrzne {
        part def UslugaOllama {
            doc /*
             * Lokalne modele: qwen3.5:9b (klasyfikator, redakcja), bge-m3 (osadzanie). Na produkcji
             * na komputerze właściciela, poza serwerem aplikacji, przez sieć Tailscale; bywa wyłączona.
             */
            @OdwolanieDoKodu { sciezka = "docker-compose.yml"; }
            port api : PortOllama;
        }

        part def UslugaLanguageTool {
            doc /* Sprawdzanie pisowni i gramatyki (en-US). Na produkcji obok Ollama, na komputerze właściciela. */
            @OdwolanieDoKodu { sciezka = "docker-compose.yml"; }
            port api : PortLanguageTool;
        }

        part def ZrodlaLiteratury {
            doc /* Źródła literatury (config/sources.yaml) pobierane do korpusu. */
            @OdwolanieDoKodu { sciezka = "config/sources.yaml"; }
        }

        part def PulaReddit {
            doc /* Pula postów (forum) jako materiał do winiet i danych syntetycznych. */
            @OdwolanieDoKodu { sciezka = "scripts/elicitation/fetch_reddit_pool.py"; }
        }
    }

    private import SystemyZewnetrzne::*;

    // =================================================================== system context
    part kontekstElicytacji {
        doc /* Kontekst: system, osoby i usługi zewnętrzne. */

        part administrator : Administrator[1..*];
        part ekspert : Ekspert[1..*];
        part inzynier : InzynierWiedzy[0..1];

        part system : SystemElicytacji;

        part ollama : UslugaOllama;
        part languageTool : UslugaLanguageTool;
        part literatura : ZrodlaLiteratury;
        part reddit : PulaReddit;

        connect administrator to system.web;
        connect ekspert to system.web;
        connect inzynier to system.badania;

        interface systemDoOllama : OllamaHttp connect
            klient ::> system.ollama to
            serwer ::> ollama.api;

        interface systemDoLanguageTool : LanguageToolHttp connect
            klient ::> system.languageTool to
            serwer ::> languageTool.api;

        connect system.badania to literatura;
        connect system.badania to reddit;
    }

    // =================================================================== use cases
    package PrzypadkyUzycia {
        doc /* Przypadki użycia. Podmiot każdego: SystemElicytacji. */

        // ----------------------------------------------------- access
        use case def Zaloguj {
            subject system : SystemElicytacji;
            actor uzytkownik : Osoba;
            objective { doc /* Zalogować się; konto blokowane po 5 nieudanych próbach. */ }
        }

        use case def PrzyjmijZaproszenie {
            subject system : SystemElicytacji;
            actor ekspert : Ekspert;
            objective { doc /* Ustawić hasło z linku zaproszenia (ważny 7 dni). */ }
        }

        // ----------------------------------------------------- admin: vignettes & experts
        use case def NapiszWiniete {
            subject system : SystemElicytacji;
            actor administrator : Administrator;
            objective { doc /* Napisać winietę (tekst pacjenta, streszczenie, "co jeśli" do Q4) jako wersję roboczą. */ }
        }

        use case def OpublikujWiniete {
            subject system : SystemElicytacji;
            actor administrator : Administrator;
            objective { doc /* Opublikować lub wycofać wersję winiety. */ }
        }

        use case def ZaprosEksperta {
            subject system : SystemElicytacji;
            actor administrator : Administrator;
            objective { doc /* Utworzyć konto eksperta i wysłać zaproszenie. */ }
        }

        use case def PrzydzielEksperta {
            subject system : SystemElicytacji;
            actor administrator : Administrator;
            objective { doc /* Przydzielić opublikowaną wersję winiety ekspertowi. */ }
        }

        use case def AnulujPrzydzial {
            subject system : SystemElicytacji;
            actor administrator : Administrator;
            objective { doc /* Anulować przydział przed zakończeniem recenzji. */ }
        }

        use case def PonowZadanie {
            subject system : SystemElicytacji;
            actor administrator : Administrator;
            objective { doc /* Ponowić nieudaną korektę, przetwarzanie lub ingestię. */ }
        }

        // ----------------------------------------------------- expert: answering
        use case def CytujFragment {
            subject system : SystemElicytacji;
            actor ekspert : Ekspert;
            objective { doc /* Zaznaczyć fragment winiety (chip [n]) i nadać mu kierunek. */ }
        }

        use case def ZapiszSzkic {
            subject system : SystemElicytacji;
            actor ekspert : Ekspert;
            objective { doc /* Autozapis szkicu z kontrolą wersji (draft_conflict). */ }
        }

        use case def ZglosOdpowiedzi {
            subject system : SystemElicytacji;
            actor ekspert : Ekspert;
            objective { doc /* Zgłosić komplet odpowiedzi; zgłoszenie jest niezmienne. */ }
        }

        use case def OdpowiedzNaWiniete {
            doc /* Wszystkie zadane pytania są widoczne od razu (bez bramki). */
            subject system : SystemElicytacji;
            actor ekspert : Ekspert;
            objective { doc /* Odpowiedzieć na zadane pytania Q1-Q6 z cytatami z winiety. */ }
            include use case cytujFragment : CytujFragment;
            include use case zapiszSzkic : ZapiszSzkic;
            include use case zglosOdpowiedzi : ZglosOdpowiedzi;
        }

        use case def SprawdzKorekte {
            subject system : SystemElicytacji;
            actor ekspert : Ekspert;
            objective { doc /* Sprawdzić poprawki korekty i powiązania zdań z cytatami; poprawić je. */ }
        }

        use case def OddajDoRecenzji {
            subject system : SystemElicytacji;
            actor ekspert : Ekspert;
            objective { doc /* Oddać sprawdzone odpowiedzi do recenzji koleżeńskiej. */ }
        }

        // ----------------------------------------------------- peer review
        use case def SkomentujOdpowiedz {
            subject system : SystemElicytacji;
            actor recenzent : Recenzent;
            objective { doc /* Skomentować odpowiedź (wsparcie / zastrzeżenie / pytanie). */ }
        }

        use case def ZaglosujNaOdpowiedz {
            subject system : SystemElicytacji;
            actor recenzent : Recenzent;
            objective { doc /* Zagłosować za / przeciw odpowiedzi na pytanie. */ }
        }

        use case def RecenzujOdpowiedzi {
            doc /* Otwarcie recenzji jest jawne i wyklucza recenzenta z przydziału tej winiety. */
            subject system : SystemElicytacji;
            actor recenzent : Recenzent;
            objective { doc /* Przeczytać i przedyskutować odpowiedzi kolegi. */ }
            include use case skomentujOdpowiedz : SkomentujOdpowiedz;
            include use case zaglosujNaOdpowiedz : ZaglosujNaOdpowiedz;
        }

        use case def RozstrzygnijOdpowiedzi {
            subject system : SystemElicytacji;
            actor administrator : Administrator;
            objective { doc /* Zatwierdzić, odrzucić lub odesłać do poprawy odpowiedzi (per pytanie). */ }
        }

        // ----------------------------------------------------- knowledge base
        use case def WyszukajWiedze {
            subject system : SystemElicytacji;
            actor administrator : Administrator;
            objective { doc /* Wyszukać jednostki wiedzy (tryb: pytanie / tekst pacjenta). */ }
        }

        use case def UsunWiedze {
            subject system : SystemElicytacji;
            actor administrator : Administrator;
            objective { doc /* Usunąć jednostkę lub całą wiedzę eksperta; przelicza BM25 (refit). */ }
        }

        use case def PrzeliczIndeks {
            subject system : SystemElicytacji;
            actor administrator : Administrator;
            objective { doc /* Przeliczyć rzadki indeks BM25 dla całego korpusu jednostek. */ }
        }

        use case def ZapytajBazeWiedzy {
            subject system : SystemElicytacji;
            actor odbiorca : OdbiorcaRag;
            objective { doc /* Odpowiedź generowana na podstawie jednostek wiedzy (RAG). */ }
            @Planowane;
        }

        // ----------------------------------------------------- research (knowledge engineer)
        use case def ZbudujKorpusLiteratury {
            subject system : SystemElicytacji;
            actor inzynier : InzynierWiedzy;
            objective { doc /* Pobrać, sparsować, pociąć i zindeksować literaturę. */ }
        }

        use case def OcenRag {
            subject system : SystemElicytacji;
            actor inzynier : InzynierWiedzy;
            objective { doc /* Zmierzyć jakość wyszukiwania i odpowiedzi (sędziowie LLM). */ }
        }

        use case def WdrozWydanie {
            doc /* Workflow Deploy (ręczny): CI, obrazy w ghcr.io, deploy.sh na VM, test dymny. */
            subject system : SystemElicytacji;
            actor inzynier : InzynierWiedzy;
            objective { doc /* Wdrożyć nową wersję bez utraty danych; migracje przed restartem. */ }
        }

        // ----------------------------------------------------- system (background jobs)
        use case def KorygujOdpowiedzi {
            doc /* Zadanie `proofread` - aktor: system. */
            subject system : SystemElicytacji;
            objective { doc /* Poprawić pisownię, zredagować odpowiedzi, powiązać zdania z cytatami. */ }
        }

        use case def ZbudujJednostki {
            doc /* Zadanie `process`. */
            subject system : SystemElicytacji;
            objective { doc /* Pociąć zatwierdzone odpowiedzi na jednostki wiedzy. */ }
        }

        use case def IngestujJednostki {
            doc /* Zadanie `ingest`. */
            subject system : SystemElicytacji;
            objective { doc /* Osadzić jednostki i zapisać je w schemacie chips. */ }
        }
    }
}
