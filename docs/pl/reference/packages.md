---
title: Pakiety expert-knowledge-core i expert-knowledge-rag
diataxis: reference
---

# Pakiety `expert-knowledge-core` i `expert-knowledge-rag`

Język: **Polski** · [English](../../reference/packages.md)

`expert-knowledge-core` (`packages/expert-knowledge-core`) zawiera wektory rzadkie BM25, pakowanie notatek, sprawdzone prompty, typy rekordów findings i stałe wyszukiwania; zależy wyłącznie od pydantic, pgvector i snowballstemmer. `expert-knowledge-rag` (`packages/expert-knowledge-rag`) udostępnia retrievery LangChain i łańcuchy odpowiedzi, które czytają schemat Postgres `chips`; zależy od pakietu core, `langchain-core`, `psycopg` i `numpy`. Oba pakiety to biblioteki Pythona (`requires-python >=3.12`) bez CLI i bez serwera.

O miejscu obu pakietów w przepływie indeksowania i wyszukiwania mówi strona [Wyszukiwanie i indeksowanie](../explanation/retrieval-and-indexing.md). Moduły backendu, które importują pakiet core, opisuje [Backend: indeksowanie i korekta](backend-indexing-proofread.md).

## expert_knowledge_core

`__init__.py` pakietu zawiera docstring i nie ma reeksportów; importuj z podmodułów.

### Moduł `bm25`

Wagi terminów BM25 zapisane jako wartości pgvector `sparsevec`. Wektor dokumentu zawiera `idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * dl / avgdl))` dla każdego terminu; wektor zapytania zawiera liczbę wystąpień każdego terminu, więc iloczyn skalarny jest wynikiem BM25.

| Nazwa | Sygnatura lub wartość | Opis |
|---|---|---|
| `Bm25Config` | model pydantic, `extra="forbid"` | Nieznane klucze powodują błąd przy wczytaniu. Pola poniżej. |
| `Bm25Config.k1` | `float = 1.2`, musi być `> 0` | Nasycenie częstości terminu. |
| `Bm25Config.b` | `float = 0.75`, `0 <= b <= 1` | Normalizacja długości. |
| `Bm25Config.stemmer` | `str \| None = "english"` | Język Snowball; `None` wyłącza stemming. |
| `Tokenizer(cfg)(text)` | `-> list[str]` | Zamienia tekst na małe litery, bierze tokeny pasujące do `[a-z0-9]+`, odrzuca stopwordy, a następnie stemuje, jeśli skonfigurowano stemmer. |
| `term_dim(token)` | `-> int` | 8-bajtowy skrót blake2b tokenu, odczytany jako big-endian, modulo `DIMENSIONS`. |
| `fit(texts, cfg)` | `-> list[SparseVector]` | Wektory dokumentów dla całego korpusu. `idf = log(1 + (n - d + 0.5) / (d + 0.5))` i `avgdl` są globalne dla korpusu. Pusta lista daje pustą listę. |
| `query_vector(text, cfg)` | `-> SparseVector \| None` | Liczby wystąpień terminów zapytania; `None`, gdy po tokenizacji nie zostaje żaden termin. |
| `DIMENSIONS` | `1 << 20` (1048576) | Szerokość każdego wektora rzadkiego; odpowiada kolumnom `sparsevec(1048576)`. |
| `STOPWORDS` | `frozenset` 49 angielskich słów | Usuwane przez `Tokenizer`. |

### Moduł `notes`

Czyste funkcje operujące na zwykłych słownikach (`records.Record`); bez modeli i bez bazy danych.

