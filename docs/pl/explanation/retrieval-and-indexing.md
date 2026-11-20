---
title: O wyszukiwaniu i indeksowaniu
diataxis: explanation
---

# O wyszukiwaniu i indeksowaniu

Język: **Polski** · [English](../../eng/explanation/retrieval-and-indexing.md)

System przechowuje dwa przeszukiwalne magazyny w jednej bazie Postgres i oba łączą gęsty embedding bge-m3 z rzadkim wektorem BM25. Chunki literatury trafiają do tabeli `chunks`, którą zapisują skrypty korpusu. Zatwierdzone spostrzeżenia ekspertów trafiają do schematu `chips`, który zapisuje backend webowy. Kod BM25, pakowanie notatek i stałe wyszukiwania znajdują się w niezależnym od frameworków pakiecie `expert-knowledge-core`, więc ingest i wyszukiwanie używają jednej kopii; pakiet `expert-knowledge-rag` czyta `chips` przez połączenie tylko do odczytu. Strona wyjaśnia, dlaczego części mają taki kształt. Listy nazw, sygnatur i wartości domyślnych są w [Pakiety](../reference/packages.md) i [Chunking i konfiguracja korpusu](../reference/chunking.md).

## Jak to się łączy

```mermaid
flowchart LR
  parsed["Sparsowane dokumenty<br/>(bucket S3)"] --> chunker["Semantyczny chunker<br/>scripts/corpus/chunking"]
  chunker --> chunked["Dokumenty podzielone na chunki<br/>(bucket S3)"]
  chunked --> indexer["index_chunks.py"]
  indexer --> chunksTable[("Tabela chunks<br/>gęsty + rzadki")]

  answers["Zatwierdzone odpowiedzi ekspertów"] --> ingest["Ingest w backendzie<br/>app.knowledge"]
  ingest --> chips[("Schemat chips<br/>jednostki, klucze cue, sesje")]

  core["expert-knowledge-core<br/>BM25, notatki, prompty, stałe"]
  core -.-> indexer
  core -.-> ingest
  core -.-> rag["expert-knowledge-rag<br/>retrievery i łańcuchy tylko do odczytu"]
  chips --> rag
  rag --> notes["Notatki z numerami [E#]"]
```

Górna ścieżka indeksuje literaturę: chunker tnie sparsowane dokumenty, `index_chunks.py` tworzy embeddingi chunków i dopasowuje BM25 na tabeli. Dolna ścieżka indeksuje spostrzeżenia ekspertów: backend zapisuje jednostki, klucze cue i sesje oraz dopasowuje na nich BM25. Linie przerywane pokazują ponowne użycie kodu pakietu core; `expert-knowledge-rag` odpytuje `chips` i zwraca notatki, które jego łańcuchy przekazują modelowi czatu. `scripts/rag/rag_common.py` wykonuje wyszukiwanie hybrydowe po `chunks` z tymi samymi stałymi (`RRF_K`, `FUSION_DEPTH`).

### Chunking: gdzie tekst jest cięty

Chunker tnie dokument tam, gdzie odległość embeddingów między sąsiednimi jednostkami gwałtownie rośnie (docstring modułu `semantic.py`). Jednostką jest zdanie akapitu albo cały element listy lub tabela. Każda jednostka dostaje embedding razem z sąsiadami: `buffer_size` określa, ile jednostek z każdej strony wchodzi do tekstu jej embeddingu (`semantic.py:83-86`), a skonfigurowana wartość to 1, czyli jedna jednostka przed i jedna po (`config/chunking.yaml:32`). Odległość powyżej skonfigurowanego progu oznacza zmianę tematu. Granice sekcji są twardymi przerwaniami, a sąsiedzi wchodzący do tekstu embeddingu jednostki pochodzą z tej samej sekcji, więc kontekst nie przecieka przez nagłówek. Dwa limity rozmiaru korygują wynik: chunk powyżej `max_tokens` jest cięty ponownie w miejscu największej odległości wewnętrznej, a chunk poniżej `min_tokens` jest łączony z sąsiadem po bliższej granicy, o ile oba mają wspólne pierwsze `merge_scope_level` elementów ścieżki nagłówków (1 w `config/chunking.yaml`), a połączenie mieści się w `max_tokens`. Rozmiar mierzy tokenizer Hugging Face wskazany w `config/chunking.yaml` (`BAAI/bge-m3`).

