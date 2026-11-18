# Model SysML v2 systemu elicytacji wiedzy eksperckiej

Model systemu w notacji tekstowej **SysML v2**, wyprowadzony z **aktualnego kodu** (nie z `docs/*.md`,
które miejscami są nieaktualne). Zarówno nazwy elementów, jak i komentarze (`doc`) są po polsku.
Nazwy są zapisane bez znaków diakrytycznych (`Przydzial`, `Winieta`), bo identyfikatory SysML v2
bez cudzysłowu to ASCII. Słownik **nazwa w kodzie → nazwa w modelu** jest w [SLOWNIK.md](SLOWNIK.md),
dzięki czemu model i kod da się nadal zestawić. Słowa kluczowe SysML (`part def`, `satisfy` itd.),
typy z biblioteki standardowej (`String`, `Integer`, `ScalarValues`, `SI`) i wartości zapisywane
w bazie (komentarz `// db:` przy literałach wyliczeń) pozostają bez zmian.

Model opisuje przede wszystkim **strukturę**. Szczegóły i wartości oznaczone `@DoUzupelnienia` / `@Propozycja`
są do uzupełnienia.

## Pliki

| Plik | Pakiet | Zawartość | Filar SysML |
|---|---|---|---|
| `00_Biblioteka.sysml` | `BibliotekaElicytacji` | metadane `@OdwolanieDoKodu`, `@Zaimplementowane`, `@Propozycja`, `@Planowane`, `@DoUzupelnienia`; typy wspólne | — |
| `01_Wymagania.sysml` | `WymaganiaElicytacji` | concerns (ZAG-xx), wymagania funkcjonalne (WYM-F-xx) i niefunkcjonalne (WYM-N-xx) | wymagania |
| `02_Kontekst.sysml` | `KontekstElicytacji` | aktorzy, systemy zewnętrzne, `kontekstElicytacji`, przypadki użycia | wymagania / kontekst |
| `03_Interfejsy.sysml` | `InterfejsyElicytacji` | elementy przepływu, porty, interfejsy | struktura |
| `04_Struktura.sysml` | `StrukturaElicytacji` | `SystemElicytacji`, moduły backendu, frontend, worker, baza, narzędzia badawcze | struktura |
| `05_Dziedzina.sysml` | `DziedzinaElicytacji` | typy wyliczeniowe, schematy `app` i `chips` | struktura (dane) |
| `06_Stany.sysml` | `StanyElicytacji` | cykl życia przydziału, wersji winiety i zadania | zachowanie |
| `07_Czynnosci.sysml` | `CzynnosciElicytacji` | od odpowiedzi do wiedzy, korekta, jednostki, ingestia, zapytanie RAG | zachowanie |
| `08_Interakcje.sysml` | `InterakcjeElicytacji` | sekwencje: zgłoszenie, wykonanie zadania, wyszukiwanie | zachowanie |
| `09_Analiza.sysml` | `AnalizaElicytacji` | RRF, budżet kontekstu, progi jakości wyszukiwania | parametryka |
| `10_Platforma.sysml` | `PlatformaElicytacji` | platforma dev (docker-compose), prod (VM Azure + komputer z modelami przez Tailscale), CI/CD (GitHub Actions, ghcr.io), środowisko testowe, czynność wdrożenia, alokacje | alokacja |
| `11_Sledzenie.sysml` | `SledzenieElicytacji` | `satisfy`, przypadki weryfikacji (testy z poziomem i informacją o CI), `verify` | wymagania |
| `12_Widoki.sysml` | `WidokiElicytacji` | widoki = diagramy | widoki |
| `13_SciezkaPrzetwarzania.sysml` | `SciezkaPrzetwarzania` | techniczna ścieżka wypełnionej winiety: artefakty, porty, komponenty (BDD), `SciezkaPrzetwarzaniaWiniety` (IBD), alokacja do modułów | struktura |

Zależności między pakietami: `00 ← 05 ← 03 ← 04 ← 02 ← 01 ← 06/07/08 ← 09 ← 10 ← 11 ← 12`, a `13`
korzysta z `03`, `04`, `05`, `06` i `02` (importy są `private`, cykle dopuszczalne w SysML v2).

