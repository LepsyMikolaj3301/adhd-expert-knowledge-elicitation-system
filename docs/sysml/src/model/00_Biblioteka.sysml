package BibliotekaElicytacji {
    doc /*
     * Biblioteka modelu: metadane łączące elementy modelu z kodem oraz wspólne typy atrybutów.
     * Każdy plik modelu importuje ten pakiet.
     *
     * Konwencja oznaczeń:
     *   @Zaimplementowane - wymaganie/element istnieje w kodzie (źródło prawdy: kod, nie docs/*.md)
     *   @Propozycja       - propozycja autora modelu, do potwierdzenia
     *   @Planowane        - zaplanowane, jeszcze nie zbudowane
     *   @DoUzupelnienia   - wartość lub treść do uzupełnienia
     *   @OdwolanieDoKodu  - ścieżka do pliku w repozytorium, z którego element wyprowadzono
     */

    private import ScalarValues::*;

    // ------------------------------------------------------------------ metadata

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
        doc /* Zaplanowane, jeszcze niezaimplementowane (np. usuwanie danych RODO, worker na produkcji). */
    }

    metadata def DoUzupelnienia {
        doc /* Do uzupełnienia: brak wartości lub treści. */
    }

    // ------------------------------------------------------------------ common value types

    attribute def Uuid :> String {
        doc /* Identyfikator UUID (kolumny `id` w schemacie `app`). */
    }

    attribute def ZnacznikCzasu :> String {
        doc /* Znacznik czasu ze strefą (timestamptz), ISO 8601. */
    }

    attribute def Sha256 :> String {
        doc /* Skrót SHA-256 zapisany szesnastkowo (64 znaki), np. content_hash. */
    }

    attribute def Json :> String {
        doc /* Dokument JSONB - struktura opisana w kodzie, w modelu traktowana jako całość. */
    }

    attribute def IdPytania :> String {
        doc /* Identyfikator pytania winiety: Q1..Q6 (backend/app/vignettes/questions.py). */
    }
}