| Funkcja | Opis |
|---|---|
| `split_sentences(text) -> list[tuple[int, int]]` | Zakresy zdań. Podział wiersza zawsze kończy zdanie. W obrębie wiersza podział nie następuje wewnątrz cytatu, po żadnym ze skrótów `e.g.`, `i.e.`, `vs.`, `etc.`, `approx.`, `hx.`, `dr.`, `r/o.` ani po numerze listy. Zdanie krótsze niż `MIN_SENTENCE_WORDS` słów łączy się z sąsiadem w tym samym wierszu. |
| `quote_spans(text) -> list[tuple[int, int, str]]` | Zakresy tekstu w cudzysłowie podwójnym (`"..."` i cudzysłowy typograficzne) oraz tekstu w `'...'` o długości od 4 do 80 znaków bez podziału wiersza. |
| `quote_pieces(sentence) -> list[str]` | Cytowane fragmenty zdania, dzielone na `...` i `…`. |
| `short_quote(text, words=8) -> str` | `«` pierwsze `words` słów `»`, z `…`, gdy tekst jest dłuższy. |
| `render_sentence(text, highlights) -> str` | Zastępuje każdy chip `⟦hN⟧` wartością `short_quote` zaznaczenia, którego `chip` wynosi N. Chip bez pasującego zaznaczenia zgłasza `KeyError`. |
| `by_question(sentences, highlights) -> list[str]` | Jeden wiersz `Qn: sentence sentence` na każdy ciąg zdań o tym samym `question_id`. |
| `overall(meta) -> str` | `overall: insufficient information`, `overall N/5` albo `no overall rating`. |
| `case_label(meta) -> str` | Etykieta złożona z rodzajnika, populacji i ujęcia, na przykład `an adult's journal entry`. |
| `header(meta, unit) -> str` | Wiersz nagłówka jednostki: klinicysta z opcjonalną rolą, etykieta przypadku, `case-level points` lub `fragment marked: <direction>` oraz ocena ogólna, połączone przez ` · `. |
| `merge_groups(units_by_id, unit_ids) -> list[list[str]]` | Grupuje identyfikatory jednostek, które mają wspólny identyfikator zdania, przechodnio; grupy i ich elementy zachowują kolejność pierwszego wystąpienia. |
| `pack_block(rec, unit_ids) -> str` | Tekst notatki: wiersz `Teaching case <vignette_id>: ...`, wiersz `Patient's words:` ze znacznikami kierunku (gdy jednostki mają zaznaczenia), następnie `Clinician's own words:` i wiersze `by_question`, każde zdanie jeden raz. |

| Stała | Wartość | Znaczenie |
|---|---|---|
| `CHIP_RE` | `⟦h(\d+)⟧` | Chip cytatu w odpowiedzi. |
| `FRAMING_LABEL` | `email`, `forum_post`, `personal_journal` na `email`, `forum post`, `journal entry` | Etykieta dla każdego ujęcia. |
| `MIN_SENTENCE_WORDS` | `4` | Krótsze zdania łączą się z sąsiadem. |
| `RENDER_WORDS` | `8` | Słowa zachowywane przez `short_quote`. |
| `CASE` | `"case"` | Reeksportowana z `records`. |

### Moduł `records`

Rekord findings zapisany w `chips.elicitation_sessions.document`. Rekordy to zwykłe słowniki; TypedDicty jedynie je opisują.

| Nazwa | Pola lub wartość |
|---|---|
| `FINDINGS_VERSION` | `1`. Rekord z inną wartością `version` nie jest odczytywany. |
| `CASE` | `"case"`: cel zdania dotyczącego tekstu jako całości. |
| `Direction` | `Literal["toward", "away", "neutral", "unclear"]` |
| `Highlight` | `id` (`h1..` ekspert, `i1..` niejawne), `origin` (`expert` lub `implicit`), `chip` (`int \| None`), `span` (`[start, end)` w winiecie), `text`, `direction` (`Direction \| None`). |
| `Sentence` | `id` (na przykład `Q2.3`), `question_id`, `idx`, `span`, `text`, `targets` (identyfikatory zaznaczeń i/lub `case`), `assigned_by` (`chip`, `quote`, `llm`, `expert` lub `None`). |
| `Unit` | `id`, `kind` (`fragment` lub `case`), `highlight`, `direction`, `sentences`, `context` (współcytowane zaznaczenia), `body`, `i1`, `i3`. |
| `Meta` | `role`, `framing`, `population`, `rating` (`int \| None`), `insufficient` (`bool`). |
| `Record` (`total=False`) | `version`, `session_id`, `expert_id`, `vignette_id`, `vignette_version`, `meta`, `highlights`, `sentences`, `units`, `flags`. |
| `is_readable(document) -> bool` | Prawda dla słownika, którego `version` jest równe `FINDINGS_VERSION` i który ma klucze `meta`, `highlights`, `sentences` i `units`. |

