---
title: Chunking i konfiguracja korpusu
diataxis: reference
---

# Chunking i konfiguracja korpusu

Język: **Polski** · [English](../../reference/chunking.md)

`scripts/corpus/chunking` tnie sparsowane dokumenty korpusu na chunki za pomocą semantycznego chunkera, sterowanego przez `config/chunking.yaml`. Ta strona wymienia także klucze `config/indexing.yaml` (ustawienia embeddingu i BM25 indeksu chunków) oraz `config/sources.yaml` (manifest źródeł etapu pobierania korpusu) wraz z wartościami domyślnymi, które definiują ich modele pydantic. Uzasadnienie projektu jest w stronie [Wyszukiwanie i indeksowanie](../explanation/retrieval-and-indexing.md); pakiet dostarczający ustawienia BM25 opisuje strona [Pakiety](packages.md), a moduł backendu walidujący `indexing.yaml` opisuje strona [Backend: indeksowanie i korekta](backend-indexing-proofread.md).

Wszystkie cztery modele konfiguracji (`ChunkingConfig` i jego części, `IndexingConfig` i jego części, `Manifest` i jego części, `Bm25Config`) odrzucają nieznane klucze (`extra="forbid"`), więc błędnie wpisany klucz powoduje błąd przy wczytaniu.

## Publiczne API `scripts/corpus/chunking`

| Nazwa | Opis |
|---|---|
| `build_chunker(cfg: ChunkingConfig) -> Chunker` | Buduje `TokenCounter(cfg.tokenizer)` i `OllamaEmbedder(**cfg.embeddings.model_dump())`. Dla `method == "semantic"` zwraca `SemanticChunker(cfg.semantic, embedder, count)`; każda inna wartość zgłasza `ValueError`. |
| `load_chunking_config(path) -> ChunkingConfig` | `yaml.safe_load` pliku, a następnie walidacja pydantic. |
| `ChunkingConfig` | Zwalidowana postać `config/chunking.yaml`. |
| `Chunk`, `Chunker` | Dataclass chunka i protokół chunkera (zob. niżej). |

`__all__` wymienia dokładnie te pięć nazw.

### Protokół `Chunker`

`Chunker` ma atrybuty `name` i `version` oraz metodę `chunk(document: dict) -> list[Chunk]`. Wejściem jest jeden sparsowany dokument, JSON zapisany przez `parse_raw_documents.py`: `document["sections"]` to lista sekcji z `id`, `path` (lista nagłówków) i `blocks`; każdy blok ma `text`, `type` i opcjonalnie `page`.

### `Chunk` (dataclass)

| Pole | Typ | Opis |
|---|---|---|
| `index` | `int` | Pozycja chunka w dokumencie. |
| `text` | `str` | Połączony tekst jednostek chunka. |
| `contextual_text` | `str` | `text` poprzedzony `H1 > H2 > ...` i pustym wierszem, gdy `contextual_header` jest prawdą, a jednostki mają wspólną ścieżkę nagłówków; w przeciwnym razie równy `text`. |
| `heading_path` | `list[str]` | Najdłuższy wspólny prefiks ścieżek nagłówków jednostek. |
| `section_ids` | `list[str]` | Różne identyfikatory sekcji, w kolejności. |
| `block_types` | `list[str]` | Różne typy bloków, w kolejności. |
| `pages` | `list[int]` | Posortowane, różne numery stron jednostek, które je mają. |
| `n_tokens` | `int` | Liczba tokenów `text`. |
| `n_units` | `int` | Liczba jednostek w chunku. |
| `breakpoint_distance` | `float \| None` | Odległość embeddingów do poprzedniej jednostki; `None` dla pierwszego chunka. Domyślnie `None`. |
| `extra` | `dict` | Domyślnie pusty; żaden kod w pakiecie chunkingu nie zapisuje do niego. |

### `Unit` (dataclass)

Najmniejszy element, którym operuje chunker: `text`, `section_id`, `path`, `block` (kolejny numer bloku w dokumencie; taki sam dla zdań jednego akapitu), `block_type`, `page` (`int | None`).

### `TokenCounter(tokenizer)`

