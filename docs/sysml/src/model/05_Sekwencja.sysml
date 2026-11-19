package SekwencjaElicytacji {
    doc /*
     * Diagram sekwencji: jedna sesja elicytacji od publikacji winiety do odczytu wiedzy przez
     * RAG kliniki. System elicytacji jest czarną skrzynką (bez wnętrza); linie życia to role
     * użytkowników i systemy zewnętrzne. Linia życia = część z `event occurrence`, komunikat =
     * `message` między zdarzeniami, kolejność na linii życia: first ... then ....
     * Nazwy komunikatów to akcje i ścieżki API z kodu (prefiks /api/v1).
     * SysML v2 nie ma fragmentów alt/loop: autozapis szkicu powtarza się wielokrotnie, a ścieżki
     * request_changes / reject i błędy zadań pokazuje maszyna stanów przydziału (07_Stany).
     */

    private import BibliotekaElicytacji::*;
    private import InteresariuszeElicytacji::Interesariusze::*;
    private import KontekstElicytacji::SystemyZewnetrzne::*;
    private import StrukturaElicytacji::SystemElicytacji;
    private import StrukturaElicytacji::Ports::*;   // komunikaty: HttpRequest, ModelRequest, SqlStatement...

    // =================================================================== elicitation session
    occurrence def SesjaElicytacji {
        doc /*
         * Szczęśliwa ścieżka jednej sesji: publish, assign, start, draft, submit, korekta w tle,
         * sprawdzenie korekty, submit_for_review, recenzja, answer-decisions (approve), process
         * i ingest w tle, zapis do bazy wiedzy. Na końcu, niezależnie od sesji, RAG kliniki
         * czyta bazę wiedzy (tylko odczyt).
         */

        part inzynierWiedzy : InzynierWiedzy {
            event occurrence publikuj;
            event occurrence przydziel;
            event occurrence rozstrzygnij;
            event occurrence widziZaingestowany;
            first publikuj then przydziel;
            first przydziel then rozstrzygnij;
            first rozstrzygnij then widziZaingestowany;
        }
        part ekspert : Ekspert {
            event occurrence rozpocznij;
            event occurrence zapiszSzkic;
            event occurrence zglos;
            event occurrence widziKorekte;
            event occurrence poprawKorekte;
            event occurrence oddajDoRecenzji;
            first rozpocznij then zapiszSzkic;
            first zapiszSzkic then zglos;
            first zglos then widziKorekte;
            first widziKorekte then poprawKorekte;
            first poprawKorekte then oddajDoRecenzji;
        }
        part recenzent : Recenzent {
            event occurrence otworzRecenzje;
            event occurrence komentujIGlosuj;
            first otworzRecenzje then komentujIGlosuj;
        }
        part system : SystemElicytacji {
            event occurrence odbierzPublikacje;
            event occurrence odbierzPrzydzial;
            event occurrence odbierzStart;
            event occurrence odbierzSzkic;
            event occurrence odbierzZgloszenie;
            event occurrence wyslijDoKorekty;
            event occurrence odbierzKorekte;
            event occurrence pokazKorekte;
            event occurrence odbierzPoprawki;
            event occurrence odbierzOddanie;
            event occurrence odbierzOtwarcie;
            event occurrence odbierzKomentarze;
            event occurrence odbierzDecyzje;
            event occurrence wyslijDoOsadzenia;
            event occurrence odbierzWektory;
            event occurrence zapiszJednostki;
            event occurrence pokazStan;
            first odbierzPublikacje then odbierzPrzydzial;
            first odbierzPrzydzial then odbierzStart;
            first odbierzStart then odbierzSzkic;
            first odbierzSzkic then odbierzZgloszenie;
            first odbierzZgloszenie then wyslijDoKorekty;
            first wyslijDoKorekty then odbierzKorekte;
            first odbierzKorekte then pokazKorekte;
            first pokazKorekte then odbierzPoprawki;
            first odbierzPoprawki then odbierzOddanie;
            first odbierzOddanie then odbierzOtwarcie;
            first odbierzOtwarcie then odbierzKomentarze;
            first odbierzKomentarze then odbierzDecyzje;
            first odbierzDecyzje then wyslijDoOsadzenia;
            first wyslijDoOsadzenia then odbierzWektory;
            first odbierzWektory then zapiszJednostki;
            first zapiszJednostki then pokazStan;
        }
        part lokalnyLlm : LokalnyLlm {
            event occurrence sprawdzIRedaguj;
            event occurrence zwrocKorekte;
            event occurrence osadzTeksty;
            event occurrence zwrocWektory;
            first sprawdzIRedaguj then zwrocKorekte;
            first zwrocKorekte then osadzTeksty;
            first osadzTeksty then zwrocWektory;
        }
        part bazaWiedzy : BazaWiedzyEksperckiej {
            event occurrence zapisz;
            event occurrence odczytaj;
            event occurrence zwrocWiersze;
            first zapisz then odczytaj;
            first odczytaj then zwrocWiersze;
        }
        part ragKliniki : RagKliniki {
            event occurrence czytaj;
            event occurrence odbierzWiersze;
            first czytaj then odbierzWiersze;
        }

        // ---------------------------------------------------- winieta i przydział
        message m01_publish of HttpRequest from inzynierWiedzy.publikuj to system.odbierzPublikacje;        // POST /vignette-versions/{id}/publish
        message m02_assign of HttpRequest from inzynierWiedzy.przydziel to system.odbierzPrzydzial;         // POST /vignette-versions/{id}/assignments

        // ---------------------------------------------------- sesja elicytacji
        message m03_start of HttpRequest from ekspert.rozpocznij to system.odbierzStart;                    // POST /assignments/{id}/start
        message m04_draft of HttpRequest from ekspert.zapiszSzkic to system.odbierzSzkic;                   // PUT  /assignments/{id}/draft (autozapis)
        message m05_submit of HttpRequest from ekspert.zglos to system.odbierzZgloszenie;                   // POST /assignments/{id}/submit

        // ---------------------------------------------------- korekta (zadanie proofread)
        message m06_proofread of ModelRequest from system.wyslijDoKorekty to lokalnyLlm.sprawdzIRedaguj;    // LanguageTool + LLM
        message m07_proofreadResult of ModelResponse from lokalnyLlm.zwrocKorekte to system.odbierzKorekte;
        message m08_proofreadCheck of HttpResponse from system.pokazKorekte to ekspert.widziKorekte;         // GET  /assignments/{id}/proofread
        message m09_proofreadEdit of HttpRequest from ekspert.poprawKorekte to system.odbierzPoprawki;       // PUT  /assignments/{id}/proofread
        message m10_submitForReview of HttpRequest from ekspert.oddajDoRecenzji to system.odbierzOddanie;    // POST /assignments/{id}/submit-for-review

        // ---------------------------------------------------- recenzja i decyzja
        message m11_reviewOpen of HttpRequest from recenzent.otworzRecenzje to system.odbierzOtwarcie;       // POST /assignments/{id}/review/open
        message m12_commentsVotes of HttpRequest from recenzent.komentujIGlosuj to system.odbierzKomentarze; // POST .../comments, PUT .../vote
        message m13_answerDecisions of HttpRequest from inzynierWiedzy.rozstrzygnij to system.odbierzDecyzje; // POST /assignments/{id}/answer-decisions

        // ---------------------------------------------------- zadania process i ingest
        message m14_embed of ModelRequest from system.wyslijDoOsadzenia to lokalnyLlm.osadzTeksty;          // bge-m3
        message m15_embeddings of ModelResponse from lokalnyLlm.zwrocWektory to system.odbierzWektory;
        message m16_ingest of SqlStatement from system.zapiszJednostki to bazaWiedzy.zapisz;                // chips + BM25
        message m17_ingested of HttpResponse from system.pokazStan to inzynierWiedzy.widziZaingestowany;     // stan ingested

        // ---------------------------------------------------- poza systemem: RAG kliniki
        message m18_read of SqlStatement from ragKliniki.czytaj to bazaWiedzy.odczytaj;                     // READ ONLY
        message m19_rows of SqlRows from bazaWiedzy.zwrocWiersze to ragKliniki.odbierzWiersze;
    }
}