### Moduł `prompts`

| Nazwa | Opis |
|---|---|
| `NOT_IN_SOURCES` | `"NOT_IN_SOURCES"`: odpowiedź, gdy notatki nie odpowiadają na pytanie. |
| `EXPERT_SYSTEM_PROMPT` | Prompt systemowy dla pytania klinicysty; prosi o 3 do 6 zdań i cytaty notatek, takie jak `[E2]`. |
| `PATIENT_SYSTEM_PROMPT` | Prompt systemowy dla tekstu pacjenta; prosi o 4 do 7 zdań i zabrania stawiania diagnoz. |
| `format_notes(texts) -> str` | Bloki `[E1] text` oddzielone pustym wierszem. |
| `build_expert_prompt(question, texts) -> str` | `Question: ...`, gdy `texts` jest puste; w przeciwnym razie blok `Notes:` a po nim pytanie. |
| `build_patient_prompt(patient_text, question, texts) -> str` | Blok `Notes:` (`(none)`, gdy `texts` jest puste), cytowany tekst pacjenta, a następnie pytanie. |

### Moduł `retrieval`

| Stała | Wartość | Znaczenie |
|---|---|---|
| `RRF_K` | `60` | Reciprocal rank fusion: wynik to suma po rankingach z `1 / (RRF_K + rank)`. |
| `FUSION_DEPTH` | `50` | Kandydaci pobierani z każdego rankingu przed fuzją. |
| `NEAR_DUPLICATE` | `0.9` | Kosinus dwóch jednostek typu case, od którego uchodzą one za tę samą ogólną odpowiedź. |
| `PATIENT_TOP_CUES` | `10` | Klucze wskazówek (cue keys) zachowywane dla każdego zdania pacjenta. |
| `CONTEXT_BONUS` | `0.5` | Waga wyników współcytowanych wskazówek. |
| `EMBEDDING_DIMENSIONS` | `1024` | Szerokość zapisanych wektorów (bge-m3). |
| `EMBEDDING_MODEL` | `"bge-m3"` | Model, którym utworzono zapisane wektory. |

### Moduł `example`

`example_record(session_id="S1", expert_id="X1", role=None) -> Record` zwraca głęboko skopiowany przykład (winieta `V001`, `vignette_version` 1) z czterema zaznaczeniami fragmentów, dziesięcioma zdaniami i zbudowanymi z nich jednostkami (po jednej na zaznaczenie z celem oraz jednostka typu case). Służy do testów, plików README i skryptów smoke.

## expert_knowledge_rag

`from expert_knowledge_rag import ...` eksportuje dziesięć nazw (`__all__`): `ExpertFilter`, `ExpertKnowledgeStore`, `ExpertQuestionRetriever`, `PatientTextRetriever`, `default_embeddings`, `expert_answer_chain`, `expert_prompt`, `format_notes`, `patient_answer_chain` i `patient_prompt`.

### `ExpertKnowledgeStore`

`ExpertKnowledgeStore(dsn=None, *, pool=None, async_pool=None, schema="chips", dimensions=1024)` to połączenie z bazą danych. Konstruktor zgłasza `ValueError`, gdy `dsn`, `pool` i `async_pool` mają wartość `None`.