Liczy tokeny tokenizerem Hugging Face o tej nazwie (`Tokenizer.from_pretrained`, bez tokenów specjalnych). Dla `None` lub gdy nie można załadować tokenizera (wypisywane jest ostrzeżenie), liczy słowa rozdzielone białymi znakami.

### Funkcje pomocnicze w `chunking.base`

| Funkcja | Opis |
|---|---|
| `split_sentences(text) -> list[str]` | Dzieli po `.`, `!` lub `?`, po których następuje biały znak, opcjonalny cudzysłów lub nawias oraz wielka litera lub cyfra. Kropki w liczbach dziesiętnych i po skrótach `e.g`, `i.e`, `et al`, `vs`, `cf`, `Fig`, `Figs`, `Tab`, `Dr`, `Mr`, `Mrs`, `Ms`, `Prof`, `approx`, `no`, `ca` (bez rozróżniania wielkości liter) nie dzielą. |
| `document_units(document, split=True) -> list[Unit]` | Spłaszcza sekcje i bloki do jednostek. Bloki z pustym tekstem są pomijane. Na zdania są dzielone wyłącznie bloki typu `paragraph` (gdy `split`); elementy list i tabele pozostają w całości. |
| `split_oversized(unit, max_tokens, count) -> list[Unit]` | Zwraca jednostkę bez zmian, gdy się mieści; w przeciwnym razie tnie ją na okna zamykane, zanim przekroczą `max_tokens` tokenów; elementami są słowa albo wiersze, gdy tekst zawiera podział wiersza. |
| `join_units(units) -> str` | Łączy teksty pustym wierszem między sekcjami, podziałem wiersza między blokami i spacją w pozostałych przypadkach. |
| `common_prefix(paths) -> list[str]` | Najdłuższy wspólny prefiks ścieżek nagłówków. |
| `build_chunk(index, units, count, contextual_header, breakpoint_distance) -> Chunk` | Wypełnia `Chunk` na podstawie jego jednostek. |

### `SemanticChunker(cfg, embedder, count)`

`name` to `"semantic"`, a `version` to `CHUNKER_VERSION`. `chunk(document)` wykonuje poniższe kroki i zwraca `[]` dla dokumentu bez jednostek:

1. `document_units(document, cfg.sentence_split)`, następnie `split_oversized` dla każdej jednostki z `cfg.max_tokens`.
2. Dla każdej jednostki buduje tekst z jednostki i do `buffer_size` sąsiadów z każdej strony (tylko sąsiedzi z tej samej sekcji, gdy `respect_sections` jest prawdą) i embeduje teksty przez `embedder.embed`. Odległość między jednostką i a i+1 wynosi `1 - dot(vector_i, vector_i+1)`.
3. Granica między jednostkami z różnych sekcji jest twardym podziałem, gdy `respect_sections` jest prawdą. Na pozostałych granicach `breakpoint_mask` wskazuje zmiany tematu; każda zmiana kończy chunk.
4. Chunk dłuższy niż `max_tokens` (i mający co najmniej dwie jednostki) jest tnięty rekurencyjnie w miejscu jego największej wewnętrznej odległości.
5. Chunki krótsze niż `min_tokens` są łączone, od najmniejszego, z tym kwalifikującym się sąsiadem, którego wspólna granica ma mniejszą odległość. Połączenie wymaga, aby oba chunki miały wspólne pierwsze `merge_scope_level` elementów ścieżki nagłówków (ich pierwszych jednostek) oraz aby rozmiar po połączeniu mieścił się w `max_tokens`. Łączenie powtarza się, aż żadne połączenie nie jest możliwe.
6. Każdy chunk jest budowany przez `build_chunk`; jego `breakpoint_distance` to odległość na jego granicy początkowej.

`breakpoint_mask(distances, cfg)` zwraca tablicę wartości logicznych, w której prawda oznacza odległość stanowiącą zmianę tematu, a dla pustego wejścia zwraca pustą tablicę:

| `type` | Odległość jest zmianą tematu, gdy |
|---|---|
| `percentile` | jest powyżej `amount`-tego percentyla odległości |
| `std_dev` | jest powyżej `mean + amount * std` |
| `interquartile` | jest powyżej `mean + amount * (q3 - q1)` |
| `gradient` | gradient odległości jest powyżej `amount`-tego percentyla gradientu |

## Stałe

| Nazwa | Wartość | Znaczenie |
|---|---|---|
| `CHUNKER_VERSION` | `"1"` | Część `config_hash()`; zmienia hash konfiguracji, gdy wynik chunkera dla tej samej konfiguracji ulega zmianie. |

## `config/chunking.yaml`

Model: `ChunkingConfig` w `scripts/corpus/chunking/config.py`. Nagłówek pliku wskazuje jako konsumenta `scripts/corpus/chunk_parsed_documents.py`, który czyta `s3://$S3_BUCKET/parsed/` i zapisuje `s3://$S3_BUCKET/chunked/`.

| Klucz | Typ | Domyślnie w modelu | Wartość w pliku | Opis |
|---|---|---|---|---|
| `method` | `Literal["semantic"]` | wymagane | `semantic` | Metoda chunkingu; blok o tej samej nazwie musi występować, inaczej walidacja kończy się błędem. |
| `documents.skip_roles` | `list[str]` | `[]` | `[]` | Dokumenty, których `source.metadata.role` jest na liście, nie są dzielone na chunki. |
| `embeddings.model` | `str` | wymagane | `bge-m3` | Model Ollama używany do obliczania odległości. |
| `embeddings.batch_size` | `int` (`> 0`) | `64` | `64` | Liczba tekstów na żądanie embeddingu. |
| `embeddings.truncate` | `bool` | `true` | `true` | Przekazywane do Ollama jako `truncate`. |
| `tokenizer` | `str \| None` | `None` | `BAAI/bge-m3` | Tokenizer Hugging Face mierzący rozmiar chunka; `null` oznacza liczenie słów. |
| `semantic.sentence_split` | `bool` | `true` | `true` | Dzielenie akapitów na zdania. |
| `semantic.buffer_size` | `int` (`>= 0`) | `1` | `1` | Sąsiedzi z każdej strony dołączani do tekstu embeddingu jednostki. |
| `semantic.breakpoint.type` | `percentile`, `std_dev`, `interquartile` lub `gradient` | `percentile` | `percentile` | Reguła `breakpoint_mask`. |
| `semantic.breakpoint.amount` | `float` | `90` | `90` | Percentyl lub mnożnik reguły. |
| `semantic.min_tokens` | `int` (`>= 0`) | `80` | `80` | Chunki poniżej tego rozmiaru są łączone. Nie może przekraczać `max_tokens`. |
| `semantic.max_tokens` | `int` (`> 0`) | `512` | `512` | Górny rozmiar chunka i jednostki. |
| `semantic.respect_sections` | `bool` | `true` | `true` | Granice sekcji są twardymi podziałami. |
| `semantic.merge_scope_level` | `int` (`>= 0`) | `1` | `1` | Zbyt małe chunki łączą się tylko z sąsiadami, którzy mają wspólne pierwsze N elementów ścieżki nagłówków. |
| `semantic.contextual_header` | `bool` | `true` | `true` | Zapisywanie ścieżki nagłówków w `contextual_text`. |

`ChunkingConfig.config_hash()` to pierwszych 12 znaków szesnastkowych SHA-256 dokumentu JSON zawierającego `CHUNKER_VERSION`, `method`, blok metody, `embeddings` i `tokenizer`. Filtr `documents` nie wchodzi w jego skład. Nagłówek `chunking.yaml` stwierdza, że hash jest zapisywany w każdym obiekcie wyjściowym oraz że zmiana klucza używanego przez aktywną metodę powoduje ponowny chunking wszystkich dokumentów.

## `config/indexing.yaml`

Model: `IndexingConfig` w `backend/app/indexing/config.py`, wczytywany przez `load_indexing_config`. Nagłówek pliku wskazuje jako konsumenta `scripts/corpus/index_chunks.py`, który czyta `s3://$S3_BUCKET/chunked/` i zapisuje do tabeli Postgres `chunks`.

