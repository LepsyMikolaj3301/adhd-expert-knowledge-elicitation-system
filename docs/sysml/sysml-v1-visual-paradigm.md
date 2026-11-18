# Model SysML v1 w Visual Paradigm: specyfikacja krok po kroku

Ten dokument opisuje, jak odtworzyć w Visual Paradigm (SysML 1.x) model systemu elicytacji wiedzy
eksperckiej: drzewo pakietów, bibliotekę (stereotypy, typy, wyliczenia, sygnały, porty) i 13 diagramów
w 10 grupach. Każdy element ma tu dokładną nazwę, typ i relacje.

**Źródłem prawdy jest model SysML v2** w `docs/sysml/src/model/` (zgodny z kodem). Model w Visual
Paradigm to jego obraz w notacji SysML v1, do rysunków w pracy. Gdy coś się zmieni, najpierw zmienia
się model v2, potem diagram v1. Diagramy 09 i 10 (model wiedzy, od odpowiedzi do jednostki) nie mają
jeszcze odpowiednika w modelu v2; ich treść pochodzi wprost z kodu (ścieżki podane przy elementach).

Nazwy menu Visual Paradigm podano dla wersji 17.x; w innych wersjach mogą się nieznacznie różnić.

---

## 0. Zasady

### 0.1 Nazwy

| Rodzaj elementu | Konwencja | Przykład |
|---|---|---|
| bloki, części, porty, stany, literały, sygnały (to, co wskazuje kod) | **dokładnie jak w kodzie / w modelu v2**, bez spacji | `StateMachine`, `state_machine`, `proofread_check` |
| interesariusze, systemy zewnętrzne, pakiety biznesowe | nazwa z modelu v2 (ASCII, PascalCase) | `InzynierWiedzy`, `RagKliniki` |
| wymagania, potrzeby, przypadki użycia, akcje w czynnościach | **czytelna polska nazwa** (z polskimi znakami, ze spacjami); nazwę z modelu v2 wpisz w *Documentation* jako `v2: <nazwa>` | „Dostęp według ról” (`v2: dostepWgRol`) |
| identyfikatory wymagań | pole **ID** wymagania | `WYM-F-01`, `ZAG-03` |

### 0.2 Ramka i nazwa diagramu

Każdy diagram SysML v1 ma ramkę z nagłówkiem (SysML 1.x, Annex A):
`<rodzaj> [<typ elementu>] <nazwa elementu> [<nazwa diagramu>]`.
W tym dokumencie przy każdym diagramie jest gotowy nagłówek. Nazwę diagramu w Visual Paradigm
ustaw na część w ostatnich nawiasach (np. `07a Bloki systemu`), a nagłówek wpisz w ramce diagramu
(*Diagram Frame*, jeśli wersja go pokazuje) albo w polu nazwy. Numer na początku nazwy utrzymuje
kolejność diagramów w drzewie.

### 0.3 Dokumentacja i odwołania do kodu

- Opis elementu (pole *Documentation*) przepisz z kolumny „opis” tabel poniżej.
- Element wskazujący kod dostaje stereotyp `«OdwolanieDoKodu»` z wartością znacznika `sciezka`
  (ścieżka względem korzenia repozytorium).
- Status realizacji: stereotyp `«Zaimplementowane»`, `«Propozycja»`, `«Planowane»` albo
  `«DoUzupelnienia»` (jak metadane w modelu v2).

### 0.4 Kolejność pracy

1. Projekt i pakiety (rozdział 1).
2. Biblioteka (rozdział 2), bo z niej korzystają wszystkie diagramy.
3. Diagramy w kolejności numerów 01–10. Bloki twórz w Model Explorer w docelowym pakiecie, a na
   diagramy przeciągaj je z drzewa; nie twórz tego samego bloku drugi raz na innym diagramie
   (zawsze *drag & drop* z Model Explorer, żeby był to ten sam element modelu).

---

## 1. Projekt i drzewo pakietów

1. *Project > New*, nazwa projektu: **`SystemElicytacjiWiedzy`**.
2. W *Model Explorer* utwórz model **`ModelSystemu`** (prawy klik na projekcie > *Model*), a w nim
   pakiety (prawy klik > *Package*) dokładnie o tych nazwach:

```
SystemElicytacjiWiedzy
└── ModelSystemu
    ├── 00 Biblioteka
    │   ├── ProfilElicytacji          (profil ze stereotypami; rozdz. 2.1)
    │   ├── TypyWartosci              (rozdz. 2.2)
    │   ├── Wyliczenia                (rozdz. 2.3)
    │   ├── Sygnaly                   (rozdz. 2.4)
    │   └── PortyIElementyPrzeplywu   (rozdz. 2.5)
    ├── 01 Interesariusze             diagram: 01 Interesariusze i potrzeby
    ├── 02 Wymagania                  diagramy: 02a, 02b, 02c
    │   ├── Funkcjonalne
    │   ├── Niefunkcjonalne
    │   └── Spelnianie                (tylko relacje «satisfy»)
    ├── 03 Kontekst                   diagramy: 03a, 03b
    │   └── SystemyZewnetrzne
    ├── 04 PrzypadkiUzycia            diagram: 04 Przypadki użycia
    ├── 05 ProcesBiznesowy            diagram: 05 Proces biznesowy
    ├── 06 Sekwencja                  diagram: 06 Sesja elicytacji
    ├── 07 Struktura                  diagramy: 07a, 07b
    │   ├── ModulyApi
    │   └── Worker
    ├── 08 Stany                      diagramy: 08a, 08b
    ├── 09 ModelWiedzy                diagramy: 09a, 09b
    │   ├── SchematApp
    │   └── SchematChips
    └── 10 OdOdpowiedziDoJednostki    diagram: 10 Od odpowiedzi do jednostki
```

3. Każdy diagram twórz prawym klikiem na jego pakiecie (*New Diagram*), żeby diagram leżał
   w pakiecie, którego dotyczy.

---

## 2. Pakiet `00 Biblioteka`

### 2.1 `ProfilElicytacji`: stereotypy

*Window > Configuration > Configure Stereotypes* (albo prawy klik na elemencie > *Stereotypes >
Edit Stereotypes...*). Utwórz stereotypy i zapisz je w profilu `ProfilElicytacji`:

| Stereotyp | Dotyczy (Base Type) | Znaczniki (Tagged Value Definitions) | Znaczenie |
|---|---|---|---|
| `OdwolanieDoKodu` | każdy element (Class, Requirement, State Machine, Activity, Port, Property) | `sciezka : Text` | ścieżka do kodu realizującego element |
| `Zaimplementowane` | Class, Requirement | — | istnieje i działa w kodzie |
| `Propozycja` | Class, Requirement, Activity, Connector | — | propozycja, do potwierdzenia |
| `Planowane` | Class, Requirement | — | zaplanowane, niezbudowane |
| `DoUzupelnienia` | Requirement | — | brak wartości lub treści |
| `stakeholder` | Actor | — | interesariusz (rola) |
| `stakeholderNeed` | Requirement | — | potrzeba interesariusza (ZAG-xx) |
| `external` | Class (Block), Actor | — | element poza granicą systemu |

Stereotypy SysML (`«block»`, `«requirement»`, `«satisfy»`, `«deriveReqt»`, `«trace»`,
`«ValueType»`, `«InterfaceBlock»`, `«allocate»`) są wbudowane w Visual Paradigm; nie twórz ich.

### 2.2 `TypyWartosci`

Utwórz `«ValueType»` (*Block Definition Diagram* > *Value Type*, albo w Model Explorer):

| Nazwa | Typ bazowy | Jednostka | Użycie |
|---|---|---|---|
| `CzasTrwania` | Real | wpisywana w wartości domyślnej (`s`, `min`, `h`, `d`) | `LEASE`, `TIMEOUT`, `INVITE_TTL` itd. |

Typy proste (`String`, `Integer`, `Real`, `Boolean`) bierz z wbudowanych typów Visual Paradigm.

### 2.3 `Wyliczenia`

Utwórz *Enumeration* z literałami **dokładnie w tej kolejności i pisowni** (to wartości z kodu):

| Wyliczenie | Literały | Kod |
|---|---|---|
| `State` | `assigned`, `in_progress`, `proofreading`, `proofread_check`, `peer_review`, `processing`, `processing_failed`, `ingesting`, `ingestion_failed`, `ingested`, `rejected`, `cancelled` | `backend/app/assignments/states.py` |
| `Action` | `start`, `cancel`, `submit`, `proofread_succeeded`, `proofread_failed`, `submit_for_review`, `processing_succeeded`, `processing_failed`, `retry_proofread`, `retry_processing`, `retry_ingestion`, `approve_answers`, `request_changes`, `reject_all_answers`, `ingestion_succeeded`, `ingestion_failed` | jw. |
| `Actor` | `assignee`, `admin`, `reviewer`, `system` | jw. |
| `Role` | `admin`, `expert` | `backend/app/users/models.py` |
| `JobKind` | `proofread`, `process`, `ingest`, `refit` | `backend/app/jobs/models.py` |
| `JobStatus` | `queued`, `running`, `done`, `failed` | jw. |
| `DecisionValue` | `approve`, `reject`, `request_changes` | `backend/app/reviews/models.py` |
| `UnitStatus` | `pending`, `approved`, `rejected`, `ingested`, `superseded`, `removed` | `backend/app/knowledge/models.py` |
| `UnitKind` | `fragment`, `case` | `backend/app/knowledge/findings.py` |
| `Direction` | `toward`, `away`, `neutral`, `unclear` | `backend/app/assignments/answers.py` |
| `VersionStatus` | `draft`, `published`, `retired` | `backend/app/vignettes/models.py` |

Każdemu wyliczeniu nadaj `«OdwolanieDoKodu»` ze ścieżką z ostatniej kolumny.

### 2.4 `Sygnaly`

Sygnały są wyzwalaczami przejść w maszynach stanów (08a, 08b) i komunikatami w sekwencji.
Utwórz *Signal* (w Model Explorer: prawy klik na pakiecie > *New Model Element > Signal*):

1. `WorkflowSignal` z atrybutem `actor : Actor`.
2. 16 sygnałów dziedziczących z `WorkflowSignal` (relacja *Generalization* do `WorkflowSignal`):
   `Start`, `Cancel`, `Submit`, `ProofreadSucceeded`, `ProofreadFailed`, `SubmitForReview`,
   `ProcessingSucceeded`, `ProcessingFailed`, `RetryProofread`, `RetryProcessing`, `RetryIngestion`,
   `ApproveAnswers`, `RequestChanges`, `RejectAllAnswers`, `IngestionSucceeded`, `IngestionFailed`.
