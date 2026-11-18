package DziedzinaElicytacji {
    doc /*
     * Model danych dziedziny (odpowiednik diagramu BDD z blokami danych / ERD).
     * Trzy obszary:
     *   SchematApp      - schemat `app` aplikacji (modele SQLAlchemy w backend/app/<moduł>/models.py)
     *   TrescOdpowiedzi - treść odpowiedzi eksperta (payload JSONB szkicu i zgłoszenia)
     *   SchematChips    - schemat RAG `chips` (migracja backend/migrations/versions/0003_pipeline.py), wypełniany przy ingestii
     * Typy wyliczeniowe odpowiadają klasom StrEnum z kodu; literały mają polskie nazwy, a wartość
     * w bazie (z kodu) podano w komentarzu `// db:` przy każdym literale.
     */

    private import ScalarValues::*;
    private import BibliotekaElicytacji::*;

    // =================================================================== enumerations
    package TypyWyliczeniowe {
        doc /* Typy wyliczeniowe. Wartość zapisywana w bazie jest w komentarzu `// db:` przy literale. */

        enum def Rola {
            doc /* Rola użytkownika. */
            @OdwolanieDoKodu { sciezka = "backend/app/users/models.py"; }
            enum administrator;  // db: admin
            enum ekspert;  // db: expert
        }

        enum def StatusWersji {
            doc /* Status wersji winiety; przypisać można tylko wersję `published`. */
            @OdwolanieDoKodu { sciezka = "backend/app/vignettes/models.py"; }
            enum szkic;  // db: draft
            enum opublikowany;  // db: published
            enum wycofany;  // db: retired
        }

        enum def StanPrzydzialu {
            doc /* Stan przydziału (w kodzie: `State`). Przejścia: StanyElicytacji::CyklZyciaPrzydzialu. */
            @OdwolanieDoKodu { sciezka = "backend/app/assignments/states.py"; }
            enum przydzielony;  // db: assigned
            enum wToku;  // db: in_progress
            enum korektaWToku;  // db: proofreading
            enum sprawdzenieKorekty;  // db: proofread_check
            enum recenzjaKolezenska;  // db: peer_review
            enum przetwarzanieWToku;  // db: processing
            enum przetwarzanieNieudane;  // db: processing_failed
            enum ingestiaWToku;  // db: ingesting
            enum ingestiaNieudana;  // db: ingestion_failed
            enum zaingestowany;  // db: ingested
            enum odrzucony;  // db: rejected
            enum anulowany;  // db: cancelled
        }

        enum def AktorPrzeplywu {
            doc /* Kto wykonuje akcję przepływu (w kodzie: `Actor`). */
            @OdwolanieDoKodu { sciezka = "backend/app/assignments/states.py"; }
            enum wykonawca;  // db: assignee
            enum administrator;  // db: admin
            enum recenzent;  // db: reviewer
            enum system;  // db: system
        }

        enum def AkcjaPrzeplywu {
            doc /* Akcja przepływu (w kodzie: `Action`). */
            @OdwolanieDoKodu { sciezka = "backend/app/assignments/states.py"; }
            enum rozpocznij;  // db: start
            enum anuluj;  // db: cancel
            enum zglos;  // db: submit
            enum korektaUdana;  // db: proofread_succeeded
            enum korektaNieudana;  // db: proofread_failed
            enum oddajDoRecenzji;  // db: submit_for_review
            enum przetwarzanieUdane;  // db: processing_succeeded
            enum przetwarzanieNieudane;  // db: processing_failed
            enum ponowKorekte;  // db: retry_proofread
            enum ponowPrzetwarzanie;  // db: retry_processing
            enum ponowIngestie;  // db: retry_ingestion
            enum zatwierdzOdpowiedzi;  // db: approve_answers
            enum zazadajPoprawek;  // db: request_changes
            enum odrzucWszystkieOdpowiedzi;  // db: reject_all_answers
            enum ingestiaUdana;  // db: ingestion_succeeded
            enum ingestiaNieudana;  // db: ingestion_failed
        }

        enum def RodzajZadania {
            doc /* Rodzaj zadania w tle. `refit` dotyczy całego korpusu (bez przydziału). */
            @OdwolanieDoKodu { sciezka = "backend/app/jobs/models.py"; }
            enum korekta;  // db: proofread
            enum przetwarzanie;  // db: process
            enum ingestia;  // db: ingest
            enum przeliczenie;  // db: refit
        }

        enum def StatusZadania {
            @OdwolanieDoKodu { sciezka = "backend/app/jobs/models.py"; }
            enum wKolejce;  // db: queued
            enum uruchomione;  // db: running
            enum zakonczone;  // db: done
            enum nieudane;  // db: failed
        }

        enum def StatusJednostki {
            doc /* Status jednostki wiedzy. */
            @OdwolanieDoKodu { sciezka = "backend/app/knowledge/models.py"; }
            enum oczekujaca;  // db: pending
            enum zatwierdzona;  // db: approved
            enum odrzucony;  // db: rejected
            enum zaingestowany;  // db: ingested
            enum zastapiona;  // db: superseded
            enum usunieta;  // db: removed
        }

        enum def WartoscDecyzji {
            doc /* Decyzja administratora o odpowiedzi (per pytanie). */
            @OdwolanieDoKodu { sciezka = "backend/app/reviews/models.py"; }
            enum zatwierdz;  // db: approve
            enum odrzuc;  // db: reject
            enum zazadajPoprawek;  // db: request_changes
        }

        enum def Stanowisko {
            doc /* Stanowisko komentarza w recenzji. */
            @OdwolanieDoKodu { sciezka = "backend/app/reviews/models.py"; }
            enum poparcie;  // db: support
            enum zastrzezenie;  // db: challenge
            enum pytanie;  // db: question
        }

        enum def WartoscGlosu {
            @OdwolanieDoKodu { sciezka = "backend/app/reviews/models.py"; }
            enum zatwierdz;  // db: approve
            enum sprzeciw;  // db: disapprove
        }

        enum def Kierunek {
            doc /* Kierunek cytatu względem cech ADHD. */
            @OdwolanieDoKodu { sciezka = "backend/app/assignments/answers.py"; }
            enum zgodny;  // db: toward
            enum przeciwny;  // db: away
            enum neutralny;  // db: neutral
            enum niejasny;  // db: unclear
        }

        enum def KierunekZmianyQ4 {
            doc /* Kierunek zmiany hipotezy w Q4 (wymagany, gdy shift > 0). */
            @OdwolanieDoKodu { sciezka = "backend/app/assignments/answers.py"; }
            enum bardziejAdhd;  // db: more_adhd
            enum mniejAdhd;  // db: less_adhd
            enum inny;  // db: other
        }

        enum def RodzajJednostki {
            doc /* fragment - jednostka przy cytacie; case - jednostka całego przypadku. */
            @OdwolanieDoKodu { sciezka = "backend/app/knowledge/models.py"; }
            enum fragment;  // db: fragment
            enum przypadek;  // db: case
        }
    }

    // =================================================================== answer content
    package TrescOdpowiedzi {
        doc /*
         * Treść odpowiedzi (AnswerPayload, format 2). Wszystkie zadane pytania są widoczne od razu
         * - nie ma bramki między pytaniami. Walidacja przy zgłoszeniu: clean_submission().
         */
        private import TypyWyliczeniowe::*;

        item def Cytat {
            doc /* Fragment winiety zacytowany przez eksperta (chip [n]). */
            @OdwolanieDoKodu { sciezka = "backend/app/assignments/answers.py"; }
            attribute chip : Integer;            // numerowane od 1, bez przerw
            attribute tekst : String;
            attribute poczatekZakresu : Integer;       // [start, end) w znakach tekstu winiety
            attribute koniecZakresu : Integer;
            attribute kierunek : Kierunek[0..1];   // wymagany przy zgłoszeniu
        }

        item def OdpowiedzQ4 {
            doc /* Q4: hipoteza robocza, przesunięcie po "co jeśli" i jego kierunek. */
            @OdwolanieDoKodu { sciezka = "backend/app/assignments/answers.py"; }
            attribute hipoteza : String[0..1];
            attribute przesuniecie : Integer[0..1];     // -2..+2
            attribute zgodny : KierunekZmianyQ4[0..1];
            attribute innyKomentarz : String[0..1];
            assert constraint zakresPrzesuniecia { przesuniecie >= -2 and przesuniecie <= 2 }
        }

        item def TrescZgloszenia {
            doc /* Szkic lub zgłoszenie odpowiedzi eksperta. */
            @OdwolanieDoKodu { sciezka = "backend/app/assignments/answers.py"; }
            attribute odpowiedzi : String[0..6];    // mapa IdPytania -> tekst (z chipami [n])
            item cytaty : Cytat[0..200];
            item q4 : OdpowiedzQ4[0..1];
            attribute ocena : Integer[0..1];    // Q6: 1..5
            attribute zaMaloInformacji : Boolean;
        }
    }

    // =================================================================== app schema
    package SchematApp {
        doc /* Schemat `app`: encje aplikacji. Związki jako referencje z krotnościami. */
        private import TypyWyliczeniowe::*;
        private import TrescOdpowiedzi::*;

        item def Uzytkownik {
            @OdwolanieDoKodu { sciezka = "backend/app/users/models.py"; }
            attribute id : Uuid;
            attribute email : String;
            attribute nazwaWyswietlana : String;
            attribute rola : Rola;
            attribute pseudonim : String;
            attribute skrotHasla : String[0..1];
            attribute czyAktywny : Boolean;
            attribute nieudaneLogowania : Integer;
            attribute zablokowanyDo : ZnacznikCzasu[0..1];
            attribute aktywnoscWidzianaO : ZnacznikCzasu[0..1];
            attribute utworzonoO : ZnacznikCzasu;
        }

        item def SesjaLogowania {
            doc /* Sesja logowania (ciasteczko); przechowywany tylko skrót tokenu. */
            @OdwolanieDoKodu { sciezka = "backend/app/auth/models.py"; }
            attribute skrotTokenu : Sha256;
            ref uzytkownik : Uzytkownik[1];
            attribute wygasaO : ZnacznikCzasu;
            attribute utworzonoO : ZnacznikCzasu;
        }

        item def Zaproszenie {
            doc /* Zaproszenie - jedyna droga założenia konta eksperta. */
            @OdwolanieDoKodu { sciezka = "backend/app/auth/models.py"; }
            attribute id : Uuid;
            ref uzytkownik : Uzytkownik[1];
            attribute skrotTokenu : Sha256;
            attribute wygasaO : ZnacznikCzasu;
            attribute wykorzystanoO : ZnacznikCzasu[0..1];
        }

        item def Winieta {
            doc /* Winieta kliniczna (kod, np. V900); treść w wersjach. */
            @OdwolanieDoKodu { sciezka = "backend/app/vignettes/models.py"; }
            attribute id : Uuid;
            attribute kod : String;
            ref utworzonyPrzez : Uzytkownik[1];
            attribute utworzonoO : ZnacznikCzasu;
            ref wersje : WersjaWiniety[1..*];
        }

        item def WersjaWiniety {
            @OdwolanieDoKodu { sciezka = "backend/app/vignettes/models.py"; }
            attribute id : Uuid;
            ref winieta : Winieta[1];
            attribute wersja : Integer;
            attribute status : StatusWersji;
            attribute tekst : String;
            attribute skrotTresci : Sha256;
            attribute kontekstowanie : String;
            attribute idPytan : IdPytania[1..6];
            attribute q4CoJesli : String[0..1];
            attribute streszczeniePacjenta : String;
            attribute wariant : Json[0..1];   // kolumna `variant`
            attribute projekt : Json;           // ukryte wskazówki i notatki - nigdy nie trafiają do ekspertów
            attribute utworzonoO : ZnacznikCzasu;
            attribute opublikowanoO : ZnacznikCzasu[0..1];
        }

        item def Przydzial {
            doc /* Jeden ekspert na jednej wersji winiety; nośnik stanu przepływu. */
            @OdwolanieDoKodu { sciezka = "backend/app/assignments/models.py"; }
            attribute id : Uuid;
            ref wersjaWiniety : WersjaWiniety[1];
            ref ekspert : Uzytkownik[1];
            ref przydzielonyPrzez : Uzytkownik[1];
            attribute stan : StanPrzydzialu;
            attribute rundaRecenzji : Integer;
            attribute rozpoczetoO : ZnacznikCzasu[0..1];
            attribute zgloszonoO : ZnacznikCzasu[0..1];
            attribute utworzonoO : ZnacznikCzasu;
            attribute zaktualizowanoO : ZnacznikCzasu;
        }

        item def SzkicOdpowiedzi {
            doc /* Autozapisywany szkic; `version` chroni przed nadpisaniem z nieaktualnej karty. */
            @OdwolanieDoKodu { sciezka = "backend/app/assignments/models.py"; }
            ref przydzial : Przydzial[1];
            item tresc : TrescZgloszenia;
            attribute wersja : Integer;
            attribute zaktualizowanoO : ZnacznikCzasu;
        }

        item def Zgloszenie {
            doc /* Niezmienne zgłoszenie (wymuszone wyzwalaczem w bazie). */
            @OdwolanieDoKodu { sciezka = "backend/app/assignments/models.py"; }
            ref przydzial : Przydzial[1];
            item tresc : TrescZgloszenia;
            attribute formatTresci : Integer;
            attribute skrotWiniety : Sha256;
            attribute zgloszonoO : ZnacznikCzasu;
        }

        item def RundaKorekty {
            doc /* Runda korekty (na rundę recenzji): podświetlenia, flagi, przebiegi korekty. */
            @OdwolanieDoKodu { sciezka = "backend/app/proofread/models.py"; }
            ref przydzial : Przydzial[1];
            attribute rundaRecenzji : Integer;
            attribute wersja : Integer;
            attribute cytaty : Json;
            attribute flagi : Json;
            attribute przebiegi : Json;
            attribute klasyfikator : String[0..1];
            attribute prompt : String[0..1];
            attribute informacjaZwrotna : Json;
            attribute zgloszonoO : ZnacznikCzasu[0..1];
        }

        item def RewizjaOdpowiedzi {
            doc /* Tekst odpowiedzi na pytanie: oryginał, propozycja korekty, wersja końcowa. */
            @OdwolanieDoKodu { sciezka = "backend/app/proofread/models.py"; }
            ref przydzial : Przydzial[1];
            attribute rundaRecenzji : Integer;
            attribute idPytania : IdPytania;
            attribute oryginal : String;
            attribute propozycja : String;
            attribute wersjaKoncowa : String;
            attribute linie : Json;
            attribute odrzucone : String[0..*];
        }

        item def UstaleniaOdpowiedzi {
            doc /* Rekord ustaleń: zdania odpowiedzi przypisane do cytatów (wejście do budowy jednostek). */
            @OdwolanieDoKodu { sciezka = "backend/app/knowledge/models.py"; }
            ref przydzial : Przydzial[1];
            attribute rekord : Json;
            attribute wersja : Integer;
            attribute wynikSprawdzenia : String[0..1];
            attribute klasyfikator : String[0..1];
            attribute prompt : String[0..1];
            attribute wersjaUstalen : Integer;
        }

        item def JednostkaWiedzy {
            doc /* Jednostka wiedzy eksperckiej - cytowana dosłownie, osadzana w RAG. */
            @OdwolanieDoKodu { sciezka = "backend/app/knowledge/models.py"; }
            attribute id : Uuid;
            ref przydzial : Przydzial[1];
            ref zgloszenie : Zgloszenie[1];
            attribute numerPorzadkowy : Integer;
            attribute rundaRecenzji : Integer;
            attribute tekst : String;
            attribute skrotTresci : Sha256;
            attribute rodzaj : RodzajJednostki[0..1];
            attribute idCytatu : String[0..1];
            attribute kierunek : Kierunek[0..1];
            attribute slowaPacjenta : String[0..1];
            attribute idZdan : String[0..*];
            attribute kontekst : String[0..*];
            attribute tekstDoOsadzenia : String[0..1];           // I1
            attribute tekstDoOsadzeniaZlaczony : String[0..1];   // I3
            attribute status : StatusJednostki;
        }

        item def UczestnikRecenzji {
            doc /* Ekspert, który otworzył recenzję - nie może już dostać tej winiety. */
            @OdwolanieDoKodu { sciezka = "backend/app/reviews/models.py"; }
            ref przydzial : Przydzial[1];
            ref ekspert : Uzytkownik[1];
            attribute otwartoO : ZnacznikCzasu;
        }

        item def KomentarzDoOdpowiedzi {
            @OdwolanieDoKodu { sciezka = "backend/app/reviews/models.py"; }
            attribute id : Uuid;
            ref przydzial : Przydzial[1];
            attribute rundaRecenzji : Integer;
            attribute idPytania : IdPytania;
            ref autor : Uzytkownik[1];
            ref rodzic : KomentarzDoOdpowiedzi[0..1];
            attribute stanowisko : Stanowisko[0..1];
            attribute tresc : String;
        }

        item def GlosNaOdpowiedz {
            @OdwolanieDoKodu { sciezka = "backend/app/reviews/models.py"; }
            ref przydzial : Przydzial[1];
            attribute rundaRecenzji : Integer;
            attribute idPytania : IdPytania;
            ref glosujacy : Uzytkownik[1];
            attribute glos : WartoscGlosu;
        }

        item def DecyzjaOOdpowiedzi {
            doc /* Decyzja administratora per pytanie; tylko administrator zamyka recenzję. */
            @OdwolanieDoKodu { sciezka = "backend/app/reviews/models.py"; }
            ref przydzial : Przydzial[1];
            attribute rundaRecenzji : Integer;
            attribute idPytania : IdPytania;
            ref recenzent : Uzytkownik[1];
            attribute decyzja : WartoscDecyzji;
            attribute komentarz : String[0..1];
            attribute skrotTresci : Sha256;
            attribute rozstrzygnietoO : ZnacznikCzasu;
        }

        item def Zadanie {
            doc /* Zadanie w tle (kolejka w Postgresie, SKIP LOCKED, dzierżawa). */
            @OdwolanieDoKodu { sciezka = "backend/app/jobs/models.py"; }
            attribute id : Uuid;
            attribute rodzaj : RodzajZadania;
            ref przydzial : Przydzial[0..1];   // brak dla zadań korpusu (refit)
            attribute status : StatusZadania;
            attribute proby : Integer;
            attribute zablokowanyDo : ZnacznikCzasu[0..1];
            attribute ostatniBlad : String[0..1];
            attribute utworzonoO : ZnacznikCzasu;
        }

        item def ZdarzenieAudytowe {
            doc /* Zdarzenie audytowe - zapisywane przy każdym przejściu stanu. */
            @OdwolanieDoKodu { sciezka = "backend/app/audit/models.py"; }
            attribute id : Uuid;
            ref aktor : Uzytkownik[0..1];
            attribute typEncji : String;
            attribute idEncji : Uuid;
            attribute akcja : String;
            attribute zStanu : String[0..1];
            attribute doStanu : String[0..1];
            attribute metadane : Json;            // kolumna `metadata`
            attribute chwila : ZnacznikCzasu;
        }
    }

    // =================================================================== chips (RAG) schema
    package SchematChips {
        doc /*
         * Schemat `chips` czytany przez bibliotekę packages/expert-knowledge-rag.
         * Wektory: bge-m3 (1024 wymiary) + rzadki wektor BM25.
         */
        @OdwolanieDoKodu { sciezka = "backend/migrations/versions/0003_pipeline.py"; }
        private import TypyWyliczeniowe::*;

        attribute def WektorGesty {
            doc /* pgvector vector(1024). */
            attribute wymiary : Integer = 1024;
        }

        attribute def WektorRzadki {
            doc /* pgvector sparsevec(1048576) - wagi BM25. */
        }

        item def Ekspert {
            attribute id : String;
            attribute rola : String[0..1];
        }

        item def Winieta {
            attribute id : String;
            attribute wersja : Integer;
            attribute poziom : String;
            attribute tekst : String;
            attribute skrotTresci : Sha256;
            attribute kontekstowanie : String;
            attribute populacja : String;
            attribute sciezkaBadawcza : String;
        }

        item def SesjaElicytacji {
            attribute id : String;
            ref ekspert : Ekspert[1];
            attribute dokument : Json;
            attribute utworzonoO : ZnacznikCzasu;
        }

        item def KluczWskazowki {
            doc /* Fragment winiety jako klucz wyszukiwania (wspólny dla ekspertów). */
            attribute id : Integer;
            attribute idWiniety : String;
            attribute wersjaWiniety : Integer;
            attribute tekst : String;
            attribute osadzenie : WektorGesty;
            attribute rzadki : WektorRzadki[0..1];
        }

        item def Cytat {
            attribute id : String;
            ref sesja : SesjaElicytacji[1];
            attribute chip : Integer[0..1];
            attribute pochodzenie : String;           // expert | implicit
            attribute kierunek : Kierunek[0..1];
            attribute kierunekZmienionyPoFladze : Boolean;
            ref kluczWskazowki : KluczWskazowki[1];
        }

        item def ZdanieOdpowiedzi {
            attribute id : String;
            ref sesja : SesjaElicytacji[1];
            attribute idPytania : IdPytania;
            attribute indeks : Integer;
            attribute cele : String[1..*];
            attribute przydzielonyPrzez : String;       // chip | quote | llm | expert
        }

        item def JednostkaUstalen {
            attribute id : String;
            ref sesja : SesjaElicytacji[1];
            attribute rodzaj : RodzajJednostki;
            ref cytat : Cytat[0..1];
            attribute kierunek : Kierunek[0..1];
            attribute populacja : String;
            attribute sciezkaBadawcza : String;
            attribute kontekstowanie : String;
            attribute segmenter : Json;
            attribute tekstDoOsadzenia : String;
            attribute osadzenie : WektorGesty;
            attribute rzadki : WektorRzadki[0..1];
            attribute tekstDoOsadzeniaZlaczony : String[0..1];
            attribute osadzenieZlaczone : WektorGesty[0..1];
            ref zdania : ZdanieOdpowiedzi[0..*];   // przez finding_unit_sentences
            ref wskazowki : KluczWskazowki[0..*];                // przez unit_cues (rola cue | context)
        }

        item def ZdarzenieRecenzji {
            ref sesja : SesjaElicytacji[1];
            attribute idWiniety : String;
            attribute rodzaj : String;             // flag_shown | toggle_changed | sentence_moved | skipped
            attribute tresc : Json;
            attribute chwila : ZnacznikCzasu;
        }
    }

}
