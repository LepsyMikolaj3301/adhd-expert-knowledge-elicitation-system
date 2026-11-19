package KontekstElicytacji {
    doc /*
     * Kontekst systemu i przypadki użycia.
     *   SystemyZewnetrzne - wszystko poza granicą systemu elicytacji (RAG kliniki, baza wiedzy,
     *                       lokalne modele, hosting)
     *   kontekstKliniki   - diagram kontekstu: klinika, która ma własny RAG po dokumentach
     *                       medycznych, a system elicytacji go dopełnia wiedzą ekspercką;
     *                       korzeń drzewa części dla `satisfy` i torów procesu (`perform`)
     *   PrzypadkiUzycia   - przypadki użycia systemu elicytacji (bez korzystania z wiedzy,
     *                       które należy do RAG kliniki)
     *   RealizacjaWymagan - przypadek użycia -> wymaganie (#refinement)
     */

    private import BibliotekaElicytacji::*;
    private import InteresariuszeElicytacji::Interesariusze::*;
    private import StrukturaElicytacji::SystemElicytacji;
    private import StrukturaElicytacji::Ports::*;
    private import ProcesElicytacji::procesBiznesowy;

    // =================================================================== external systems
    package SystemyZewnetrzne {
        part def BazaWiedzyEksperckiej {
            doc /*
             * Baza wiedzy: schemat `chips` w PostgreSQL z pgvector (jednostki wiedzy, cytaty, zdania,
             * wektory bge-m3 i BM25). Zapisuje do niej tylko system elicytacji (ingest, usuwanie);
             * RAG kliniki tylko czyta. Fizycznie ta sama instancja PostgreSQL co schemat `app`
             * systemu, ale to osobny, publiczny kontrakt danych.
             */
            @OdwolanieDoKodu { sciezka = "backend/migrations/versions/0003_pipeline.py"; }
            port zapis : SqlPort;
            port odczyt : SqlPort;
        }

        part def RagKliniki {
            doc /*
             * Samodzielny system kliniki, poza granicą systemu elicytacji: RAG po dokumentach
             * medycznych kliniki. Może dołączyć bibliotekę expert-knowledge-rag (retrievery
             * ExpertQuestionRetriever, PatientTextRetriever) i czytać bazę wiedzy, tylko do odczytu.
             */
            @Propozycja;
            @OdwolanieDoKodu { sciezka = "packages/expert-knowledge-rag"; }
            port wiedza : ~SqlPort;
            port llm : ~OllamaPort;
        }

        part def DokumentyMedyczne {
            doc /* Dokumenty medyczne kliniki (wytyczne, procedury, dokumentacja), zindeksowane przez RAG kliniki. */
        }

        part def LokalnyLlm :> Aktor {
            doc /*
             * Lokalne modele na komputerze właściciela z GPU, osiągalne z serwera tylko przez sieć
             * Tailscale; bywa wyłączony (wtedy działa bramka mocy, Compute). Ollama: qwen3.5:9b
             * (klasyfikator, redakcja), bge-m3 (osadzanie). LanguageTool: pisownia i gramatyka (en-US).
             */
            @OdwolanieDoKodu { sciezka = "docker-compose.yml"; }
            port ollama : OllamaPort;
            port languagetool : LanguageToolPort;
        }

        part def Hosting {
            doc /*
             * Maszyna wirtualna Azure (Standard_B2s, 4 GB, Ubuntu), docker compose: Caddy (TLS)
             * -> nginx (frontend) -> API, worker, PostgreSQL; obrazy z ghcr.io. Z internetu tylko
             * porty 80 i 443; SSH i wdrożenie przez Tailscale; codzienna kopia bazy. Szczegóły
             * wdrożenia są poza modelem (docs/azure-setup-guide.md).
             */
            @OdwolanieDoKodu { sciezka = "infra/azure/docker-compose.yml"; }
        }
    }

    private import SystemyZewnetrzne::*;

    // =================================================================== system context
    part kontekstKliniki {
        doc /*
         * Kontekst: samodzielna klinika z własnym RAG po dokumentach medycznych. System elicytacji
         * zbiera wiedzę od ekspertów i zapisuje ją do bazy wiedzy; RAG kliniki czyta ją obok
         * dokumentów medycznych. Granica systemu = hosting.system.
         * Części osób wykonują kroki procesu biznesowego (`perform` = tory diagramu czynności).
         */

        part pacjent : Pacjent {
            perform procesBiznesowy.zebranieWypowiedziPacjenta;
        }
        part inzynierWiedzy : InzynierWiedzy {
            perform procesBiznesowy.zebranieWypowiedziPacjenta;
            perform procesBiznesowy.elicytacja.przygotujWiniete;
            perform procesBiznesowy.elicytacja.przydzielEksperta;
            perform procesBiznesowy.elicytacja.rozstrzygnij;
        }
        part ekspert : Ekspert[1..*] {
            perform procesBiznesowy.elicytacja.odpowiedzNaWiniete;
            perform procesBiznesowy.elicytacja.zglosOdpowiedzi;
            perform procesBiznesowy.elicytacja.sprawdzKorekte;
            perform procesBiznesowy.elicytacja.oddajDoRecenzji;
        }
        part recenzent : Recenzent[0..*] {
            doc /* Inny ekspert w roli recenzenta tej samej sesji. */
            perform procesBiznesowy.elicytacja.recenzja;
        }
        part klinicysta : Klinicysta[1..*] {
            perform procesBiznesowy.wykorzystanieWKlinice.zadajPytanie;
            perform procesBiznesowy.wykorzystanieWKlinice.przeczytajOdpowiedz;
        }

        part hosting : Hosting {
            part system : SystemElicytacji {
                perform procesBiznesowy.elicytacja.korektaAutomatyczna;
                perform procesBiznesowy.elicytacja.zbudujJednostki;
                perform procesBiznesowy.elicytacja.wgrajDoBazyWiedzy;
            }
            part bazaWiedzy : BazaWiedzyEksperckiej;
        }

        part ragKliniki : RagKliniki {
            perform procesBiznesowy.wykorzystanieWKlinice.szukajWDokumentachMedycznych;
            perform procesBiznesowy.wykorzystanieWKlinice.szukajWBazieWiedzy;
            perform procesBiznesowy.wykorzystanieWKlinice.wygenerujOdpowiedz;
        }
        part dokumentyMedyczne : DokumentyMedyczne;
        part lokalnyLlm : LokalnyLlm;

        // ---------------------------------------------------- osoby
        connection wypowiedziPacjenta connect pacjent to inzynierWiedzy {
            doc /* Pośrednio: wypowiedzi pacjenta stają się tekstem winiety (poza systemem). */
        }
        connect inzynierWiedzy to hosting.system.web;
        connect ekspert to hosting.system.web;
        connect recenzent to hosting.system.web;
        connect klinicysta to ragKliniki;

        // ---------------------------------------------------- baza wiedzy: zapis tylko z systemu, odczyt z RAG kliniki
        flow zapisWiedzy of SqlStatement from hosting.system.wiedza.statement to hosting.bazaWiedzy.zapis.statement {
            doc /* Ingest jednostek, usuwanie wiedzy, przeliczanie BM25 (worker i API). */
        }
        flow odczytWiedzy of SqlStatement from ragKliniki.wiedza.statement to hosting.bazaWiedzy.odczyt.statement {
            doc /*
             * RAG kliniki pyta bazę wiedzy przez expert-knowledge-rag (ExpertKnowledgeStore),
             * w transakcjach READ ONLY; jednostki wiedzy (SqlRows) wracają tą samą drogą.
             */
        }
        connect ragKliniki to dokumentyMedyczne;

        // ---------------------------------------------------- lokalne modele
        flow of ModelRequest from hosting.system.ollama.request to lokalnyLlm.ollama.request;
        flow of ModelRequest from hosting.system.languagetool.request to lokalnyLlm.languagetool.request;
        flow ragDoLlm of ModelRequest from ragKliniki.llm.request to lokalnyLlm.ollama.request {
            doc /* RAG kliniki może generować odpowiedzi tym samym lokalnym modelem albo własnym. */
            @Propozycja;
        }
    }

    // =================================================================== use cases
    package PrzypadkiUzycia {
        doc /*
         * Przypadki użycia systemu elicytacji (podmiot: SystemElicytacji). Korzystanie z wiedzy
         * (pytania klinicysty) należy do RAG kliniki i nie jest przypadkiem użycia tego systemu.
         * LokalnyLlm jest aktorem drugorzędnym przypadków wykonywanych przez zadania w tle.
         */

        // ----------------------------------------------------- konto
        use case def PrzyjmijZaproszenie {
            doc /* POST /auth/accept-invite: link z zaproszenia (ważny 7 dni) jest jednorazowy. */
            subject system : SystemElicytacji;
            actor ekspert : Ekspert;
            objective { doc /* Założyć konto z zaproszenia inżyniera wiedzy i ustawić hasło. */ }
        }

        use case def ZalogujSie {
            doc /*
             * Wykonuje ekspert albo inżynier wiedzy. POST /auth/login, /auth/logout; po 5 nieudanych
             * próbach blokada na 15 min, sesja ważna 12 h.
             */
            subject system : SystemElicytacji;
            actor ekspert : Ekspert[0..1];
            actor inzynierWiedzy : InzynierWiedzy[0..1];
            objective { doc /* Zalogować się i pracować w swojej roli (admin albo expert). */ }
        }

        // ----------------------------------------------------- ekspert: odpowiedzi w sesji elicytacji
        use case def OdpowiedzNaWiniete {
            doc /*
             * Część sesji elicytacji (przydziału) wykonywana przez eksperta: czyta winietę (tekst
             * pacjenta) i odpowiada naraz na wszystkie zadane pytania (Q1-Q6), cytując jej fragmenty.
             * Stany: assigned -> in_progress (start) -> proofreading (submit).
             */
            subject system : SystemElicytacji;
            actor ekspert : Ekspert;
            objective { doc /* Zgłosić komplet odpowiedzi z cytatami z winiety. */ }
            include use case cytujFragmenty : CytujFragmenty;
            include use case zapiszSzkic : ZapiszSzkic;
            include use case zglosOdpowiedzi : ZglosOdpowiedzi;
        }

        use case def CytujFragmenty {
            subject system : SystemElicytacji;
            actor ekspert : Ekspert;
            objective { doc /* Zaznaczyć fragment winiety (chip [n]) i nadać mu kierunek. */ }
        }

        use case def ZapiszSzkic {
            subject system : SystemElicytacji;
            actor ekspert : Ekspert;
            objective { doc /* Autozapis szkicu z kontrolą wersji (409 draft_conflict). */ }
        }

        use case def ZglosOdpowiedzi {
            subject system : SystemElicytacji;
            actor ekspert : Ekspert;
            objective { doc /* Zgłosić komplet odpowiedzi; zgłoszenie (Submission) jest niezmienne. */ }
            include use case korektaAutomatyczna : KorektaAutomatyczna;
        }

        use case def KorektaAutomatyczna {
            doc /* Zadanie proofread w workerze: proofreading -> proofread_check. */
            subject system : SystemElicytacji;
            actor llm : SystemyZewnetrzne::LokalnyLlm;
            objective { doc /* Poprawić pisownię, zredagować odpowiedzi, powiązać zdania z cytatami. */ }
        }

        use case def SprawdzKorekte {
            doc /* Stan proofread_check; kończy się submit_for_review (-> peer_review). */
            subject system : SystemElicytacji;
            actor ekspert : Ekspert;
            objective { doc /* Sprawdzić i poprawić teksty po korekcie i powiązania zdań z cytatami, oddać do recenzji. */ }
        }

        // ----------------------------------------------------- recenzent
        use case def RecenzujOdpowiedzi {
            doc /* Otwarcie recenzji jest jawne i wyklucza recenzenta z przydziału tej winiety. */
            subject system : SystemElicytacji;
            actor recenzent : Recenzent;
            objective { doc /* Przeczytać i przedyskutować odpowiedzi kolegi. */ }
            include use case skomentujOdpowiedz : SkomentujOdpowiedz;
            include use case zaglosujNaOdpowiedz : ZaglosujNaOdpowiedz;
        }

        use case def SkomentujOdpowiedz {
            subject system : SystemElicytacji;
            actor recenzent : Recenzent;
            objective { doc /* Skomentować odpowiedź (support / challenge / question). */ }
        }

        use case def ZaglosujNaOdpowiedz {
            subject system : SystemElicytacji;
            actor recenzent : Recenzent;
            objective { doc /* Zagłosować za albo przeciw odpowiedzi na pytanie (approve / disapprove). */ }
        }

        // ----------------------------------------------------- inżynier wiedzy
        use case def PrzygotujWiniete {
            subject system : SystemElicytacji;
            actor inzynierWiedzy : InzynierWiedzy;
            objective { doc /* Napisać winietę (tekst pacjenta, streszczenie, pytania), opublikować albo wycofać wersję. */ }
        }

        use case def ZaprosIPrzydzielEksperta {
            subject system : SystemElicytacji;
            actor inzynierWiedzy : InzynierWiedzy;
            objective { doc /* Zaprosić eksperta (link ważny 7 dni), przydzielić mu opublikowaną wersję winiety, w razie potrzeby anulować przydział. */ }
        }

        use case def RozstrzygnijRecenzje {
            doc /* answer-decisions: approve -> processing, request_changes -> proofread_check (nowa runda), reject -> rejected. */
            subject system : SystemElicytacji;
            actor inzynierWiedzy : InzynierWiedzy;
            objective { doc /* Zdecydować o każdej odpowiedzi: zatwierdzić, odesłać do poprawy albo odrzucić. */ }
            include use case zasilenieBazyWiedzy : ZasilenieBazyWiedzy;
        }

        use case def ZasilenieBazyWiedzy {
            doc /* Zadania process i ingest w workerze: processing -> ingesting -> ingested. */
            subject system : SystemElicytacji;
            actor llm : SystemyZewnetrzne::LokalnyLlm;
            objective { doc /* Pociąć zatwierdzone odpowiedzi na jednostki wiedzy, osadzić je (bge-m3) i zapisać w bazie wiedzy. */ }
        }

        use case def PonowNieudaneZadanie {
            subject system : SystemElicytacji;
            actor inzynierWiedzy : InzynierWiedzy;
            objective { doc /* Ponowić nieudaną korektę, przetwarzanie lub ingestię (retry). */ }
        }

        use case def ZarzadzajBazaWiedzy {
            subject system : SystemElicytacji;
            actor inzynierWiedzy : InzynierWiedzy;
            objective { doc /* Przejrzeć i przeszukać jednostki wiedzy, usunąć jednostkę albo całą wiedzę eksperta, przeliczyć BM25. */ }
        }

        use case def UsunDaneEksperta {
            doc /* WYM-N-10, jeszcze niezaimplementowane. Szerzej niż ZarzadzajBazaWiedzy: także zgłoszenia i konto. */
            @Planowane;
            subject system : SystemElicytacji;
            actor inzynierWiedzy : InzynierWiedzy;
            objective { doc /* Na żądanie eksperta (RODO) usunąć jedną jednostkę albo całe zgłoszenie lub eksperta z odpowiedziami. */ }
        }
    }

    // =================================================================== use cases -> requirements
    package RealizacjaWymagan {
        doc /*
         * Który przypadek użycia doprecyzowuje które wymaganie (#refinement: przypadek użycia
         * jest dokładniejszym opisem wymagania, jak «refine» w SysML 1.x). Wymagania przekrojowe
         * (WYM-F-12, WYM-F-13, WYM-F-22 i większość niefunkcjonalnych) nie mają tu powiązań:
         * spełniają je elementy struktury (02_Wymagania::Spelnianie).
         */
        private import ModelingMetadata::*;
        private import PrzypadkiUzycia::*;
        private import WymaganiaElicytacji::Funkcjonalne::*;
        private import WymaganiaElicytacji::Niefunkcjonalne::*;

        // konto
        #refinement dependency PrzyjmijZaproszenie to kontaTylkoZZaproszen;
        #refinement dependency ZalogujSie to dostepWgRol;
        #refinement dependency ZalogujSie to ochronaLogowania;
        #refinement dependency ZalogujSie to czasZyciaSesji;

        // ekspert
        #refinement dependency OdpowiedzNaWiniete to wszystkiePytaniaWidoczne;
        #refinement dependency OdpowiedzNaWiniete to ukrytyProjektWiniety;
        #refinement dependency CytujFragmenty to cytatyZgodneZWinieta;
        #refinement dependency CytujFragmenty to kierunekCytatu;
        #refinement dependency ZapiszSzkic to autozapisSzkicu;
        #refinement dependency ZglosOdpowiedzi to kompletneZgloszenie;
        #refinement dependency ZglosOdpowiedzi to niezmienneZgloszenie;
        #refinement dependency ZglosOdpowiedzi to pseudonimizacja;
        #refinement dependency KorektaAutomatyczna to automatycznaKorekta;
        #refinement dependency KorektaAutomatyczna to budzetKontekstu;
        #refinement dependency KorektaAutomatyczna to zadaniaCzekajaNaMoc;
        #refinement dependency SprawdzKorekte to autorSprawdzaKorekte;

        // recenzent
        #refinement dependency RecenzujOdpowiedzi to otwartaRecenzja;
        #refinement dependency SkomentujOdpowiedz to administratorDecyduje;
        #refinement dependency ZaglosujNaOdpowiedz to administratorDecyduje;

        // inżynier wiedzy
        #refinement dependency PrzygotujWiniete to wersjonowanieWiniet;
        #refinement dependency PrzygotujWiniete to anonimowaWinieta;
        #refinement dependency ZaprosIPrzydzielEksperta to kontaTylkoZZaproszen;
        #refinement dependency ZaprosIPrzydzielEksperta to przydzialTylkoOpublikowanych;
        #refinement dependency RozstrzygnijRecenzje to administratorDecyduje;
        #refinement dependency RozstrzygnijRecenzje to gotowoscMocyPrzedZadaniem;
        #refinement dependency ZasilenieBazyWiedzy to budowaJednostek;
        #refinement dependency ZasilenieBazyWiedzy to ingestiaJednostek;
        #refinement dependency PonowNieudaneZadanie to ponawianieNieudanychZadan;
        #refinement dependency ZarzadzajBazaWiedzy to wyszukiwanieWiedzy;
        #refinement dependency ZarzadzajBazaWiedzy to usuwanieWiedzy;
        #refinement dependency UsunDaneEksperta to usuwanieDanychRodo;
    }
}