3. Sygnały zadań (bez dziedziczenia):
   - `Claim` z atrybutem `kind_ready : Boolean` (rodzaj zadania jest w `compute.ready_kinds()`);
   - `JobSucceeded`;
   - `JobError` z atrybutami `permanent : Boolean` (`PermanentJobError`) i `compute_down : Boolean`
     (`compute.is_down_for(kind)`);
   - `LeaseExpired`.

### 2.5 `PortyIElementyPrzeplywu`

**Typy portów** (`«InterfaceBlock»`; port po stronie klienta to ten sam typ z zaznaczonym
*Is Conjugated*, oznaczany `~`):

| InterfaceBlock | Opis (Documentation) |
|---|---|
| `HttpPort` | REST `/api/v1`, JSON, ciasteczko sesji |
| `SqlPort` | PostgreSQL (asyncpg w aplikacji, psycopg w expert-knowledge-rag) |
| `OllamaPort` | Ollama: `/api/chat` (redakcja, klasyfikator), `/api/embed` (bge-m3), `/api/tags` (sonda) |
| `LanguageToolPort` | LanguageTool: `/v2/check`, `/v2/languages` (sonda) |

**Elementy przepływu** (`«block»`, używane jako *Item Flow* na połączeniach IBD):
`WypowiedzPacjenta` (wypowiedź pacjenta, materiał winiety), `HttpRequest`, `HttpResponse`,
`ModelRequest`, `ModelResponse`, `SqlStatement`, `SqlRows`. Klasy danych (`Job`, `KnowledgeUnit`
itd.) tworzysz w pakiecie `09 ModelWiedzy` (rozdz. 11) i też używasz ich jako elementów przepływu;
jeśli rysujesz w kolejności numerów, utwórz te bloki od razu (same nazwy), a atrybuty dodaj w 09.

---

## 3. Grupa 01: interesariusze i potrzeby

**Diagram:** *Requirement Diagram* w pakiecie `01 Interesariusze`, nazwa **`01 Interesariusze i potrzeby`**.
Nagłówek: `req [Package] 01 Interesariusze [01 Interesariusze i potrzeby]`.

### 3.1 Interesariusze (*Actor* `«stakeholder»`, pakiet `01 Interesariusze`)

| Nazwa | Stereotypy | Opis (Documentation) |
|---|---|---|
| `Pacjent` | `«stakeholder»` | Interesariusz pośredni. Jego wypowiedzi inżynier wiedzy przerabia na winietę. Nie korzysta z systemu. |
| `Ekspert` | `«stakeholder»`, `«OdwolanieDoKodu» sciezka=backend/app/users/models.py` | Psychiatra lub psycholog. Odpowiada na winiety, sprawdza korektę. Kod: rola `expert`, aktor `assignee`. |
| `Recenzent` | `«stakeholder»`, `«OdwolanieDoKodu» sciezka=backend/app/reviews/access.py` | Ekspert czytający i komentujący odpowiedzi kolegi (aktor `reviewer`). Nie jest osobnym kontem. |
| `InzynierWiedzy` | `«stakeholder»`, `«OdwolanieDoKodu» sciezka=backend/app/users/models.py` | Administrator aplikacji (rola `admin`): winiety, przydziały, decyzje, ponowienia, baza wiedzy. To rola, nie osoba. |
| `Klinicysta` | `«stakeholder»` | Użytkownik RAG kliniki. Nie loguje się do systemu elicytacji. |

Relacja: **`Recenzent` → `Ekspert`: *Generalization*** (Recenzent jest Ekspertem).

### 3.2 Potrzeby (*Requirement* `«stakeholderNeed»`, pakiet `01 Interesariusze`)

| ID | Nazwa | v2 | Tekst (Text) | Interesariusze («trace» od potrzeby do aktora) |
|---|---|---|---|---|
| ZAG-01 | Wierność wiedzy | `wiernoscWiedzy` | Wiedza w bazie to słowa eksperta, sprawdzone przez niego po korekcie, a nie parafraza modelu językowego. | InzynierWiedzy, Klinicysta |
| ZAG-02 | Odpowiedzi bez wpływu | `odpowiedziBezWplywu` | Odpowiedź eksperta nie jest zabarwiona lekturą cudzych odpowiedzi ani zamysłem autora winiety. | InzynierWiedzy |
| ZAG-03 | Mały nakład eksperta | `malyNakladEksperta` | Ekspert poświęca czas na wiedzę, nie na obsługę narzędzia. | Ekspert |
| ZAG-04 | Kontrola nad bazą wiedzy | `kontrolaNadBazaWiedzy` | Inżynier wiedzy decyduje, co trafia do bazy wiedzy, i może to z niej usunąć. | InzynierWiedzy |
| ZAG-05 | Prywatność eksperta | `prywatnoscEksperta` | Dane ekspertów są chronione; w zgłoszeniach i w bazie wiedzy ekspert nie występuje z nazwiska (RODO). | Ekspert |
| ZAG-06 | Śladowalność | `sladowalnosc` | Każdą zmianę stanu i każdą jednostkę wiedzy da się odtworzyć do źródła: ekspert, winieta, cytat, decyzja. | InzynierWiedzy, Klinicysta |
| ZAG-07 | Ochrona danych pacjenta | `ochronaDanychPacjenta` | Z winiety ani z bazy wiedzy nie da się zidentyfikować pacjenta. | Pacjent |
| ZAG-08 | Wiedza dla RAG kliniki | `wiedzaDlaRagKliniki` | Klinika może dołączyć wiedzę ekspercką do swojego RAG obok dokumentów medycznych, bez przebudowy tego RAG i bez prawa zapisu do bazy wiedzy. | Klinicysta |

### 3.3 Kroki

1. Przeciągnij 5 aktorów w górny rząd: `Pacjent`, `Ekspert`, `Recenzent`, `InzynierWiedzy`, `Klinicysta`.
   Narysuj generalizację `Recenzent` → `Ekspert`.
2. Pod nimi utwórz 8 potrzeb (shape *Requirement*), wpisz ID i Text, nadaj `«stakeholderNeed»`.
3. Narysuj zależności `«trace»` z każdej potrzeby do jej interesariuszy (ostatnia kolumna; 11 relacji).

---

## 4. Grupa 02: wymagania

**Diagramy** (*Requirement Diagram*, pakiet `02 Wymagania`):

| Nazwa diagramu | Nagłówek | Zawartość |
|---|---|---|
| `02a Wymagania funkcjonalne` | `req [Package] 02 Wymagania [02a Wymagania funkcjonalne]` | wymaganie-kontener `WYM-F`, 24 wymagania funkcjonalne, potrzeby, na które odpowiadają, relacje `«deriveReqt»` |
| `02b Wymagania niefunkcjonalne` | `req [Package] 02 Wymagania [02b Wymagania niefunkcjonalne]` | kontener `WYM-N`, 20 wymagań, potrzeby, `«deriveReqt»` |
| `02c Spełnianie` | `req [Package] Spelnianie [02c Spełnianie]` | bloki z 07 i 03 + relacje `«satisfy»` (opcjonalnie; patrz 4.4) |

### 4.1 Kroki

1. W pakiecie `Funkcjonalne` utwórz wymaganie-kontener **ID `WYM-F`, nazwa „Wymagania funkcjonalne”**;
   w `Niefunkcjonalne` kontener **ID `WYM-N`, nazwa „Wymagania niefunkcjonalne”**.
2. Każde wymaganie z tabel 4.2 i 4.3 utwórz jako *Requirement* w odpowiednim pakiecie, wpisz ID, nazwę,
   Text, stereotypy statusu i `«OdwolanieDoKodu»`. Połącz je z kontenerem relacją **zawierania**
   (*Containment*, kółko z krzyżykiem przy kontenerze).
3. Przeciągnij z `01 Interesariusze` potrzeby z kolumny „pochodzi z” i narysuj **`«deriveReqt»`
   od wymagania do potrzeby** (strzałka od wymagania pochodnego do źródłowego).
4. Wartości (np. 7 dni, 3 próby) są w tekście wymagania; SysML v1 nie ma atrybutów wymagań.

### 4.2 Wymagania funkcjonalne (pakiet `Funkcjonalne`)

Numer WYM-F-20 jest wolny (usunięte wymaganie); numerów nie przesuwaj.