Każdy chunk przechowuje dwa teksty: zwykły `text` i `contextual_text`, który zaczyna się od ścieżki nagłówków. Indeks domyślnie tworzy embedding z `contextual_text` (`text_field` w `config/indexing.yaml`), więc nagłówek staje się częścią tego, co zapytanie może dopasować.

### Indeksowanie: gęsty i rzadki w jednym wierszu

Wektor gęsty to embedding bge-m3 chunka (1024 wartości, w `chunks` indeksowany indeksem HNSW na odległości cosinusowej). Wektor rzadki zawiera wagi BM25, tak że zwykły iloczyn skalarny między zapisanym wektorem a wektorem zapytania jest równy wynikowi BM25. Dzięki temu jedna kolumna pgvector i jeden operator (`<#>`, ujemny iloczyn skalarny) wyrażają BM25 wewnątrz Postgresa. Terminy są haszowane do 2^20 wymiarów, więc nie istnieje tabela słownika; kolizja haszy tylko łączy dwa terminy (docstring `bm25.py`). Kolumna rzadka celowo nie ma indeksu: korpus jest mały, a indeks HNSW na `sparsevec` byłby przybliżony (komentarz w `backend/db/init.sql`).

BM25 potrzebuje statystyk całego korpusu (`idf` i średnia długość dokumentu). Dlatego indekser dopasowuje wektory rzadkie od nowa na całej tabeli przy każdym uruchomieniu, nawet gdy wszystkie dokumenty zostały pominięte, a backend robi to samo na całości `chips` po ingeście. Z tego powodu hasz, który decyduje, czy dokument wymaga ponownego embeddingu, pomija `sparse`: zmiana ustawień BM25 nigdy nie wymaga nowego embeddingu. Strona gęsta jest pomijana dla dokumentu, którego hasz pliku z chunkami i hasz indeksowania są niezmienione.

### Wyszukiwanie: ranking, fuzja i notatki

Wyszukiwanie szereguje kandydatów dwa razy, raz według gęstej odległości cosinusowej i raz według BM25, a oba rankingi łączy fuzją rang (reciprocal rank fusion): wynik elementu to suma `1 / (RRF_K + rank)` po rankingach. Fuzja działa na rangach, więc nie potrzebuje wspólnej skali dla wartości cosinusowych i BM25. Wiersz, który nie ma wspólnego terminu z zapytaniem, ma wynik BM25 równy 0 i nie jest trafieniem w rankingu rzadkim. Zapytanie złożone wyłącznie ze stopwords nie ma wektora rzadkiego, więc wyszukiwanie hybrydowe wraca do samego rankingu gęstego.

Magazyn ekspertów przechowuje jednostki spostrzeżeń: po jednej na każde ukierunkowane zaznaczenie oraz jedną dla zdań o przypadku jako całości. Każda jednostka ma dwa teksty, `i1` (tekst po recenzji) i `i3` (ten sam z dodanymi słowami pacjenta), każdy z własnym wektorem gęstym i rzadkim. Pytania domyślnie przeszukują `i1`, czyli indeks wybrany w ewaluacjach (komentarz w `sql.py`). Do tego magazynu prowadzą dwa retrievery:

- `ExpertQuestionRetriever` przeszukuje jednostki pytaniem klinicysty.
- `PatientTextRetriever` dzieli tekst pacjenta na zdania, szereguje klucze cue (słowa pacjenta, które eksperci zaznaczyli) dla każdego zdania, łączy rankingi zdań i szereguje jednostki według wyniku ich własnego cue plus bonusu za pozostałe cue cytowane razem z nim. Kombinacja słów pacjenta wyprzedza więc pojedyncze słowo.

Ogólne odpowiedzi o przypadku jako całości powtarzają się w sesjach i zapełniałyby wynik ogólnego pytania. Retriever pytań przesuwa na koniec jednostkę przypadku, która jest prawie duplikatem (cosinus co najmniej `NEAR_DUPLICATE`) lepiej uszeregowanej jednostki przypadku.

