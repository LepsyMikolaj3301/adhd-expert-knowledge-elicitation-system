package InterfejsyElicytacji {
    doc /*
     * Interfejsy: elementy przepływające (item def), porty (port def) i interfejsy (interface def).
     * Konwencja: port def opisuje stronę dostawcy usługi; strona klienta używa portu sprzężonego (~).
     */

    private import ScalarValues::*;
    private import BibliotekaElicytacji::*;
    private import DziedzinaElicytacji::TrescOdpowiedzi::*;
    private import DziedzinaElicytacji::SchematApp::*;

    // =================================================================== flowing items
    package Elementy {
        item def ZapytanieHttp {
            doc /* Żądanie REST pod /api/v1 (JSON, ciasteczko sesji). */
            attribute metoda : String;
            attribute sciezka : String;
            attribute tresc : Json[0..1];
        }

        item def OdpowiedzHttp {
            doc /* Odpowiedź REST; widoki przydziału zawierają `allowed_actions`. */
            attribute status : Integer;
            attribute tresc : Json[0..1];
        }

        item def InstrukcjaSql {
            doc /* Zapytanie SQL (asyncpg / psycopg). */
            attribute sql : String;
        }

        item def WynikSql;

        item def ZapytanieOsadzenia {
            doc /* Żądanie osadzenia tekstów modelem bge-m3. */
            attribute model : String = "bge-m3";
            attribute teksty : String[1..*];
        }

        item def Osadzenie {
            doc /* Wektor gęsty, 1024 wymiary. */
            attribute wymiary : Integer = 1024;
        }

        item def ZapytanieCzatu {
            doc /* Wywołanie lokalnego LLM (klasyfikator, korekta): num_ctx 8192. */
            attribute model : String;
            attribute prompt : String;
            attribute rozmiarKontekstu : Integer = 8192;
            attribute temperatura : Real;
        }

        item def OdpowiedzModelu {
            attribute tekst : String;
        }

        item def ZapytanieSprawdzeniaGramatyki {
            attribute tekst : String;
            attribute jezyk : String = "en-US";
        }

        item def DopasowaniaGramatyczne {
            doc /* Dopasowania LanguageTool (pisownia, gramatyka). */
            attribute dopasowania : Json;
        }

        item def ZapytanieListyModeli {
            doc /* GET /api/tags - sonda mocy obliczeniowej (backend/app/compute.py), limit 3 s. */
        }

        item def ListaModeli {
            doc /* Nazwy modeli pobranych w Ollama (np. bge-m3:latest, qwen3.5:9b). */
            attribute modele : String[0..*];
        }

        item def ZapytanieListyJezykow {
            doc /* GET /v2/languages - sonda dostępności LanguageTool, limit 3 s. */
        }

        item def ListaJezykow;

        item def ObiektWMagazynie {
            doc /* Obiekt w magazynie S3 (MinIO): surowy / sparsowany / pocięty dokument. */
            attribute bucket : String;
            attribute klucz : String;
        }

        item def ZapytanieWyszukiwania {
            doc /* POST /knowledge-units/search: pytanie klinicysty lub tekst pacjenta. */
            @OdwolanieDoKodu { sciezka = "backend/app/knowledge/schemas.py"; }
            attribute zapytanie : String;
            attribute tryb : String;     // question | patient_text
            attribute k : Integer = 8;   // 1..20
        }

        item def WynikWyszukiwania {
            @OdwolanieDoKodu { sciezka = "backend/app/knowledge/schemas.py"; }
            attribute trafienia : Json;       // rank, score, similarity, jednostka
        }
    }

    private import Elementy::*;

    // =================================================================== ports
    package Porty {
        port def PortHttp {
            doc /* Strona serwera HTTP. */
            in item zapytanie : ZapytanieHttp;
            out item odpowiedz : OdpowiedzHttp;
        }

        port def PortSql {
            doc /* Strona serwera bazy danych. */
            in item instrukcja : InstrukcjaSql;
            out item wynik : WynikSql;
        }

        port def PortOllama {
            doc /* Strona usługi Ollama: osadzanie i generowanie. */
            in item zapytanieOsadzenia : ZapytanieOsadzenia;
            out item osadzenie : Osadzenie;
            in item zapytanieCzatu : ZapytanieCzatu;
            out item odpowiedzModelu : OdpowiedzModelu;
            in item zapytanieModeli : ZapytanieListyModeli;
            out item listaModeli : ListaModeli;
        }

        port def PortLanguageTool {
            doc /* Strona usługi LanguageTool. */
            in item sprawdzenie : ZapytanieSprawdzeniaGramatyki;
            out item dopasowania : DopasowaniaGramatyczne;
            in item zapytanieJezykow : ZapytanieListyJezykow;
            out item listaJezykow : ListaJezykow;
        }

        port def PortS3 {
            doc /* Strona magazynu obiektów zgodnego z S3. */
            in item zapisz : ObiektWMagazynie;
            out item pobierz : ObiektWMagazynie;
        }
    }

    private import Porty::*;

    // =================================================================== interfaces
    package DefinicjeInterfejsow {
        interface def ApiRest {
            doc /* Przeglądarka/nginx -> FastAPI, prefiks /api/v1. */
            @OdwolanieDoKodu { sciezka = "backend/app/main.py"; }
            end klient : ~PortHttp;
            end serwer : PortHttp;
            flow of ZapytanieHttp from klient.zapytanie to serwer.zapytanie;
            flow of OdpowiedzHttp from serwer.odpowiedz to klient.odpowiedz;
        }

        interface def PolaczenieSql {
            doc /* Połączenie z Postgresem (asyncpg); na produkcji kontener w tej samej sieci compose. */
            @OdwolanieDoKodu { sciezka = "backend/app/core/db.py"; }
            end klient : ~PortSql;
            end serwer : PortSql;
            flow of InstrukcjaSql from klient.instrukcja to serwer.instrukcja;
            flow of WynikSql from serwer.wynik to klient.wynik;
        }

        interface def OllamaHttp {
            doc /* Na produkcji przez sieć Tailscale do komputera właściciela (OLLAMA_BASE_URL = http://PC_HOST:11434). */
            @OdwolanieDoKodu { sciezka = "backend/app/ollama.py"; }
            end klient : ~PortOllama;
            end serwer : PortOllama;
            flow of ZapytanieOsadzenia from klient.zapytanieOsadzenia to serwer.zapytanieOsadzenia;
            flow of Osadzenie from serwer.osadzenie to klient.osadzenie;
            flow of ZapytanieCzatu from klient.zapytanieCzatu to serwer.zapytanieCzatu;
            flow of OdpowiedzModelu from serwer.odpowiedzModelu to klient.odpowiedzModelu;
            flow of ZapytanieListyModeli from klient.zapytanieModeli to serwer.zapytanieModeli;
            flow of ListaModeli from serwer.listaModeli to klient.listaModeli;
        }

        interface def LanguageToolHttp {
            doc /* Na produkcji przez sieć Tailscale (LANGUAGETOOL_URL = http://PC_HOST:8010). */
            @OdwolanieDoKodu { sciezka = "backend/app/proofread/grammar.py"; }
            end klient : ~PortLanguageTool;
            end serwer : PortLanguageTool;
            flow of ZapytanieSprawdzeniaGramatyki from klient.sprawdzenie to serwer.sprawdzenie;
            flow of DopasowaniaGramatyczne from serwer.dopasowania to klient.dopasowania;
            flow of ZapytanieListyJezykow from klient.zapytanieJezykow to serwer.zapytanieJezykow;
            flow of ListaJezykow from serwer.listaJezykow to klient.listaJezykow;
        }

        interface def ApiS3 {
            @OdwolanieDoKodu { sciezka = "scripts/corpus/storage.py"; }
            end klient : ~PortS3;
            end serwer : PortS3;
            flow of ObiektWMagazynie from klient.zapisz to serwer.zapisz;
            flow of ObiektWMagazynie from serwer.pobierz to klient.pobierz;
        }
    }
}
