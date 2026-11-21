# Model SysML v2 systemu elicytacji wiedzy eksperckiej

Model systemu w notacji tekstowej **SysML v2**, wyprowadzony z **aktualnego kodu** (nie z `docs/*.md`,
które miejscami są nieaktualne). Pokazuje jeden przepływ: od wypowiedzi pacjenta, przez sesję elicytacji
z winietą, korektę, recenzję i decyzję, po bazę wiedzy, z której korzysta **osobny RAG kliniki**.

Wartości docelowe wymagań (atrybuty bez wartości) i elementy `@Propozycja` są do uzupełnienia przez autora.

## Konwencja nazw

- **Po polsku** (bez znaków diakrytycznych w identyfikatorach) jest poziom biznesowy: interesariusze,
  potrzeby, wymagania, przypadki użycia, kroki procesu, a także wszystkie opisy `doc`.
- **Po angielsku, dokładnie jak w kodzie**, jest to, co wskazuje kod: bloki i moduły (`assignments`,
  `state_machine`, `compute`, `jobs`), klasy ORM (`Assignment`, `Submission`, `KnowledgeUnit`, `Job`),
  stany, akcje i aktorzy przepływu (`in_progress`, `proofread_check`, `submit_for_review`, `assignee`),
  rodzaje zadań, stałe (`MAX_ATTEMPTS`, `LEASE`) i ścieżki API w komunikatach sekwencji.
  `def` są w PascalCase, a usage mają nazwę z kodu (dozwolony snake_case).
- Nazwy będące słowami kluczowymi SysML są w cudzysłowie: `'state'`, `'action'`, `'actor'`.
- `@OdwolanieDoKodu { sciezka = "..."; }` wskazuje plik lub katalog w repozytorium.

## Pliki

| Plik | Pakiet | Zawartość |
|---|---|---|
| `00_Biblioteka.sysml` | `BibliotekaElicytacji` | `Aktor` (abstrakcyjny typ bazowy aktorów); metadane `@OdwolanieDoKodu`, `@Zaimplementowane`, `@Propozycja`, `@Planowane` |
| `01_Interesariusze.sysml` | `InteresariuszeElicytacji` | interesariusze (pacjent, ekspert, recenzent, inżynier wiedzy, klinicysta) i ich potrzeby (`concern` ZAG-01..08) |
| `02_Wymagania.sysml` | `WymaganiaElicytacji` | wymagania WYM-F / WYM-N z `frame` do potrzeb; pakiet `Spelnianie` (`satisfy`) |
| `03_Kontekst.sysml` | `KontekstElicytacji` | systemy zewnętrzne, `kontekstKliniki` (diagram kontekstu, tory procesu, przepływy `flow`), przypadki użycia, `RealizacjaWymagan` (przypadek użycia → wymaganie, `#refinement`) |
| `04_Proces.sysml` | `ProcesElicytacji` | proces biznesowy: przed systemem / system elicytacji / RAG kliniki |
| `05_Sekwencja.sysml` | `SekwencjaElicytacji` | sesja elicytacji (jeden przydział), system jako czarna skrzynka (komunikaty z `StrukturaElicytacji::Ports`; odpowiedzi HTTP tylko po odpytaniu API) |
| `06_Struktura.sysml` | `StrukturaElicytacji` | klasy ORM (`Vignette`, `VignetteVersion`, `Assignment`… z powiązaniami `ref item`), komunikaty i porty (`in`/`out item`), bloki (API, worker, baza), IBD systemu z przepływami |
| `07_Stany.sysml` | `StanyElicytacji` | `State`, `Action`, `Actor`, `JobKind`, `JobStatus`; `AssignmentLifecycle`, `JobLifecycle` |
| `08_Widoki.sysml` | `WidokiElicytacji` | 12 widoków (diagramów) typowanych widokami standardowymi, pod wizualizator VS Code |

## Widoki (diagramy)

Typ widoku (widok standardowy z `StandardViewDefinitions`) wybiera diagram w wizualizatorze wtyczki
SysML v2 dla VS Code: **SysML: Visualize Model** na folderze `src/model/`, potem menu widoków →
**SysML Views** → nazwa widoku. Wizualizator rozpoznaje typ tylko po nazwie typu samego widoku, dlatego
widoki nie mają własnych `view def`.

