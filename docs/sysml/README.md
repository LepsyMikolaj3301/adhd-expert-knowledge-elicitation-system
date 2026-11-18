# SysON: podgląd modelu SysML v2 jako diagramy

Lokalna instancja [Eclipse SysON](https://eclipse.dev/syson/) (Docker Compose: aplikacja + Postgres),
do której wysyłasz modele tekstowe `.sysml` i oglądasz je jako diagramy w przeglądarce.

## Uruchomienie (z WSL)

```bash
cd docs/sysml
docker compose up -d        # SysON pod http://localhost:8080
docker compose down         # zatrzymanie (dane zostają w postgres-data/)
```

Skrypty rozmawiają z `http://localhost:8080`; inny adres: `SYSON_URL=http://host:port ./push.sh`.

## Wysyłanie modelu do SysON: `push.sh`

```bash
./push.sh                   # każdy folder z src/ -> osobny projekt
./push.sh moj-model         # tylko src/moj-model/
./push.sh ../model          # dowolny folder z plikami *.sysml; nazwa folderu = nazwa projektu
```

- Źródłem jest folder z plikami `*.sysml`. Pliki są sklejane (alfabetycznie) i wysyłane jako
  **jeden dokument**: SysON rozwiązuje odwołania tylko do tego, co już wczytał, więc przy
  osobnych plikach każde odwołanie do późniejszego pliku (typ, specjalizacja, `expose`)
  po cichu by przepadło.
- **Istniejący projekt o tej samej nazwie jest usuwany i tworzony od nowa**, więc zmiany
  zrobione tylko w interfejsie SysON przepadają. Prawdą jest tekst.
- Dla każdego `view` z modelu skrypt tworzy też diagram, wypełniony elementami z `expose`:
  widok, którego `view def` ma `render asInterconnectionDiagram` (albo z `interconnection`
  w nazwie), daje Interconnection View; `view def :> StandardViewDefinitions::ActionFlowView`
  daje Action Flow View, `:> StandardViewDefinitions::StateTransitionView` State Transition
  View; pozostałe General View (także wtedy, gdy SysON nie zna danego typu diagramu).
- `expose Pakiet::*` pokazuje w SysON sam węzeł pakietu; żeby zobaczyć jego zawartość,
  użyj `expose Pakiet::**` albo wskaż elementy po kolei.
- Po otwarciu diagramu kliknij **Arrange all** (układ liczy przeglądarka, skrypt tego nie zrobi).
- Widoki skrypt szuka tylko w pakietach (`view` zagnieżdżony np. w `part def` nie dostanie diagramu).
  Projekt jest kasowany na starcie, więc do końca działania skryptu nie przeglądaj go w SysON.

## Zrzut projektów z SysON: `export.sh`

```bash
./export.sh                 # każdy projekt -> models/<projekt>/elements.json
```

Zapisuje elementy modelu przez REST API (posortowane po `@id`, więc nadają się do `git diff`).
To zrzut do wglądu i porównań, nie źródło: do SysON wraca się przez `push.sh` z plików `.sysml`.

## Pilot SysML v2 (renderowanie i walidacja)

Referencyjna implementacja OMG ([SysML v2 Pilot Implementation](https://github.com/Systems-Modeling/SysML-v2-Pilot-Implementation),
jądro Jupyter `sysml`, wersja 0.63.1 = wydanie 2026-09.1) jako serwer Jupyter bez interfejsu.
Służy do **walidacji** tekstu (parser i reguły OMG są ostrzejsze niż w SysON) i **renderowania**
diagramów poleceniem `%viz` (PlantUML + Graphviz -> SVG). Do edycji i przeglądania zostaje SysON.

```bash
docker compose --profile pilot up -d --build sysml-pilot   # http://localhost:8890, token: sysml
docker compose --profile pilot stop sysml-pilot             # zatrzymanie (samo `docker compose down` zatrzymuje też SysON)
PILOT_TOKEN=... PILOT_PORT=8891 docker compose --profile pilot up -d sysml-pilot   # inny token / port na hoście
```

- Zwykłe `docker compose up -d` uruchamia tylko SysON (usługa jest w profilu `pilot`).
- Z devcontainera: `http://host.docker.internal:8890` (REST `/api/kernels` + websocket
  `/api/kernels/<id>/channels`), nagłówek `Authorization: token sysml`.
- `src/` jest zamontowane tylko do odczytu w `/models`.
- Port na hoście to 8890, bo 8888 na Windows zajmuje VS Code (przekierowanie portu z devcontainera);
  na nim żądania wiszą bez odpowiedzi. Inny port: `PILOT_PORT`. W kontenerze serwer zawsze słucha na 8888.
- Model wysyłaj jako **jedną komórkę** (pliki sklejone w kolejności nazw, jak w `push.sh`):
  komórka widzi tylko komórki wcześniejsze, a **komórka z jakimkolwiek błędem jest w całości
  odrzucana**, więc `%viz` znajdzie elementy dopiero wtedy, gdy model nie ma błędów (ostrzeżenia nie szkodzą).
- Przykład: `%viz --view=state StanyElicytacji::AssignmentLifecycle` (widoki: `tree`, `interconnection`,
  `action`, `state`, `sequence`, `case`, `mixed`).

## Pliki

| Plik | Rola |
|---|---|
| `docker-compose.yml` | SysON + Postgres; w profilu `pilot` także pilot SysML v2 |
| `pilot/Dockerfile` | obraz pilota SysML v2 (Jupyter + jądro `sysml`, Java 21, Graphviz) |
| `push.sh` | tekst `.sysml` -> projekt w SysON |
| `export.sh` | projekty z SysON -> `models/*/elements.json` |
| `src/` | źródła `.sysml` (jeden folder = jeden projekt) |
| `postgres-data/` | dane bazy (w `.gitignore`) |
