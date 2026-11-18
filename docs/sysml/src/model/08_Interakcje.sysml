package InterakcjeElicytacji {
    doc /*
     * Interakcje (odpowiedniki diagramów sekwencji). Linie życia = części, komunikaty = message
     * między zdarzeniami (event occurrence). Kolejność na linii życia: first ... then ....
     *   InterakcjaZgloszeniaOdpowiedzi - zgłoszenie odpowiedzi
     *   InterakcjaWykonaniaZadania     - wykonanie zadania przez workera (przykład: proofread)
     *   InterakcjaOdmowyBezMocy        - zgłoszenie przy wyłączonym komputerze z modelami (503)
     *   InterakcjaWyszukiwaniaWiedzy   - wyszukiwanie w bazie wiedzy
     * SysML v2 nie ma fragmentów alt/opt; warianty opisano w doc i osobnych interakcjach.
     */

    private import ScalarValues::*;
    private import BibliotekaElicytacji::*;
    private import InterfejsyElicytacji::Elementy::*;
    private import KontekstElicytacji::Aktorzy::*;
    private import KontekstElicytacji::SystemyZewnetrzne::*;
    private import StrukturaElicytacji::*;
    private import StrukturaElicytacji::ModulyBackendu::*;
    private import SciezkaPrzetwarzania::Komponenty::BramkaMocyObliczeniowej;

    item def ZamiarUzytkownika {
        doc /* Działanie użytkownika w interfejsie (kliknięcie). */
    }

    item def WywolaniePrzejscia {
        doc /* Wywołanie transition(db, assignment, action, actor, actor_id). */
        @OdwolanieDoKodu { sciezka = "backend/app/assignments/state_machine.py"; }
    }

    item def WywolanieSprawdzeniaMocy {
        doc /* require_compute(kind) w API albo ready_kinds() w workerze. */
        @OdwolanieDoKodu { sciezka = "backend/app/compute.py"; }
    }

    item def BrakiMocy {
        doc /* details.missing: ollama, languagetool, model <nazwa>. */
        attribute braki : String[0..*];
    }

    // =================================================================== submit
    occurrence def InterakcjaZgloszeniaOdpowiedzi {
        doc /*
         * POST /assignments/{id}/submit. Wariant: walidacja nie przechodzi ->
         * 422 submission_incomplete (lub inny kod), stan się nie zmienia.
         * Osobno: zapis szkicu ze starą wersją -> 409 draft_conflict (InterakcjaKonfliktuSzkicu).
         */
        @OdwolanieDoKodu { sciezka = "backend/app/assignments/router.py"; }

        part ekspert : Ekspert {
            event occurrence klikZglos;
            event occurrence widziKorekte;
            first klikZglos then widziKorekte;
        }
        part frontend : FrontendWebowy {
            event occurrence odbierzKlik;
            event occurrence wyslijZgloszenie;
            event occurrence odbierzWidok;
            event occurrence wyswietlWidok;
            first odbierzKlik then wyslijZgloszenie;
            first wyslijZgloszenie then odbierzWidok;
            first odbierzWidok then wyswietlWidok;
        }
        part api : BackendApi {
            event occurrence odbierzZgloszenie;
            event occurrence zazadajBlokady;
            event occurrence zazadajSzkicu;
            event occurrence wywolajPrzejscie;
            event occurrence zazadajCommit;
            event occurrence wyslijWidok;
            first odbierzZgloszenie then zazadajBlokady;
            first zazadajBlokady then zazadajSzkicu;
            first zazadajSzkicu then wywolajPrzejscie;
            first wywolajPrzejscie then zazadajCommit;
            first zazadajCommit then wyslijWidok;
        }
        part maszynaStanow : MaszynaStanowPrzeplywu {
            event occurrence odbierzPrzejscie;
            event occurrence zapiszStanAudytIZadanie;
            first odbierzPrzejscie then zapiszStanAudytIZadanie;
        }
        part baza : BazaPostgres {
            event occurrence zablokujWiersz;
            event occurrence odczytajSzkic;
            event occurrence zapiszPrzejscie;
            event occurrence commit;
            first zablokujWiersz then odczytajSzkic;
            first odczytajSzkic then zapiszPrzejscie;
            first zapiszPrzejscie then commit;
        }

        message m01_klik of ZamiarUzytkownika from ekspert.klikZglos to frontend.odbierzKlik;
        message m02_postZgloszenie of ZapytanieHttp from frontend.wyslijZgloszenie to api.odbierzZgloszenie;
        message m03_blokadaPrzydzialu of InstrukcjaSql from api.zazadajBlokady to baza.zablokujWiersz;
        message m04_wczytanieSzkicu of InstrukcjaSql from api.zazadajSzkicu to baza.odczytajSzkic;
        message m05_przejscie of WywolaniePrzejscia from api.wywolajPrzejscie to maszynaStanow.odbierzPrzejscie;
        message m06_stanAudytZadanie of InstrukcjaSql from maszynaStanow.zapiszStanAudytIZadanie to baza.zapiszPrzejscie;
        message m07_commit of InstrukcjaSql from api.zazadajCommit to baza.commit;
        message m08_widok of OdpowiedzHttp from api.wyslijWidok to frontend.odbierzWidok;
        message m09_pokazanie of ZamiarUzytkownika from frontend.wyswietlWidok to ekspert.widziKorekte;
    }

    occurrence def InterakcjaKonfliktuSzkicu {
        doc /* PUT /assignments/{id}/draft z nieaktualną wersją -> 409 draft_conflict, tekst nie jest nadpisany. */
        @OdwolanieDoKodu { sciezka = "backend/app/assignments/service.py"; }

        part frontend : FrontendWebowy {
            event occurrence wyslijSzkic;
            event occurrence odbierzKonflikt;
            first wyslijSzkic then odbierzKonflikt;
        }
        part api : BackendApi {
            event occurrence odbierzSzkic;
            event occurrence wyslijKonflikt;
            first odbierzSzkic then wyslijKonflikt;
        }

        message m01_putSzkic of ZapytanieHttp from frontend.wyslijSzkic to api.odbierzSzkic;
        message m02_konflikt of OdpowiedzHttp from api.wyslijKonflikt to frontend.odbierzKonflikt;
    }

    // =================================================================== job execution
    occurrence def InterakcjaWykonaniaZadania {
        doc /*
         * Jedno wykonanie zadania (run_once) na przykładzie `proofread`:
         * 0) z REQUIRE_COMPUTE: gotowe rodzaje zadań z sondy (nowa sonda, gdy starsza niż 15 s);
         * 1) pobranie zadania (SKIP LOCKED, tylko gotowe rodzaje), running, attempts + 1, dzierżawa;
         * 2) część wolna PREPARE bez transakcji (LanguageTool, LLM), równolegle heartbeat;
         * 3) blokada przydziału, sprawdzenie, że dzierżawa nadal należy do workera, zapis wyniku
         *    (HANDLERS), done, transition(*_succeeded), commit.
         * Warianty błędu: komputer z modelami niedostępny -> queued bez zużycia próby; błąd
         * przejściowy -> queued; trwały lub 3. próba -> failed + transition(*_failed).
         * Pełny przebieg z decyzjami: CzynnosciElicytacji::WykonanieZadania.
         */
        @OdwolanieDoKodu { sciezka = "backend/app/jobs/worker.py"; }

        part worker : WorkerZadan {
            event occurrence zapytajOGotowosc;
            event occurrence przejmij;
            event occurrence sprawdzGramatyke;
            event occurrence wywolajLlm;
            event occurrence odnowDzierzawe;
            event occurrence zablokujPrzydzial;
            event occurrence zapiszWynik;
            event occurrence wywolajPrzejscie;
            event occurrence zazadajCommit;
            first zapytajOGotowosc then przejmij;
            first przejmij then sprawdzGramatyke;
            first sprawdzGramatyke then wywolajLlm;
            first wywolajLlm then odnowDzierzawe;
            first odnowDzierzawe then zablokujPrzydzial;
            first zablokujPrzydzial then zapiszWynik;
            first zapiszWynik then wywolajPrzejscie;
            first wywolajPrzejscie then zazadajCommit;
        }
        part moc : BramkaMocyObliczeniowej {
            event occurrence odbierzPytanie;
            event occurrence sondujOllama;
            event occurrence sondujLanguageTool;
            first odbierzPytanie then sondujOllama;
            first odbierzPytanie then sondujLanguageTool;
        }
        part languageTool : UslugaLanguageTool {
            event occurrence sonda;
            event occurrence sprawdzenie;
            first sonda then sprawdzenie;
        }
        part ollama : UslugaOllama {
            event occurrence sonda;
            event occurrence generuj;
            first sonda then generuj;
        }
        part maszynaStanow : MaszynaStanowPrzeplywu {
            event occurrence odbierzPrzejscie;
            event occurrence zapiszStanAudyt;
            first odbierzPrzejscie then zapiszStanAudyt;
        }
        part baza : BazaPostgres {
            event occurrence nastepneZadanie;
            event occurrence dzierzawa;
            event occurrence zablokujWiersz;
            event occurrence zapiszRundeWBazie;
            event occurrence zapiszPrzejscie;
            event occurrence commit;
            first nastepneZadanie then dzierzawa;
            first dzierzawa then zablokujWiersz;
            first zablokujWiersz then zapiszRundeWBazie;
            first zapiszRundeWBazie then zapiszPrzejscie;
            first zapiszPrzejscie then commit;
        }

        message m00a_gotoweRodzaje of WywolanieSprawdzeniaMocy from worker.zapytajOGotowosc to moc.odbierzPytanie;
        message m00b_sondaOllama of ZapytanieListyModeli from moc.sondujOllama to ollama.sonda;
        message m00c_sondaLanguageTool of ZapytanieListyJezykow from moc.sondujLanguageTool to languageTool.sonda;
        message m01_nastepneZadanie of InstrukcjaSql from worker.przejmij to baza.nastepneZadanie;
        message m02_gramatyka of ZapytanieSprawdzeniaGramatyki from worker.sprawdzGramatyke to languageTool.sprawdzenie;
        message m03_redakcja of ZapytanieCzatu from worker.wywolajLlm to ollama.generuj;
        message m04_heartbeat of InstrukcjaSql from worker.odnowDzierzawe to baza.dzierzawa;
        message m05_blokada of InstrukcjaSql from worker.zablokujPrzydzial to baza.zablokujWiersz;
        message m06_zapis of InstrukcjaSql from worker.zapiszWynik to baza.zapiszRundeWBazie;
        message m07_przejscie of WywolaniePrzejscia from worker.wywolajPrzejscie to maszynaStanow.odbierzPrzejscie;
        message m08_stanAudyt of InstrukcjaSql from maszynaStanow.zapiszStanAudyt to baza.zapiszPrzejscie;
        message m09_commit of InstrukcjaSql from worker.zazadajCommit to baza.commit;
    }

    // =================================================================== refused without compute
    occurrence def InterakcjaOdmowyBezMocy {
        doc /*
         * REQUIRE_COMPUTE, komputer z modelami wyłączony. POST /assignments/{id}/submit: blokada,
         * walidacja, transition(submit) -> require_compute(proofread) czyta ostatnią sondę obserwatora
         * (bez czekania na sieć pod blokadą) -> DomainError 503 compute_unavailable
         * {missing: [ollama | languagetool | model <nazwa>]} -> rollback: stan in_progress, brak zadania.
         * Ten sam przebieg dla zatwierdzenia odpowiedzi (sprawdza też bge-m3) i ponowień.
         */
        @OdwolanieDoKodu { sciezka = "backend/app/compute.py"; }

        part ekspert : Ekspert {
            event occurrence klikZglos;
            event occurrence widziKomunikat;
            first klikZglos then widziKomunikat;
        }
        part frontend : FrontendWebowy {
            event occurrence odbierzKlik;
            event occurrence wyslijZgloszenie;
            event occurrence odbierzOdmowe;
            event occurrence pokazKomunikat;
            first odbierzKlik then wyslijZgloszenie;
            first wyslijZgloszenie then odbierzOdmowe;
            first odbierzOdmowe then pokazKomunikat;
        }
        part api : BackendApi {
            event occurrence odbierzZgloszenie;
            event occurrence zazadajBlokady;
            event occurrence wywolajPrzejscie;
            event occurrence wycofaj;
            event occurrence wyslijOdmowe;
            first odbierzZgloszenie then zazadajBlokady;
            first zazadajBlokady then wywolajPrzejscie;
            first wywolajPrzejscie then wycofaj;
            first wycofaj then wyslijOdmowe;
        }
        part maszynaStanow : MaszynaStanowPrzeplywu {
            event occurrence odbierzPrzejscie;
            event occurrence zapytajOMoc;
            event occurrence zglosBlad;
            first odbierzPrzejscie then zapytajOMoc;
            first zapytajOMoc then zglosBlad;
        }
        part moc : BramkaMocyObliczeniowej {
            event occurrence odczytajSonde;
            event occurrence zwrocBraki;
            first odczytajSonde then zwrocBraki;
        }
        part baza : BazaPostgres {
            event occurrence zablokujWiersz;
            event occurrence rollback;
            first zablokujWiersz then rollback;
        }

        message m01_klik of ZamiarUzytkownika from ekspert.klikZglos to frontend.odbierzKlik;
        message m02_postZgloszenie of ZapytanieHttp from frontend.wyslijZgloszenie to api.odbierzZgloszenie;
        message m03_blokada of InstrukcjaSql from api.zazadajBlokady to baza.zablokujWiersz;
        message m04_przejscie of WywolaniePrzejscia from api.wywolajPrzejscie to maszynaStanow.odbierzPrzejscie;
        message m05_requireCompute of WywolanieSprawdzeniaMocy from maszynaStanow.zapytajOMoc to moc.odczytajSonde;
        message m06_braki of BrakiMocy from moc.zwrocBraki to maszynaStanow.zglosBlad;
        message m07_rollback of InstrukcjaSql from api.wycofaj to baza.rollback;
        message m08_odpowiedz503 of OdpowiedzHttp from api.wyslijOdmowe to frontend.odbierzOdmowe;
        message m09_komunikat of ZamiarUzytkownika from frontend.pokazKomunikat to ekspert.widziKomunikat;
    }

    // =================================================================== knowledge search
    occurrence def InterakcjaWyszukiwaniaWiedzy {
        doc /* POST /knowledge-units/search: osadzenie zapytania, wyszukiwanie hybrydowe w chips, wyniki. */
        @OdwolanieDoKodu { sciezka = "backend/app/knowledge/search.py"; }

        part administrator : Administrator {
            event occurrence wpiszZapytanie;
            event occurrence widziTrafienia;
            first wpiszZapytanie then widziTrafienia;
        }
        part frontend : FrontendWebowy {
            event occurrence odbierzZapytanie;
            event occurrence wyslijWyszukiwanie;
            event occurrence odbierzTrafienia;
            event occurrence wyswietlWidok;
            first odbierzZapytanie then wyslijWyszukiwanie;
            first wyslijWyszukiwanie then odbierzTrafienia;
            first odbierzTrafienia then wyswietlWidok;
        }
        part api : BackendApi {
            event occurrence odbierzWyszukiwanie;
            event occurrence zazadajOsadzenia;
            event occurrence odbierzOsadzenie;
            event occurrence zapytajWyszukiwanie;
            event occurrence odbierzWiersze;
            event occurrence wyslijTrafienia;
            first odbierzWyszukiwanie then zazadajOsadzenia;
            first zazadajOsadzenia then odbierzOsadzenie;
            first odbierzOsadzenie then zapytajWyszukiwanie;
            first zapytajWyszukiwanie then odbierzWiersze;
            first odbierzWiersze then wyslijTrafienia;
        }
        part ollama : UslugaOllama {
            event occurrence osadz;
            event occurrence zwrocOsadzenie;
            first osadz then zwrocOsadzenie;
        }
        part baza : BazaPostgres {
            event occurrence wyszukiwanieHybrydowe;
            event occurrence zwrocWiersze;
            first wyszukiwanieHybrydowe then zwrocWiersze;
        }

        message m01_zapytanie of ZamiarUzytkownika from administrator.wpiszZapytanie to frontend.odbierzZapytanie;
        message m02_wyszukanie of ZapytanieWyszukiwania from frontend.wyslijWyszukiwanie to api.odbierzWyszukiwanie;
        message m03_osadzenie of ZapytanieOsadzenia from api.zazadajOsadzenia to ollama.osadz;
        message m04_wektor of Osadzenie from ollama.zwrocOsadzenie to api.odbierzOsadzenie;
        message m05_sql of InstrukcjaSql from api.zapytajWyszukiwanie to baza.wyszukiwanieHybrydowe;
        message m06_wiersze of WynikSql from baza.zwrocWiersze to api.odbierzWiersze;
        message m07_trafienia of WynikWyszukiwania from api.wyslijTrafienia to frontend.odbierzTrafienia;
        message m08_pokazanie of ZamiarUzytkownika from frontend.wyswietlWidok to administrator.widziTrafienia;
    }
}