| Widok | Typ widoku → diagram w wizualizatorze | Diagram SysML v1 (Visual Paradigm) | Źródło |
|---|---|---|---|
| `interesariuszeIPotrzeby` | `GeneralView` → General | interesariusze, aktorzy (`:> Aktor`) i potrzeby (req / bdd) | `01` |
| `wymagania` | `GeneralView` → General | Requirement Diagram (req) | `02` |
| `spelnianieWymagan` | `GeneralView` → General | Requirement Diagram (req) z relacjami satisfy | `02` |
| `kontekstSystemu` | `InterconnectionView` → Interconnection | IBD kontekstu | `03` |
| `przypadkiUzycia` | `GeneralView` → General (rysunek uc: widok Case z menu) | Use Case Diagram (uc) | `03` |
| `procesBiznesowy` | `ActionFlowView` → Action Flow | Activity Diagram (act) z torami | `04` |
| `sekwencjaSesjiElicytacji` | `SequenceView` → Sequence | Sequence Diagram (sd) | `05` |
| `strukturaSystemu` | `GeneralView` → General | Block Definition Diagram (bdd) | `06` |
| `modelDanych` | `GeneralView` → General | Block Definition Diagram (bdd), model danych | `06` |
| `wnetrzeSystemu` | `InterconnectionView` → Interconnection | Internal Block Diagram (ibd) | `06` |
| `stanyPrzydzialu` | `StateTransitionView` → State Transition | State Machine Diagram (stm) | `07` |
| `stanyZadania` | `StateTransitionView` → State Transition | State Machine Diagram (stm) | `07` |

Powiązania przypadek użycia → wymaganie (`RealizacjaWymagan`) i `satisfy` można też przejrzeć jako
macierz: **SysML: Edit Model** → Traceability.

Najważniejsze decyzje w modelu:

- **Granica systemu** to `kontekstKliniki.hosting.system`. Baza wiedzy (schemat `chips`) jest osobnym
  elementem: system tylko do niej zapisuje, RAG kliniki tylko z niej czyta (`expert-knowledge-rag`,
  transakcje READ ONLY). Fizycznie to ta sama instancja PostgreSQL co schemat `app`.
- **Interesariusz a aktor.** Aktorem jest ten, kto sam korzysta z systemu: `Ekspert` (i przez niego
  `Recenzent`), `InzynierWiedzy` i `LokalnyLlm` dziedziczą po `BibliotekaElicytacji::Aktor`. Pacjent
  i klinicysta są interesariuszami, ale nie aktorami. W SysML v2 `actor` jest rolą w przypadku
  użycia, a nie osobnym rodzajem elementu, dlatego podział zapisuje abstrakcyjny typ bazowy.
- **Inżynier wiedzy** to rola administratora w aplikacji. Deweloper (autor systemu) nie jest aktorem
  ani interesariuszem: wdrożenie, CI/CD i testy są poza modelem.
- **Tory** diagramu czynności są zapisane jako `perform` w częściach `kontekstKliniki`; wykonawca jest
  też w pierwszym zdaniu `doc` każdego kroku (na wypadek, gdyby narzędzie nie rysowało torów).
- **Gdzie leży logika** (`wnetrzeSystemu`): akcje osób idą przez API do `state_machine.transition()`,
  który w jednej transakcji zapisuje stan, zdarzenie audytowe i zadanie (`JOB_ON_ENTRY`); worker
  pobiera zadania z tabeli `jobs` i sam woła `transition()` jako `system`. Etapy przekazują sobie dane
  przez bazę, nie w pamięci. Połączenia między modułami a tabelami są logiczne; fizycznie biegną
  przez porty `sql` (delegowane wewnątrz `BackendApi`, `Worker` i `AppDatabase`).
- **Maszyny stanów są sprzężone**: wejście przydziału w stan zadania tworzy `Job` (`EnqueueJob`),
  a koniec zadania wysyła do przydziału `*_succeeded` / `*_failed` (`ReportJobResult`).
- **HTTP w sekwencji**: system niczego nie wysyła do przeglądarki sam; o końcu zadania w tle frontend
  dowiaduje się, odpytując API.