| ID | Nazwa | v2 | Tekst | Status | sciezka | «deriveReqt» do |
|---|---|---|---|---|---|---|
| WYM-F-01 | Dostęp według ról | `dostepWgRol` | System rozróżnia role admin i expert; każde wywołanie API sprawdza uprawnienia roli. | Zaimplementowane | `backend/app/auth/dependencies.py` | — |
| WYM-F-02 | Konta tylko z zaproszeń | `kontaTylkoZZaproszen` | Konto eksperta powstaje tylko z zaproszenia inżyniera wiedzy, ważnego 7 dni (INVITE_TTL). | Zaimplementowane | `backend/app/auth/service.py` | — |
| WYM-F-03 | Wersjonowanie winiet | `wersjonowanieWiniet` | Winieta ma wersje o statusie draft → published → retired. | Zaimplementowane | `backend/app/vignettes/models.py` | — |
| WYM-F-04 | Przydział tylko opublikowanych | `przydzialTylkoOpublikowanych` | Przydzielić można tylko wersję opublikowaną; jedna wersja – wielu ekspertów. | Zaimplementowane | `backend/app/assignments/service.py` | — |
| WYM-F-05 | Ukryty projekt winiety | `ukrytyProjektWiniety` | Pole design (zaplanowane wskazówki, notatki punktacji) nigdy nie trafia do ekspertów ani recenzentów. | Zaimplementowane | `backend/app/assignments/schemas.py` | ZAG-02 |
| WYM-F-06 | Wszystkie pytania widoczne | `wszystkiePytaniaWidoczne` | Ekspert widzi od razu wszystkie zadane pytania wersji winiety. | Zaimplementowane | `backend/app/assignments/service.py` | — |
| WYM-F-07 | Cytaty zgodne z winietą | `cytatyZgodneZWinieta` | Cytaty (chipy) są numerowane od 1 bez przerw, ich zakres odpowiada dokładnie tekstowi winiety, a każdy chip [n] w odpowiedzi wskazuje istniejący cytat. | Zaimplementowane | `backend/app/assignments/answers.py` | ZAG-01 |
| WYM-F-08 | Kierunek cytatu | `kierunekCytatu` | Przy zgłoszeniu każdy cytat ma kierunek: toward / away / neutral / unclear. | Zaimplementowane | `backend/app/assignments/answers.py` | — |
| WYM-F-09 | Kompletne zgłoszenie | `kompletneZgloszenie` | Zgłoszenie wymaga odpowiedzi na każde zadane pytanie otwarte. Q4: hipoteza robocza, przesunięcie −2..+2, kierunek przy przesunięciu > 0, uzasadnienie przy przesunięciu ≠ 0. Q6: ocena 1–5 albo „za mało informacji”. | Zaimplementowane | `backend/app/assignments/answers.py` | ZAG-03 |
| WYM-F-10 | Autozapis szkicu | `autozapisSzkicu` | Szkic zapisuje się z numerem wersji; nieaktualna karta dostaje draft_conflict zamiast nadpisać tekst. | Zaimplementowane | `backend/app/assignments/service.py` | ZAG-03 |
| WYM-F-11 | Niezmienne zgłoszenie | `niezmienneZgloszenie` | Zgłoszenie (Submission) jest niezmienne (wyzwalacz w bazie) i zawiera skrót winiety oraz pseudonim eksperta. | Zaimplementowane | `backend/app/assignments/models.py` | ZAG-06 |
| WYM-F-12 | Jeden punkt przejść | `jedenPunktPrzejsc` | Stan przydziału zmienia wyłącznie transition(): w jednej transakcji zmienia stan, zapisuje zdarzenie audytowe i kolejkuje zadanie nowego stanu (JOB_ON_ENTRY). | Zaimplementowane | `backend/app/assignments/state_machine.py` | ZAG-06 |
| WYM-F-13 | Dozwolone akcje | `dozwoloneAkcje` | Każdy widok przydziału zawiera allowed_actions – frontend nie powiela reguł przepływu. | Zaimplementowane | `backend/app/assignments/service.py` | — |
| WYM-F-14 | Automatyczna korekta | `automatycznaKorekta` | Po zgłoszeniu system poprawia pisownię (LanguageTool), proponuje redakcję (LLM), odrzuca zdania-śmieci i wiąże zdania odpowiedzi z cytatami. | Zaimplementowane | `backend/app/proofread/pipeline.py` | ZAG-03 |
| WYM-F-15 | Autor sprawdza korektę | `autorSprawdzaKorekte` | Autor sprawdza i może poprawić wynik korekty i powiązania przed oddaniem do recenzji. | Zaimplementowane | `backend/app/proofread/service.py` | ZAG-01 |
| WYM-F-16 | Otwarta recenzja | `otwartaRecenzja` | Odpowiedzi w recenzji może czytać każdy aktywny ekspert poza autorem i osobami, które same mają jeszcze odpowiedzieć na tę winietę. Otwarcie recenzji jest rejestrowane i wyklucza recenzenta z przydziału tej winiety. | Zaimplementowane | `backend/app/reviews/access.py` | ZAG-02 |
| WYM-F-17 | Administrator decyduje | `administratorDecyduje` | Recenzenci komentują i głosują, ale tylko inżynier wiedzy (admin) decyduje, per pytanie: approve, reject albo request_changes – wtedy zaczyna się nowa runda. | Zaimplementowane | `backend/app/reviews/service.py` | ZAG-04 |
| WYM-F-18 | Budowa jednostek | `budowaJednostek` | Zatwierdzone odpowiedzi są cięte na jednostki wiedzy (fragment przy cytacie, case – cały przypadek). | Zaimplementowane | `backend/app/knowledge/findings.py` | ZAG-01 |
| WYM-F-19 | Ingestia jednostek | `ingestiaJednostek` | Jednostki są osadzane (bge-m3 + BM25) i zapisywane w bazie wiedzy (schemat chips). | Zaimplementowane | `backend/app/knowledge/ingest.py` | ZAG-06 |
| WYM-F-21 | Ponawianie nieudanych zadań | `ponawianieNieudanychZadan` | Inżynier wiedzy ponawia nieudaną korektę, przetwarzanie lub ingestię (retry). | Zaimplementowane | `backend/app/assignments/service.py` | — |
| WYM-F-22 | Ślad audytowy | `sladAudytowy` | Każde przejście stanu zapisuje zdarzenie audytowe (kto, co, z jakiego stanu do jakiego). | Zaimplementowane | `backend/app/audit/service.py` | ZAG-06 |
| WYM-F-23 | Wyszukiwanie wiedzy | `wyszukiwanieWiedzy` | Podgląd bazy wiedzy dla inżyniera wiedzy: wyszukiwanie jednostek tymi samymi retrieverami co RAG kliniki (pytanie albo tekst pacjenta), k = 1..20. | Zaimplementowane | `backend/app/knowledge/router.py` | ZAG-04 |
| WYM-F-24 | Usuwanie wiedzy | `usuwanieWiedzy` | Inżynier wiedzy usuwa jednostkę albo całą wiedzę eksperta; indeks BM25 jest przeliczany (zadanie refit). | Zaimplementowane | `backend/app/knowledge/removal.py` | ZAG-04 |
| WYM-F-25 | Udostępnienie bazy wiedzy | `udostepnienieBazyWiedzy` | Baza wiedzy (schemat chips) jest dostępna dla zewnętrznego RAG przez bibliotekę expert-knowledge-rag, tylko do odczytu (transakcje READ ONLY). Zapisuje do niej tylko system elicytacji. | Zaimplementowane | `packages/expert-knowledge-rag/src/expert_knowledge_rag/store.py` | ZAG-08 |

### 4.3 Wymagania niefunkcjonalne (pakiet `Niefunkcjonalne`)

Numer WYM-N-14 jest wolny (usunięte: jakość odpowiedzi RAG należy do RAG kliniki).

| ID | Nazwa | v2 | Tekst | Status | sciezka | «deriveReqt» do |
|---|---|---|---|---|---|---|
| WYM-N-01 | Modele lokalne | `modeleLokalne` | Modele językowe działają lokalnie (Ollama na komputerze właściciela, osiągalnym tylko przez Tailscale); odpowiedzi i tekst winiet nie trafiają do zewnętrznych usług AI. | Propozycja | — | ZAG-05, ZAG-07 |
| WYM-N-02 | Budżet kontekstu | `budzetKontekstu` | Każde wywołanie LLM mieści się w oknie kontekstu małego modelu (num_ctx 8192). | Zaimplementowane | `backend/app/knowledge/classifier.py` | — |
| WYM-N-03 | Ograniczone ponawianie zadań | `ograniczonePonawianieZadan` | Zadanie ma najwyżej 3 próby (MAX_ATTEMPTS); dzierżawa 5 min (LEASE) odnawiana w trakcie pracy, więc zadanie po awarii workera jest przejmowane po jednej dzierżawie. | Zaimplementowane | `backend/app/jobs/queue.py` | — |
| WYM-N-04 | Ochrona logowania | `ochronaLogowania` | Po 5 nieudanych logowaniach konto jest blokowane na 15 min (MAX_FAILED_LOGINS, LOCKOUT); ta sama odpowiedź dla każdego błędu logowania. | Zaimplementowane | `backend/app/auth/service.py` | — |
| WYM-N-05 | Czas życia sesji | `czasZyciaSesji` | Sesja wygasa po 12 h (SESSION_TTL_HOURS). | Zaimplementowane | `backend/app/settings.py` | — |
| WYM-N-06 | Pseudonimizacja | `pseudonimizacja` | Zgłoszenia i baza wiedzy identyfikują eksperta pseudonimem, nie nazwiskiem. | Zaimplementowane | `backend/app/assignments/service.py` | ZAG-05 |
| WYM-N-07 | Skalowalne workery | `skalowalneWorkery` | Wiele workerów może działać równolegle bez pobrania tego samego zadania (FOR UPDATE SKIP LOCKED). | Zaimplementowane | `backend/app/jobs/queue.py` | — |
| WYM-N-08 | Bezpieczne migracje | `bezpieczneMigracje` | Migracja przed uruchomieniem nowego kodu (usługa migrate w compose; API i worker startują po jej sukcesie); każda zgodna z działającym wydaniem. | Zaimplementowane | `infra/azure/deploy.sh` | — |
| WYM-N-09 | Tanie hostowanie | `tanieHostowanie` | Jedna mała maszyna wirtualna (Azure Standard_B2s, 4 GB) z limitami pamięci kontenerów; modele na komputerze właściciela; maszynę można wyłączać. | Propozycja | `infra/azure/docker-compose.yml` | — |
| WYM-N-10 | Usuwanie danych (RODO) | `usuwanieDanychRodo` | Usunięcie danych na dwóch poziomach: jedna jednostka; całe zgłoszenie lub ekspert z odpowiedziami. | Planowane | — | ZAG-05 |
| WYM-N-11 | Dostępność | `dostepnosc` | Dostępność usługi w okresie zbierania danych (wartość do uzupełnienia, np. 0,99). Zależy od VM i komputera z modelami. | DoUzupelnienia | — | — |
| WYM-N-12 | Szybkość działania | `szybkoscDzialania` | Czas odpowiedzi interfejsu (p95, bez zadań w tle) – do uzupełnienia. | DoUzupelnienia | — | — |
| WYM-N-13 | Jakość wyszukiwania | `jakoscWyszukiwania` | Jakość wyszukiwania jednostek na zbiorze ewaluacyjnym. Do rozstrzygnięcia: k = 4 czy 8; test regresji sprawdza hit@4 ≥ 0,8, MRR ≥ 0,5, nDCG@10 ≥ 0,4. | DoUzupelnienia | — | ZAG-08 |
| WYM-N-15 | Dostępność interfejsu | `dostepnoscInterfejsu` | Interfejs dostępny (WCAG) – poziom do uzupełnienia. | Propozycja, DoUzupelnienia | — | ZAG-03 |
| WYM-N-16 | Gotowość mocy przed zadaniem | `gotowoscMocyPrzedZadaniem` | Gdy komputer z modelami nie jest gotowy, żądanie osoby, które zakolejkowałoby zadanie wymagające modeli, dostaje 503 compute_unavailable, zanim cokolwiek się zmieni. API czyta ostatnią sondę (limit 3 s, wiek ≤ 30 s). | Zaimplementowane | `backend/app/compute.py` | ZAG-03 |
| WYM-N-17 | Zadania czekają na moc | `zadaniaCzekajaNaMoc` | Worker nie pobiera zadania, którego maszyna nie działa; błąd przy niedziałającej maszynie nie zużywa próby; korekta nie pomija wtedy LanguageTool ani modelu. | Zaimplementowane | `backend/app/jobs/worker.py` | ZAG-01 |
| WYM-N-18 | Kontrola zdrowia usług | `kontrolaZdrowiaUslug` | Każdy długo działający kontener ma kontrolę zdrowia (API /api/v1/health, worker – plik życia ≤ 60 s, frontend /healthz, Postgres pg_isready); wdrożenie czeka na zdrowie (180 s), potem test dymny. | Zaimplementowane | `infra/azure/docker-compose.yml` | — |
| WYM-N-19 | Kopie zapasowe bazy | `kopieZapasoweBazy` | Codzienna kopia bazy (pg_dump), przechowywana 7 dni. | Zaimplementowane | `infra/azure/backup.sh` | ZAG-06 |
| WYM-N-20 | Ograniczona ekspozycja sieci | `ograniczonaEkspozycjaSieci` | Z internetu tylko porty 80 i 443 (TLS); Postgres niepublikowany; Ollama i LanguageTool tylko przez Tailscale; SSH i wdrożenie przez Tailscale. | Zaimplementowane | `infra/azure/Caddyfile` | ZAG-05, ZAG-07 |
| WYM-N-21 | Anonimowa winieta | `anonimowaWinieta` | Tekst winiety nie zawiera danych pozwalających zidentyfikować pacjenta. Obowiązek inżyniera wiedzy; kod tego nie sprawdza. | Propozycja | — | ZAG-07 |

