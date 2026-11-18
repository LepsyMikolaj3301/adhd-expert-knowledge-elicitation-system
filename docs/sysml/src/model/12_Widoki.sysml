package WidokiElicytacji {
    doc /*
     * Widoki = "diagramy" modelu. Każdy widok wskazuje (expose) elementy i sposób renderowania.
     * Standardowe renderowania SysML v2: asTreeDiagram, asInterconnectionDiagram, asElementTable.
     * Dla typów diagramów spoza biblioteki standardowej zdefiniowano własne renderowania
     * (np. jakoDiagramStanow) - narzędzie (SysIDE, Pilot Implementation %viz, eksport do
     * Visual Paradigm) dobiera odpowiedni rodzaj diagramu.
     *
     * Odpowiedniki SysML v1:  req, uc, bdd, ibd, pkg, stm, act, sd (seq), par, tabela alokacji.
     */

    private import Views::*;
    private import BibliotekaElicytacji::*;

    // =================================================================== renderings
    package Renderowania {
        rendering jakoDiagramWymagan {
            doc /* SysML v1: req */
        }
        rendering jakoDiagramPrzypadkowUzycia {
            doc /* SysML v1: uc */
        }
        rendering jakoDiagramPakietow {
            doc /* SysML v1: pkg */
        }
        rendering jakoDiagramStanow {
            doc /* SysML v1: stm */
        }
        rendering jakoDiagramCzynnosci {
            doc /* SysML v1: act */
        }
        rendering jakoDiagramSekwencji {
            doc /* SysML v1: sd */
        }
        rendering jakoDiagramParametryczny {
            doc /* SysML v1: par */
        }
    }

    private import Renderowania::*;

    // =================================================================== view definitions
    // Krótka nazwa <...> i specjalizacja widoku standardowego są potrzebne SysON: panel Views
    // grupuje diagramy po nich (bez tego pokazuje błąd "null").
    view def <req> WidokWymagan :> StandardViewDefinitions::GeneralView {
        doc /* Wymagania, concerns i ich relacje. */
        render jakoDiagramWymagan;
    }
    view def <uc> WidokPrzypadkowUzycia :> StandardViewDefinitions::GeneralView {
        render jakoDiagramPrzypadkowUzycia;
    }
    view def <pkg> WidokPakietow :> StandardViewDefinitions::GeneralView {
        render jakoDiagramPakietow;
    }
    view def <bdd> WidokDefinicji :> StandardViewDefinitions::GeneralView {
        doc /* Hierarchia definicji (odpowiednik BDD). */
        render asTreeDiagram;
    }
    view def <ibd> WidokPolaczen :> StandardViewDefinitions::InterconnectionView {
        doc /* Części, porty i połączenia (odpowiednik IBD). */
        render asInterconnectionDiagram;
    }
    view def <stm> WidokStanow :> StandardViewDefinitions::StateTransitionView {
        render jakoDiagramStanow;
    }
    view def <act> WidokCzynnosci :> StandardViewDefinitions::ActionFlowView {
        render jakoDiagramCzynnosci;
    }
    view def <sd> WidokSekwencji :> StandardViewDefinitions::GeneralView {
        render jakoDiagramSekwencji;
    }
    view def <par> WidokParametryczny :> StandardViewDefinitions::GeneralView {
        render jakoDiagramParametryczny;
    }
    view def <tab> WidokTabelaryczny :> StandardViewDefinitions::GeneralView {
        render asElementTable;
    }

    // =================================================================== views (diagrams)

    // ---- 1. wymagania
    view wymagania : WidokWymagan {
        doc /* R1-R2: concerns i wymagania systemowe. */
        expose WymaganiaElicytacji::**;
    }
    view macierzSledzenia : WidokTabelaryczny {
        doc /* R3: satisfy + verify. */
        expose SledzenieElicytacji::**;
    }

    // ---- 2. kontekst i przypadki użycia
    view kontekstSystemu : WidokPolaczen {
        doc /* U1: system, osoby, usługi zewnętrzne. */
        expose KontekstElicytacji::kontekstElicytacji;
        expose KontekstElicytacji::kontekstElicytacji::**;
    }
    view przypadkiUzycia : WidokPrzypadkowUzycia {
        doc /* U2. */
        expose KontekstElicytacji::Aktorzy::**;
        expose KontekstElicytacji::PrzypadkyUzycia::**;
    }

    // ---- 3. struktura
    view organizacjaModelu : WidokPakietow {
        doc /* S1: pakiety modelu. */
        expose BibliotekaElicytacji;
        expose WymaganiaElicytacji;
        expose KontekstElicytacji;
        expose InterfejsyElicytacji;
        expose StrukturaElicytacji;
        expose DziedzinaElicytacji;
        expose StanyElicytacji;
        expose CzynnosciElicytacji;
        expose InterakcjeElicytacji;
        expose AnalizaElicytacji;
        expose PlatformaElicytacji;
        expose SledzenieElicytacji;
        expose SciezkaPrzetwarzania;
    }
    view dekompozycjaSystemu : WidokDefinicji {
        doc /* S2: BDD systemu. */
        expose StrukturaElicytacji::**;
    }
    view dekompozycjaBackendu : WidokDefinicji {
        doc /* S3: BDD backendu + zależności modułów. */
        expose StrukturaElicytacji::BackendApi;
        expose StrukturaElicytacji::ModulyBackendu::**;
        expose StrukturaElicytacji::ZaleznosciModulow::**;
        expose StrukturaElicytacji::Biblioteki::**;
    }
    view interfejsy : WidokDefinicji {
        doc /* S4: elementy przepływu, porty, interfejsy. */
        expose InterfejsyElicytacji::**;
    }
    view wnetrzeSystemu : WidokPolaczen {
        doc /* S5: IBD systemu. */
        expose StrukturaElicytacji::SystemElicytacji;
        expose StrukturaElicytacji::SystemElicytacji::**;
    }
    view modelDziedziny : WidokDefinicji {
        doc /* S6: model danych aplikacji. */
        expose DziedzinaElicytacji::TypyWyliczeniowe::**;
        expose DziedzinaElicytacji::TrescOdpowiedzi::**;
        expose DziedzinaElicytacji::SchematApp::**;
    }
    view modelDanychRag : WidokDefinicji {
        doc /* S6b: schemat chips. */
        expose DziedzinaElicytacji::SchematChips::**;
    }

    // ---- 3b. ścieżka przetwarzania wypełnionej winiety (13_SciezkaPrzetwarzania)
    view sciezkaPrzetwarzaniaBdd : WidokDefinicji {
        doc /* S7: BDD - komponenty ścieżki, artefakty i porty artefaktów. */
        expose SciezkaPrzetwarzania::SciezkaPrzetwarzaniaWiniety;
        expose SciezkaPrzetwarzania::Komponenty::**;
        expose SciezkaPrzetwarzania::Artefakty::**;
        expose SciezkaPrzetwarzania::PortyArtefaktow::**;
    }
    view sciezkaPrzetwarzaniaIbd : WidokPolaczen {
        doc /* S8: IBD - od zgłoszenia przez kolejkę, worker i magazyn stanu do chips. */
        expose SciezkaPrzetwarzania::SciezkaPrzetwarzaniaWiniety;
        expose SciezkaPrzetwarzania::SciezkaPrzetwarzaniaWiniety::**;
    }
    view wnetrzeKorekty : WidokPolaczen {
        doc /* S9: IBD zadania proofread - PREPARE (rozbiór, korekta odpowiedzi, warstwy powiązań, flagi) i zapis rundy. */
        expose SciezkaPrzetwarzania::Komponenty::EtapKorekty::**;
        expose SciezkaPrzetwarzania::Komponenty::PrzygotowanieKorekty::**;
        expose SciezkaPrzetwarzania::Komponenty::KorektaOdpowiedzi::**;
    }
    view wnetrzeCieciaIIngestii : WidokPolaczen {
        doc /* S10: IBD zadań process i ingest. */
        expose SciezkaPrzetwarzania::Komponenty::EtapCiecia::**;
        expose SciezkaPrzetwarzania::Komponenty::EtapIngestii::**;
    }
    view alokacjaSciezki : WidokTabelaryczny {
        doc /* A4: części ścieżki -> moduły i kontenery. */
        expose SciezkaPrzetwarzania::AlokacjaSciezki::**;
    }

    // ---- 4. zachowanie
    view stanyPrzydzialu : WidokStanow {
        doc /* B1. */
        expose StanyElicytacji::CyklZyciaPrzydzialu;
        expose StanyElicytacji::CyklZyciaPrzydzialu::**;
    }
    view stanyWiniety : WidokStanow {
        doc /* B2. */
        expose StanyElicytacji::CyklZyciaWersjiWiniety;
        expose StanyElicytacji::CyklZyciaWersjiWiniety::**;
    }
    view stanyZadania : WidokStanow {
        expose StanyElicytacji::CyklZyciaZadania;
        expose StanyElicytacji::CyklZyciaZadania::**;
    }
    view odOdpowiedziDoWiedzy : WidokCzynnosci {
        doc /* B3: z torami z PlatformaElicytacji::AlokacjaCzynnosci. */
        expose CzynnosciElicytacji::OdOdpowiedziDoWiedzy;
        expose CzynnosciElicytacji::OdOdpowiedziDoWiedzy::**;
        expose PlatformaElicytacji::AlokacjaCzynnosci::**;
    }
    view potokKorekty : WidokCzynnosci {
        expose CzynnosciElicytacji::PotokKorekty;
        expose CzynnosciElicytacji::PotokKorekty::**;
    }
    view jednostkiIIngestia : WidokCzynnosci {
        expose CzynnosciElicytacji::ZbudujJednostki;
        expose CzynnosciElicytacji::ZbudujJednostki::**;
        expose CzynnosciElicytacji::IngestujJednostki;
        expose CzynnosciElicytacji::IngestujJednostki::**;
    }
    view zapytanieRag : WidokCzynnosci {
        doc /* B5. */
        expose CzynnosciElicytacji::ZapytanieRag;
        expose CzynnosciElicytacji::ZapytanieRag::**;
    }
    view sekwencjaZgloszenia : WidokSekwencji {
        doc /* B6. */
        expose InterakcjeElicytacji::InterakcjaZgloszeniaOdpowiedzi;
        expose InterakcjeElicytacji::InterakcjaZgloszeniaOdpowiedzi::**;
    }
    view sekwencjaZadania : WidokSekwencji {
        doc /* B7. */
        expose InterakcjeElicytacji::InterakcjaWykonaniaZadania;
        expose InterakcjeElicytacji::InterakcjaWykonaniaZadania::**;
    }
    view wykonanieZadania : WidokCzynnosci {
        doc /* B8: run_once z decyzjami (moc, dzierżawa, rodzaje błędów). */
        expose CzynnosciElicytacji::WykonanieZadania;
        expose CzynnosciElicytacji::WykonanieZadania::**;
    }
    view sekwencjaOdmowyBezMocy : WidokSekwencji {
        doc /* B9: 503 compute_unavailable. */
        expose InterakcjeElicytacji::InterakcjaOdmowyBezMocy;
        expose InterakcjeElicytacji::InterakcjaOdmowyBezMocy::**;
    }
    view sekwencjaWyszukiwania : WidokSekwencji {
        expose InterakcjeElicytacji::InterakcjaWyszukiwaniaWiedzy;
        expose InterakcjeElicytacji::InterakcjaWyszukiwaniaWiedzy::**;
    }

    // ---- 5. parametryka
    view budzetLlm : WidokParametryczny {
        doc /* P2. */
        expose AnalizaElicytacji::budzetWywolanLlm;
        expose AnalizaElicytacji::budzetWywolanLlm::**;
    }
    view parametrykaJakosciRag : WidokParametryczny {
        doc /* P1. */
        expose AnalizaElicytacji::jakoscRag;
        expose AnalizaElicytacji::jakoscRag::**;
    }
    view parametrykaWdrozenia : WidokParametryczny {
        doc /* P3: budżet pamięci VM, puls dzierżawy, wiek sondy mocy. */
        expose AnalizaElicytacji::budzetPamieciVm;
        expose AnalizaElicytacji::budzetPamieciVm::**;
        expose AnalizaElicytacji::niezawodnoscZadan;
        expose AnalizaElicytacji::niezawodnoscZadan::**;
    }

    // ---- 6. platforma i alokacje
    view wdrozenieProdukcyjne : WidokPolaczen {
        doc /* A2: VM Azure (compose) + komputer z modelami przez Tailscale. */
        expose PlatformaElicytacji::PlatformaProd;
        expose PlatformaElicytacji::PlatformaProd::**;
        expose PlatformaElicytacji::AlokacjaProd::**;
    }
    view wdrozenieDeweloperskie : WidokPolaczen {
        doc /* A3. */
        expose PlatformaElicytacji::PlatformaDev;
        expose PlatformaElicytacji::PlatformaDev::**;
        expose PlatformaElicytacji::AlokacjaDev::**;
    }
    view platformaCiCd : WidokPolaczen {
        doc /* A5: GitHub Actions, rejestr obrazów, środowisko testowe. */
        expose PlatformaElicytacji::PlatformaCiCd;
        expose PlatformaElicytacji::PlatformaCiCd::**;
        expose PlatformaElicytacji::SrodowiskoTestowe;
        expose PlatformaElicytacji::SrodowiskoTestowe::**;
    }
    view potokWdrozenia : WidokCzynnosci {
        doc /* B10: workflow Deploy z torami (runner, VM). */
        expose PlatformaElicytacji::WdrozenieWydania;
        expose PlatformaElicytacji::WdrozenieWydania::**;
    }
    view planTestow : WidokTabelaryczny {
        doc /* R4: przypadki testowe z poziomem i informacją, czy działają w CI. */
        expose SledzenieElicytacji::Weryfikacja::**;
    }
    view macierzAlokacji : WidokTabelaryczny {
        doc /* A1: czynności -> wykonawcy, oprogramowanie -> węzły. */
        expose PlatformaElicytacji::AlokacjaCzynnosci::**;
        expose PlatformaElicytacji::AlokacjaDev::**;
        expose PlatformaElicytacji::AlokacjaProd::**;
        expose SciezkaPrzetwarzania::AlokacjaSciezki::**;
    }
}
