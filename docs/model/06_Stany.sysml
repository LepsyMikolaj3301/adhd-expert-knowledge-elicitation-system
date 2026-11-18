package StanyElicytacji {
    doc /*
     * Maszyny stanów (diagramy stm).
     *   CyklZyciaPrzydzialu - 1:1 z TRANSITIONS w backend/app/assignments/state_machine.py
     *                         (19 przejść; strażnik = aktor uprawniony do akcji)
     *   CyklZyciaWersjiWiniety - szkic -> opublikowany -> wycofany
     *   CyklZyciaZadania       - kolejka zadań: wKolejce -> uruchomione -> udane | nieudane
     * Sygnały przepływu niosą aktora (`wykonujeAktor`), strażniki sprawdzają uprawnienie jak check_transition().
     */

    private import ScalarValues::*;
    private import BibliotekaElicytacji::*;
    private import DziedzinaElicytacji::TypyWyliczeniowe::*;

    // =================================================================== signals
    package Sygnaly {
        doc /* Jeden sygnał na AkcjaPrzeplywu. */

        item def SygnalPrzeplywu {
            attribute wykonujeAktor : AktorPrzeplywu;
        }

        item def Rozpocznij :> SygnalPrzeplywu;
        item def Anuluj :> SygnalPrzeplywu;
        item def Zglos :> SygnalPrzeplywu;
        item def KorektaUdana :> SygnalPrzeplywu;
        item def KorektaNieudana :> SygnalPrzeplywu;
        item def OddajDoRecenzji :> SygnalPrzeplywu;
        item def PrzetwarzanieUdane :> SygnalPrzeplywu;
        item def PrzetwarzanieNieudane :> SygnalPrzeplywu;
        item def PonowKorekte :> SygnalPrzeplywu;
        item def PonowPrzetwarzanie :> SygnalPrzeplywu;
        item def PonowIngestie :> SygnalPrzeplywu;
        item def ZatwierdzOdpowiedzi :> SygnalPrzeplywu;
        item def ZazadajPoprawek :> SygnalPrzeplywu;
        item def OdrzucWszystkieOdpowiedzi :> SygnalPrzeplywu;
        item def IngestiaUdana :> SygnalPrzeplywu;
        item def IngestiaNieudana :> SygnalPrzeplywu;

        // wersje winiet
        item def Opublikuj;
        item def Wycofaj;

        // zadania
        item def Przejmij {
            doc /* Worker pobiera zadanie; rodzajGotowy = rodzaj jest w compute.ready_kinds() (lub kontrola wyłączona). */
            attribute rodzajGotowy : Boolean;
        }
        item def ZadanieUdane;
        item def ZadanieZBledem {
            doc /*
             * trwaly = PermanentJobError (np. NoUnits, UnitsNotEmbeddable);
             * mocNiedostepna = compute.is_down_for(kind) po błędzie (komputer z modelami nie działa).
             */
            attribute trwaly : Boolean;
            attribute mocNiedostepna : Boolean;
        }
        item def DzierzawaWygasla;
    }

    private import Sygnaly::*;

    // =================================================================== actions used on entry
    action def ZakolejkujZadanie {
        doc /* JOB_ON_ENTRY: wejście w stan zadania kolejkuje Job w tej samej transakcji. */
        @OdwolanieDoKodu { sciezka = "backend/app/assignments/state_machine.py"; }
        in rodzaj : RodzajZadania;
    }

    action def ZapiszZdarzenieAudytowe {
        doc /* record_event(): każde przejście zapisuje zdarzenie audytowe. */
        @OdwolanieDoKodu { sciezka = "backend/app/audit/service.py"; }
    }

    // =================================================================== assignment
    state def CyklZyciaPrzydzialu {
        doc /*
         * Cykl życia przydziału. Stany zadań w tle (korektaWToku, przetwarzanieWToku, ingestiaWToku) kolejkują
         * zadanie przy wejściu; frontend odpytuje, gdy widzi jeden z nich.
         * przetwarzanieNieudane jest wspólny dla korekty i przetwarzania - ponowienie uruchamia to,
         * które się nie powiodło.
         * Z REQUIRE_COMPUTE przejście wykonywane przez osobę do stanu zadania (t04 zgłoszenie,
         * t10 zatwierdzenie, t15, t16, t19 ponowienia) najpierw sprawdza komputer z modelami;
         * gdy nie jest gotowy: 503 compute_unavailable i przejście nie zachodzi (stan bez zmian).
         * Przejścia systemu (t13 przetwarzanie -> ingestia) nie są sprawdzane: worker sam wstrzymuje
         * zadanie (CyklZyciaZadania::czekanieNaMoc).
         */
        @OdwolanieDoKodu { sciezka = "backend/app/assignments/state_machine.py"; }

        entry; then przydzielony;

        state przydzielony;
        state wToku {
            doc /* Odpowiadanie; autozapis szkicu. */
        }
        state korektaWToku {
            entry action zakolejkuj : ZakolejkujZadanie { in rodzaj = RodzajZadania::korekta; }
        }
        state sprawdzenieKorekty {
            doc /* Autor sprawdza korektę i powiązania; wraca tu po odesłaniu do poprawy. */
        }
        state recenzjaKolezenska {
            doc /* Komentarze i głosy recenzentów; decyduje administrator. */
        }
        state przetwarzanieWToku {
            entry action zakolejkuj : ZakolejkujZadanie { in rodzaj = RodzajZadania::przetwarzanie; }
        }
        state przetwarzanieNieudane;
        state ingestiaWToku {
            entry action zakolejkuj : ZakolejkujZadanie { in rodzaj = RodzajZadania::ingestia; }
        }
        state ingestiaNieudana;
        state zaingestowany;
        state odrzucony;
        state anulowany;

        // ---------------------------------------------------- TRANSITIONS (19)
        transition t01_rozpoczecie
            first przydzielony
            accept s : Rozpocznij if s.wykonujeAktor == AktorPrzeplywu::wykonawca
            then wToku;

        transition t02_anulowaniePrzydzielonego
            first przydzielony
            accept s : Anuluj if s.wykonujeAktor == AktorPrzeplywu::administrator
            then anulowany;

        transition t03_anulowanieWToku
            first wToku
            accept s : Anuluj if s.wykonujeAktor == AktorPrzeplywu::administrator
            then anulowany;

        transition t04_zgloszenie
            first wToku
            accept s : Zglos if s.wykonujeAktor == AktorPrzeplywu::wykonawca
            then korektaWToku;

        transition t05_korektaUdana
            first korektaWToku
            accept s : KorektaUdana if s.wykonujeAktor == AktorPrzeplywu::system
            then sprawdzenieKorekty;

        transition t06_korektaNieudana
            first korektaWToku
            accept s : KorektaNieudana if s.wykonujeAktor == AktorPrzeplywu::system
            then przetwarzanieNieudane;

        transition t07_anulowaniePrzySprawdzeniu
            first sprawdzenieKorekty
            accept s : Anuluj if s.wykonujeAktor == AktorPrzeplywu::administrator
            then anulowany;

        transition t08_oddanieDoRecenzji
            first sprawdzenieKorekty
            accept s : OddajDoRecenzji if s.wykonujeAktor == AktorPrzeplywu::wykonawca
            then recenzjaKolezenska;

        transition t09_anulowaniePrzyRecenzji
            first recenzjaKolezenska
            accept s : Anuluj if s.wykonujeAktor == AktorPrzeplywu::administrator
            then anulowany;

        transition t10_zatwierdzenieOdpowiedzi
            first recenzjaKolezenska
            accept s : ZatwierdzOdpowiedzi if s.wykonujeAktor == AktorPrzeplywu::administrator
            then przetwarzanieWToku;

        transition t11_odrzucenieWszystkich
            first recenzjaKolezenska
            accept s : OdrzucWszystkieOdpowiedzi if s.wykonujeAktor == AktorPrzeplywu::administrator
            then odrzucony;

        transition t12_zadaniePoprawek
            first recenzjaKolezenska
            accept s : ZazadajPoprawek if s.wykonujeAktor == AktorPrzeplywu::administrator
            then sprawdzenieKorekty;

        transition t13_przetwarzanieUdane
            first przetwarzanieWToku
            accept s : PrzetwarzanieUdane if s.wykonujeAktor == AktorPrzeplywu::system
            then ingestiaWToku;

        transition t14_przetwarzanieNieudane
            first przetwarzanieWToku
            accept s : PrzetwarzanieNieudane if s.wykonujeAktor == AktorPrzeplywu::system
            then przetwarzanieNieudane;

        transition t15_ponowienieKorekty
            first przetwarzanieNieudane
            accept s : PonowKorekte if s.wykonujeAktor == AktorPrzeplywu::administrator
            then korektaWToku;

        transition t16_ponowieniePrzetwarzania
            first przetwarzanieNieudane
            accept s : PonowPrzetwarzanie if s.wykonujeAktor == AktorPrzeplywu::administrator
            then przetwarzanieWToku;

        transition t17_ingestiaUdana
            first ingestiaWToku
            accept s : IngestiaUdana if s.wykonujeAktor == AktorPrzeplywu::system
            then zaingestowany;

        transition t18_ingestiaNieudana
            first ingestiaWToku
            accept s : IngestiaNieudana if s.wykonujeAktor == AktorPrzeplywu::system
            then ingestiaNieudana;

        transition t19_ponowienieIngestii
            first ingestiaNieudana
            accept s : PonowIngestie if s.wykonujeAktor == AktorPrzeplywu::administrator
            then ingestiaWToku;

        // stany końcowe (TERMINAL_STATES)
        transition t20_koniecZaingestowany first zaingestowany then done;
        transition t21_koniecOdrzucony first odrzucony then done;
        transition t22_koniecAnulowany first anulowany then done;
    }

    // =================================================================== vignette version
    state def CyklZyciaWersjiWiniety {
        doc /* Wersja robocza jest edytowalna; przydzielić można tylko opublikowaną. */
        @OdwolanieDoKodu { sciezka = "backend/app/vignettes/router.py"; }

        entry; then szkic;

        state szkic;
        state opublikowany;
        state wycofany;

        transition opublikuj first szkic accept Opublikuj then opublikowany;
        transition wycofaj first opublikowany accept Wycofaj then wycofany;
        transition koniecWycofane first wycofany then done;
    }

    // =================================================================== job
    state def CyklZyciaZadania {
        doc /*
         * Zadanie w kolejce (next_job: najstarsze queued albo running z wygasłą dzierżawą,
         * SKIP LOCKED, tylko rodzaje gotowe). Błąd przejściowy wraca do kolejki; błąd przy
         * niedziałającym komputerze z modelami wraca do kolejki bez zużycia próby; błąd trwały
         * lub 3. próba kończy porażką i wysyła sygnał *_failed do przydziału.
         */
        @OdwolanieDoKodu { sciezka = "backend/app/jobs/worker.py"; }

        attribute proby : Integer = 0;
        attribute maksymalnaLiczbaProb : Integer = 3;

        entry; then wKolejce;

        state wKolejce;
        state uruchomione {
            doc /* Dzierżawa 5 min, odnawiana co 1/3 dzierżawy (heartbeat). */
        }
        state udane {
            doc /* StatusZadania::zakonczone; przydział dostaje *_succeeded. */
        }
        state nieudane {
            doc /* StatusZadania::nieudane; przydział dostaje *_failed. */
        }

        transition przejmij
            first wKolejce
            accept p : Przejmij if p.rodzajGotowy and proby < maksymalnaLiczbaProb
            then uruchomione;

        transition przejecieWyczerpane
            first wKolejce
            accept p : Przejmij if p.rodzajGotowy and proby >= maksymalnaLiczbaProb
            then nieudane;

        transition powodzenie
            first uruchomione
            accept ZadanieUdane
            then udane;

        // próba się nie liczy (attempts - 1); last_error zostaje zapisany
        transition czekanieNaMoc
            first uruchomione
            accept e : ZadanieZBledem if not e.trwaly and e.mocNiedostepna
            then wKolejce;

        transition bladPrzejsciowy
            first uruchomione
            accept e : ZadanieZBledem if not e.trwaly and not e.mocNiedostepna and proby < maksymalnaLiczbaProb
            then wKolejce;

        transition bladTrwaly
            first uruchomione
            accept e : ZadanieZBledem if e.trwaly or (not e.mocNiedostepna and proby >= maksymalnaLiczbaProb)
            then nieudane;

        transition dzierzawaWygasla
            first uruchomione
            accept DzierzawaWygasla
            then wKolejce;

        transition koniecUdane first udane then done;
        transition koniecNieudane first nieudane then done;
    }
}