### 4.4 Spełnianie (`«satisfy»`, pakiet `Spelnianie`, diagram `02c`)

Relację rysuj **od bloku do wymagania** (`«satisfy»`). Bloki powstają w rozdziałach 5 i 9; wróć tu
po narysowaniu 07a. Diagram `02c` jest opcjonalny: relacje możesz też utworzyć na diagramie i usunąć
same widoki (*Delete View*), żeby zostały w modelu bez zaśmiecania rysunku. W SysML v1 `«satisfy»`
wskazuje blok, nie konkretną część; kolumna „część w modelu v2” mówi, która to część.

| Wymaganie | Blok (`«satisfy»` od bloku) | Część w modelu v2 |
|---|---|---|
| WYM-F-01, WYM-F-02, WYM-N-04, WYM-N-05 | `Auth` | `system.api.auth` |
| WYM-F-03 | `Vignettes` | `system.api.vignettes` |
| WYM-F-04, F-05, F-06, F-07, F-08, F-09, F-10, F-13, F-21, WYM-N-06 | `Assignments` | `system.api.assignments` |
| WYM-F-12, WYM-F-22 | `StateMachine` | `system.api.assignments.state_machine` |
| WYM-F-15 | `Proofread` | `system.api.proofread` |
| WYM-F-16, WYM-F-17 | `Reviews` | `system.api.reviews` |
| WYM-F-23, WYM-F-24 | `Knowledge` | `system.api.knowledge` |
| WYM-N-16, WYM-N-17 | `Compute` | `system.api.compute`, `system.worker.compute` |
| WYM-F-14, WYM-N-02 | `ProofreadJob` | `system.worker.handlers.proofread` |
| WYM-F-18 | `ProcessJob` | `system.worker.handlers.process` |
| WYM-F-19 | `IngestJob` | `system.worker.handlers.ingest` |
| WYM-N-03, WYM-N-07 | `JobQueue` | `system.worker.queue` |
| WYM-F-11 | `AppDatabase` | `system.db` |
| WYM-F-25 | `BazaWiedzyEksperckiej` | `hosting.bazaWiedzy` |
| WYM-N-01 | `LokalnyLlm` | `lokalnyLlm` |
| WYM-N-08, N-09, N-18, N-19, N-20 | `Hosting` | `hosting` |

Bez `«satisfy»`: WYM-N-10, N-11, N-12, N-13, N-15, N-21.

---

## 5. Grupa 03: kontekst

**Diagramy** (pakiet `03 Kontekst`):

| Nazwa diagramu | Typ | Nagłówek |
|---|---|---|
| `03a Kontekst kliniki – bloki` | Block Definition Diagram | `bdd [Package] 03 Kontekst [03a Kontekst kliniki – bloki]` |
| `03b Kontekst kliniki – połączenia` | Internal Block Diagram (bloku `KontekstKliniki`) | `ibd [Block] KontekstKliniki [03b Kontekst kliniki – połączenia]` |

### 5.1 Bloki (pakiet `03 Kontekst` i `SystemyZewnetrzne`)

| Blok | Pakiet | Stereotypy | Porty (nazwa : typ) | Opis |
|---|---|---|---|---|
| `KontekstKliniki` | `03 Kontekst` | `«block»` | — | Samodzielna klinika z RAG po dokumentach medycznych; system elicytacji dopełnia go wiedzą ekspercką. Granica systemu = `hosting.system`. |
| `Hosting` | `SystemyZewnetrzne` | `«block»`, `«external»`, `«OdwolanieDoKodu» sciezka=infra/azure/docker-compose.yml` | — | VM Azure (Standard_B2s, 4 GB), docker compose: Caddy → nginx → API, worker, PostgreSQL; tylko porty 80/443; SSH i wdrożenie przez Tailscale; codzienna kopia bazy. |
| `BazaWiedzyEksperckiej` | `SystemyZewnetrzne` | `«block»`, `«external»`, `«OdwolanieDoKodu» sciezka=backend/migrations/versions/0003_pipeline.py` | `zapis : SqlPort`, `odczyt : SqlPort` | Schemat chips (pgvector + BM25). Zapisuje tylko system elicytacji; RAG kliniki tylko czyta. Fizycznie ta sama instancja PostgreSQL co schemat app. |
| `RagKliniki` | `SystemyZewnetrzne` | `«block»`, `«external»`, `«Propozycja»`, `«OdwolanieDoKodu» sciezka=packages/expert-knowledge-rag` | `wiedza : ~SqlPort`, `llm : ~OllamaPort` | Samodzielny RAG kliniki po dokumentach medycznych; może dołączyć bibliotekę expert-knowledge-rag i czytać bazę wiedzy. |
| `DokumentyMedyczne` | `SystemyZewnetrzne` | `«block»`, `«external»` | — | Dokumenty medyczne kliniki zindeksowane przez RAG kliniki. |
| `LokalnyLlm` | `SystemyZewnetrzne` | `«block»`, `«external»`, `«OdwolanieDoKodu» sciezka=docker-compose.yml` | `ollama : OllamaPort`, `languagetool : LanguageToolPort` | Komputer właściciela z GPU przez Tailscale: Ollama (qwen3.5:9b, bge-m3) i LanguageTool; bywa wyłączony. |
| `SystemElicytacji` | `07 Struktura` (rozdz. 9) | `«block»` | `web : HttpPort`, `wiedza : ~SqlPort`, `ollama : ~OllamaPort`, `languagetool : ~LanguageToolPort` | System elicytacji wiedzy eksperckiej. Na tym diagramie czarna skrzynka: bez części. |

`~` oznacza port z zaznaczonym *Is Conjugated*.

### 5.2 Diagram 03a (bdd): kompozycje

Narysuj **asocjacje kompozycji** (wypełniony romb przy całości) z nazwą roli i krotnością po stronie części:

| Całość | Część (typ) | Rola | Krotność |
|---|---|---|---|
| `KontekstKliniki` | `Pacjent` (aktor) | `pacjent` | 1 |
| `KontekstKliniki` | `InzynierWiedzy` (aktor) | `inzynierWiedzy` | 1 |
| `KontekstKliniki` | `Ekspert` (aktor) | `ekspert` | 1..* |
| `KontekstKliniki` | `Recenzent` (aktor) | `recenzent` | 0..* |
| `KontekstKliniki` | `Klinicysta` (aktor) | `klinicysta` | 1..* |
| `KontekstKliniki` | `Hosting` | `hosting` | 1 |
| `Hosting` | `SystemElicytacji` | `system` | 1 |
| `Hosting` | `BazaWiedzyEksperckiej` | `bazaWiedzy` | 1 |
| `KontekstKliniki` | `RagKliniki` | `ragKliniki` | 1 |
| `KontekstKliniki` | `DokumentyMedyczne` | `dokumentyMedyczne` | 1 |
| `KontekstKliniki` | `LokalnyLlm` | `lokalnyLlm` | 1 |

Do aktorów w SysML v1 używa się zwykłej asocjacji (aktor nie jest blokiem). Jeśli Visual Paradigm
nie pozwala na kompozycję do aktora, narysuj asocjację z rolą i krotnością jak w tabeli.

### 5.3 Diagram 03b (ibd)

1. Utwórz IBD z bloku `KontekstKliniki` (prawy klik na bloku > *Sub Diagrams > New > Internal Block
   Diagram*); ramka diagramu to blok `KontekstKliniki`.
2. Dodaj części (*Part Property*) zgodnie z tabelą 5.2. Części `system` i `bazaWiedzy` umieść
   **wewnątrz** części `hosting`. Osoby: jeśli VP nie pozwala typować części aktorem, użyj
   *Actor* na diagramie i połącz go konektorem (tak robi wiele narzędzi SysML v1).
3. Pokaż porty z 5.1 na częściach `system`, `bazaWiedzy`, `ragKliniki`, `lokalnyLlm`.
4. Narysuj konektory (*Connector*), nazwij je i dodaj *Item Flow* tam, gdzie podano:

| Nazwa konektora | Od | Do | Item Flow (kierunek) | Uwagi |
|---|---|---|---|---|
| `wypowiedziPacjenta` | `pacjent` | `inzynierWiedzy` | `WypowiedzPacjenta` (pacjent → inżynier) | pośrednio, poza systemem |
| — | `inzynierWiedzy` | `hosting.system.web` | — | przeglądarka |
| — | `ekspert` | `hosting.system.web` | — | przeglądarka |
| — | `recenzent` | `hosting.system.web` | — | przeglądarka |
| — | `klinicysta` | `ragKliniki` | — | |
| `zapisWiedzy` | `hosting.system.wiedza` | `hosting.bazaWiedzy.zapis` | `KnowledgeUnit` (system → baza) | ingest, usuwanie, BM25 |
| `odczytWiedzy` | `ragKliniki.wiedza` | `hosting.bazaWiedzy.odczyt` | `KnowledgeUnit` (baza → RAG) | tylko odczyt (READ ONLY) |
| — | `ragKliniki` | `dokumentyMedyczne` | — | |
| — | `hosting.system.ollama` | `lokalnyLlm.ollama` | `ModelRequest` / `ModelResponse` | Tailscale |
| — | `hosting.system.languagetool` | `lokalnyLlm.languagetool` | `ModelRequest` / `ModelResponse` | Tailscale |
| `ragDoLlm` | `ragKliniki.llm` | `lokalnyLlm.ollama` | — | stereotyp `«Propozycja»` |

5. Dodaj komentarz (*Note*) przy części `system`: „Granica systemu elicytacji. Wnętrze: 07b.”

---

## 6. Grupa 04: przypadki użycia

**Diagram:** *Use Case Diagram* w pakiecie `04 PrzypadkiUzycia`, nazwa **`04 Przypadki użycia`**.
Nagłówek: `uc [Package] 04 PrzypadkiUzycia [04 Przypadki użycia]`.

1. Narysuj **System (prostokąt granicy)** i ustaw jako podmiot blok `SystemElicytacji` (nazwa granicy
   `SystemElicytacji`).
2. Aktorzy główni po lewej (przeciągnij z `01 Interesariusze`): `Ekspert`, `Recenzent` (z generalizacją
   do `Ekspert`), `InzynierWiedzy`. Aktor drugorzędny po prawej: `LokalnyLlm` (utwórz *Actor*
   `LokalnyLlm` ze stereotypem `«external»` albo pokaż blok `LokalnyLlm` jako aktora). **Nie
   pokazuj** `Klinicysta` ani `Pacjent` – korzystanie z wiedzy nie jest przypadkiem użycia tego systemu.