| Klucz | Typ | Domyślnie w modelu | Wartość w pliku | Opis |
|---|---|---|---|---|
| `embeddings.model` | `str` | wymagane | `bge-m3` | Model embeddingów Ollama. |
| `embeddings.batch_size` | `int` (`> 0`) | `64` | `32` | Liczba tekstów na żądanie embeddingu. |
| `embeddings.truncate` | `bool` | `true` | `true` | Przekazywane do Ollama jako `truncate`. |
| `embeddings.dimensions` | `int` (`> 0`) | wymagane | `1024` | Oczekiwana szerokość wektora. Gdy model zwraca inną szerokość, `index_chunks.py` zapisuje ten plik jako `FAILED` i przechodzi do następnego pliku. Gdy `chunks.embedding` ma inny typ `vector(N)`, kończy działanie przed zaindeksowaniem jakiegokolwiek pliku. |
| `text_field` | `contextual_text` lub `text` | `contextual_text` | `contextual_text` | Pole chunka, które jest embedowane i na którym dopasowywany jest BM25. |
| `sparse.k1` | `float` (`> 0`) | `1.2` | `1.2` | Nasycenie BM25. |
| `sparse.b` | `float` (`0..1`) | `0.75` | `0.75` | Normalizacja długości w BM25. |
| `sparse.stemmer` | `str \| None` | `english` | `english` | Język Snowball albo `null` dla braku stemmingu. |

`sparse` to `Bm25Config` z pakietu core. `build_embedder(cfg)` buduje `OllamaEmbedder(**cfg.embeddings.model_dump(exclude={"dimensions"}))`.

`OllamaEmbedder(model, batch_size=64, truncate=True, base_url=None)` wysyła partie tekstów do endpointu Ollama `/api/embed` i zgłasza `RuntimeError`, gdy Ollama odpowiada 404 (model nie został pobrany). `base_url` domyślnie przyjmuje `settings.ollama_base_url`.

## `config/sources.yaml`

Model: `Manifest` w `scripts/corpus/sources.py`, wczytywany przez `load_manifest`. Nagłówek pliku wskazuje jako konsumentów `scripts/corpus/fetch_sources.py` (pobieranie do `data/raw/<id>/`) i `scripts/corpus/upload_raw_documents.py`. Nagłówek stwierdza: `attempts` są wypróbowywane po kolei, a pierwsza odpowiedź, która przechodzi sprawdzenie `expect`, jest zapisywana bez modyfikacji; co najwyżej jedno żądanie na sekundę na host, z nagłówkiem User-Agent zawierającym `CONTACT_EMAIL`; sekrety pochodzą wyłącznie ze zmiennych środowiskowych.

### Poziom główny

| Klucz | Typ | Domyślnie | Opis |
|---|---|---|---|
| `sources` | `list[Source]` | wymagane | Źródła do pobrania. Identyfikatory muszą być unikatowe. |
| `excluded` | `list[Excluded]` | `[]` | Źródła wyłączone ze wszystkich etapów. Identyfikator nie może występować na obu listach. |

### `sources[]`

| Klucz | Typ | Domyślnie | Opis |
|---|---|---|---|
| `id` | `str` | wymagane | Identyfikator źródła; nazwa folderu w `data/raw/`. |
| `title` | `str` | wymagane | Tytuł. |
| `doi`, `pmid`, `pmcid`, `release_or_version` | `str \| None` | `None` | Identyfikatory i wersja. |
| `metadata.role` | `str` | wymagane | Rola kopiowana do `meta.json`: w pliku `level0_structured` (ICD-11 MMS) lub `literature_claims`. |
| `metadata.licence`, `citation`, `evidence_level`, `population` | `str \| None` | `None` | Pola opisowe. |
| `attempts` | `list` | `None` | Uporządkowane próby pobrania (niżej). |
| `manual` | obiekt | `None` | Pliki umieszczone ręcznie, podawane jako `manual.paths` (`list[str]`, wymagane wewnątrz `manual`); pierwsza istniejąca ścieżka jest kopiowana do `data/raw/<id>/`. |
| `auth` | obiekt | `None` | API chronione poświadczeniami (niżej). |
| `required_headers` | `dict[str, str]` | `None` | Nagłówki żądań źródła API. |
| `endpoints` | `dict[str, str]` | `None` | Nazwane adresy URL API źródła API. |