## BDD i IBD

| Co | BDD (definicje) | IBD (połączenia) |
|---|---|---|
| system jako całość | `dekompozycjaSystemu` (`04`) | `wnetrzeSystemu` - `SystemElicytacji` (`04`) |
| backend | `dekompozycjaBackendu` (`04`) | — |
| kontekst | — | `kontekstSystemu` - `kontekstElicytacji` (`02`) |
| ścieżka przetwarzania winiety | `sciezkaPrzetwarzaniaBdd` (`13`) | `sciezkaPrzetwarzaniaIbd` - `SciezkaPrzetwarzaniaWiniety`; wnętrza: `wnetrzeKorekty`, `wnetrzeCieciaIIngestii` (`13`) |
| wdrożenie | — | `wdrozenieProdukcyjne`, `wdrozenieDeweloperskie`, `platformaCiCd` (`10`) |

IBD ścieżki pokazuje przekazania przez bazę jawnie: etapy nie wymieniają danych w pamięci, tylko przez
`magazynStanu` (tabele `app`) i `kolejka` (tabela `jobs`). Każde zadanie ma fazę PREPARE (bez
transakcji, modele) i HANDLERS (zapis pod blokadą przydziału, razem z przejściem stanu).

## Widoki (diagramy)

| Widok w `12_Widoki.sysml` | Odpowiednik SysML v1 (Visual Paradigm) | Źródło |
|---|---|---|
| `wymagania` | Requirement Diagram (req) | `01` |
| `macierzSledzenia` | Requirement / Allocation Table | `11` |
| `kontekstSystemu` | IBD kontekstu (lub BDD kontekstu) | `02` |
| `przypadkiUzycia` | Use Case Diagram (uc) | `02` |
| `organizacjaModelu` | Package Diagram (pkg) | wszystkie |
| `dekompozycjaSystemu` | Block Definition Diagram (bdd) | `04` |
| `dekompozycjaBackendu` | BDD + Package Diagram (zależności modułów) | `04` |
| `interfejsy` | BDD (interface blocks, flow properties) | `03` |
| `wnetrzeSystemu` | Internal Block Diagram (ibd) | `04` |
| `modelDziedziny`, `modelDanychRag` | BDD z blokami danych i typami wartości | `05` |
| `stanyPrzydzialu`, `stanyWiniety`, `stanyZadania` | State Machine Diagram (stm) | `06` |
| `odOdpowiedziDoWiedzy` (z torami), `potokKorekty`, `jednostkiIIngestia`, `zapytanieRag` | Activity Diagram (act) | `07`, `10` |
| `wykonanieZadania`, `potokWdrozenia` | Activity Diagram (act) | `07`, `10` |
| `sekwencjaZgloszenia`, `sekwencjaZadania`, `sekwencjaWyszukiwania`, `sekwencjaOdmowyBezMocy` | Sequence Diagram (sd) | `08` |
| `budzetLlm`, `parametrykaJakosciRag`, `parametrykaWdrozenia` | Parametric Diagram (par) | `09` |
| `wdrozenieProdukcyjne`, `wdrozenieDeweloperskie`, `platformaCiCd` | BDD/IBD platformy + «allocate» | `10` |
| `sciezkaPrzetwarzaniaBdd` | Block Definition Diagram (bdd) | `13` |
| `sciezkaPrzetwarzaniaIbd`, `wnetrzeKorekty`, `wnetrzeCieciaIIngestii` | Internal Block Diagram (ibd) | `13` |
| `macierzAlokacji`, `alokacjaSciezki` | Allocation Table / Matrix | `10`, `13` |
| `planTestow` | tabela przypadków weryfikacji | `11` |

**Minimalny komplet do pracy:** `wymagania`, `macierzSledzenia`, `kontekstSystemu`, `przypadkiUzycia`,
`dekompozycjaSystemu`, `wnetrzeSystemu`, `modelDziedziny`, `stanyPrzydzialu`, `odOdpowiedziDoWiedzy`,
`sekwencjaZgloszenia`, `parametrykaJakosciRag`, `wdrozenieProdukcyjne`, `sciezkaPrzetwarzaniaIbd`.

