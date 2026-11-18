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
  w nazwie), daje Interconnection View, pozostałe General View.
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

## Pliki

| Plik | Rola |
|---|---|
| `docker-compose.yml` | SysON + Postgres |
| `push.sh` | tekst `.sysml` -> projekt w SysON |
| `export.sh` | projekty z SysON -> `models/*/elements.json` |
| `src/` | źródła `.sysml` (jeden folder = jeden projekt) |
| `postgres-data/` | dane bazy (w `.gitignore`) |