Dla każdego źródła wymagane jest dokładnie jedno z `attempts`, `manual` i `auth`. Plik zawiera siedem źródeł: `icd11_mms_6a05` (`auth`), `wfadhd_consensus_2021`, `euro_consensus_adult_adhd_2019`, `nice_ng87`, `discourse_review_lifespan` i `carruthers_2021_pragmatics` (`attempts`) oraz `aadpa_guideline_2022` (`manual`).

### `attempts[]`

| Klucz | Typ | Domyślnie | Opis |
|---|---|---|---|
| `kind` | `http` lub `europepmc_resolve` | wymagane | Typ próby. |
| `expect` | `pdf`, `xml`, `html` lub `json` | wymagane dla `http` | Oczekiwany typ odpowiedzi. |
| `name` | `str` | `source` | Nazwa zapisanego pliku (`http` z `url`). |
| `url` / `urls` | `str` / `dict[str, str]` | `None` | Dla `http` wymagane jest dokładnie jedno z nich; przy `urls` każdy cel musi zostać pobrany. |
| `query` | `str` | wymagane dla `europepmc_resolve` | Wyszukiwanie w Europe PMC; jeśli trafienie ma PMCID, pobierany jest jego pełnotekstowy XML. |

### `auth`

| Klucz | Typ | Opis |
|---|---|---|
| `type` | `oauth2_client_credentials` | Jedyna wartość akceptowana przez model. |
| `token_url`, `scope` | `str` | Endpoint OAuth i zakres (scope). |
| `env` | `list[str]` | Zmienne środowiskowe z poświadczeniami: w pliku `ICD_CLIENT_ID`, `ICD_CLIENT_SECRET`. |
| `token_ttl_minutes` | `int` | Czas życia tokenu; w pliku `55`. |

### `excluded[]`

| Klucz | Typ | Domyślnie | Opis |
|---|---|---|---|
| `id` | `str \| None` | `None` | Identyfikator źródła; gdy jest ustawiony, `excluded_source_ids()` go zwraca, więc etapy pomijają to źródło. |
| `name` | `str` | wymagane | Nazwa. |
| `reason` | `str` | wymagane | Powód wyłączenia źródła. |

Plik wyklucza pięć pozycji: encję 6A05 ICD-11 Foundation (`id` `icd11_foundation_6a05_diagnostic_requirements`), PDF ICD-11 CDDR (`id` `icd11_cddr_pdf`), DSM-5-TR, wytyczne CADDRA 4.1 oraz NCBI Bookshelf NBK53659.

## Źródła w kodzie

- `scripts/corpus/chunking/__init__.py` - build_chunker, eksporty
- `scripts/corpus/chunking/base.py` - Unit, Chunk, Chunker, TokenCounter, funkcje pomocnicze dla zdań i jednostek
- `scripts/corpus/chunking/config.py` - ChunkingConfig, SemanticConfig, BreakpointConfig, CHUNKER_VERSION, config_hash
- `scripts/corpus/chunking/semantic.py` - SemanticChunker, breakpoint_mask
- `config/chunking.yaml` - aktywna metoda i hiperparametry
- `config/indexing.yaml` - ustawienia embeddingu i BM25
- `config/sources.yaml` - wartości manifestu źródeł
- `scripts/corpus/sources.py` - modele manifestu, wartości domyślne i walidatory
- `backend/app/indexing/config.py` - IndexingConfig, EmbeddingConfig i ich wartości domyślne
- `backend/app/indexing/__init__.py` - build_embedder
- `backend/app/embeddings.py` - zachowanie żądań OllamaEmbedder
- `scripts/corpus/index_chunks.py:54-66,193-198` - sprawdzenia wymiarów względem tabeli i wyniku modelu
- `packages/expert-knowledge-core/src/expert_knowledge_core/bm25.py:21-26` - wartości domyślne Bm25Config