| Parametr | Typ | Domyślnie | Opis |
|---|---|---|---|
| `dsn` | `str \| None` | `None` | Ciąg połączenia; używany, gdy nie podano puli. |
| `pool` | dowolny obiekt z `.connection()` | `None` | Pula synchroniczna, na przykład `psycopg_pool.ConnectionPool`. |
| `async_pool` | dowolny obiekt z asynchronicznym `.connection()` | `None` | Pula asynchroniczna, na przykład `AsyncConnectionPool`. |
| `schema` | `str` | `"chips"` | Schemat Postgres; w każdym zapytaniu cytowany jako identyfikator. |
| `dimensions` | `int` | `EMBEDDING_DIMENSIONS` (1024) | Szerokość, jaką muszą mieć wektory zapytań. |

| Metoda | Opis |
|---|---|
| `vector_text(vector) -> str` | Formatuje embedding zapytania jako `[v1,v2,...]`, używając `%.8g` dla każdej wartości. Zgłasza `ValueError`, gdy długość różni się od `dimensions`; komunikat wymienia bge-m3. |
| `run(queries) -> list[Rows]` | Uruchamia pary `(query, params)` po kolei w jednej transakcji, po `SET TRANSACTION READ ONLY`, i zwraca wiersze każdego zapytania jako słowniki. Używa `pool.connection()` lub `psycopg.connect(dsn, prepare_threshold=None)`. Przy samym `async_pool` kończy się niepowodzeniem asercji. |
| `arun(queries) -> list[Rows]` | Asynchroniczny odpowiednik `run`, używający `async_pool.connection()` lub `psycopg.AsyncConnection.connect(dsn, prepare_threshold=None)`. |

### Retrievery

Oba retrievery dziedziczą po `BaseRetriever` z LangChain, implementują synchroniczne i asynchroniczne wyszukiwanie i zwracają spakowane notatki jako obiekty `Document`. Mają wspólne pola:

| Pole | Typ | Domyślnie | Opis |
|---|---|---|---|
| `store` | `ExpertKnowledgeStore` | wymagane | Dostęp do bazy danych. |
| `embeddings` | `Embeddings` z LangChain | wymagane | Musi to być model, którym utworzono zapisane wektory (bge-m3). |
| `k` | `int` (`>= 1`) | `4` | Liczba zwracanych notatek; argument nazwany `k` wywołania go nadpisuje. |
| `search` | `"hybrid"`, `"dense"` lub `"bm25"` | `"hybrid"` | Tryb hybrid łączy rankingi gęsty i BM25 za pomocą RRF. |
| `filter` | `ExpertFilter` | `ExpertFilter()` | Które jednostki wyszukiwanie może zwrócić. |
| `merge_shared` | `bool` | `True` | Jednostki jednej sesji, które mają wspólne zdanie, stają się jedną notatką. |
| `bm25` | `Bm25Config` | `Bm25Config()` | Tokenizacja zapytania; musi być równa konfiguracji użytej dla zapisanych wektorów. |
| `fusion_depth` | `int` | `FUSION_DEPTH` (50) | Kandydaci na ranking. |
| `overfetch` | `int` (`>= 1`) | `4` | Liczba jednostek pobieranych na każdą żądaną notatkę (`k * overfetch`). |

**`ExpertQuestionRetriever`** przyjmuje pytanie klinicysty i zwraca notatki. Dodaje dwa pola:

| Pole | Typ | Domyślnie | Opis |
|---|---|---|---|
| `index` | `"i1"`, `"i3"` lub `"both"` | `"i1"` | `i1` przeszukuje zrecenzowany tekst, `i3` tekst z dopisanymi słowami pacjenta, `both` łączy oba. |
| `downweight_duplicate_cases` | `bool` | `True` | Jednostki case, które są niemal duplikatem lepiej ocenionej jednostki case, przesuwają się na koniec. |

