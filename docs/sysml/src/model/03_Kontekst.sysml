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

        part def LokalnyLlm {
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
        connection zapisWiedzy connect hosting.system.wiedza to hosting.bazaWiedzy.zapis {
            doc /* Ingest jednostek, usuwanie wiedzy, przeliczanie BM25 (worker i API). */
        }
        connection odczytWiedzy connect ragKliniki.wiedza to hosting.bazaWiedzy.odczyt {
            doc /* expert-knowledge-rag: ExpertKnowledgeStore, transakcje READ ONLY. */
        }
        connect ragKliniki to dokumentyMedyczne;

        // ---------------------------------------------------- lokalne modele
        connect hosting.system.ollama to lokalnyLlm.ollama;
        connect hosting.system.languagetool to lokalnyLlm.languagetool;
        connection ragDoLlm connect ragKliniki.llm to lokalnyLlm.ollama {
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

        // ----------------------------------------------------- ekspert: sesja elicytacji
        use case def PrzeprowadzSesjeElicytacji {
            doc /*
             * Sesja elicytacji wiedzy z winietą: ekspert czyta winietę (tekst pacjenta) i odpowiada
             * naraz na wszystkie zadane pytania (Q1-Q6), cytując jej fragmenty.
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
    }
}