## Konwencje

- `def` = typ, usage = wystąpienie. Korzeniem drzewa części jest `KontekstElicytacji::kontekstElicytacji`,
  a w nim `system : SystemElicytacji`. Do niego odnoszą się `satisfy` i `allocate`.
- Definicje w `PascalCase`, wystąpienia, literały wyliczeń i stany w `camelCase` (`sprawdzenieKorekty`).
  Wartość zapisywana w bazie (np. `proofread_check`) jest w komentarzu `// db:` przy literale wyliczenia.
- Wymagania mają krótkie identyfikatory `<'WYM-F-07'>`, zagadnienia interesariuszy `<'ZAG-01'>`
  (dawniej `REQ-F-xx`, `REQ-N-xx`, `C-xx`).
- `@OdwolanieDoKodu { sciezka = "..."; }` wskazuje plik lub katalog w repozytorium.
- Polskie nazwy nie kolidują ze słowami kluczowymi SysML, więc cudzysłów nie jest potrzebny. W wersji
  z angielskimi nazwami wymagały go `'variant'`, `'at'`, `'meta'`, `'comment'`, `'case'`, `'language'`,
  `'state'`, `'actor'`, `'action'` (teraz `wariant`, `chwila`, `metadane`, `komentarz`, `przypadek`,
  `jezyk`, `stan`, `aktor`, `akcja`). Nazwa `classifier` kolidowała ze słowem kluczowym KerML (teraz
  `klasyfikator`).
- Standardowe renderowania SysML (`asTreeDiagram`, `asInterconnectionDiagram`, `asElementTable`) i słowa
  `start` / `done` w przepływach czynności (`first start; ... then done;`) pochodzą z biblioteki
  standardowej i zostają po angielsku. Literały `AkcjaPrzeplywu::rozpocznij` i `StatusZadania::zakonczone`
  to osobne elementy modelu.
- SysML v2 nie ma fragmentów `alt` ani relacji «extend». Warianty sekwencji opisano w `doc` i w osobnych
  interakcjach (`InterakcjaKonfliktuSzkicu`).

## Jak otworzyć i sprawdzić

Pliki **nie były sprawdzane parserem**. Zalecane:

1. **VS Code + SysIDE (Sensmetry)**: otwórz katalog `docs/model/`. Błędy składni i nierozwiązane
   nazwy pojawią się w edytorze.
2. **SysML v2 Pilot Implementation (Jupyter)**: wczytaj pliki w kolejności numerów i renderuj widok,
   np. `%viz --view tree WidokiElicytacji::dekompozycjaSystemu`.
3. **Visual Paradigm (SysML 1.x)**: widoki z tabeli powyżej przerysuj jako diagramy odpowiedniego typu.
   Model tekstowy pozostaje źródłem prawdy.

## Do uzupełnienia (`@DoUzupelnienia`)

- Progi jakości: `WYM-N-13 jakoscWyszukiwania` (`minimalnaPelnoscAt4`, MRR), `WYM-N-14 jakoscOdpowiedzi`.
- `WYM-N-11 dostepnosc`, `WYM-N-12 szybkoscDzialania`, `WYM-N-15 dostepnoscInterfejsu`: wartości docelowe.
- `WYM-N-10 usuwanieDanychRodo` (@Planowane): element spełniający po implementacji.
- `WYM-N-01 modeleLokalne`, `WYM-N-09 tanieHostowanie` (@Propozycja): potwierdzić.
- Bez testu weryfikującego: `budzetKontekstu`, `skalowalneWorkery`, `pseudonimizacja`, `kopieZapasoweBazy`,
  `ograniczonaEkspozycjaSieci`, `tanieHostowanie`.
- `AnalizaElicytacji::budzetPamieciVm`: `rezerwaSystemuMB`.
- `TestRegresjiWyszukiwania` ma progi testu (hit@4 ≥ 0,8, MRR ≥ 0,5, nDCG@10 ≥ 0,4, tolerancja 0,02);
  czy przyjąć je jako wartości `WYM-N-13`, decyduje autor.
