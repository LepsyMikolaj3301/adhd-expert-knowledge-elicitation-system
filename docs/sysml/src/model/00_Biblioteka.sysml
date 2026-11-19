package BibliotekaElicytacji {
    doc /*
     * Biblioteka modelu: metadane łączące elementy modelu z kodem. Każdy plik modelu importuje
     * ten pakiet.
     */

    private import ScalarValues::*;

    abstract part def Aktor {
        doc /*
         * Aktor systemu elicytacji: osoba lub system zewnętrzny, który sam korzysta z systemu
         * (ekspert, recenzent, inżynier wiedzy, lokalny LLM). Interesariusz, który z systemu nie
         * korzysta (pacjent, klinicysta), nie jest aktorem.
         */
    }

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
}