Zachowanie: puste zapytanie zwraca `[]`. Gdy `search` ma wartość inną niż `"dense"`, zapytanie jest zamieniane na wektor BM25; jeśli po tokenizacji nie zostaje żaden termin, `hybrid` przechodzi na `dense`, a `bm25` zwraca `[]`. Przy `search="bm25"` model embeddingów nie jest wywoływany. Wyszukiwanie jednostek, reguła niemal-duplikatów, zapytanie o rekordy sesji i `build_documents` wykonują się w tej kolejności, a zwracanych jest pierwszych `k` notatek.

**`PatientTextRetriever`** przyjmuje tekst pacjenta i zwraca notatki o zaznaczeniach, do których jest podobny. Ma wyłącznie wspólne pola. Zachowanie:

1. Dzieli tekst przez `notes.split_sentences` (cały tekst po obcięciu białych znaków, jeśli nic z tego nie wynika).
2. Embeduje zdania przez `embed_documents`, chyba że `search="bm25"`.
3. Uruchamia jedno `sql.cues_search` na zdanie po kluczach wskazówek. Zdanie bez terminów BM25 przechodzi na `dense` w trybie `hybrid` i jest pomijane w trybie `bm25`; brak zapytań oznacza `[]`.
4. Ocenia każdą wskazówkę przez `ranking.cue_scores` (RRF po rankingach zdań) i wczytuje jednostki tych wskazówek przez `sql.units_for_cues`.
5. Układa jednostki w ranking przez `ranking.rank_by_cues`, zachowuje `k * overfetch` i buduje notatki.

Nie stosuje reguły niemal-duplikatów.

### `ExpertFilter`

Model pydantic; każde ustawione pole musi być spełnione.

| Pole | Typ | Domyślnie | Dotyczy |
|---|---|---|---|
| `populations` | `list[str] \| None` | `None` | Jednostek (`population`). |
| `tracks` | `list[str] \| None` | `None` | Jednostek (`track`). |
| `framings` | `list[str] \| None` | `None` | Jednostek (`framing`). |
| `vignettes` | `list[str] \| None` | `None` | Jednostek i kluczy wskazówek (`vignette_id = ANY`). |
| `exclude_vignettes` | `list[str]` | `[]` | Jednostek i kluczy wskazówek (`vignette_id <> ALL`). |
| `experts` | `list[str] \| None` | `None` | Tylko jednostek (`expert_id`); klucze wskazówek są wspólne, więc nie są filtrowane według eksperta. |

`on_unit(alias="u")` i `on_cue(alias="c")` zwracają `(conditions, params)` z sparametryzowanymi warunkami; `all_of(conditions)` łączy je przez `AND` albo daje `TRUE`, gdy warunków nie ma.

### Łańcuchy

| Funkcja | Wejście | Wyjście |
|---|---|---|
| `expert_answer_chain(retriever, llm)` | ciąg znaków lub słownik z `question` | `{"answer": str, "notes": [Document]}` |
| `patient_answer_chain(retriever, llm)` | ciąg znaków lub słownik z `patient_text` i opcjonalnym `question` | `{"answer": str, "notes": [Document]}` |

Gdy retriever nie zwraca dokumentów, odpowiedzią jest `NOT_IN_SOURCES`, `notes` jest puste, a model nie jest wywoływany. Domyślnym `question` łańcucha pacjenta jest `DEFAULT_PATIENT_QUESTION` (`"What do the notes say about how this text should be read?"`, zdefiniowane w `chains.py`).

### Prompty i embeddingi

| Nazwa | Opis |
|---|---|
| `expert_prompt()` | `ChatPromptTemplate` z promptem systemowym eksperta z pakietu core i zmiennymi `notes` i `question`. |
| `patient_prompt()` | `ChatPromptTemplate` z promptem systemowym pacjenta z pakietu core i zmiennymi `notes`, `patient_text` i `question`. |
| `format_notes(docs) -> str` | `core.prompts.format_notes` zastosowane do `page_content` dokumentów. |
| `default_embeddings(base_url="http://localhost:11434", **kwargs)` | Zwraca `langchain_ollama.OllamaEmbeddings(model="bge-m3", base_url=base_url, **kwargs)`. Import następuje wewnątrz funkcji, więc dodatek `ollama` jest potrzebny dopiero przy jej wywołaniu. |