- `AnalizaElicytacji::budzetWywolanLlm`: `tokenyPromptu`, `tokenyOdpowiedzi` z pomiaru.
- Mapowanie test → wymaganie w `11_Sledzenie.sysml` wyprowadzono z treści testów; potwierdzić.

## Zmiany 2026-11-18

Poza modelem jest teraz to, co nie wchodzi w skład systemu: **tymczasowe skrypty z `scripts/`** i
**szybki RAG po korpusie dokumentów**. Usunięto:

- `NarzedziaBadawcze` (skrypty korpusu, elicytacji, ewaluacji RAG, bazy danych; persony ekspertów
  syntetycznych) wraz z interfejsami, połączeniami i alokacją na kontener `dev`;
- korpus dokumentów (pakiet danych, czynność wraz z krokami i widokiem, tabele) razem z magazynem
  plików i jego węzłami w platformie deweloperskiej;
- systemy zewnętrzne korpusu i puli postów oraz powiązane z nimi przypadki użycia;
- ewaluację przez skrypty: `EwaluacjaRag`, `UruchomienieEwaluacji`, `MetrykiWyszukiwania`,
  `JakoscOdpowiedziWgSedziow`, test `UruchomienieEwaluacjiRag`, test `TestStrazyLadowaniaChips`
  (strażnik ładowarki fikstur) i poziom testu `skryptow`.

Zostaje RAG po jednostkach eksperckich (`packages/expert-knowledge-*`, czynność `ZapytanieRag`).
Zmiany pomocnicze: `satisfy odpowiedziRag` wskazuje teraz `system.backend.rag` (dawniej
`system.badania.rag`); odwołania do `scripts/db/chips_schema.sql` zastąpiono migracją
`backend/migrations/versions/0003_pipeline.py`; `jakoscRag` ma własne atrybuty `pelnoscAt4` i `mrr`
(do uzupełnienia) zamiast przebiegu ewaluacji.

Skutki do rozstrzygnięcia: `WYM-N-14 jakoscOdpowiedzi` nie ma już ani `satisfy`, ani `verify`;
`inzynier` w `kontekstElicytacji` nie ma połączenia z systemem (jego jedyny pozostały przypadek użycia,
`WdrozWydanie`, przebiega przez CI/VM).

## Zmiany 2026-11-17

- **Wdrożenie:** Render + Neon zastąpione jedną VM Azure (Caddy → nginx → API, worker, Postgres w
  compose, obrazy z ghcr.io) i komputerem właściciela z Ollama i LanguageTool przez Tailscale. Worker
  jest teraz wdrożony (nie `@Planowane`).
- **Moc obliczeniowa:** nowy moduł `backend/app/compute.py` (`REQUIRE_COMPUTE`): 503
  `compute_unavailable` w API, wstrzymywanie zadań w workerze, korekta bez pomijania usług.
  Nowe wymagania `WYM-N-16`..`WYM-N-20`, stan `czekanieNaMoc` w cyklu zadania, czynność
  `WykonanieZadania`, sekwencja `InterakcjaOdmowyBezMocy`.
- **Testy:** nowy układ (unit, api, integration), baza testów API na przebieg
  (`rag_<pid>_test`), regresja jakości wyszukiwania, specyfikacje vitest; CI bez bazy.
- **Badania:** filtr ekspertów w `expert-knowledge-rag`. (Fikstury, persony i migawki zostały
  później wyłączone z modelu, zob. 2026-11-18.)
- **Ścieżka przetwarzania:** nowy plik `13_SciezkaPrzetwarzania.sysml` (BDD + IBD).

## Rozbieżności kod ↔ dokumentacja (stan na 2026-11-16)

Model idzie za kodem. W `docs/` są nieaktualne opisy:

- **Brak bramki między pytaniami.** Wszystkie zadane pytania są widoczne od razu
  (`_visible_questions` w `backend/app/assignments/service.py`). Pozostałości: `GATE` w
  `backend/app/vignettes/questions.py` oraz komentarze w `assignments/schemas.py` i `assignments/answers.py`.
- **Inne stany przepływu** niż w `docs/backend-workflow.md`. Kod: `proofreading → proofread_check →
  peer_review → processing → ingesting`. Dokumentacja: `processing → expert_check → building_units → …`.
