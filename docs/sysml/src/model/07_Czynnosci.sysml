package CzynnosciElicytacji {
    doc /*
     * Czynności (diagramy act).
     *   OdOdpowiedziDoWiedzy - od przydziału do jednostek w bazie wiedzy (główny proces elicytacji)
     *   PotokKorekty         - zadanie `proofread` (prepare + record)
     *   ZbudujJednostki      - zadanie `process`
     *   IngestujJednostki    - zadanie `ingest`
     *   WykonanieZadania     - jedno wykonanie zadania przez workera (run_once): bramka mocy, dzierżawa, błędy
     *   ZapytanieRag         - wyszukiwanie hybrydowe i odpowiedź RAG
     * Tory (kto wykonuje czynność) są przypisane alokacjami w PlatformaElicytacji::AlokacjaCzynnosci.
     * Strukturę, która wykonuje zadania, opisuje 13_SciezkaPrzetwarzania (BDD + IBD).
     */

    private import ScalarValues::*;
    private import BibliotekaElicytacji::*;
    private import DziedzinaElicytacji::TypyWyliczeniowe::*;
    private import DziedzinaElicytacji::TrescOdpowiedzi::*;
    private import DziedzinaElicytacji::SchematApp::*;
    private import InterfejsyElicytacji::Elementy::*;

    // =================================================================== step definitions
    package Kroki {
        doc /* Czynności elementarne, z wejściami i wyjściami. */

        // ---------------------------------------------------- answering (ekspert)
        action def RozpocznijOdpowiadanie {
            in item przydzial : Przydzial;
        }
        action def CytujFragmenty {
            doc /* Zaznaczenie fragmentów winiety i nadanie kierunku. */
            in item wersja : WersjaWiniety;
            out item cytaty : Cytat[0..200];
        }
        action def NapiszOdpowiedzi {
            doc /* Odpowiedzi na wszystkie zadane pytania, z chipami [n]; Q4 i Q6 strukturalnie. */
            in item wersja : WersjaWiniety;
            out item tresc : TrescZgloszenia;
        }
        action def ZapiszSzkic {
            doc /* PUT /assignments/{id}/draft z numerem wersji (draft_conflict). */
            in item tresc : TrescZgloszenia;
            out item szkic : SzkicOdpowiedzi;
        }
        action def WalidujIZglos {
            doc /* clean_submission(): kompletność, cytaty, kierunki, reguły Q4/Q6; potem transition(submit). */
            @OdwolanieDoKodu { sciezka = "backend/app/assignments/service.py"; }
            in item szkic : SzkicOdpowiedzi;
            out item zgloszenie : Zgloszenie;
        }

        // ---------------------------------------------------- check & review
        action def SprawdzKorekte {
            doc /* Autor przegląda propozycje korekty i powiązania zdań z cytatami. */
            @OdwolanieDoKodu { sciezka = "backend/app/proofread/service.py"; }
            in item runda : RundaKorekty;
            out item rewizje : RewizjaOdpowiedzi[1..*];
        }
        action def OtworzRecenzje {
            doc /* POST /assignments/{id}/review/open - rejestruje uczestnika recenzji. */
            out item uczestnik : UczestnikRecenzji;
        }
        action def KomentujOdpowiedzi {
            out item komentarze : KomentarzDoOdpowiedzi[0..*];
        }
        action def GlosujNaOdpowiedzi {
            out item glosy : GlosNaOdpowiedz[0..*];
        }
        action def RozstrzygnijOdpowiedzi {
            doc /* Administrator: decyzja per pytanie; wynik zbiorczy steruje przepływem. */
            out item decyzje : DecyzjaOOdpowiedzi[1..*];
            out rozstrzygniecie : WartoscDecyzji;
        }

        // ---------------------------------------------------- proofread job
        action def OdrzucSmieci {
            @OdwolanieDoKodu { sciezka = "backend/app/proofread/garbage.py"; }
            in tekst : String;
            out oczyszczony : String;
            out odrzucone : String[0..*];
        }
        action def SprawdzGramatyke {
            doc /*
             * LanguageTool; słownictwo winiety i terminy kliniczne są chronione. Niedostępny: bez
             * REQUIRE_COMPUTE przebieg jest pomijany ("unavailable"), z REQUIRE_COMPUTE zadanie kończy
             * się błędem i czeka na komputer z modelami.
             */
            @OdwolanieDoKodu { sciezka = "backend/app/proofread/grammar.py"; }
            in tekst : String;
            out poprawiony : String;
        }
        action def Zredaguj {
            doc /*
             * LLM (prompt Answer_enhance.v1, num_ctx 8192); wyłączone, gdy ENHANCE_MODEL pusty.
             * Niedostępny model: jak w SprawdzGramatyke (pominięcie tylko bez REQUIRE_COMPUTE).
             */
            @OdwolanieDoKodu { sciezka = "backend/app/proofread/enhance.py"; }
            in pytanie : String;
            in tekst : String;
            out zredagowany : String[0..1];
        }
        action def Uloz {
            in tekst : String;
            out uporzadkowany : String;
        }
        action def PowiazLinie {
            doc /* Linie odpowiedzi wiązane z cytatami po chipach i cytowanych słowach. */
            @OdwolanieDoKodu { sciezka = "backend/app/proofread/links.py"; }
            in item cytaty : Cytat[0..*];
            out linie : Json;
        }
        action def KlasyfikujReszte {
            doc /* Linie bez powiązania - klasyfikator LLM (Expert_sentence_targets.v1). */
            @OdwolanieDoKodu { sciezka = "backend/app/knowledge/classifier.py"; }
            in linie : Json;
            out oznaczone : Json;
        }
        action def OznaczUstalenia {
            doc /* findings.check(): flagi do pokazania autorowi (np. cytat bez zdania). */
            @OdwolanieDoKodu { sciezka = "backend/app/knowledge/findings.py"; }
            in oznaczone : Json;
            out flagi : Json;
        }
        action def ZapiszRunde {
            doc /* Zapis rundy korekty pod blokadą przydziału; potem transition(proofread_succeeded). */
            @OdwolanieDoKodu { sciezka = "backend/app/proofread/service.py"; }
            out item runda : RundaKorekty;
        }

        // ---------------------------------------------------- units & ingestion
        action def WybierzZatwierdzoneOdpowiedzi {
            in item decyzje : DecyzjaOOdpowiedzi[1..*];
            out item rewizje : RewizjaOdpowiedzi[1..*];
        }
        action def ZbudujRekordUstalen {
            @OdwolanieDoKodu { sciezka = "backend/app/knowledge/findings.py"; }
            in item rewizje : RewizjaOdpowiedzi[1..*];
            out item ustalenia : UstaleniaOdpowiedzi;
        }
        action def PotnijNaJednostki {
            doc /* build_units(): jednostki `fragment` (przy cytacie) i `case` (cały przypadek). */
            @OdwolanieDoKodu { sciezka = "backend/app/knowledge/findings.py"; }
            in item ustalenia : UstaleniaOdpowiedzi;
            out item jednostki : JednostkaWiedzy[1..*];
        }
        action def OdmowyIngestii {
            doc /*
             * ingest.load - odmowy (błędy trwałe, bez ponawiania): brak jednostek -> NoUnits;
             * jednostka bez I1/I3 -> UnitsNotEmbeddable; brak rekordu ustaleń -> NoFindings.
             */
            @OdwolanieDoKodu { sciezka = "backend/app/knowledge/ingest.py"; }
            in item jednostki : JednostkaWiedzy[1..*];
        }
        action def OsadzJednostki {
            doc /* bge-m3, jedno wywołanie: I1 (tekst jednostki), I2 (słowa pacjenta cytatów), I3 (I1 + słowa pacjenta). */
            @OdwolanieDoKodu { sciezka = "backend/app/knowledge/embedding.py"; }
            in item jednostki : JednostkaWiedzy[1..*];
            out item wektory : Osadzenie[1..*];
        }
        action def ZapiszChips {
            doc /* Zapis do schematu chips (sesja, cytaty, zdania, jednostki, wskazówki). */
            @OdwolanieDoKodu { sciezka = "backend/app/knowledge/ingest.py"; }
            in item jednostki : JednostkaWiedzy[1..*];
            in item wektory : Osadzenie[1..*];
        }
        action def OdswiezWektoryRzadkie {
            doc /* Przeliczenie BM25 (idf globalne) pod blokadą doradczą. */
            @OdwolanieDoKodu { sciezka = "backend/app/knowledge/ingest.py"; }
        }

        // ---------------------------------------------------- RAG query
        action def OsadzZapytanie {
            in item zapytanie : ZapytanieWyszukiwania;
            out item wektor : Osadzenie;
        }
        action def ZapytanieRzadkie {
            doc /* expert_knowledge_core.bm25.query_vector */
            in item zapytanie : ZapytanieWyszukiwania;
            out rzadki : Json;
        }
        action def RankujIFuzjuj {
            doc /* Rankingi gęsty i rzadki, fuzja RRF (cue_scores), obniżenie duplikatów przypadków. */
            @OdwolanieDoKodu { sciezka = "packages/expert-knowledge-rag/src/expert_knowledge_rag/ranking.py"; }
            in item wektor : Osadzenie;
            in rzadki : Json;
            out item trafienia : WynikWyszukiwania;
        }
        action def ZbudujKontekst {
            doc /* build_documents + format_notes: notatki eksperckie do promptu. */
            @OdwolanieDoKodu { sciezka = "packages/expert-knowledge-rag/src/expert_knowledge_rag/documents.py"; }
            in item trafienia : WynikWyszukiwania;
            out notatki : String;
        }
        action def WygenerujOdpowiedz {
            @OdwolanieDoKodu { sciezka = "packages/expert-knowledge-rag/src/expert_knowledge_rag/chains.py"; }
            in notatki : String;
            out item odpowiedz : OdpowiedzModelu;
        }
    }

    private import Kroki::*;

    // =================================================================== jobs (sub-activities)
    action def PotokKorekty {
        doc /*
         * Zadanie `proofread`. Dla każdej odpowiedzi: śmieci -> gramatyka -> redakcja LLM ->
         * gramatyka ponownie -> układ. Potem wspólnie: wiązanie linii, klasyfikacja reszty, flagi,
         * zapis rundy. Część wolna (do flag) działa bez transakcji.
         */
        @OdwolanieDoKodu { sciezka = "backend/app/proofread/pipeline.py"; }
        in item zgloszenie : Zgloszenie;
        out item runda : RundaKorekty;

        action dlaKazdejOdpowiedzi {
            doc /* Powtarzane dla każdego zadanego pytania z odpowiedzią. */
            action odrzucSmieci : OdrzucSmieci;
            action gramatyka : SprawdzGramatyke;
            action redakcja : Zredaguj;
            action gramatykaPonownie : SprawdzGramatyke;
            action uklad : Uloz;

            first start;
            then odrzucSmieci;
            then gramatyka;
            then redakcja;
            then gramatykaPonownie;
            then uklad;
            then done;

            flow from odrzucSmieci.oczyszczony to gramatyka.tekst;
            flow from gramatyka.poprawiony to redakcja.tekst;
            flow from redakcja.zredagowany to gramatykaPonownie.tekst;
            flow from gramatykaPonownie.poprawiony to uklad.tekst;
        }
        action powiazLinie : PowiazLinie;
        action klasyfikujReszte : KlasyfikujReszte;
        action oznaczUstalenia : OznaczUstalenia;
        action zapiszRunde : ZapiszRunde;

        first start;
        then dlaKazdejOdpowiedzi;
        then powiazLinie;
        then klasyfikujReszte;
        then oznaczUstalenia;
        then zapiszRunde;
        then done;

        flow from powiazLinie.linie to klasyfikujReszte.linie;
        flow from klasyfikujReszte.oznaczone to oznaczUstalenia.oznaczone;
        flow from zapiszRunde.runda to runda;
    }

    action def ZbudujJednostki {
        doc /* Zadanie `process`: tylko odpowiedzi zatwierdzone w bieżącej rundzie, z liniami powiązanymi przez autora. */
        @OdwolanieDoKodu { sciezka = "backend/app/jobs/handlers.py"; }
        in item decyzje : DecyzjaOOdpowiedzi[1..*];
        out item jednostki : JednostkaWiedzy[1..*];

        action wybierzZatwierdzone : WybierzZatwierdzoneOdpowiedzi;
        action zbudujRekord : ZbudujRekordUstalen;
        action potnij : PotnijNaJednostki;

        first start;
        then wybierzZatwierdzone;
        then zbudujRekord;
        then potnij;
        then done;

        flow from decyzje to wybierzZatwierdzone.decyzje;
        flow from wybierzZatwierdzone.rewizje to zbudujRekord.rewizje;
        flow from zbudujRekord.ustalenia to potnij.ustalenia;
        flow from potnij.jednostki to jednostki;
    }

    action def IngestujJednostki {
        doc /*
         * Zadanie `ingest`. PREPARE (bez transakcji): wczytanie z odmowami, osadzenie.
         * HANDLERS (pod blokadą przydziału): blokada doradcza BM25, zastąpienie wierszy sesji w chips,
         * przeliczenie BM25 dla całego schematu, jednostki -> ingested.
         */
        @OdwolanieDoKodu { sciezka = "backend/app/jobs/handlers.py"; }
        in item jednostki : JednostkaWiedzy[1..*];

        action odmowyIngestii : OdmowyIngestii;
        action osadz : OsadzJednostki;
        action zapiszChips : ZapiszChips;
        action odswiezWektoryRzadkie : OdswiezWektoryRzadkie;

        first start;
        then odmowyIngestii;
        then osadz;
        then zapiszChips;
        then odswiezWektoryRzadkie;
        then done;

        flow from jednostki to osadz.jednostki;
        flow from osadz.wektory to zapiszChips.wektory;
    }

    // =================================================================== worker: one job
    action def WykonanieZadania {
        doc /*
         * run_once(): jedno zadanie od pobrania do zapisu. main() powtarza to w pętli. Zadanie
         * korpusu (refit) nie ma przydziału: bez PREPARE i blokady przydziału, porażka nie zmienia
         * stanu przepływu. Struktura: SciezkaPrzetwarzania::Komponenty::PetlaWorkera.
         */
        @OdwolanieDoKodu { sciezka = "backend/app/jobs/worker.py"; }

        first start;
        then action ustalGotoweRodzaje {
            doc /* compute.ready_kinds(): rodzaje, których maszyna działa (sonda nie starsza niż 15 s); None = wszystkie. */
        }
        then action pobierzZadanie {
            doc /* next_job(kinds): najstarsze queued lub running z wygasłą dzierżawą, FOR UPDATE SKIP LOCKED. */
            out jest : Boolean;
            out wyczerpane : Boolean;     // attempts >= 3: poprzedni worker padł w ostatniej próbie
        }
        then decide czyJestPraca;
            if not pobierzZadanie.jest then odczekaj;
            if pobierzZadanie.jest and pobierzZadanie.wyczerpane then wyczerpanePrzejecie;
            else oznaczUruchomione;

        action odczekaj {
            doc /* Brak pracy: 2 s przerwy. */
        }
        then done;

        action wyczerpanePrzejecie {
            doc /* failed, last_error = LeaseExpired, transition(*_failed). */
        }
        then done;

        action oznaczUruchomione {
            doc /* running, attempts + 1, locked_until = teraz + 5 min; commit. Startuje puls dzierżawy. */
        }
        then action przygotuj {
            doc /* PREPARE[kind](assignment_id): wolna część bez transakcji i blokady (LanguageTool, LLM, bge-m3). */
            out blad : Boolean;
        }
        then decide poPrzygotowaniu;
            if przygotuj.blad then scalenieBledow;
            else zablokujISprawdz;

        action zablokujISprawdz {
            doc /* lock_assignment, potem _current: czy dzierżawa nadal należy do tego workera (status, attempts). */
            out mojaDzierzawa : Boolean;
        }
        then decide czyMojaDzierzawa;
            if not zablokujISprawdz.mojaDzierzawa then done;
            else zapiszWynik;

        action zapiszWynik {
            doc /* HANDLERS[kind](db, assignment, prepared) - w transakcji, pod blokadą. */
            out blad : Boolean;
        }
        then decide poZapisie;
            if zapiszWynik.blad then scalenieBledow;
            else przejscieUdane;

        action przejscieUdane {
            doc /*
             * done, locked_until = null, transition(*_succeeded, system) - nowy stan może zakolejkować
             * kolejne zadanie (JOB_ON_ENTRY, bez sprawdzania mocy); commit.
             */
        }
        then done;

        merge scalenieBledow;
        then action sprawdzPrzyczyne {
            doc /* PermanentJobError? compute.is_down_for(kind) - nowa sonda, od razu? numer próby? */
            out trwaly : Boolean;
            out mocNiedostepna : Boolean;
            out ostatniaProba : Boolean;     // attempt >= MAX_ATTEMPTS (3)
        }
        then decide wgPrzyczyny;
            if sprawdzPrzyczyne.trwaly then oznaczNieudane;
            if not sprawdzPrzyczyne.trwaly and sprawdzPrzyczyne.mocNiedostepna then czekajNaMoc;
            if not sprawdzPrzyczyne.trwaly and not sprawdzPrzyczyne.mocNiedostepna and sprawdzPrzyczyne.ostatniaProba then oznaczNieudane;
            else ponowPozniej;

        action oznaczNieudane {
            doc /* failed + transition(*_failed): przydział -> processing_failed / ingestion_failed. */
        }
        then done;

        action czekajNaMoc {
            doc /* queued, attempts - 1: próba się nie liczy; zadanie czeka, aż komputer z modelami wróci. */
        }
        then done;

        action ponowPozniej {
            doc /* queued, last_error = nazwa klasy wyjątku. */
        }
        then done;
    }

    // =================================================================== main process
    action def OdOdpowiedziDoWiedzy {
        doc /*
         * Proces od przydziału do bazy wiedzy. Ekspert cytuje i odpowiada równolegle (wszystkie
         * pytania widoczne od razu), szkic zapisuje się automatycznie. Po zgłoszeniu: korekta,
         * sprawdzenie przez autora, recenzja koleżeńska, decyzja administratora. Odesłanie do
         * poprawy wraca do sprawdzenia korekty (nowa runda).
         */
        in item przydzial : Przydzial;
        in item wersja : WersjaWiniety;
        out item jednostki : JednostkaWiedzy[0..*];

        action rozpocznijOdpowiadanie : RozpocznijOdpowiadanie;
        action cytujFragmenty : CytujFragmenty;
        action napiszOdpowiedzi : NapiszOdpowiedzi;
        action zapiszSzkic : ZapiszSzkic;
        action zglos : WalidujIZglos;
        action korekta : PotokKorekty;
        action sprawdzKorekte : SprawdzKorekte;
        action otworzRecenzje : OtworzRecenzje;
        action komentujOdpowiedzi : KomentujOdpowiedzi;
        action glos : GlosujNaOdpowiedzi;
        action rozstrzygnijOdpowiedzi : RozstrzygnijOdpowiedzi;
        action zbudujJednostki : ZbudujJednostki;
        action ingestia : IngestujJednostki;

        // ---------------------------------------------------- control flow
        first start;
        then rozpocznijOdpowiadanie;
        then fork rozwidlenieOdpowiadania;
            then cytujFragmenty;
            then napiszOdpowiedzi;

        first cytujFragmenty then zlaczenieOdpowiadania;
        first napiszOdpowiedzi then zlaczenieOdpowiadania;
        join zlaczenieOdpowiadania;
        then zapiszSzkic;
        then zglos;
        then korekta;
        then merge scalenieSprawdzenia;
        then sprawdzKorekte;
        then otworzRecenzje;
        then fork rozwidlenieRecenzji;
            then komentujOdpowiedzi;
            then glos;

        first komentujOdpowiedzi then zlaczenieRecenzji;
        first glos then zlaczenieRecenzji;
        join zlaczenieRecenzji;
        then rozstrzygnijOdpowiedzi;
        then decide decyzjaWgWyniku;
            if rozstrzygnijOdpowiedzi.rozstrzygniecie == WartoscDecyzji::zatwierdz then zbudujJednostki;
            if rozstrzygnijOdpowiedzi.rozstrzygniecie == WartoscDecyzji::zazadajPoprawek then scalenieSprawdzenia;
            else done;

        first zbudujJednostki then ingestia;
        first ingestia then done;

        // ---------------------------------------------------- object flow
        flow from przydzial to rozpocznijOdpowiadanie.przydzial;
        flow from wersja to cytujFragmenty.wersja;
        flow from wersja to napiszOdpowiedzi.wersja;
        flow from napiszOdpowiedzi.tresc to zapiszSzkic.tresc;
        flow from zapiszSzkic.szkic to zglos.szkic;
        flow from zglos.zgloszenie to korekta.zgloszenie;
        flow from korekta.runda to sprawdzKorekte.runda;
        flow from rozstrzygnijOdpowiedzi.decyzje to zbudujJednostki.decyzje;
        flow from zbudujJednostki.jednostki to ingestia.jednostki;
        flow from zbudujJednostki.jednostki to jednostki;
    }

    // =================================================================== RAG query
    action def ZapytanieRag {
        doc /*
         * Zapytanie do bazy wiedzy. Tryb `question` (ExpertQuestionRetriever) albo `patient_text`
         * (PatientTextRetriever: wyszukuje po kluczach-wskazówkach z winiet). Generowanie
         * odpowiedzi: @Planowane w aplikacji.
         */
        @OdwolanieDoKodu { sciezka = "packages/expert-knowledge-rag/src/expert_knowledge_rag/retrievers.py"; }
        in item zapytanie : ZapytanieWyszukiwania;
        out item odpowiedz : OdpowiedzModelu[0..1];

        action osadzZapytanie : OsadzZapytanie;
        action zapytanieRzadkie : ZapytanieRzadkie;
        action rankujIFuzjuj : RankujIFuzjuj;
        action zbudujKontekst : ZbudujKontekst;
        action generuj : WygenerujOdpowiedz;

        first start;
        then fork rozwidlenieZapytania;
            then osadzZapytanie;
            then zapytanieRzadkie;

        first osadzZapytanie then zlaczenieZapytania;
        first zapytanieRzadkie then zlaczenieZapytania;
        join zlaczenieZapytania;
        then rankujIFuzjuj;
        then zbudujKontekst;
        then generuj;
        then done;

        flow from zapytanie to osadzZapytanie.zapytanie;
        flow from zapytanie to zapytanieRzadkie.zapytanie;
        flow from osadzZapytanie.wektor to rankujIFuzjuj.wektor;
        flow from zapytanieRzadkie.rzadki to rankujIFuzjuj.rzadki;
        flow from rankujIFuzjuj.trafienia to zbudujKontekst.trafienia;
        flow from zbudujKontekst.notatki to generuj.notatki;
        flow from generuj.odpowiedz to odpowiedz;
    }
}