## Słowniczek: pojęcie ↔ kod

| Pojęcie | W kodzie |
|---|---|
| winieta, wersja winiety | `Vignette`, `VignetteVersion` (`draft` → `published` → `retired`) |
| przydział | `Assignment`, stan `Assignment.state` |
| sesja elicytacji | jeden przydział, od `assigned` do `ingested`; w bazie wiedzy `session_id` = id przydziału. Część eksperta (start → submit) to przypadek użycia `OdpowiedzNaWiniete` |
| szkic, zgłoszenie | `AnswerDraft`, `Submission` |
| cytat (chip [n]) | podświetlenie (`highlight`) |
| korekta, sprawdzenie korekty | `proofread` (`ProofreadRound`, `AnswerRevision`), stan `proofread_check` |
| recenzja koleżeńska | `peer_review` (`ReviewParticipant`, `AnswerComment`, `AnswerVote`) |
| decyzja | `AnswerDecision` (`approve` / `reject` / `request_changes`) |
| rekord ustaleń, jednostka wiedzy | `AnswerFindings`, `KnowledgeUnit` (`fragment`, `case`) |
| przetwarzanie, ingestia | zadania `process`, `ingest` |
| zadanie w tle | `Job`, `JobKind`, `JobStatus` |
| bramka mocy | `compute.py`, `REQUIRE_COMPUTE`, `503 compute_unavailable` |
| baza wiedzy | schemat `chips` (pgvector + BM25) |
| inżynier wiedzy, ekspert, recenzent, system | aktorzy `admin`, `assignee`, `reviewer`, `system` |

## Jak otworzyć i sprawdzić

1. **VS Code + wtyczka SysML v2** (zalecane): otwórz katalog `docs/sysml/src/model/`; diagramy przez
   **SysML: Visualize Model** (sekcja „Widoki”), eksport do PNG/SVG przez **SysML: Export Visualization**.
   Wtyczka sprawdza składnię i typy; nie sprawdza końców `flow` ani celów `dependency`.
2. **Visual Paradigm (SysML 1.x)**: widoki z tabeli przerysuj jako diagramy odpowiedniego typu.
   Model tekstowy pozostaje źródłem prawdy.
3. SysON (`docs/sysml/README.md`, `./push.sh`) nie jest już używany.

## Do uzupełnienia

- `WYM-N-15 dostepnoscInterfejsu`: `poziomWcag` (np. "2.1 AA").
- `Compute.REQUIRE_COMPUTE`: bez wartości, bo zależy od środowiska (produkcja true, dev i testy false).
- Bez `satisfy`: `WYM-N-11 dostepnosc` (0,99), `WYM-N-13 jakoscWyszukiwania` (progi z testu regresji),
  `WYM-N-15`.
- `WYM-N-01 modeleLokalne`, `WYM-N-21 anonimowaWinieta` (@Propozycja): potwierdzić.
- `WYM-N-10 usuwanieDanychRodo` (@Planowane): element spełniający po implementacji.
- `RagKliniki` i część procesu `wykorzystanieWKlinice` (@Propozycja): to nie jest część systemu.
- Numery `WYM-F-20`, `WYM-N-08`, `WYM-N-09`, `WYM-N-14` i `WYM-N-20` są wolne (usunięte wymagania); numerów nie przesuwano.

## Rozbieżności kod ↔ dokumentacja

Model idzie za kodem. W `docs/` są nieaktualne opisy:

- **Brak bramki między pytaniami.** Wszystkie zadane pytania są widoczne od razu
  (`_visible_questions` w `backend/app/assignments/service.py`). Pozostałość: `GATE` w
  `backend/app/vignettes/questions.py`.
- **Inne stany przepływu** niż w `notes/backend-workflow.md`. Kod: `proofreading → proofread_check →
  peer_review → processing → ingesting`. Dokumentacja: `processing → expert_check → building_units → …`.

## Historia

Wcześniejsza, pełniejsza wersja modelu (37 widoków: plan testów, macierze alokacji, wdrożenie
produkcyjne i deweloperskie, CI/CD, parametryka, szczegółowa ścieżka przetwarzania) jest w historii
gita, w commicie `d35647d`.
