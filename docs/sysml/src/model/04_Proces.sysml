package ProcesElicytacji {
    doc /*
     * Proces biznesowy (diagram czynności, Action Flow View): od wypowiedzi pacjenta, przez sesję
     * elicytacji, korektę, recenzję i decyzję, po bazę wiedzy, z której korzysta osobny RAG kliniki.
     *
     *   zebranieWypowiedziPacjenta - przed systemem (pacjent, inżynier wiedzy)
     *   elicytacja                 - SYSTEM ELICYTACJI (ten model)
     *   wykorzystanieWKlinice      - POZA SYSTEMEM: RAG kliniki (@Propozycja)
     *
     * Część kliniczna nie jest następnikiem elicytacji: łączy je tylko przepływ jednostek wiedzy
     * przez bazę wiedzy, a klinika czyta ją niezależnie od konkretnej sesji elicytacji.
     * Sesja elicytacji = jeden przydział (Assignment); w bazie wiedzy session_id = id przydziału.
     * Tory (kto wykonuje krok) są w KontekstElicytacji::kontekstKliniki (`perform`); wykonawca
     * jest też w pierwszym zdaniu `doc` każdego kroku.
     * Ścieżki błędów (processing_failed, ingestion_failed, retry, cancel) pokazuje maszyna stanów
     * przydziału (07_Stany), nie ten diagram.
     */

    private import BibliotekaElicytacji::*;
    private import StrukturaElicytacji::Data::KnowledgeUnit;
    // Krótka nazwa, żeby warunki przy `decide` mieściły się na diagramie.
    alias Akcja for StanyElicytacji::Action;

    item def WypowiedzPacjenta {
        doc /* Wypowiedź pacjenta (np. z wywiadu); materiał tekstu winiety po usunięciu danych identyfikujących. */
    }

    action def ProcesBiznesowy {

        // ---------------------------------------------------- przed systemem
        action zebranieWypowiedziPacjenta {
            doc /* Wykonawcy: pacjent i inżynier wiedzy. Poza systemem: wypowiedzi pacjenta, z których powstanie winieta. */
            out item wypowiedzi : WypowiedzPacjenta[1..*];
        }

        // ---------------------------------------------------- system elicytacji
        action elicytacja {
            doc /*
             * SYSTEM ELICYTACJI: przygotowanie winiety, a potem jedna sesja elicytacji (jeden
             * przydział, od przydzielEksperta do wgrajDoBazyWiedzy), kończona jednostkami w bazie wiedzy.
             */
            in item wypowiedzi : WypowiedzPacjenta[1..*];
            out item jednostki : KnowledgeUnit[0..*];

            action przygotujWiniete {
                doc /*
                 * Wykonawca: inżynier wiedzy. Winieta (tekst pacjenta, streszczenie, pytania Q1-Q6)
                 * jako wersja robocza, potem publish (VignetteVersion: draft -> published).
                 */
                in item wypowiedzi : WypowiedzPacjenta[1..*];
            }
            action przydzielEksperta {
                doc /* Wykonawca: inżynier wiedzy. POST /vignette-versions/{id}/assignments: Assignment w stanie assigned. */
            }
            action odpowiedzNaWiniete {
                doc /*
                 * Wykonawca: ekspert. start (assigned -> in_progress); cytaty i odpowiedzi na wszystkie
                 * pytania naraz; autozapis szkicu (PUT .../draft).
                 */
            }
            action zglosOdpowiedzi {
                doc /* Wykonawca: ekspert. submit: walidacja (clean_submission), niezmienne Submission; in_progress -> proofreading. */
            }
            action korektaAutomatyczna {
                doc /*
                 * Wykonawca: system (worker, zadanie proofread). LanguageTool, redakcja LLM, wiązanie
                 * zdań z cytatami; ProofreadRound + AnswerRevision; proofreading -> proofread_check.
                 */
            }
            action sprawdzKorekte {
                doc /* Wykonawca: ekspert. Stan proofread_check: autor sprawdza i poprawia teksty i powiązania (PUT .../proofread). */
            }
            action oddajDoRecenzji {
                doc /* Wykonawca: ekspert. submit_for_review: proofread_check -> peer_review. */
            }
            action recenzja {
                doc /* Wykonawcy: recenzenci (inni eksperci). review/open, komentarze i głosy do każdej odpowiedzi. */
            }
            action rozstrzygnij {
                doc /*
                 * Wykonawca: inżynier wiedzy. answer-decisions, per pytanie approve / request_changes /
                 * reject. Wynik dla przydziału: approve_answers, request_changes albo reject_all_answers.
                 */
                out wynik : Akcja;
            }
            action zbudujJednostki {
                doc /* Wykonawca: system (worker, zadanie process). Zatwierdzone odpowiedzi -> AnswerFindings + KnowledgeUnit; processing -> ingesting. */
                out item jednostki : KnowledgeUnit[1..*];
            }
            action wgrajDoBazyWiedzy {
                doc /*
                 * Wykonawca: system (worker, zadanie ingest). Osadzenie bge-m3, zapis do bazy wiedzy
                 * (chips), przeliczenie BM25; ingesting -> ingested.
                 */
                in item jednostki : KnowledgeUnit[1..*];
                out item zapisane : KnowledgeUnit[1..*];
            }

            // Jawne pary `first a then b`: samo `then b;` po odwołaniu (nie deklaracji) zaczyna
            // się od ostatnio zadeklarowanego węzła (tu `start`), a nie od poprzedniego kroku.
            first start then przygotujWiniete;
            first przygotujWiniete then przydzielEksperta;
            first przydzielEksperta then odpowiedzNaWiniete;
            first odpowiedzNaWiniete then zglosOdpowiedzi;
            first zglosOdpowiedzi then korektaAutomatyczna;
            first korektaAutomatyczna then poPoprawkach;
            merge poPoprawkach;
            first poPoprawkach then sprawdzKorekte;
            first sprawdzKorekte then oddajDoRecenzji;
            first oddajDoRecenzji then recenzja;
            first recenzja then rozstrzygnij;
            first rozstrzygnij then wgDecyzji;
            decide wgDecyzji;
                if rozstrzygnij.wynik == Akcja::approve_answers then zbudujJednostki;
                if rozstrzygnij.wynik == Akcja::request_changes then poPoprawkach;
                else done;

            first zbudujJednostki then wgrajDoBazyWiedzy;
            first wgrajDoBazyWiedzy then done;

            flow from wypowiedzi to przygotujWiniete.wypowiedzi;
            flow from zbudujJednostki.jednostki to wgrajDoBazyWiedzy.jednostki;
            flow from wgrajDoBazyWiedzy.zapisane to jednostki;
        }

        // ---------------------------------------------------- poza systemem: RAG kliniki
        action wykorzystanieWKlinice {
            doc /* POZA SYSTEMEM ELICYTACJI: RAG kliniki odpowiada klinicyście z dokumentów medycznych i z bazy wiedzy. */
            @Propozycja;
            in item wiedza : KnowledgeUnit[0..*];

            action zadajPytanie {
                doc /* Wykonawca: klinicysta. Pytanie kliniczne albo tekst pacjenta. */
            }
            action szukajWDokumentachMedycznych {
                doc /* Wykonawca: RAG kliniki. Własny indeks dokumentów medycznych kliniki. */
            }
            action szukajWBazieWiedzy {
                doc /*
                 * Wykonawca: RAG kliniki, przez expert-knowledge-rag (ExpertQuestionRetriever albo
                 * PatientTextRetriever); tylko odczyt bazy wiedzy.
                 */
                in item wiedza : KnowledgeUnit[0..*];
            }
            action wygenerujOdpowiedz {
                doc /* Wykonawca: RAG kliniki (LLM). Odpowiedź z fragmentów dokumentów i notatek eksperckich. */
            }
            action przeczytajOdpowiedz {
                doc /* Wykonawca: klinicysta. */
            }

            first start then zadajPytanie;
            first zadajPytanie then rozwidlenie;
            fork rozwidlenie;
                then szukajWDokumentachMedycznych;
                then szukajWBazieWiedzy;
            first szukajWDokumentachMedycznych then polaczenie;
            first szukajWBazieWiedzy then polaczenie;
            join polaczenie;
            first polaczenie then wygenerujOdpowiedz;
            first wygenerujOdpowiedz then przeczytajOdpowiedz;
            first przeczytajOdpowiedz then done;

//            flow from wiedza to szukajWBazieWiedzy.wiedza;
        }

        first start then zebranieWypowiedziPacjenta;
        first zebranieWypowiedziPacjenta then elicytacja;

        flow from zebranieWypowiedziPacjenta.wypowiedzi to elicytacja.wypowiedzi;
        flow from elicytacja.jednostki to wykorzystanieWKlinice.wiedza;
    }

    action procesBiznesowy : ProcesBiznesowy;
}
