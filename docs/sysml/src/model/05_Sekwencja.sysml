package SekwencjaElicytacji {
    doc /*
     * Diagram sekwencji: jedna sesja elicytacji (jeden przydział, Assignment) na tle publikacji
     * winiety przed nią i odczytu wiedzy przez RAG kliniki po niej. System elicytacji jest czarną
     * skrzynką (bez wnętrza); linie życia to role użytkowników i systemy zewnętrzne. Linia życia
     * = część z `event occurrence`, komunikat = `message` między zdarzeniami, kolejność na linii
     * życia: first ... then ....
     * Nazwy komunikatów to akcje i ścieżki API z kodu (prefiks /api/v1).
     * HTTP: każdy komunikat do systemu to żądanie przeglądarki, a odpowiedź wraca tym samym
     * połączeniem. Odpowiedź (HttpResponse) jest narysowana tylko tam, gdzie osoba na nią czeka
     * i z nią dalej pracuje. System nie wysyła nic do przeglądarki sam: o końcu zadania w tle
     * frontend dowiaduje się, odpytując API (polling).
     * SysML v2 nie ma fragmentów alt/loop: autozapis szkicu i odpytywanie powtarzają się
     * wielokrotnie, a ścieżki request_changes / reject i błędy zadań pokazuje maszyna stanów
     * przydziału (07_Stany).
     */

    private import BibliotekaElicytacji::*;
    private import InteresariuszeElicytacji::Interesariusze::*;
    private import KontekstElicytacji::SystemyZewnetrzne::*;
    private import StrukturaElicytacji::SystemElicytacji;
    private import StrukturaElicytacji::Ports::*;   // komunikaty: HttpRequest, ModelRequest, SqlStatement...

    // =================================================================== elicitation session
    occurrence def SesjaElicytacji {
        doc /*
         * Szczęśliwa ścieżka jednej sesji elicytacji (przydziału): assign, start, draft, submit,
         * korekta w tle, sprawdzenie korekty, submit_for_review, recenzja, answer-decisions
         * (approve), process i ingest w tle, zapis do bazy wiedzy (session_id = id przydziału).
         * Przed sesją: publikacja winiety. Po niej, niezależnie od sesji: RAG kliniki czyta bazę
         * wiedzy (tylko odczyt).
         */

        part inzynierWiedzy : InzynierWiedzy {
            event occurrence publikuj;
            event occurrence przydziel;
            event occurrence rozstrzygnij;
            event occurrence odpytajStan;
            event occurrence widziZaingestowany;
            first publikuj then przydziel;
            first przydziel then rozstrzygnij;
            first rozstrzygnij then odpytajStan;
            first odpytajStan then widziZaingestowany;
        }
        part ekspert : Ekspert {
            event occurrence rozpocznij;
            event occurrence zapiszSzkic;
            event occurrence zglos;
            event occurrence odpytajStan;
            event occurrence pobierzKorekte;
            event occurrence widziKorekte;
            event occurrence poprawKorekte;
            event occurrence oddajDoRecenzji;
            first rozpocznij then zapiszSzkic;
            first zapiszSzkic then zglos;
            first zglos then odpytajStan;
            first odpytajStan then pobierzKorekte;
            first pobierzKorekte then widziKorekte;
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
            event occurrence odbierzOdpytanie;
            event occurrence odbierzPobranieKorekty;
            event occurrence pokazKorekte;
            event occurrence odbierzPoprawki;
            event occurrence odbierzOddanie;
            event occurrence odbierzOtwarcie;
            event occurrence odbierzKomentarze;
            event occurrence odbierzDecyzje;
            event occurrence wyslijDoOsadzenia;
            event occurrence odbierzWektory;
            event occurrence zapiszJednostki;
            event occurrence odbierzOdpytanieStanu;
            event occurrence pokazStan;
            first odbierzPublikacje then odbierzPrzydzial;
            first odbierzPrzydzial then odbierzStart;
            first odbierzStart then odbierzSzkic;
            first odbierzSzkic then odbierzZgloszenie;
            first odbierzZgloszenie then wyslijDoKorekty;
            first wyslijDoKorekty then odbierzKorekte;
            first odbierzKorekte then odbierzOdpytanie;
            first odbierzOdpytanie then odbierzPobranieKorekty;
            first odbierzPobranieKorekty then pokazKorekte;
            first pokazKorekte then odbierzPoprawki;
            first odbierzPoprawki then odbierzOddanie;
            first odbierzOddanie then odbierzOtwarcie;
            first odbierzOtwarcie then odbierzKomentarze;
            first odbierzKomentarze then odbierzDecyzje;
            first odbierzDecyzje then wyslijDoOsadzenia;
            first wyslijDoOsadzenia then odbierzWektory;
            first odbierzWektory then zapiszJednostki;
            first zapiszJednostki then odbierzOdpytanieStanu;
            first odbierzOdpytanieStanu then pokazStan;
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

        // ---------------------------------------------------- przed sesją: winieta
        message m01_publish of HttpRequest from inzynierWiedzy.publikuj to system.odbierzPublikacje;        // POST /vignette-versions/{id}/publish

        // ---------------------------------------------------- sesja: przydział i odpowiedzi
        message m02_assign of HttpRequest from inzynierWiedzy.przydziel to system.odbierzPrzydzial;         // POST /vignette-versions/{id}/assignments
        message m03_start of HttpRequest from ekspert.rozpocznij to system.odbierzStart;                    // POST /assignments/{id}/start
        message m04_draft of HttpRequest from ekspert.zapiszSzkic to system.odbierzSzkic;                   // PUT  /assignments/{id}/draft (autozapis)
        message m05_submit of HttpRequest from ekspert.zglos to system.odbierzZgloszenie;                   // POST /assignments/{id}/submit

        // ---------------------------------------------------- korekta (zadanie proofread)
        message m06_proofread of ModelRequest from system.wyslijDoKorekty to lokalnyLlm.sprawdzIRedaguj;    // LanguageTool + LLM
        message m07_proofreadResult of ModelResponse from lokalnyLlm.zwrocKorekte to system.odbierzKorekte;
        message m08_poll of HttpRequest from ekspert.odpytajStan to system.odbierzOdpytanie;                 // GET  /assignments/{id} co 4 s, aż stan proofread_check
        message m09_proofreadGet of HttpRequest from ekspert.pobierzKorekte to system.odbierzPobranieKorekty; // GET  /assignments/{id}/proofread
        message m10_proofreadCheck of HttpResponse from system.pokazKorekte to ekspert.widziKorekte;         // odpowiedź na m09: teksty po korekcie i powiązania
        message m11_proofreadEdit of HttpRequest from ekspert.poprawKorekte to system.odbierzPoprawki;       // PUT  /assignments/{id}/proofread
        message m12_submitForReview of HttpRequest from ekspert.oddajDoRecenzji to system.odbierzOddanie;    // POST /assignments/{id}/submit-for-review

        // ---------------------------------------------------- recenzja i decyzja
        message m13_reviewOpen of HttpRequest from recenzent.otworzRecenzje to system.odbierzOtwarcie;       // POST /assignments/{id}/review/open
        message m14_commentsVotes of HttpRequest from recenzent.komentujIGlosuj to system.odbierzKomentarze; // POST .../comments, PUT .../vote
        message m15_answerDecisions of HttpRequest from inzynierWiedzy.rozstrzygnij to system.odbierzDecyzje; // POST /assignments/{id}/answer-decisions

        // ---------------------------------------------------- zadania process i ingest
        message m16_embed of ModelRequest from system.wyslijDoOsadzenia to lokalnyLlm.osadzTeksty;          // bge-m3
        message m17_embeddings of ModelResponse from lokalnyLlm.zwrocWektory to system.odbierzWektory;
        message m18_ingest of SqlStatement from system.zapiszJednostki to bazaWiedzy.zapisz;                // chips + BM25
        message m19_poll of HttpRequest from inzynierWiedzy.odpytajStan to system.odbierzOdpytanieStanu;     // GET  /assignments co 10 s, dopóki trwa zadanie w tle
        message m20_ingested of HttpResponse from system.pokazStan to inzynierWiedzy.widziZaingestowany;     // odpowiedź na m19: stan ingested

        // ---------------------------------------------------- po sesji, poza systemem: RAG kliniki
        message m21_read of SqlStatement from ragKliniki.czytaj to bazaWiedzy.odczytaj;                     // READ ONLY
        message m22_rows of SqlRows from bazaWiedzy.zwrocWiersze to ragKliniki.odbierzWiersze;
    }
}
