# Model SysML v2 systemu elicytacji wiedzy eksperckiej

Model systemu w notacji tekstowej **SysML v2**, wyprowadzony z **aktualnego kodu** (nie z `docs/*.md`,
które miejscami są nieaktualne). Pokazuje jeden przepływ: od wypowiedzi pacjenta, przez sesję elicytacji
z winietą, korektę, recenzję i decyzję, po bazę wiedzy, z której korzysta **osobny RAG kliniki**.

Szczegóły i wartości oznaczone `@DoUzupelnienia` / `@Propozycja` są do uzupełnienia przez autora.

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
| `00_Biblioteka.sysml` | `BibliotekaElicytacji` | metadane `@OdwolanieDoKodu`, `@Zaimplementowane`, `@Propozycja`, `@Planowane`, `@DoUzupelnienia` |
| `01_Interesariusze.sysml` | `InteresariuszeElicytacji` | interesariusze (pacjent, ekspert, recenzent, inżynier wiedzy, klinicysta) i ich potrzeby (`concern` ZAG-01..08) |
| `02_Wymagania.sysml` | `WymaganiaElicytacji` | wymagania WYM-F / WYM-N z `frame` do potrzeb; pakiet `Spelnianie` (`satisfy`) |
| `03_Kontekst.sysml` | `KontekstElicytacji` | systemy zewnętrzne, `kontekstKliniki` (diagram kontekstu, tory procesu), przypadki użycia |
| `04_Proces.sysml` | `ProcesElicytacji` | proces biznesowy: przed systemem / system elicytacji / RAG kliniki |
| `05_Sekwencja.sysml` | `SekwencjaElicytacji` | sesja elicytacji, system jako czarna skrzynka |
| `06_Struktura.sysml` | `StrukturaElicytacji` | klasy ORM, porty, bloki (API, worker, baza), IBD systemu |
| `07_Stany.sysml` | `StanyElicytacji` | `State`, `Action`, `Actor`, `JobKind`, `JobStatus`; `AssignmentLifecycle`, `JobLifecycle` |
| `08_Widoki.sysml` | `WidokiElicytacji` | definicje widoków i 10 widoków (diagramów) |

## Widoki (diagramy)

| Widok | Diagram SysML v1 (Visual Paradigm) | Widok w SysON | Źródło |
|---|---|---|---|
| `interesariuszeIPotrzeby` | interesariusze i potrzeby (req / bdd) | General View | `01` |
| `wymagania` | Requirement Diagram (req) | General View | `02` |
| `kontekstSystemu` | IBD kontekstu | Interconnection View | `03` |
| `przypadkiUzycia` | Use Case Diagram (uc) | General View | `03` |
| `procesBiznesowy` | Activity Diagram (act) z torami | Action Flow View | `04` |
| `sekwencjaSesjiElicytacji` | Sequence Diagram (sd) | General View (SysON nie ma widoku sekwencji) | `05` |
| `strukturaSystemu` | Block Definition Diagram (bdd) | General View | `06` |
| `wnetrzeSystemu` | Internal Block Diagram (ibd) | Interconnection View | `06` |
| `stanyPrzydzialu` | State Machine Diagram (stm) | State Transition View | `07` |
| `stanyZadania` | State Machine Diagram (stm) | State Transition View | `07` |

Najważniejsze decyzje w modelu:

- **Granica systemu** to `kontekstKliniki.hosting.system`. Baza wiedzy (schemat `chips`) jest osobnym
  elementem: system tylko do niej zapisuje, RAG kliniki tylko z niej czyta (`expert-knowledge-rag`,
  transakcje READ ONLY). Fizycznie to ta sama instancja PostgreSQL co schemat `app`.
- **Inżynier wiedzy** to rola administratora w aplikacji. Deweloper (autor systemu) nie jest aktorem
  ani interesariuszem: wdrożenie, CI/CD i testy są poza modelem.
- **Tory** diagramu czynności są zapisane jako `perform` w częściach `kontekstKliniki`; wykonawca jest
  też w pierwszym zdaniu `doc` każdego kroku (na wypadek, gdyby narzędzie nie rysowało torów).
- **Gdzie leży logika** (`wnetrzeSystemu`): akcje osób idą przez API do `state_machine.transition()`,
  który w jednej transakcji zapisuje stan, zdarzenie audytowe i zadanie (`JOB_ON_ENTRY`); worker
  pobiera zadania z tabeli `jobs` i sam woła `transition()` jako `system`. Etapy przekazują sobie dane
  przez bazę, nie w pamięci.

## Słowniczek: pojęcie ↔ kod

| Pojęcie | W kodzie |
|---|---|
| winieta, wersja winiety | `Vignette`, `VignetteVersion` (`draft` → `published` → `retired`) |
| przydział | `Assignment`, stan `Assignment.state` |
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

1. **SysON** (zalecane): `docs/sysml/README.md`. `./push.sh` wysyła wszystkie pliki jako jeden dokument
   i tworzy diagram dla każdego widoku (typ diagramu z `view def`). Uwaga: kasuje i tworzy od nowa
   projekt o nazwie folderu (`model`). Po otwarciu diagramu kliknij **Arrange all**.
2. **VS Code + SysIDE (Sensmetry)**: otwórz katalog `docs/sysml/src/model/`.
3. **Visual Paradigm (SysML 1.x)**: widoki z tabeli przerysuj jako diagramy odpowiedniego typu.
   Model tekstowy pozostaje źródłem prawdy.

## Do uzupełnienia (`@DoUzupelnienia`, `@Propozycja`)

- `WYM-N-13 jakoscWyszukiwania`: `k` (4 jak w teście regresji czy 8) i próg; test regresji sprawdza
  hit@4 ≥ 0,8, MRR ≥ 0,5, nDCG@10 ≥ 0,4 (tolerancja 0,02).
- `WYM-N-11 dostepnosc`, `WYM-N-12 szybkoscDzialania`, `WYM-N-15 dostepnoscInterfejsu`: wartości docelowe.
- `WYM-N-01 modeleLokalne`, `WYM-N-09 tanieHostowanie`, `WYM-N-21 anonimowaWinieta` (@Propozycja): potwierdzić.
- `WYM-N-10 usuwanieDanychRodo` (@Planowane): element spełniający po implementacji.
- `RagKliniki` i część procesu `wykorzystanieWKlinice` (@Propozycja): to nie jest część systemu.
- Numer `WYM-F-20` jest wolny (usunięte wymaganie); numerów nie przesuwano.

## Rozbieżności kod ↔ dokumentacja

Model idzie za kodem. W `docs/` są nieaktualne opisy:

- **Brak bramki między pytaniami.** Wszystkie zadane pytania są widoczne od razu
  (`_visible_questions` w `backend/app/assignments/service.py`). Pozostałość: `GATE` w
  `backend/app/vignettes/questions.py`.
- **Inne stany przepływu** niż w `docs/backend-workflow.md`. Kod: `proofreading → proofread_check →
  peer_review → processing → ingesting`. Dokumentacja: `processing → expert_check → building_units → …`.

## Historia

Wcześniejsza, pełniejsza wersja modelu (37 widoków: plan testów, macierze alokacji, wdrożenie
produkcyjne i deweloperskie, CI/CD, parametryka, szczegółowa ścieżka przetwarzania) jest w historii
gita, w commicie `d35647d`.