### Moduły wewnętrzne

Te moduły nie wchodzą do `__all__`, ale definiują reguły wyszukiwania.

| Nazwa | Opis |
|---|---|
| `documents.build_documents(hits, records, *, merge=True) -> list[Document]` | Jeden `Document` na notatkę, uporządkowany według pozycji jej najlepszej jednostki. `page_content` to `pack_block` grupy. Sesja, której rekordu brakuje, który nie jest czytelny albo któremu brakuje jednostki, daje jeden `Document` na jednostkę z `embed_text` jako treścią i zalogowane ostrzeżenie. |
| `documents.SOURCE` | `"expert"`; wartość `metadata["source"]`. |
| `documents.local_id(hit)` | Identyfikator jednostki wewnątrz rekordu: identyfikator bez prefiksu `<session_id>-<vignette_id>-`; zgłasza `ValueError`, gdy prefiksu brakuje. |
| `ranking.UnitHit` | Zamrożony dataclass: `id`, `session_id`, `expert_id`, `vignette_id`, `vignette_version`, `kind`, `highlight_id`, `direction`, `embed_text`, `score`, `vector` (`np.ndarray \| None`, ustawiany tylko dla jednostek case). `UnitHit.from_row(row, score=None)` buduje go z wiersza. |
| `ranking.downweight_duplicate_cases(hits)` | Jednostki case, których kosinus względem zachowanej jednostki case stojącej przed nimi w rankingu wynosi co najmniej `NEAR_DUPLICATE`, trafiają na koniec; pozostałe jednostki zachowują kolejność. |
| `ranking.cue_scores(rankings, rrf_k)` | Suma `1 / (rrf_k + rank)` dla każdej wskazówki po rankingach zdań. |
| `ranking.rank_by_cues(rows, score)` | Jednostki, których własna wskazówka uzyskała wynik, z wynikiem `own + CONTEXT_BONUS * sum(context cue scores)`, posortowane malejąco według wyniku, a następnie według identyfikatora. |
| `sql.units_search(schema, *, index, search, limit, filter, dense=None, sparse=None, depth=FUSION_DEPTH)` | Zapytanie po `finding_units`: jedno CTE rankingu na parę kolumn gęstych i/lub rzadkich, łączone przez `sum(1.0 / (RRF_K + rank))`, uporządkowane według wyniku, a następnie identyfikatora. Ranking gęsty używa odległości kosinusowej `<=>`; ranking rzadki używa `<#>` i zachowuje tylko wiersze z wartością ujemną (wspólny termin). Jednostki case zwracają swój `embedding` jako tekst w `vector`. |
| `sql.cues_search(schema, *, search, filter, dense=None, sparse=None, top=PATIENT_TOP_CUES, depth=FUSION_DEPTH)` | Rankinguje `cue_keys` jako `cue_id`, `score`. Biorą udział tylko wskazówki, które mają jednostkę dopuszczoną przez filtr. |
| `sql.units_for_cues(schema, cue_ids, filter)` | Jednostki, których własna wskazówka (`unit_cues.role = 'cue'`) należy do `cue_ids`, z `cue_id` i tablicą `context_ids` (`role = 'context'`). |
| `sql.sessions(schema, session_ids)` | `id` i `document` wierszy `elicitation_sessions`. |
| `sql.INDEXES` | `i1` to (`embedding`, `sparse`); `i3` to (`embedding_combined`, `sparse_combined`); `both` to obie pary. |
| `sql.UNIT_COLUMNS` | `id`, `session_id`, `expert_id`, `vignette_id`, `vignette_version`, `kind`, `highlight_id`, `direction`, `embed_text`. |
| `sql.Search`, `sql.Index`, `sql.Query` | `Literal["hybrid", "dense", "bm25"]`, `Literal["i1", "i3", "both"]`, `tuple[Composed, dict]`. |