3. Przypadki użycia (*Use Case*, wewnątrz granicy):

| Nazwa | v2 | Cel (Documentation) | Aktor (asocjacja) |
|---|---|---|---|
| Przeprowadź sesję elicytacji | `PrzeprowadzSesjeElicytacji` | Ekspert czyta winietę i odpowiada naraz na wszystkie zadane pytania (Q1–Q6), cytując fragmenty. Stany: assigned → in_progress → proofreading. | Ekspert |
| Cytuj fragmenty | `CytujFragmenty` | Zaznaczyć fragment winiety (chip [n]) i nadać mu kierunek. | — (include) |
| Zapisz szkic | `ZapiszSzkic` | Autozapis szkicu z kontrolą wersji (409 draft_conflict). | — (include) |
| Zgłoś odpowiedzi | `ZglosOdpowiedzi` | Zgłosić komplet odpowiedzi; zgłoszenie jest niezmienne. | — (include) |
| Korekta automatyczna | `KorektaAutomatyczna` | Zadanie proofread: pisownia, redakcja, powiązanie zdań z cytatami (proofreading → proofread_check). | LokalnyLlm |
| Sprawdź korektę | `SprawdzKorekte` | Sprawdzić i poprawić teksty i powiązania, oddać do recenzji (proofread_check → peer_review). | Ekspert |
| Recenzuj odpowiedzi | `RecenzujOdpowiedzi` | Przeczytać i przedyskutować odpowiedzi kolegi; otwarcie recenzji wyklucza recenzenta z przydziału tej winiety. | Recenzent |
| Skomentuj odpowiedź | `SkomentujOdpowiedz` | Komentarz support / challenge / question. | — (include) |
| Zagłosuj na odpowiedź | `ZaglosujNaOdpowiedz` | Głos approve / disapprove. | — (include) |
| Przygotuj winietę | `PrzygotujWiniete` | Napisać winietę (tekst pacjenta, streszczenie, pytania), opublikować albo wycofać wersję. | InzynierWiedzy |
| Zaproś i przydziel eksperta | `ZaprosIPrzydzielEksperta` | Zaproszenie (7 dni), przydział opublikowanej wersji, anulowanie przydziału. | InzynierWiedzy |
| Rozstrzygnij recenzję | `RozstrzygnijRecenzje` | Per pytanie: approve → processing, request_changes → proofread_check, reject → rejected. | InzynierWiedzy |
| Zasilenie bazy wiedzy | `ZasilenieBazyWiedzy` | Zadania process i ingest: jednostki wiedzy, osadzenie bge-m3, zapis do bazy wiedzy. | LokalnyLlm |
| Ponów nieudane zadanie | `PonowNieudaneZadanie` | Retry korekty, przetwarzania lub ingestii. | InzynierWiedzy |
| Zarządzaj bazą wiedzy | `ZarzadzajBazaWiedzy` | Przegląd i wyszukiwanie jednostek, usuwanie jednostki lub wiedzy eksperta, przeliczenie BM25. | InzynierWiedzy |

4. Relacje `«include»` (strzałka od bazowego do włączanego):

| Bazowy | Włączany |
|---|---|
| Przeprowadź sesję elicytacji | Cytuj fragmenty |
| Przeprowadź sesję elicytacji | Zapisz szkic |
| Przeprowadź sesję elicytacji | Zgłoś odpowiedzi |
| Zgłoś odpowiedzi | Korekta automatyczna |
| Recenzuj odpowiedzi | Skomentuj odpowiedź |
| Recenzuj odpowiedzi | Zagłosuj na odpowiedź |
| Rozstrzygnij recenzję | Zasilenie bazy wiedzy |

---

## 7. Grupa 05: proces biznesowy (czynność z torami)

**Diagram:** *Activity Diagram* aktywności `ProcesBiznesowy` w pakiecie `05 ProcesBiznesowy`, nazwa
**`05 Proces biznesowy`**. Nagłówek: `act [Activity] ProcesBiznesowy [05 Proces biznesowy]`.

### 7.1 Tory (pionowe *Swimlane*, od lewej)

Utwórz jeden *Vertical Swimlane* z partycjami w tej kolejności. Partycje zgrupuj w dwie partycje
nadrzędne, żeby granica systemu była widoczna:

| Partycja nadrzędna | Partycja | Reprezentuje (*Represents*, jeśli VP pozwala) |
|---|---|---|
| — | `pacjent : Pacjent` | część `KontekstKliniki::pacjent` |
| **SYSTEM ELICYTACJI** | `inzynierWiedzy : InzynierWiedzy` | `KontekstKliniki::inzynierWiedzy` |
| **SYSTEM ELICYTACJI** | `ekspert : Ekspert` | `KontekstKliniki::ekspert` |
| **SYSTEM ELICYTACJI** | `recenzent : Recenzent` | `KontekstKliniki::recenzent` |
| **SYSTEM ELICYTACJI** | `system : SystemElicytacji` | `Hosting::system` |
| **KLINIKA (poza systemem)** | `klinicysta : Klinicysta` | `KontekstKliniki::klinicysta` |
| **KLINIKA (poza systemem)** | `ragKliniki : RagKliniki` | `KontekstKliniki::ragKliniki` |

### 7.2 Węzły i akcje (w kolejności przepływu)

Akcje to *Action*; nazwa = czytelna nazwa, *Documentation* = opis + `v2: <nazwa>`.

| # | Węzeł | Tor | Opis (Documentation) |
|---|---|---|---|
| 1 | *Initial Node* | pacjent | |
| 2 | Zbierz wypowiedzi pacjenta | pacjent | Poza systemem, z udziałem inżyniera wiedzy. Pin wyjściowy `wypowiedzi : WypowiedzPacjenta [1..*]`. (`v2: zebranieWypowiedziPacjenta`) |
| 3 | Przygotuj winietę | inzynierWiedzy | Tekst pacjenta, streszczenie, pytania Q1–Q6; publish (VignetteVersion: draft → published). Pin wejściowy `wypowiedzi`. (`v2: przygotujWiniete`) |
| 4 | Przydziel eksperta | inzynierWiedzy | POST /vignette-versions/{id}/assignments: Assignment w stanie assigned. |
| 5 | Odpowiedz na winietę | ekspert | start (assigned → in_progress); cytaty i odpowiedzi na wszystkie pytania; autozapis szkicu. |
| 6 | Zgłoś odpowiedzi | ekspert | submit: walidacja, niezmienne Submission; in_progress → proofreading. |
| 7 | Korekta automatyczna | system | Zadanie proofread: LanguageTool, redakcja LLM, wiązanie zdań z cytatami; proofreading → proofread_check. |
| 8 | *Merge Node* `poPoprawkach` | ekspert | |
| 9 | Sprawdź korektę | ekspert | proofread_check: autor poprawia teksty i powiązania (PUT .../proofread). |
| 10 | Oddaj do recenzji | ekspert | submit_for_review: proofread_check → peer_review. |
| 11 | Recenzja | recenzent | review/open, komentarze i głosy do każdej odpowiedzi. |
| 12 | Rozstrzygnij | inzynierWiedzy | answer-decisions per pytanie; wynik dla przydziału: approve_answers / request_changes / reject_all_answers. |
| 13 | *Decision Node* `wgDecyzji` | inzynierWiedzy | |
| 14 | Zbuduj jednostki | system | Zadanie process: zatwierdzone odpowiedzi → AnswerFindings + KnowledgeUnit; processing → ingesting. Pin wyjściowy `jednostki : KnowledgeUnit [1..*]`. |
| 15 | Wgraj do bazy wiedzy | system | Zadanie ingest: osadzenie bge-m3, zapis do chips, BM25; ingesting → ingested. Pin wejściowy `jednostki`. |
| 16 | *Data Store Node* `«datastore» Baza wiedzy : KnowledgeUnit` | na granicy torów system / ragKliniki | Baza wiedzy (chips). |
| 17 | *Flow Final* | system | koniec sesji (zaingestowana) |
| 18 | *Flow Final* | inzynierWiedzy | koniec sesji (odrzucona) |
| 19 | *Initial Node* | klinicysta | klinika działa niezależnie od sesji |
| 20 | Zadaj pytanie | klinicysta | Pytanie kliniczne albo tekst pacjenta. |
| 21 | *Fork Node* | ragKliniki | |
| 22 | Szukaj w dokumentach medycznych | ragKliniki | Własny indeks dokumentów kliniki. |
| 23 | Szukaj w bazie wiedzy | ragKliniki | expert-knowledge-rag (ExpertQuestionRetriever albo PatientTextRetriever); tylko odczyt. Pin wejściowy `wiedza : KnowledgeUnit [0..*]`. |
| 24 | *Join Node* | ragKliniki | |
| 25 | Wygeneruj odpowiedź | ragKliniki | LLM: odpowiedź z dokumentów i notatek eksperckich. |
| 26 | Przeczytaj odpowiedź | klinicysta | |
| 27 | *Flow Final* | klinicysta | |

Używaj **Flow Final** (⊗), nie *Activity Final*: część kliniczna działa niezależnie, a Activity Final
zakończyłby całą aktywność.

### 7.3 Przepływy

**Sterowania** (*Control Flow*): 1→2→3→4→5→6→7→8→9→10→11→12→13;
13→14 ze strażnikiem `[approve_answers]`; 13→8 ze strażnikiem `[request_changes]`;
13→18 ze strażnikiem `[reject_all_answers]`; 14→15→17; 19→20→21; 21→22; 21→23; 22→24; 23→24; 24→25→26→27.

**Obiektów** (*Object Flow*): pin `wypowiedzi` (2) → pin `wypowiedzi` (3); pin `jednostki` (14) →
pin `jednostki` (15); 15 → 16 (`Baza wiedzy`); 16 → pin `wiedza` (23).

Przepływ 16 → 23 to jedyne połączenie systemu z kliniką: klinika nie czeka na sesję, tylko czyta bazę.
Ścieżek błędów (processing_failed, retry, cancel) tu nie rysuj; są na 08a.

---

## 8. Grupa 06: sekwencja (system jako czarna skrzynka)

**Diagram:** *Sequence Diagram* interakcji `SesjaElicytacji` w pakiecie `06 Sekwencja`, nazwa
**`06 Sesja elicytacji`**. Nagłówek: `sd [Interaction] SesjaElicytacji [06 Sesja elicytacji]`.

### 8.1 Linie życia (od lewej)

