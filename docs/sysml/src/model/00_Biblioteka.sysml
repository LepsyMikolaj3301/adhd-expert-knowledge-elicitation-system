package BibliotekaElicytacji {
    doc /*
     * Biblioteka modelu: metadane łączące elementy modelu z kodem. Każdy plik modelu importuje
     * ten pakiet.
     *
     * Konwencja oznaczeń:
     *   @Zaimplementowane - istnieje i działa w kodzie (źródło prawdy: kod, nie docs/*.md)
     *   @Propozycja       - propozycja autora modelu, do potwierdzenia
     *   @Planowane        - zaplanowane, jeszcze nie zbudowane
     *   @DoUzupelnienia   - brak wartości lub treści
     *   @OdwolanieDoKodu  - ścieżka (względem korzenia repozytorium) do kodu realizującego element
     */

    private import ScalarValues::*;

    metadata def OdwolanieDoKodu {
        doc /* Ścieżka (względem korzenia repozytorium) do kodu realizującego element. */
        attribute sciezka : String;
    }

    metadata def Zaimplementowane {
        doc /* Element istnieje i działa w obecnym kodzie. */
    }

    metadata def Propozycja {
        doc /* Propozycja - wymaga decyzji autora pracy. */
    }

    metadata def Planowane {
        doc /* Zaplanowane, jeszcze niezaimplementowane (np. usuwanie danych RODO). */
    }

    metadata def DoUzupelnienia {
        doc /* Do uzupełnienia: brak wartości lub treści. */
    }
}