Metadane notatki (`documents._metadata`): `source`, `unit_ids`, `session_id`, `expert_id`, `vignette_id`, `vignette_version`, `kinds`, `directions`, `patient_words` (lista `text` i `direction`), `score` (najlepszej jednostki) i `merged` (`True`, gdy notatka zawiera więcej niż jedną jednostkę).

## Zależności

| Pakiet | Zależności (`pyproject.toml`) |
|---|---|
| `expert-knowledge-core` | `pydantic>=2.6`, `pgvector>=0.3`, `snowballstemmer>=3.1.1` |
| `expert-knowledge-rag` | `expert-knowledge-core` (źródło w workspace uv), `langchain-core>=1.0,<2`, `psycopg[binary]>=3.2`, `numpy>=2.0` |
| `expert-knowledge-rag`, dodatek `ollama` | `langchain-ollama>=1.0` |
| `expert-knowledge-rag`, dodatek `pool` | `psycopg-pool>=3.2` |

Konfiguracja pytest pakietu rag ustawia `asyncio_mode = "auto"` i deklaruje marker `integration` (wymaga Postgresa z `DATABASE_URL`).

## Źródła w kodzie

- `packages/expert-knowledge-core/pyproject.toml` - zależności core
- `packages/expert-knowledge-core/src/expert_knowledge_core/__init__.py` - docstring pakietu, brak reeksportów
- `packages/expert-knowledge-core/src/expert_knowledge_core/bm25.py` - Bm25Config, Tokenizer, fit, query_vector, DIMENSIONS, STOPWORDS
- `packages/expert-knowledge-core/src/expert_knowledge_core/example.py` - example_record
- `packages/expert-knowledge-core/src/expert_knowledge_core/notes.py` - dzielenie na zdania, renderowanie, pakowanie, stałe
- `packages/expert-knowledge-core/src/expert_knowledge_core/prompts.py` - prompty systemowe, NOT_IN_SOURCES, budowniczowie promptów
- `packages/expert-knowledge-core/src/expert_knowledge_core/records.py` - TypedDicty rekordów, FINDINGS_VERSION, is_readable
- `packages/expert-knowledge-core/src/expert_knowledge_core/retrieval.py` - stałe wyszukiwania
- `packages/expert-knowledge-rag/pyproject.toml` - zależności rag, dodatki, ustawienia pytest
- `packages/expert-knowledge-rag/src/expert_knowledge_rag/__init__.py` - publiczne eksporty
- `packages/expert-knowledge-rag/src/expert_knowledge_rag/chains.py` - łańcuchy odpowiedzi, DEFAULT_PATIENT_QUESTION
- `packages/expert-knowledge-rag/src/expert_knowledge_rag/documents.py` - build_documents, metadane, local_id
- `packages/expert-knowledge-rag/src/expert_knowledge_rag/filters.py` - ExpertFilter, all_of
- `packages/expert-knowledge-rag/src/expert_knowledge_rag/ollama.py` - default_embeddings
- `packages/expert-knowledge-rag/src/expert_knowledge_rag/prompts.py` - szablony promptów, format_notes
- `packages/expert-knowledge-rag/src/expert_knowledge_rag/ranking.py` - UnitHit, obniżanie wagi duplikatów, ocena wskazówek
- `packages/expert-knowledge-rag/src/expert_knowledge_rag/retrievers.py` - oba retrievery i ich pola
- `packages/expert-knowledge-rag/src/expert_knowledge_rag/sql.py` - budowniczowie zapytań, INDEXES, UNIT_COLUMNS
- `packages/expert-knowledge-rag/src/expert_knowledge_rag/store.py` - ExpertKnowledgeStore