| # | Linia życia | Typ | Kształt |
|---|---|---|---|
| L1 | `inzynierWiedzy` | `InzynierWiedzy` | *Actor* |
| L2 | `ekspert` | `Ekspert` | *Actor* |
| L3 | `recenzent` | `Recenzent` | *Actor* |
| L4 | `system` | `SystemElicytacji` | *Lifeline* (blok; bez wnętrza) |
| L5 | `lokalnyLlm` | `LokalnyLlm` | *Lifeline* |
| L6 | `bazaWiedzy` | `BazaWiedzyEksperckiej` | *Lifeline* |
| L7 | `ragKliniki` | `RagKliniki` | *Lifeline* |

### 8.2 Komunikaty

„sync” = *Synchronous Message* (pełny grot) z *Reply* (linia przerywana) o podanej nazwie;
„async” = *Asynchronous Message* (otwarty grot). Wywołania osób to żądania HTTP z odpowiedzią.

| # | Od → Do | Nazwa komunikatu | Rodzaj | Odpowiedź (Reply) | Uwaga (endpoint, prefiks /api/v1) |
|---|---|---|---|---|---|
| m01 | L1 → L4 | `publish` | sync | `published` | POST /vignette-versions/{id}/publish |
| m02 | L1 → L4 | `assign` | sync | `assignment (assigned)` | POST /vignette-versions/{id}/assignments |
| m03 | L2 → L4 | `start` | sync | `assignment (in_progress)` | POST /assignments/{id}/start |
| m04 | L2 → L4 | `draft` | sync | `draft version` | PUT /assignments/{id}/draft – w fragmencie `loop` |
| m05 | L2 → L4 | `submit` | sync | `assignment (proofreading)` | POST /assignments/{id}/submit |
| m06 | L4 → L5 | `proofread` | sync | `m07 proofreadResult` | LanguageTool /v2/check + Ollama /api/chat |
| m08 | L4 → L2 | `proofreadCheck` | async | — | GET /assignments/{id}/proofread (frontend odpytuje) |
| m09 | L2 → L4 | `proofreadEdit` | sync | `revision` | PUT /assignments/{id}/proofread |
| m10 | L2 → L4 | `submit_for_review` | sync | `assignment (peer_review)` | POST /assignments/{id}/submit-for-review |
| m11 | L3 → L4 | `review/open` | sync | `204` | POST /assignments/{id}/review/open |
| m12 | L3 → L4 | `comments, vote` | sync | `ok` | POST .../answers/{q}/comments, PUT .../answers/{q}/vote |
| m13 | L1 → L4 | `answer-decisions` | sync | `assignment` | POST /assignments/{id}/answer-decisions |
| m14 | L4 → L5 | `embed` | sync | `m15 embeddings` | Ollama /api/embed (bge-m3) |
| m16 | L4 → L6 | `ingest` | async | — | zapis chips + BM25 |
| m17 | L4 → L1 | `ingested` | async | — | stan ingested widoczny w widoku przydziału |
| m18 | L7 → L6 | `read` | sync | `m19 rows` | READ ONLY (expert-knowledge-rag) |

### 8.3 Fragmenty i niezmienniki stanu

1. **`loop`** wokół m04, warunek `[autozapis, wielokrotnie]`.
2. **`alt`** obejmujący wszystko od m14 do m17, z trzema operandami:
   - `[approve_answers]`: m14, m15, m16, m17;
   - `[request_changes]`: komunikat zwrotny `L4 → L2` „nowa runda” (async) i niezmiennik `{proofread_check}`;
   - `[reject_all_answers]`: komunikat `L4 → L1` „rejected” (async).
3. **`opt`** wokół m18–m19, warunek `[klinika korzysta z bazy wiedzy]`, z notatką „niezależnie od sesji”.
4. **Niezmienniki stanu** (*State Invariant*) na linii `system` po komunikatach:
   m02 `{assigned}`, m03 `{in_progress}`, m05 `{proofreading}`, m07 `{proofread_check}`,
   m10 `{peer_review}`, m13 `{processing}`, m15 `{ingesting}`, m16 `{ingested}`.
   Łączą sekwencję z maszyną stanów 08a.

---

## 9. Grupa 07: struktura (BDD i IBD)

**Diagramy** (pakiet `07 Struktura`):

| Nazwa | Typ | Nagłówek |
|---|---|---|
| `07a Bloki systemu` | Block Definition Diagram | `bdd [Package] 07 Struktura [07a Bloki systemu]` |
| `07b Wnętrze systemu` | Internal Block Diagram bloku `SystemElicytacji` | `ibd [Block] SystemElicytacji [07b Wnętrze systemu]` |

### 9.1 Bloki

Wszystkie z `«block»` i `«OdwolanieDoKodu»`. Kompartmenty: *values* (atrybuty z typem i wartością
domyślną), *operations* (funkcje z kodu), *ports*. Typy czasu: `CzasTrwania`.

**Pakiet `07 Struktura`:**

| Blok | sciezka | values | operations | ports | Opis |
|---|---|---|---|---|---|
| `SystemElicytacji` | — | — | — | `web : HttpPort`, `wiedza : ~SqlPort`, `ollama : ~OllamaPort`, `languagetool : ~LanguageToolPort` | System elicytacji wiedzy eksperckiej (ADHD); granica systemu. |
| `Frontend` | `frontend/src` | — | — | `web : HttpPort`, `api_client : ~HttpPort` | Vue 3 SPA przez nginx; pokazuje allowed_actions; w stanach zadań odpytuje API. |
| `BackendApi` | `backend/app/main.py` | — | — | `http : HttpPort`, `sql : ~SqlPort`, `chips : ~SqlPort`, `ollama : ~OllamaPort`, `languagetool : ~LanguageToolPort` | FastAPI, /api/v1, /api/v1/health. |
| `Worker` | `backend/app/jobs/worker.py` | `POLL_SECONDS : Real = 2.0`, `ALIVE_SECONDS : Real = 10.0`, `ALIVE_FILE : String = "/tmp/worker-alive"` | `main()`, `run_once()` | `sql : ~SqlPort`, `chips : ~SqlPort`, `ollama : ~OllamaPort`, `languagetool : ~LanguageToolPort` | Proces zadań w tle; wiele instancji. Zachowanie: 08b. |
| `AppDatabase` | `backend/migrations/versions` | — | — | `sql : SqlPort` | PostgreSQL 16 + pgvector, schemat app. Części `jobs` (tabela jobs = kolejka) i `workflow` (tabele przepływu). |

**Pakiet `ModulyApi`:**

| Blok | sciezka | values | operations | ports |
|---|---|---|---|---|
| `Auth` | `backend/app/auth/service.py` | `MAX_FAILED_LOGINS : Integer = 5`, `LOCKOUT : CzasTrwania = 15 min`, `INVITE_TTL : CzasTrwania = 7 d` | `require_role()` | — |
| `Users` | `backend/app/users` | — | — | — |
| `Vignettes` | `backend/app/vignettes` | — | `publish_version()`, `retire_version()` | — |
| `Assignments` | `backend/app/assignments` | — | `check_draft()`, `clean_submission()` | — |
| `StateMachine` | `backend/app/assignments/state_machine.py` | — | `transition(assignment, action : Action, actor : Actor)`, `check_transition()`, `lock_assignment()`, `user_actions()` | — |
| `Proofread` | `backend/app/proofread/service.py` | — | `relink()` (z `links.py`) | — |
| `Reviews` | `backend/app/reviews` | — | `submit_decisions()` | — |
| `Knowledge` | `backend/app/knowledge/router.py` | — | `search_knowledge_units()`, `remove_units()` | `ollama : ~OllamaPort`, `chips : ~SqlPort` |
| `Compute` | `backend/app/compute.py` | `REQUIRE_COMPUTE : Boolean`, `TIMEOUT : CzasTrwania = 3 s`, `WATCH_EVERY : CzasTrwania = 10 s`, `API_TRUSTS : CzasTrwania = 30 s`, `WORKER_TRUSTS : CzasTrwania = 15 s` | `probe()`, `watch()`, `require_compute(kind : JobKind)`, `ready_kinds()`, `is_down_for(kind : JobKind)` | `ollama : ~OllamaPort`, `languagetool : ~LanguageToolPort` |

**Pakiet `Worker`:**

| Blok | sciezka | values | operations | ports |
|---|---|---|---|---|
| `JobQueue` | `backend/app/jobs/queue.py` | `MAX_ATTEMPTS : Integer = 3`, `LEASE : CzasTrwania = 5 min` | `next_job(kinds)` | — |
| `JobHandlers` | `backend/app/jobs/handlers.py` | — | — | — |
| `ProofreadJob` | `backend/app/proofread/pipeline.py` | — | `prepare()`, `record()` | `ollama : ~OllamaPort`, `languagetool : ~LanguageToolPort` |
| `ProcessJob` | `backend/app/jobs/handlers.py` | — | `process()` | — |
| `IngestJob` | `backend/app/knowledge/ingest.py` | — | `load()`, `embed()`, `write()` | `ollama : ~OllamaPort`, `chips : ~SqlPort` |
| `RefitJob` | `backend/app/jobs/handlers.py` | — | `refit()` | `chips : ~SqlPort` |

Opisy (Documentation) bloków `StateMachine`, `Compute`, `JobQueue`, `ProofreadJob`, `ProcessJob`,
`IngestJob`, `Worker` przepisz z `docs/sysml/src/model/06_Struktura.sysml` (pole `doc` bloku o tej
samej nazwie): to one tłumaczą, gdzie leży logika.

### 9.2 Diagram 07a (bdd): kompozycje

| Całość | Część | Rola | Krotność |
|---|---|---|---|
| `SystemElicytacji` | `Frontend` | `frontend` | 1 |
| `SystemElicytacji` | `BackendApi` | `api` | 1 |
| `SystemElicytacji` | `Worker` | `worker` | 0..* |
| `SystemElicytacji` | `AppDatabase` | `db` | 1 |
| `BackendApi` | `Auth`, `Users`, `Vignettes`, `Assignments`, `Proofread`, `Reviews`, `Knowledge`, `Compute` | `auth`, `users`, `vignettes`, `assignments`, `proofread`, `reviews`, `knowledge`, `compute` | 1 każda |
| `Assignments` | `StateMachine` | `state_machine` | 1 |
| `Worker` | `JobQueue` | `queue` | 1 |
| `Worker` | `JobHandlers` | `handlers` | 1 |
| `Worker` | `StateMachine` | `state_machine` | 1 |
| `Worker` | `Compute` | `compute` | 1 |
| `JobHandlers` | `ProofreadJob`, `ProcessJob`, `IngestJob`, `RefitJob` | `proofread`, `process`, `ingest`, `refit` | 1 każda |

`StateMachine` i `Compute` są częściami zarówno `BackendApi`, jak i `Worker`: ten sam kod działa
w obu procesach (API wykonuje akcje osób, worker akcje systemu). Na diagramie to dwie kompozycje
do tego samego bloku – tak ma być. Układ: `SystemElicytacji` u góry, pod nim cztery kontenery,
pod `BackendApi` moduły, pod `Worker` jego części.

