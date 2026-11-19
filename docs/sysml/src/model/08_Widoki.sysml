package WidokiElicytacji {
    doc /*
     * Widoki = diagramy modelu (12). Każdy widok wskazuje (expose) elementy i sposób renderowania.
     * Typ diagramu w SysON wynika ze specjalizacji `view def` (docs/sysml/push.sh):
     *   InterconnectionView -> Interconnection View, ActionFlowView -> Action Flow View,
     *   StateTransitionView -> State Transition View, pozostałe -> General View.
     * SysON nie ma widoku sekwencji: sekwencja trafia do General View.
     */

    private import Views::*;

    // =================================================================== renderings
    package Renderowania {
        rendering jakoDiagramWymagan {
            doc /* SysML v1: req */
        }
        rendering jakoDiagramPrzypadkowUzycia {
            doc /* SysML v1: uc */
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
    }

    private import Renderowania::*;

    // =================================================================== view definitions
    // Krótka nazwa i specjalizacja widoku standardowego
    // grupuje diagramy po nich
    view def <stk> WidokInteresariuszy :> StandardViewDefinitions::GeneralView {
        doc /* Interesariusze i ich potrzeby (concerns). */
        render jakoDiagramWymagan;
    }
    view def <req> WidokWymagan :> StandardViewDefinitions::GeneralView {
        doc /* Wymagania i potrzeby, na które odpowiadają (frame). */
        render jakoDiagramWymagan;
    }
    view def <uc> WidokPrzypadkowUzycia :> StandardViewDefinitions::GeneralView {
        render jakoDiagramPrzypadkowUzycia;
    }
    view def <sat> WidokSpelniania :> StandardViewDefinitions::GeneralView {
        doc /* Wymagania i elementy, które je spełniają (satisfy). */
        render jakoDiagramWymagan;
    }
    view def <bdd> WidokDefinicji :> StandardViewDefinitions::GeneralView {
        doc /* Bloki i ich części (odpowiednik BDD). */
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

    // =================================================================== views (diagrams)

    // ---- 1. interesariusze i potrzeby
    view interesariuszeIPotrzeby : WidokInteresariuszy {
        doc /* Aktor (z biblioteki) i jego podtypy: kto z interesariuszy sam korzysta z systemu. */
        expose BibliotekaElicytacji::Aktor;
        expose InteresariuszeElicytacji::Interesariusze::**;
        expose KontekstElicytacji::SystemyZewnetrzne::LokalnyLlm;
        expose InteresariuszeElicytacji::Potrzeby::**;
    }

    // ---- 2. wymagania
    view wymagania : WidokWymagan {
        doc /* Bez pakietu Spelnianie, żeby nie wciągać bloków struktury. */
        expose WymaganiaElicytacji::WymaganieSystemowe;
        expose WymaganiaElicytacji::Funkcjonalne::**;
        expose WymaganiaElicytacji::Niefunkcjonalne::**;
        expose InteresariuszeElicytacji::Potrzeby::**;
    }

    // ---- 2b. wymagania i ich spełnianie
    view spelnianieWymagan : WidokSpelniania {
        doc /* Każde `satisfy` łączy wymaganie z częścią systemu (API, worker, baza, hosting). */
        expose WymaganiaElicytacji::Spelnianie::**;
        expose WymaganiaElicytacji::Funkcjonalne::**;
        expose WymaganiaElicytacji::Niefunkcjonalne::**;
        expose KontekstElicytacji::kontekstKliniki::hosting::**;
        expose KontekstElicytacji::kontekstKliniki::lokalnyLlm;
    }

    // ---- 3. kontekst
    view kontekstSystemu : WidokPolaczen {
        doc /* Klinika: osoby, system elicytacji (czarna skrzynka), baza wiedzy, RAG kliniki, lokalne modele, hosting. */
        expose KontekstElicytacji::kontekstKliniki;
        expose KontekstElicytacji::kontekstKliniki::**;
    }

    // ---- 4. przypadki użycia
    view przypadkiUzycia : WidokPrzypadkowUzycia {
        expose KontekstElicytacji::PrzypadkiUzycia::**;
        expose InteresariuszeElicytacji::Interesariusze::Ekspert;
        expose InteresariuszeElicytacji::Interesariusze::Recenzent;
        expose InteresariuszeElicytacji::Interesariusze::InzynierWiedzy;
        expose KontekstElicytacji::SystemyZewnetrzne::LokalnyLlm;
    }

    // ---- 5. proces biznesowy
    view procesBiznesowy : WidokCzynnosci {
        doc /* Od wypowiedzi pacjenta do odpowiedzi klinicysty; granica: elicytacja / wykorzystanieWKlinice. */
        expose ProcesElicytacji::ProcesBiznesowy;
        expose ProcesElicytacji::ProcesBiznesowy::**;
    }

    // ---- 6. sekwencja
    view sekwencjaSesjiElicytacji : WidokSekwencji {
        doc /* System jako czarna skrzynka; linie życia: role i systemy zewnętrzne. */
        expose SekwencjaElicytacji::SesjaElicytacji;
        expose SekwencjaElicytacji::SesjaElicytacji::**;
    }

    // ---- 7. BDD
    view strukturaSystemu : WidokDefinicji {
        doc /* Bloki systemu: kontenery, moduły API, części workera. */
        expose StrukturaElicytacji::SystemElicytacji;
        expose StrukturaElicytacji::SystemElicytacji::*;
        expose StrukturaElicytacji::Frontend;
        expose StrukturaElicytacji::BackendApi;
        expose StrukturaElicytacji::BackendApi::*;
        expose StrukturaElicytacji::Worker;
        expose StrukturaElicytacji::Worker::*;
        expose StrukturaElicytacji::AppDatabase;
        expose StrukturaElicytacji::Auth;
        expose StrukturaElicytacji::Users;
        expose StrukturaElicytacji::Vignettes;
        expose StrukturaElicytacji::Assignments;
        expose StrukturaElicytacji::Assignments::*;
        expose StrukturaElicytacji::StateMachine;
        expose StrukturaElicytacji::Proofread;
        expose StrukturaElicytacji::Reviews;
        expose StrukturaElicytacji::Knowledge;
        expose StrukturaElicytacji::Compute;
        expose StrukturaElicytacji::JobQueue;
        expose StrukturaElicytacji::JobHandlers;
        expose StrukturaElicytacji::JobHandlers::*;
        expose StrukturaElicytacji::ProofreadJob;
        expose StrukturaElicytacji::ProcessJob;
        expose StrukturaElicytacji::IngestJob;
        expose StrukturaElicytacji::RefitJob;
    }

    // ---- 7b. model danych (BDD)
    view modelDanych : WidokDefinicji {
        doc /* Klasy ORM schematu app i ich powiązania; wyliczenia użyte w atrybutach. */
        expose StrukturaElicytacji::Data::*;
        expose StanyElicytacji::State;
        expose StanyElicytacji::JobKind;
        expose StanyElicytacji::JobStatus;
    }

    // ---- 8. IBD
    view wnetrzeSystemu : WidokPolaczen {
        doc /* Gdzie leży logika: API i worker przekazują sobie pracę przez bazę (tabela jobs, schemat app). */
        expose StrukturaElicytacji::SystemElicytacji;
        expose StrukturaElicytacji::SystemElicytacji::**;
    }

    // ---- 9-10. maszyny stanów
    view stanyPrzydzialu : WidokStanow {
        expose StanyElicytacji::AssignmentLifecycle;
        expose StanyElicytacji::AssignmentLifecycle::**;
    }
    view stanyZadania : WidokStanow {
        expose StanyElicytacji::JobLifecycle;
        expose StanyElicytacji::JobLifecycle::**;
    }
}
