package WidokiElicytacji {
    doc /*
     * Widoki = diagramy modelu (12). Każdy widok wskazuje (expose) elementy, a jego typ wybiera
     * diagram w wizualizatorze wtyczki SysML v2 dla VS Code (SysML: Visualize Model na folderze
     * modelu, potem menu widoków -> SysML Views):
     *   StandardViewDefinitions::GeneralView         -> General (bloki, wymagania, przypadki użycia)
     *   StandardViewDefinitions::InterconnectionView -> Interconnection (IBD), render asInterconnectionDiagram
     *   StandardViewDefinitions::ActionFlowView      -> Action Flow (diagram czynności)
     *   StandardViewDefinitions::StateTransitionView -> State Transition (maszyna stanów)
     *   StandardViewDefinitions::SequenceView        -> Sequence (linie życia i komunikaty)
     * Wizualizator rozpoznaje typ tylko po nazwie typu samego widoku, dlatego widoki są typowane
     * bezpośrednio widokami standardowymi (bez własnych `view def`). Odpowiednik w SysML 1.x
     * (Visual Paradigm) jest w pierwszym zdaniu `doc` każdego widoku.
     */

    private import Views::*;
    private import StandardViewDefinitions::*;

    // =================================================================== views (diagrams)

    // ---- 1. interesariusze i potrzeby
    view interesariuszeIPotrzeby : GeneralView {
        doc /*
         * SysML 1.x: bdd/req. Interesariusze i ich potrzeby; Aktor (z biblioteki) i jego podtypy
         * pokazują, kto z interesariuszy sam korzysta z systemu.
         */
        expose BibliotekaElicytacji::Aktor;
        expose InteresariuszeElicytacji::Interesariusze::**;
        expose KontekstElicytacji::SystemyZewnetrzne::LokalnyLlm;
        expose InteresariuszeElicytacji::Potrzeby::**;
    }

    // ---- 2. wymagania
    view wymagania : GeneralView {
        doc /* SysML 1.x: req. Wymagania i potrzeby (frame); bez pakietu Spelnianie, żeby nie wciągać bloków struktury. */
        expose WymaganiaElicytacji::WymaganieSystemowe;
        expose WymaganiaElicytacji::Funkcjonalne::**;
        expose WymaganiaElicytacji::Niefunkcjonalne::**;
        expose InteresariuszeElicytacji::Potrzeby::**;
    }

    // ---- 2b. wymagania i ich spełnianie
    view spelnianieWymagan : GeneralView {
        doc /*
         * SysML 1.x: req z relacjami satisfy. Każde `satisfy` łączy wymaganie z częścią systemu
         * (API, worker, baza, hosting). Tabelę pokrycia daje też SysML: Edit Model -> Traceability.
         */
        expose WymaganiaElicytacji::Spelnianie::**;
        expose WymaganiaElicytacji::Funkcjonalne::**;
        expose WymaganiaElicytacji::Niefunkcjonalne::**;
        expose KontekstElicytacji::kontekstKliniki::hosting::**;
        expose KontekstElicytacji::kontekstKliniki::lokalnyLlm;
    }

    // ---- 3. kontekst
    view kontekstSystemu : InterconnectionView {
        doc /* SysML 1.x: ibd kontekstu. Klinika: osoby, system elicytacji (czarna skrzynka), baza wiedzy, RAG kliniki, lokalne modele, hosting. */
        render asInterconnectionDiagram;
        expose KontekstElicytacji::kontekstKliniki;
        expose KontekstElicytacji::kontekstKliniki::**;
    }

    // ---- 4. przypadki użycia
    view przypadkiUzycia : GeneralView {
        doc /*
         * SysML 1.x: uc. Przypadki użycia, aktorzy i include. W wizualizatorze także widok Case
         * z menu widoków (rysuje aktorów i przypadki użycia całego modelu, bez zawężenia expose).
         */
        expose KontekstElicytacji::PrzypadkiUzycia::**;
        expose InteresariuszeElicytacji::Interesariusze::Ekspert;
        expose InteresariuszeElicytacji::Interesariusze::Recenzent;
        expose InteresariuszeElicytacji::Interesariusze::InzynierWiedzy;
        expose KontekstElicytacji::SystemyZewnetrzne::LokalnyLlm;
    }

    // ---- 5. proces biznesowy
    view procesBiznesowy : ActionFlowView {
        doc /* SysML 1.x: act z torami. Od wypowiedzi pacjenta do odpowiedzi klinicysty; granica: elicytacja / wykorzystanieWKlinice. */
        expose ProcesElicytacji::ProcesBiznesowy;
        expose ProcesElicytacji::ProcesBiznesowy::**;
    }

    // ---- 6. sekwencja
    view sekwencjaSesjiElicytacji : SequenceView {
        doc /* SysML 1.x: sd. System jako czarna skrzynka; linie życia: role i systemy zewnętrzne, komunikaty m01-m22 (odpowiedzi HTTP tylko po odpytaniu). */
        expose SekwencjaElicytacji::SesjaElicytacji;
        expose SekwencjaElicytacji::SesjaElicytacji::**;
    }

    // ---- 7. BDD (trzy widoki, żeby diagramy były czytelne)
    view strukturaSystemu : GeneralView {
        doc /* SysML 1.x: bdd. Kontenery systemu. */
        expose StrukturaElicytacji::SystemElicytacji;
        expose StrukturaElicytacji::Frontend;
        expose StrukturaElicytacji::BackendApi;
        expose StrukturaElicytacji::Worker;
        expose StrukturaElicytacji::AppDatabase;
    }
    view strukturaApi : GeneralView {
        doc /* SysML 1.x: bdd. Moduły backendu API. */
        expose StrukturaElicytacji::BackendApi;
        expose StrukturaElicytacji::Auth;
        expose StrukturaElicytacji::Users;
        expose StrukturaElicytacji::Vignettes;
        expose StrukturaElicytacji::Assignments;
        expose StrukturaElicytacji::StateMachine;
        expose StrukturaElicytacji::Proofread;
        expose StrukturaElicytacji::Reviews;
        expose StrukturaElicytacji::Knowledge;
    }
    view strukturaWorkera : GeneralView {
        doc /* SysML 1.x: bdd. Części workera i jego zadania. */
        expose StrukturaElicytacji::Worker;
        expose StrukturaElicytacji::Compute;
        expose StrukturaElicytacji::JobQueue;
        expose StrukturaElicytacji::JobHandlers;
        expose StrukturaElicytacji::ProofreadJob;
        expose StrukturaElicytacji::ProcessJob;
        expose StrukturaElicytacji::IngestJob;
        expose StrukturaElicytacji::RefitJob;
    }

    // ---- 7b. model danych (BDD)
    view modelDanych : GeneralView {
        doc /* SysML 1.x: bdd (model danych). Klasy ORM schematu app i ich powiązania; wyliczenia użyte w atrybutach. */
        expose StrukturaElicytacji::Data::*;
        expose StanyElicytacji::State;
        expose StanyElicytacji::JobKind;
        expose StanyElicytacji::JobStatus;
    }

    // ---- 8. IBD
    view wnetrzeSystemu : InterconnectionView {
        doc /*
         * SysML 1.x: ibd. Gdzie leży logika: API i worker przekazują sobie pracę przez bazę (tabela
         * jobs, schemat app); przepływy (flow) niosą komunikaty z portów.
         */
        render asInterconnectionDiagram;
        expose StrukturaElicytacji::SystemElicytacji;
        expose StrukturaElicytacji::SystemElicytacji::**;
    }

    // ---- 9-10. maszyny stanów
    view stanyPrzydzialu : StateTransitionView {
        doc /* SysML 1.x: stm. Cykl życia przydziału (19 przejść z TRANSITIONS). */
        expose StanyElicytacji::AssignmentLifecycle;
        expose StanyElicytacji::AssignmentLifecycle::**;
    }
    view stanyZadania : StateTransitionView {
        doc /* SysML 1.x: stm. Cykl życia zadania w kolejce (jobs). */
        expose StanyElicytacji::JobLifecycle;
        expose StanyElicytacji::JobLifecycle::**;
    }
}