### 9.3 Diagram 07b (ibd): gdzie leży logika

1. IBD z bloku `SystemElicytacji`; porty brzegowe na ramce: `web`, `wiedza`, `ollama`, `languagetool`.
2. Części: `frontend : Frontend`, `api : BackendApi`, `worker : Worker [0..*]`, `db : AppDatabase`.
   Wewnątrz `api` pokaż `assignments` (a w nim `state_machine`), `knowledge`, `compute`. Wewnątrz
   `worker` pokaż `queue`, `handlers` (a w nim `proofread`, `process`, `ingest`, `refit`),
   `state_machine`, `compute`. Wewnątrz `db` pokaż `jobs` i `workflow` (części bez typu albo
   bloki `JobsTable`, `WorkflowTables` w pakiecie `07 Struktura`).
3. Konektory i przepływy:

| Nazwa | Od | Do | Item Flow | Opis |
|---|---|---|---|---|
| — (binding) | port `web` ramki | `frontend.web` | — | *Binding Connector* (delegacja) |
| — | `frontend.api_client` | `api.http` | `HttpRequest` | REST /api/v1 |
| — | `api.sql` | `db.sql` | — | |
| — | `worker.sql` | `db.sql` | — | |
| `api_transition` | `api.assignments.state_machine` | `db.workflow` | `Assignment`, `AuditEvent` | akcje osób: stan + zdarzenie audytowe |
| `api_enqueue` | `api.assignments.state_machine` | `db.jobs` | `Job` | JOB_ON_ENTRY w tej samej transakcji |
| `next_job` | `db.jobs` | `worker.queue` | `Job` | SKIP LOCKED, tylko gotowe rodzaje |
| `handlers_write` | `worker.handlers` | `db.workflow` | `ProofreadRound`, `AnswerRevision`, `AnswerFindings`, `KnowledgeUnit` | pod blokadą przydziału |
| `worker_transition` | `worker.state_machine` | `db.workflow` | `Assignment`, `AuditEvent` | akcje systemu (*_succeeded / *_failed) |
| `worker_enqueue` | `worker.state_machine` | `db.jobs` | `Job` | po process od razu ingest |
| — | `api.chips` | port `wiedza` ramki | — | podgląd, usuwanie |
| — | `worker.chips` | port `wiedza` ramki | `KnowledgeUnit` | ingest, refit |
| — | `api.ollama`, `worker.ollama` | port `ollama` ramki | `ModelRequest` | osadzenie zapytania, sonda; korekta, osadzanie |
| — | `api.languagetool`, `worker.languagetool` | port `languagetool` ramki | `ModelRequest` | sonda; korekta |

4. Notatka na diagramie: „Etapy nie przekazują sobie danych w pamięci: wszystko idzie przez bazę
   (tabela jobs i schemat app), a wynik do bazy wiedzy (chips).”

---

## 10. Grupa 08: maszyny stanów

**Diagramy** (*State Machine Diagram*, pakiet `08 Stany`):

| Nazwa | Maszyna stanów | Właściciel (*classifier behavior*) | Nagłówek |
|---|---|---|---|
| `08a Cykl życia przydziału` | `AssignmentLifecycle` | blok `StateMachine` | `stm [State Machine] AssignmentLifecycle [08a Cykl życia przydziału]` |
| `08b Cykl życia zadania` | `JobLifecycle` | blok `Worker` | `stm [State Machine] JobLifecycle [08b Cykl życia zadania]` |

Utwórz maszynę stanów jako zachowanie bloku (prawy klik na bloku > *Sub Diagrams > New > State
Machine Diagram*), żeby była jego *classifier behavior*; daj jej `«OdwolanieDoKodu»`
(`backend/app/assignments/state_machine.py` dla 08a, `backend/app/jobs/worker.py` dla 08b).
Etykieta przejścia w SysML v1: `wyzwalacz [strażnik] / efekt`.

### 10.1 08a `AssignmentLifecycle`

**Stany** (nazwy = literały `State`): `assigned`, `in_progress` (*do*: „odpowiadanie; autozapis
szkicu”), `proofreading` (*entry*: `enqueue(proofread)`), `proofread_check`, `peer_review`,
`processing` (*entry*: `enqueue(process)`), `processing_failed`, `ingesting` (*entry*:
`enqueue(ingest)`), `ingestion_failed`, `ingested`, `rejected`, `cancelled`.
Plus *Initial* → `assigned` i jeden *Final State*.

Stany zadań (`proofreading`, `processing`, `ingesting`) wyróżnij kolorem: w nich pracuje worker.

