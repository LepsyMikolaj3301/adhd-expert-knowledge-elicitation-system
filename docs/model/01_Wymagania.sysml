package WymaganiaElicytacji {
    doc /*
     * Wymagania (diagram wymagań). Źródłem wymagań oznaczonych @Zaimplementowane jest kod
     * (nie docs/*.md, które mogą być nieaktualne). Pozostałe: @Propozycja / @Planowane / @DoUzupelnienia -
     * do uzupełnienia przez autora pracy.
     *
     * Identyfikatory:  ZAG-xx concern,  WYM-F-xx funkcjonalne,  WYM-N-xx niefunkcjonalne.
     * Relacje satisfy / verify: SledzenieElicytacji.
     */

    private import ScalarValues::*;
    private import ISQ::DurationValue;
    private import SI::*;
    private import BibliotekaElicytacji::*;
    private import StrukturaElicytacji::SystemElicytacji;
    private import KontekstElicytacji::Aktorzy::*;

    // =================================================================== base definition
    requirement def WymaganieSystemowe {
        doc /* Wymaganie systemowe; podmiotem jest cały system. */
        subject system : SystemElicytacji;
    }

    // =================================================================== stakeholder concerns
    package Zagadnienia {
        concern <'ZAG-01'> wiernoscWiedzy {
            doc /* Wiedza w bazie to dosłowne słowa eksperta, nie parafraza modelu. */
            stakeholder inzynier : InzynierWiedzy;
            stakeholder odbiorca : OdbiorcaRag;
        }

        concern <'ZAG-02'> odpowiedziBezWplywu {
            doc /* Odpowiedzi eksperta nie są zabarwione lekturą cudzych odpowiedzi. */
            stakeholder inzynier : InzynierWiedzy;
        }

        concern <'ZAG-03'> malyNakladEksperta {
            doc /* Ekspert poświęca czas na wiedzę, nie na obsługę narzędzia. */
            stakeholder ekspert : Ekspert;
        }

        concern <'ZAG-04'> kontrolaNadBazaWiedzy {
            doc /* Administrator decyduje, co trafia do bazy wiedzy, i może to usunąć. */
            stakeholder administrator : Administrator;
        }

        concern <'ZAG-05'> prywatnosc {
            doc /* Dane ekspertów są chronione i pseudonimizowane; RODO. */
            stakeholder podmiotDanych : PodmiotDanych;
        }

        concern <'ZAG-06'> sladowalnosc {
            doc /* Każdą zmianę stanu i każdą jednostkę da się odtworzyć do źródła. */
            stakeholder inzynier : InzynierWiedzy;
            stakeholder administrator : Administrator;
        }
    }

    private import Zagadnienia::*;

    // =================================================================== functional
    package Funkcjonalne {

        // ---------------------------------------------------- access
        requirement <'WYM-F-01'> dostepWgRol : WymaganieSystemowe {
            doc /* System rozróżnia role admin i expert; każde wywołanie API sprawdza uprawnienia roli. */
            @Zaimplementowane;
            @OdwolanieDoKodu { sciezka = "backend/app/users/models.py"; }
        }

        requirement <'WYM-F-02'> kontaTylkoZZaproszen : WymaganieSystemowe {
            doc /* Konto eksperta powstaje tylko z zaproszenia administratora (ważnego 7 dni). */
            @Zaimplementowane;
            @OdwolanieDoKodu { sciezka = "backend/app/auth/service.py"; }
            attribute waznoscZaproszenia : DurationValue = 7 [d];
        }

        // ---------------------------------------------------- vignettes
        requirement <'WYM-F-03'> wersjonowanieWiniet : WymaganieSystemowe {
            doc /* Winieta ma wersje o statusie draft -> published -> retired. */
            @Zaimplementowane;
            @OdwolanieDoKodu { sciezka = "backend/app/vignettes/models.py"; }
        }

        requirement <'WYM-F-04'> przydzialTylkoOpublikowanych : WymaganieSystemowe {
            doc /* Przydzielić można tylko wersję opublikowaną; jedna wersja - wielu ekspertów. */
            @Zaimplementowane;
            @OdwolanieDoKodu { sciezka = "backend/app/assignments/service.py"; }
        }

        requirement <'WYM-F-05'> ukrytyProjektWiniety : WymaganieSystemowe {
            doc /* Pole `design` (zaplanowane wskazówki, notatki punktacji) nigdy nie trafia do ekspertów ani recenzentów. */
            @Zaimplementowane;
            @OdwolanieDoKodu { sciezka = "backend/app/assignments/schemas.py"; }
            frame odpowiedziBezWplywu;
        }

        // ---------------------------------------------------- answering
        requirement <'WYM-F-06'> wszystkiePytaniaWidoczne : WymaganieSystemowe {
            doc /* Ekspert widzi od razu wszystkie zadane pytania wersji winiety (question_ids). */
            @Zaimplementowane;
            @OdwolanieDoKodu { sciezka = "backend/app/assignments/service.py"; }
        }

        requirement <'WYM-F-07'> cytatyZgodneZWinieta : WymaganieSystemowe {
            doc /*
             * Cytaty (chipy) są numerowane od 1 bez przerw, ich zakres odpowiada dokładnie tekstowi
             * winiety, a każdy chip [n] w odpowiedzi wskazuje istniejący cytat.
             */
            @Zaimplementowane;
            @OdwolanieDoKodu { sciezka = "backend/app/assignments/answers.py"; }
            frame wiernoscWiedzy;
        }

        requirement <'WYM-F-08'> kierunekCytatu : WymaganieSystemowe {
            doc /* Przy zgłoszeniu każdy cytat ma kierunek: toward / away / neutral / unclear. */
            @Zaimplementowane;
            @OdwolanieDoKodu { sciezka = "backend/app/assignments/answers.py"; }
        }

        requirement <'WYM-F-09'> kompletneZgloszenie : WymaganieSystemowe {
            doc /*
             * Zgłoszenie wymaga odpowiedzi na każde zadane pytanie otwarte (długość nie jest
             * sprawdzana). Q4: hipoteza robocza, przesunięcie -2..+2, kierunek przy przesunięciu > 0,
             * uzasadnienie przy przesunięciu != 0. Q6: ocena 1-5 albo "za mało informacji".
             */
            @Zaimplementowane;
            @OdwolanieDoKodu { sciezka = "backend/app/assignments/answers.py"; }
            frame malyNakladEksperta;
        }

        requirement <'WYM-F-10'> autozapisSzkicu : WymaganieSystemowe {
            doc /* Szkic zapisuje się z numerem wersji; nieaktualna karta dostaje draft_conflict zamiast nadpisać tekst. */
            @Zaimplementowane;
            @OdwolanieDoKodu { sciezka = "backend/app/assignments/service.py"; }
        }

        requirement <'WYM-F-11'> niezmienneZgloszenie : WymaganieSystemowe {
            doc /*
             * Zgłoszenie jest niezmienne (wyzwalacz w bazie) i zawiera skrót winiety oraz pseudonim
             * eksperta.
             */
            @Zaimplementowane;
            @OdwolanieDoKodu { sciezka = "backend/app/assignments/models.py"; }
            frame sladowalnosc;
        }

        // ---------------------------------------------------- workflow
        requirement <'WYM-F-12'> jedenPunktPrzejsc : WymaganieSystemowe {
            doc /*
             * Stan przydziału zmienia wyłącznie transition(): w jednej transakcji zmienia stan,
             * zapisuje zdarzenie audytowe i kolejkuje zadanie nowego stanu.
             */
            @Zaimplementowane;
            @OdwolanieDoKodu { sciezka = "backend/app/assignments/state_machine.py"; }
            frame sladowalnosc;
        }

        requirement <'WYM-F-13'> dozwoloneAkcje : WymaganieSystemowe {
            doc /* Każdy widok przydziału zawiera allowed_actions - frontend nie powiela reguł przepływu. */
            @Zaimplementowane;
            @OdwolanieDoKodu { sciezka = "backend/app/assignments/service.py"; }
        }

        requirement <'WYM-F-14'> automatycznaKorekta : WymaganieSystemowe {
            doc /*
             * Po zgłoszeniu system poprawia pisownię (LanguageTool), proponuje redakcję (LLM),
             * odrzuca zdania-śmieci i wiąże zdania odpowiedzi z cytatami.
             */
            @Zaimplementowane;
            @OdwolanieDoKodu { sciezka = "backend/app/proofread/pipeline.py"; }
            frame malyNakladEksperta;
        }

        requirement <'WYM-F-15'> autorSprawdzaKorekte : WymaganieSystemowe {
            doc /* Autor sprawdza i może poprawić wynik korekty i powiązania przed oddaniem do recenzji. */
            @Zaimplementowane;
            @OdwolanieDoKodu { sciezka = "backend/app/proofread/service.py"; }
            frame wiernoscWiedzy;
        }

        requirement <'WYM-F-16'> otwartaRecenzja : WymaganieSystemowe {
            doc /*
             * Odpowiedzi w recenzji może czytać każdy aktywny ekspert poza autorem i osobami, które
             * same mają jeszcze odpowiedzieć na tę winietę. Otwarcie recenzji jest rejestrowane i
             * wyklucza recenzenta z przydziału tej winiety.
             */
            @Zaimplementowane;
            @OdwolanieDoKodu { sciezka = "backend/app/reviews/access.py"; }
            frame odpowiedziBezWplywu;
        }

        requirement <'WYM-F-17'> administratorDecyduje : WymaganieSystemowe {
            doc /*
             * Recenzenci komentują i głosują, ale tylko administrator decyduje (per pytanie):
             * zatwierdza, odrzuca albo odsyła do autora - wtedy zaczyna się nowa runda.
             */
            @Zaimplementowane;
            @OdwolanieDoKodu { sciezka = "backend/app/reviews/service.py"; }
            frame kontrolaNadBazaWiedzy;
        }

        requirement <'WYM-F-18'> budowaJednostek : WymaganieSystemowe {
            doc /* Zatwierdzone odpowiedzi są cięte na jednostki wiedzy (fragment przy cytacie, przypadek). */
            @Zaimplementowane;
            @OdwolanieDoKodu { sciezka = "backend/app/knowledge/findings.py"; }
            frame wiernoscWiedzy;
        }

        requirement <'WYM-F-19'> ingestiaJednostek : WymaganieSystemowe {
            doc /* Jednostki są osadzane (bge-m3 + BM25) i zapisywane w schemacie chips. */
            @Zaimplementowane;
            @OdwolanieDoKodu { sciezka = "backend/app/knowledge/ingest.py"; }
        }

        requirement <'WYM-F-21'> ponawianieNieudanychZadan : WymaganieSystemowe {
            doc /* Administrator ponawia nieudaną korektę, przetwarzanie lub ingestię. */
            @Zaimplementowane;
            @OdwolanieDoKodu { sciezka = "backend/app/assignments/service.py"; }
        }

        requirement <'WYM-F-22'> sladAudytowy : WymaganieSystemowe {
            doc /* Każde przejście stanu zapisuje zdarzenie audytowe (kto, co, z jakiego stanu do jakiego). */
            @Zaimplementowane;
            @OdwolanieDoKodu { sciezka = "backend/app/audit/models.py"; }
            frame sladowalnosc;
        }

        // ---------------------------------------------------- knowledge base
        requirement <'WYM-F-23'> wyszukiwanieWiedzy : WymaganieSystemowe {
            doc /* Wyszukiwanie jednostek: pytanie klinicysty albo tekst pacjenta, k = 1..20. */
            @Zaimplementowane;
            @OdwolanieDoKodu { sciezka = "backend/app/knowledge/search.py"; }
            attribute maksymalneK : Integer = 20;
        }

        requirement <'WYM-F-24'> usuwanieWiedzy : WymaganieSystemowe {
            doc /* Administrator usuwa jednostkę albo całą wiedzę eksperta; indeks BM25 jest przeliczany. */
            @Zaimplementowane;
            @OdwolanieDoKodu { sciezka = "backend/app/knowledge/removal.py"; }
            frame kontrolaNadBazaWiedzy;
        }

        requirement <'WYM-F-25'> odpowiedziRag : WymaganieSystemowe {
            doc /* Odpowiedzi generowane na podstawie jednostek wiedzy w czasie zapytania. */
            @Planowane;
            @OdwolanieDoKodu { sciezka = "packages/expert-knowledge-rag/src/expert_knowledge_rag/chains.py"; }
        }
    }

    // =================================================================== non-functional
    package Niefunkcjonalne {

        requirement <'WYM-N-01'> modeleLokalne : WymaganieSystemowe {
            doc /*
             * Modele językowe działają lokalnie (Ollama na komputerze właściciela, osiągalnym z serwera
             * tylko przez sieć Tailscale); treść odpowiedzi nie trafia do zewnętrznych usług AI.
             */
            @Propozycja;
            frame prywatnosc;
        }

        requirement <'WYM-N-02'> budzetKontekstu : WymaganieSystemowe {
            doc /* Każde wywołanie LLM mieści się w oknie kontekstu małego modelu. */
            @Zaimplementowane;
            @OdwolanieDoKodu { sciezka = "backend/app/knowledge/classifier.py"; }
            attribute rozmiarKontekstu : Integer = 8192;
        }

        requirement <'WYM-N-03'> ograniczonePonawianieZadan : WymaganieSystemowe {
            doc /*
             * Zadanie ma najwyżej 3 próby; dzierżawa 5 min odnawiana w trakcie pracy, więc zadanie
             * po awarii workera jest przejmowane po jednej dzierżawie.
             */
            @Zaimplementowane;
            @OdwolanieDoKodu { sciezka = "backend/app/jobs/queue.py"; }
            attribute maksymalnaLiczbaProb : Integer = 3;
            attribute dzierzawa : DurationValue = 5 [min];
        }

        requirement <'WYM-N-04'> ochronaLogowania : WymaganieSystemowe {
            doc /* Konto blokowane po 5 nieudanych logowaniach; ta sama odpowiedź dla każdego błędu. */
            @Zaimplementowane;
            @OdwolanieDoKodu { sciezka = "backend/app/auth/service.py"; }
            attribute maksymalnaLiczbaNieudanychLogowan : Integer = 5;
            require constraint { system.backend.uwierzytelnianie.maksymalnaLiczbaNieudanychLogowan <= maksymalnaLiczbaNieudanychLogowan }
        }

        requirement <'WYM-N-05'> czasZyciaSesji : WymaganieSystemowe {
            doc /* Sesja wygasa po 12 h (SESSION_TTL_HOURS). */
            @Zaimplementowane;
            @OdwolanieDoKodu { sciezka = "backend/app/settings.py"; }
            attribute waznoscSesji : DurationValue = 12 [h];
        }

        requirement <'WYM-N-06'> pseudonimizacja : WymaganieSystemowe {
            doc /* Zgłoszenia i baza wiedzy identyfikują eksperta pseudonimem, nie nazwiskiem. */
            @Zaimplementowane;
            @OdwolanieDoKodu { sciezka = "backend/app/assignments/service.py"; }
            frame prywatnosc;
        }

        requirement <'WYM-N-07'> skalowalneWorkery : WymaganieSystemowe {
            doc /* Wiele workerów może działać równolegle bez pobrania tego samego zadania (SKIP LOCKED). */
            @Zaimplementowane;
            @OdwolanieDoKodu { sciezka = "backend/app/jobs/queue.py"; }
        }

        requirement <'WYM-N-08'> bezpieczneMigracje : WymaganieSystemowe {
            doc /*
             * Migracja przed uruchomieniem nowego kodu (usługa `migrate` w compose; API i worker startują
             * po jej sukcesie); każda zgodna z działającym wydaniem (najpierw dodaj, usuń później).
             */
            @Zaimplementowane;
            @OdwolanieDoKodu { sciezka = "infra/azure/deploy.sh"; }
        }

        requirement <'WYM-N-09'> tanieHostowanie : WymaganieSystemowe {
            doc /*
             * Jedna mała maszyna wirtualna (Azure Standard_B2s, 4 GB) z limitami pamięci kontenerów;
             * modele (GPU) na komputerze właściciela; maszynę można wyłączać (płaci się wtedy tylko
             * za dysk i adres IP). Budżet pamięci: AnalizaElicytacji::budzetPamieciVm.
             */
            @Propozycja;
            @OdwolanieDoKodu { sciezka = "infra/azure/docker-compose.yml"; }
            attribute pamiecVmGB : Integer = 4;
        }

        requirement <'WYM-N-10'> usuwanieDanychRodo : WymaganieSystemowe {
            doc /* Usunięcie danych na dwóch poziomach: jedna jednostka; całe zgłoszenie lub ekspert z odpowiedziami. */
            @Planowane;
            frame prywatnosc;
        }

        requirement <'WYM-N-11'> dostepnosc : WymaganieSystemowe {
            doc /*
             * Dostępność usługi w okresie zbierania danych. Zależy od dwóch maszyn: VM (aplikacja)
             * i komputera właściciela (modele) - bez niego zgłoszenia i decyzje czekają (WYM-N-16).
             */
            @DoUzupelnienia;
            attribute docelowaDostepnosc : Real;   // do uzupełnienia, np. 0.99
        }

        requirement <'WYM-N-12'> szybkoscDzialania : WymaganieSystemowe {
            doc /* Czas odpowiedzi interfejsu (bez zadań w tle). */
            @DoUzupelnienia;
            attribute czasOdpowiedziP95 : DurationValue;   // do uzupełnienia
        }

        requirement <'WYM-N-13'> jakoscWyszukiwania : WymaganieSystemowe {
            doc /* Jakość wyszukiwania na zbiorze ewaluacyjnym (patrz AnalizaElicytacji::JakoscWyszukiwania). */
            @DoUzupelnienia;
            attribute minimalnaPelnoscAtK : Real;   // do uzupełnienia
            attribute k : Integer = 8;
        }

        requirement <'WYM-N-14'> jakoscOdpowiedzi : WymaganieSystemowe {
            doc /* Jakość odpowiedzi RAG oceniana przez sędziów LLM. */
            @DoUzupelnienia;
            attribute minimalnaOcenaSedziow : Real;  // do uzupełnienia
        }

        requirement <'WYM-N-15'> dostepnoscInterfejsu : WymaganieSystemowe {
            doc /* Interfejs dostępny (WCAG). */
            @Propozycja;
            @DoUzupelnienia;
        }

        // ---------------------------------------------------- wdrożenie: modele na osobnej maszynie
        requirement <'WYM-N-16'> gotowoscMocyPrzedZadaniem : WymaganieSystemowe {
            doc /*
             * Gdy komputer z modelami nie jest gotowy, żądanie osoby, które zakolejkowałoby zadanie
             * wymagające modeli, dostaje 503 compute_unavailable (z listą braków), zanim cokolwiek się
             * zmieni: przydział zostaje w swoim stanie, zadanie nie powstaje. API nie czeka na sieć pod
             * blokadą wiersza - czyta ostatnią sondę.
             */
            @Zaimplementowane;
            @OdwolanieDoKodu { sciezka = "backend/app/compute.py"; }
            frame malyNakladEksperta;
            attribute limitCzasuSondy : DurationValue = 3 [s];
            attribute maksymalnyWiekSondy : DurationValue = 30 [s];
        }

        requirement <'WYM-N-17'> zadaniaCzekajaNaMoc : WymaganieSystemowe {
            doc /*
             * Worker nie pobiera zadania, którego maszyna nie działa; błąd zadania przy niedziałającej
             * maszynie nie zużywa próby. Korekta nie pomija wtedy LanguageTool ani modelu redakcji -
             * autor nie dostaje niesprawdzonej odpowiedzi.
             */
            @Zaimplementowane;
            @OdwolanieDoKodu { sciezka = "backend/app/jobs/worker.py"; }
            frame wiernoscWiedzy;
        }

        requirement <'WYM-N-18'> kontrolaZdrowiaUslug : WymaganieSystemowe {
            doc /*
             * Każdy długo działający kontener ma kontrolę zdrowia (API /api/v1/health, worker - plik
             * życia nie starszy niż 60 s, frontend /healthz, Postgres pg_isready); wdrożenie czeka, aż
             * API, worker i frontend będą zdrowe, a potem robi test dymny.
             */
            @Zaimplementowane;
            @OdwolanieDoKodu { sciezka = "infra/azure/docker-compose.yml"; }
            attribute maksymalnyWiekPlikuZycia : DurationValue = 60 [s];
            attribute czasOczekiwaniaNaZdrowie : DurationValue = 180 [s];
        }

        requirement <'WYM-N-19'> kopieZapasoweBazy : WymaganieSystemowe {
            doc /* Codzienna kopia bazy (pg_dump), przechowywana 7 dni; także po starcie wyłączonej na noc VM. */
            @Zaimplementowane;
            @OdwolanieDoKodu { sciezka = "infra/azure/backup.sh"; }
            frame sladowalnosc;
            attribute przechowywanie : DurationValue = 7 [d];
        }

        requirement <'WYM-N-20'> ograniczonaEkspozycjaSieci : WymaganieSystemowe {
            doc /*
             * Z internetu dostępne są tylko porty 80 i 443 (TLS, certyfikat Let's Encrypt); Postgres
             * nie jest publikowany; Ollama i LanguageTool słuchają na 127.0.0.1 i są osiągalne tylko
             * przez sieć Tailscale; SSH do VM i wdrożenie idą przez Tailscale.
             */
            @Zaimplementowane;
            @OdwolanieDoKodu { sciezka = "infra/azure/Caddyfile"; }
            frame prywatnosc;
        }
    }
}