Trafienie nie jest zwracane jako surowy wiersz. Retrievery ładują rekord spostrzeżeń sesji i pakują jednostki w notatkę: wiersz przypadku, słowa pacjenta ze znacznikami kierunku od eksperta oraz własne zdania eksperta, każde raz, z chipami cytatów wyrenderowanymi jako krótkie cytaty. Jednostki jednej sesji, które mają wspólne zdanie, są łączone w jedną notatkę, więc zdanie się nie powtarza. Łańcuchy numerują notatki `[E1]`, `[E2]` i tak dalej, a ewaluowane prompty systemowe proszą model o ich cytowanie. Gdy nie znaleziono żadnej notatki, łańcuchy odpowiadają `NOT_IN_SOURCES` i nie wywołują modelu: bez notatek model odpowiada z wiedzy ogólnej, czemu łańcuchy mają zapobiegać (docstring `chains.py`).

## Dlaczego `expert-knowledge-core` jest niezależny od frameworków

Pakiet core zawiera to, w czym ingest backendu webowego i pakiet wyszukiwania muszą się zgadzać: wektory rzadkie BM25, notatki, rekord spostrzeżeń, prompty i stałe wyszukiwania. Nie ma w nim LangChain, frameworka webowego ani sterownika bazy danych (docstring `__init__.py`; zależności w `pyproject.toml` to pydantic, pgvector i snowballstemmer).

Każdy z tych elementów musi być identyczny po obu stronach. Zapytanie musi być tokenizowane dokładnie tak jak zapisane wektory, inaczej wagi BM25 i terminy zapytania się nie spotkają. Tekst, z którego utworzono embedding, i tekst pakowany do notatki muszą pozostawać zsynchronizowane (docstring `notes.py`). Rekord zapisywany przez ingest musi być rekordem czytanym przez wyszukiwanie, czego pilnuje `FINDINGS_VERSION`: rekord z inną wersją nie jest czytany. Docstring pakietu podaje jako jego cel to, w czym ingest aplikacji webowej i pakiet wyszukiwania muszą się zgadzać: jedną kopię tych elementów, bez LangChain, bez frameworka webowego i bez sterownika bazy danych (`__init__.py:1-7`). Konfiguracja indeksowania backendu używa `Bm25Config` z pakietu core, więc YAML indeksowania i retrievery walidują te same ustawienia.

## Dlaczego `expert-knowledge-rag` jest tylko do odczytu

`ExpertKnowledgeStore` wykonuje każde wywołanie w transakcji, która zaczyna się od `SET TRANSACTION READ ONLY`. Docstring podaje powód: błąd lub wrogi ciąg zapytania nie może zmienić bazy wiedzy. Zapisywanie jest zadaniem ingestu backendu, który zapisuje jednostki, oblicza ich embeddingi i dopasowuje BM25 od nowa.

Inne wybory w pakiecie wspierają użycie z różnych hostów. Gdy store otwiera własne połączenie z DSN, przekazuje `prepare_threshold=None` (`store.py:64`, `:91`), więc nie są używane prepared statements; docstring klasy podaje powód: dzięki temu działa za poolerem połączeń (`store.py:19-22`). Z `pool=` lub `async_pool=` store używa połączenia, które wydaje pula wywołującego, bez zmian (`store.py:59-61`, `:86-88`). Store przyjmuje DSN, pulę synchroniczną lub pulę asynchroniczną. Wektory podróżują jako tekst i są rzutowane w SQL (`CAST(CAST(x AS text) AS vector)`), więc na połączeniu nie trzeba rejestrować żadnego kodeka. Nazwa schematu jest cytowana jako identyfikator, a filtry stają się sparametryzowanymi warunkami. Wyszukiwanie administratora w backendzie używa tych retrieverów bezpośrednio, więc trafienie w tym narzędziu jest trafieniem, które dostałaby aplikacja odpowiadająca na pytania (docstring `search.py`).

## Ograniczenia i kompromisy

Kilka wartości to ta sama liczba w różnych miejscach i muszą pozostać równe:

- Model embeddingów i szerokość: `EMBEDDING_MODEL` i `EMBEDDING_DIMENSIONS` w pakiecie core, `embeddings.model` i `dimensions` w `config/indexing.yaml` oraz kolumny `vector(1024)` w bazie danych. `ExpertKnowledgeStore.vector_text` odrzuca wektor zapytania o złej szerokości, a `index_chunks.py` sprawdza szerokość kolumny tabeli i wyjścia modelu.
- Szerokość wektora rzadkiego: `DIMENSIONS` (`1 << 20`) i kolumny `sparsevec(1048576)`.
- Ustawienia BM25: pole `bm25` retrieverów musi być równe blokowi `sparse` z `config/indexing.yaml`, według którego dopasowano zapisane wektory.