**Przejścia** (kolejność jak w `TRANSITIONS`; nazwa przejścia = kolumna „#”):

| # | Ze stanu | Do stanu | Wyzwalacz (sygnał) | Strażnik |
|---|---|---|---|---|
| t01 | assigned | in_progress | `Start` | `[actor = assignee]` |
| t02 | assigned | cancelled | `Cancel` | `[actor = admin]` |
| t03 | in_progress | cancelled | `Cancel` | `[actor = admin]` |
| t04 | in_progress | proofreading | `Submit` | `[actor = assignee]` |
| t05 | proofreading | proofread_check | `ProofreadSucceeded` | `[actor = system]` |
| t06 | proofreading | processing_failed | `ProofreadFailed` | `[actor = system]` |
| t07 | proofread_check | cancelled | `Cancel` | `[actor = admin]` |
| t08 | proofread_check | peer_review | `SubmitForReview` | `[actor = assignee]` |
| t09 | peer_review | cancelled | `Cancel` | `[actor = admin]` |
| t10 | peer_review | processing | `ApproveAnswers` | `[actor = admin]` |
| t11 | peer_review | rejected | `RejectAllAnswers` | `[actor = admin]` |
| t12 | peer_review | proofread_check | `RequestChanges` | `[actor = admin]` |
| t13 | processing | ingesting | `ProcessingSucceeded` | `[actor = system]` |
| t14 | processing | processing_failed | `ProcessingFailed` | `[actor = system]` |
| t15 | processing_failed | proofreading | `RetryProofread` | `[actor = admin]` |
| t16 | processing_failed | processing | `RetryProcessing` | `[actor = admin]` |
| t17 | ingesting | ingested | `IngestionSucceeded` | `[actor = system]` |
| t18 | ingesting | ingestion_failed | `IngestionFailed` | `[actor = system]` |
| t19 | ingestion_failed | ingesting | `RetryIngestion` | `[actor = admin]` |
| t20 | ingested | *Final* | — | — |
| t21 | rejected | *Final* | — | — |
| t22 | cancelled | *Final* | — | — |

Notatka na diagramie: „Z REQUIRE_COMPUTE przejścia osób do stanu zadania (t04, t10, t15, t16, t19)
najpierw sprawdzają komputer z modelami; gdy nie jest gotowy: 503 compute_unavailable i przejście
nie zachodzi.”

Sugerowany układ: ścieżka główna w poziomie (assigned → in_progress → proofreading → proofread_check
→ peer_review → processing → ingesting → ingested), stany błędów pod nią (processing_failed pod
proofreading/processing, ingestion_failed pod ingesting), rejected i cancelled nad nią.

### 10.2 08b `JobLifecycle`

Atrybuty maszyny (albo bloku `Worker`): `attempts : Integer = 0`, `MAX_ATTEMPTS : Integer = 3`.

**Stany:** `queued`, `running` (*do*: „dzierżawa LEASE 5 min, odnawiana co 1/3 (_heartbeat); attempts + 1”),
`finished` (Documentation: „JobStatus.done; przydział dostaje *_succeeded”), `failed` („JobStatus.failed;
przydział dostaje *_failed”). *Initial* → `queued`; `finished` i `failed` → *Final*.

| Nazwa | Ze stanu | Do stanu | Wyzwalacz | Strażnik | Efekt |
|---|---|---|---|---|---|
| `claim` | queued | running | `Claim` | `[kind_ready and attempts < MAX_ATTEMPTS]` | `/ attempts := attempts + 1` |
| `claim_exhausted` | queued | failed | `Claim` | `[kind_ready and attempts >= MAX_ATTEMPTS]` | `/ last_error := LeaseExpired` |
| `succeeded` | running | finished | `JobSucceeded` | — | `/ transition(*_succeeded)` |
| `wait_for_compute` | running | queued | `JobError` | `[not permanent and compute_down]` | `/ attempts := attempts − 1` |
| `transient_error` | running | queued | `JobError` | `[not permanent and not compute_down and attempts < MAX_ATTEMPTS]` | — |
| `permanent_error` | running | failed | `JobError` | `[permanent or (not compute_down and attempts >= MAX_ATTEMPTS)]` | `/ transition(*_failed)` |
| `lease_expired` | running | queued | `LeaseExpired` | — | — |

---

## 11. Grupa 09: model wiedzy (bloki danych)

Tej grupy nie ma jeszcze w modelu v2; treść pochodzi z klas ORM i migracji.

**Diagramy** (*Block Definition Diagram*, pakiet `09 ModelWiedzy`):

| Nazwa | Nagłówek | Zawartość |
|---|---|---|
| `09a Od winiety do jednostki wiedzy` | `bdd [Package] SchematApp [09a Od winiety do jednostki wiedzy]` | bloki schematu app |
| `09b Baza wiedzy (chips)` | `bdd [Package] SchematChips [09b Baza wiedzy (chips)]` | bloki schematu chips + `«trace»` z app |

### 11.1 09a: pakiet `SchematApp`

Bloki `«block»` (nazwa = klasa ORM) z `«OdwolanieDoKodu»` i najważniejszymi wartościami:

| Blok | sciezka | values |
|---|---|---|
| `Vignette` | `backend/app/vignettes/models.py` | `code : String` |
| `VignetteVersion` | jw. | `version : Integer`, `status : VersionStatus`, `text : String`, `patient_summary : String` |
| `Assignment` | `backend/app/assignments/models.py` | `state : State`, `review_round : Integer` |
| `AnswerDraft` | jw. | `version : Integer` |
| `Submission` | jw. | `vignette_hash : String`, `payload_format : Integer` |
| `ProofreadRound` | `backend/app/proofread/models.py` | `review_round : Integer`, `version : Integer` |
| `AnswerRevision` | jw. | `question_id : String`, `original : String`, `proposed : String`, `final : String` |
| `ReviewParticipant` | `backend/app/reviews/models.py` | — |
| `AnswerComment` | jw. | `question_id : String`, `stance : String`, `body : String` |
| `AnswerVote` | jw. | `question_id : String`, `vote : String` |
| `AnswerDecision` | jw. | `question_id : String`, `decision : DecisionValue` |
| `AnswerFindings` | `backend/app/knowledge/models.py` | `findings_version : Integer` |
| `KnowledgeUnit` | jw. | `kind : UnitKind`, `text : String`, `direction : Direction`, `content_hash : String`, `status : UnitStatus` |
| `Job` | `backend/app/jobs/models.py` | `kind : JobKind`, `status : JobStatus`, `attempts : Integer`, `last_error : String` |
| `AuditEvent` | `backend/app/audit/models.py` | `action : String`, `from_state : String`, `to_state : String` |

Asocjacje (krotność po stronie celu; pochodzą z kluczy obcych):

| Od | Do | Krotność (od : do) | Rodzaj |
|---|---|---|---|
| `Vignette` | `VignetteVersion` | 1 : 1..* | kompozycja |
| `VignetteVersion` | `Assignment` | 1 : 0..* | asocjacja |
| `Assignment` | `AnswerDraft` | 1 : 0..1 | kompozycja |
| `Assignment` | `Submission` | 1 : 0..1 | kompozycja (niezmienne) |
| `Assignment` | `ProofreadRound` | 1 : 0..* (jedna na rundę recenzji) | kompozycja |
| `ProofreadRound` | `AnswerRevision` | 1 : 0..* (jedna na pytanie) | kompozycja |
| `Assignment` | `ReviewParticipant` | 1 : 0..* | kompozycja |
| `Assignment` | `AnswerComment` | 1 : 0..* | kompozycja |
| `Assignment` | `AnswerVote` | 1 : 0..* | kompozycja |
| `Assignment` | `AnswerDecision` | 1 : 0..* (na rundę i pytanie) | kompozycja |
| `Assignment` | `AnswerFindings` | 1 : 0..1 | kompozycja |
| `Assignment` | `KnowledgeUnit` | 1 : 0..* | asocjacja |
| `Submission` | `KnowledgeUnit` | 1 : 0..* | asocjacja (źródło jednostki) |
| `Assignment` | `Job` | 0..1 : 0..* | asocjacja (refit nie ma przydziału) |

Układ: lewa kolumna `Vignette` → `VignetteVersion` → `Assignment`, środek etapy w kolejności
przepływu (`AnswerDraft`, `Submission`, `ProofreadRound`/`AnswerRevision`, recenzja,
`AnswerDecision`, `AnswerFindings`), prawa kolumna `KnowledgeUnit`. `Job` i `AuditEvent` na dole.

### 11.2 09b: pakiet `SchematChips`

Bloki (nazwa = tabela schematu chips), `«OdwolanieDoKodu» sciezka=backend/migrations/versions/0003_pipeline.py`:

| Blok | values |
|---|---|
| `experts` | `id : String`, `role : String` |
| `vignettes` | `id : String`, `version : Integer`, `tier : String`, `text : String` |
| `elicitation_sessions` | `id : String`, `document : String` (JSON) |
| `cue_keys` | `text : String`, `embedding : String` (vector 1024) |
| `highlights` | `chip : Integer`, `direction : String`, `origin : String` |
| `answer_sentences` | `question_id : String`, `idx : Integer`, `targets : String[*]`, `assigned_by : String` |
| `finding_units` | `kind : String`, `embed_text : String`, `embedding : String` (vector 1024), `embed_text_combined : String` |
| `finding_unit_sentences` | `ord : Integer` |
| `unit_cues` | `role : String` |
| `review_events` | `kind : String`, `payload : String` |

Asocjacje: `experts` 1 — 0..* `elicitation_sessions`; `elicitation_sessions` 1 — 0..* `highlights`,
`answer_sentences`, `finding_units`, `review_events` (kompozycje, ON DELETE CASCADE);
`cue_keys` 1 — 0..* `highlights`; `highlights` 0..1 — 0..* `finding_units`;
`finding_units` 0..* — 0..* `answer_sentences` przez `finding_unit_sentences`;
`finding_units` 0..* — 0..* `cue_keys` przez `unit_cues`.

Ślad z app do chips (zależności `«trace»`, przeciągnij bloki z 09a): `KnowledgeUnit` → `finding_units`;
`Assignment` → `elicitation_sessions` (id sesji = id przydziału); `AnswerRevision` → `answer_sentences`.

---

## 12. Grupa 10: od odpowiedzi do jednostki wiedzy

Tej grupy nie ma jeszcze w modelu v2; treść pochodzi z kodu potoku.

**Diagram:** *Activity Diagram* aktywności `OdOdpowiedziDoJednostki` w pakiecie
`10 OdOdpowiedziDoJednostki`, nazwa **`10 Od odpowiedzi do jednostki`**.
Nagłówek: `act [Activity] OdOdpowiedziDoJednostki [10 Od odpowiedzi do jednostki]`.

### 12.1 Tory

| Partycja | Reprezentuje |
|---|---|
| `ekspert : Ekspert` | autor odpowiedzi |
| `inzynierWiedzy : InzynierWiedzy` | |
| `worker : Worker` | zadania proofread, process, ingest |
| `lokalnyLlm : LokalnyLlm` | LanguageTool, Ollama |
| `bazaWiedzy : BazaWiedzyEksperckiej` | |

### 12.2 Węzły

| # | Węzeł | Tor | Opis / kod |
|---|---|---|---|
| 1 | *Initial Node* | ekspert | |
| 2 | *Object Node* `Submission` | ekspert | niezmienne zgłoszenie |
| 3 | *Expansion Region* «iterative» „dla każdej odpowiedzi” z węzłem wejściowym odpowiedzi | worker | `proofread_answer()` w `backend/app/proofread/pipeline.py` |
| 3.1 | Odrzuć śmieci | worker | `garbage.py` |
| 3.2 | Sprawdź pisownię | lokalnyLlm | LanguageTool (`grammar.py`) |
| 3.3 | Zredaguj | lokalnyLlm | LLM, prompt Answer_enhance.v1 (`enhance.py`); pomijane, gdy ENHANCE_MODEL pusty |
| 3.4 | Sprawdź pisownię ponownie | lokalnyLlm | LanguageTool |
| 3.5 | Jedno zdanie na linię | worker | `layout()` |
| 4 | Powiąż linie z cytatami | worker | warstwa 1: chip [n]; warstwa 2: cytowane słowa (`links.py`) |
| 5 | Przypisz resztę linii | lokalnyLlm | warstwa 3: klasyfikator LLM, prompt Expert_sentence_targets.v1 (`classifier.py`) |
| 6 | Oznacz flagi | worker | `findings.check()` |
| 7 | Zapisz rundę korekty | worker | HANDLERS pod blokadą: `ProofreadRound` + `AnswerRevision`; `transition(proofread_succeeded)` |
| 8 | *Object Node* `AnswerRevision [1..*]` | worker | |
| 9 | Sprawdź korektę | ekspert | popraw teksty i przypisania linii (`relink()` bez modelu) |
| 10 | Oddaj do recenzji | ekspert | `submit_for_review` |
| 11 | Recenzja i decyzja | inzynierWiedzy | *Call Behavior Action* (szczegóły: 05); wynik `AnswerDecision [1..*]` |
| 12 | *Decision Node* | inzynierWiedzy | `[approve_answers]` → 13; `[request_changes]` → 9 (przez *Merge* przed 9); `[reject_all_answers]` → *Flow Final* |
| 13 | Wybierz zatwierdzone odpowiedzi | worker | decyzje approve z bieżącej rundy × rewizje tej rundy (`handlers.process`) |
| 14 | Zbuduj rekord ustaleń | worker | `AnswerFindings` (`findings.py`); brak → NoFindings (błąd trwały) |
| 15 | Potnij na jednostki | worker | `build_units()`: jednostka `fragment` na każde podświetlenie ze zdaniami + jedna `case`; brak → NoUnits |
| 16 | *Object Node* `KnowledgeUnit [1..*]` (status approved) | worker | `transition(processing_succeeded)` |
| 17 | Wczytaj do ingestii | worker | `ingest.load()`; odmowy: NoUnits, UnitsNotEmbeddable, NoFindings |
| 18 | Osadź teksty | lokalnyLlm | bge-m3, jedno wywołanie: I1 tekst jednostki, I2 słowa pacjenta, I3 = I1 + słowa pacjenta (`embedding.py`) |
| 19 | Zapisz w bazie wiedzy | bazaWiedzy | `ingest.write()`: blokada BM25, zastąpienie wierszy sesji w chips |
| 20 | Przelicz BM25 | bazaWiedzy | `refresh_sparse()` dla całego schematu; jednostki → ingested; `transition(ingestion_succeeded)` |
| 21 | *Flow Final* | bazaWiedzy | |

Przepływy sterowania w kolejności numerów (3.1→3.2→3.3→3.4→3.5 wewnątrz regionu); przepływy
obiektów: 2 → region 3; 7 → 8 → 9; 11 → 12 (`AnswerDecision`); 15 → 16 → 17.
Notatka: „Kroki 3–6 to PREPARE (bez transakcji, modele); 7, 13–16 i 19–20 to HANDLERS
(pod blokadą wiersza przydziału, w transakcji przejścia stanu).”

---

## 13. Lista kontrolna

- [ ] Pakiety i nazwy dokładnie jak w rozdziale 1; każdy diagram w swoim pakiecie.
- [ ] Biblioteka: 8 stereotypów, `CzasTrwania`, 11 wyliczeń, 21 sygnałów, 4 InterfaceBlocki, 7 bloków przepływu.
- [ ] 01: 5 interesariuszy, 8 potrzeb, 11 relacji «trace», generalizacja Recenzent → Ekspert.
- [ ] 02: 24 + 20 wymagań w kontenerach WYM-F i WYM-N, «deriveReqt» do potrzeb; «satisfy» wg tabeli 4.4.
- [ ] 03: bdd z 11 kompozycjami, ibd z portami i 11 konektorami.
- [ ] 04: 15 przypadków użycia, 7 «include», LokalnyLlm jako aktor drugorzędny; bez Klinicysty.
- [ ] 05: 7 torów w dwóch grupach (SYSTEM ELICYTACJI / KLINIKA), datastore Baza wiedzy, Flow Final zamiast Activity Final.
- [ ] 06: 7 linii życia, komunikaty m01–m19, fragmenty loop / alt / opt, niezmienniki stanu.
- [ ] 07: 20 bloków (5 + 9 + 6), kompozycje z tabeli 9.2, IBD z przepływami przez `db.jobs` i `db.workflow`.
- [ ] 08: 08a 12 stanów i 22 przejścia (zgodne z TRANSITIONS); 08b 4 stany i 7 przejść.
- [ ] 09: 15 bloków app + 10 bloków chips, «trace» app → chips.
- [ ] 10: 5 torów, region rozszerzenia dla każdej odpowiedzi, notatka PREPARE/HANDLERS.
- [ ] Każdy element wskazujący kod ma `«OdwolanieDoKodu»` ze ścieżką.