Projekt rezygnuje z pewnych rzeczy dla prostoty. BM25 jest dopasowywane od nowa dla całego korpusu przy każdym ingeście; komentarz w backendzie oznacza to jako skrót, który odpowiada setkom jednostek. Wyszukiwanie rzadkie w `chunks` to dokładny skan bez indeksu. Prompty i stałe to te, które ewaluowano, a moduł promptów stwierdza, że zmiana jednego słowa zmienia to, co zmierzono.

## Powiązane strony

- [Pakiety](../reference/packages.md) - API, stałe i wartości domyślne obu pakietów
- [Chunking i konfiguracja korpusu](../reference/chunking.md) - chunker, `chunking.yaml`, `indexing.yaml`, `sources.yaml`
- [Backend: indeksowanie i korekta](../reference/backend-indexing-proofread.md) - moduły backendu, które używają pakietu core
- [Rdzeń API backendu](../reference/backend-core-api.md) - embedder i ustawienia w backendzie
- [Architektura](architecture.md) - kontenery całego systemu
- [Indeks dokumentacji](../index.md)

## Źródła w kodzie

- `packages/expert-knowledge-core/src/expert_knowledge_core/__init__.py` - cel pakietu core
- `packages/expert-knowledge-core/src/expert_knowledge_core/bm25.py` - projekt wektora rzadkiego BM25, haszowanie, tokenizacja
- `packages/expert-knowledge-core/src/expert_knowledge_core/notes.py` - pakowanie notatek i powód istnienia jednej kopii
- `packages/expert-knowledge-core/src/expert_knowledge_core/records.py` - rekord spostrzeżeń i ochrona wersji
- `packages/expert-knowledge-core/src/expert_knowledge_core/prompts.py` - ewaluowane prompty i odpowiedź powstrzymania się
- `packages/expert-knowledge-core/src/expert_knowledge_core/retrieval.py` - stałe wyszukiwania
- `packages/expert-knowledge-core/pyproject.toml` - zależności core
- `packages/expert-knowledge-rag/src/expert_knowledge_rag/store.py` - transakcje tylko do odczytu, pule, prepared statements
- `packages/expert-knowledge-rag/src/expert_knowledge_rag/retrievers.py` - dwa retrievery i ich kroki
- `packages/expert-knowledge-rag/src/expert_knowledge_rag/sql.py` - hybrydowy SQL, RRF, indeksy i1 i i3, wektory rzutowane przez tekst
- `packages/expert-knowledge-rag/src/expert_knowledge_rag/ranking.py` - reguła prawie-duplikatu i punktacja cue
- `packages/expert-knowledge-rag/src/expert_knowledge_rag/documents.py` - pakowanie trafień w notatki
- `packages/expert-knowledge-rag/src/expert_knowledge_rag/chains.py` - powstrzymanie się od odpowiedzi i numeracja [E#]
- `scripts/corpus/chunking/semantic.py` - algorytm chunkingu semantycznego
- `scripts/corpus/chunking/config.py` - parametry chunkingu i hasz konfiguracji
- `scripts/corpus/chunking/base.py` - jednostki, tekst kontekstowy, liczenie tokenów
- `scripts/corpus/index_chunks.py` - indeksowanie gęste, reguła pomijania, ponowne dopasowanie rzadkie, sprawdzenia wymiarów
- `scripts/rag/rag_common.py:1-30,81-100` - wyszukiwanie hybrydowe po tabeli chunks
- `config/chunking.yaml` - ustawienia chunkingu
- `config/indexing.yaml` - ustawienia embeddingów i wektora rzadkiego, text_field
- `backend/db/init.sql:35-69` - tabela chunks, indeks HNSW, kolumna rzadka bez indeksu
- `backend/app/indexing/config.py` - IndexingConfig używa Bm25Config
- `backend/app/indexing/__init__.py` - pakiet indexing importuje moduł bm25 z core
- `backend/app/knowledge/ingest.py:285-377` - jednostki, klucze cue i ponowne dopasowanie BM25 po chips
- `backend/app/knowledge/search.py:1-94` - wyszukiwanie administratora używa retrieverów rag
