---
title: Backend indeksowania i korekty
diataxis: reference
---

# Moduły backendu `app.indexing` i `app.proofread`

Język: **Polski** · [English](../../eng/reference/backend-indexing-proofread.md)

`app.indexing` wczytuje i waliduje `config/indexing.yaml` oraz buduje embeddera Ollama. `app.proofread` koryguje przesłaną odpowiedź (usuwanie śmieci, gramatyka LanguageTool, opcjonalne ulepszenie przez model, jedno zdanie w wierszu), wiąże każdy wiersz z cytatem i obsługuje krok edycji i zatwierdzenia przez autora. `app.proofread` nie ma własnego routera; router przydziałów udostępnia jego funkcje serwisowe.

Powiązane strony: [winiety i wiedza](backend-vignettes-knowledge.md), [przydziały i zadania](backend-assignments-jobs.md), [recenzje](backend-reviews.md), [pakiety współdzielone](packages.md), [wyszukiwanie i indeksowanie](../explanation/retrieval-and-indexing.md), [architektura](../explanation/architecture.md).

## Indeksowanie: publiczne API

| Nazwa | Sygnatura | Zachowanie |
|---|---|---|
| `load_indexing_config` | `(path: Path) -> IndexingConfig` | parsuje YAML przez `yaml.safe_load` i waliduje go; nieznane klucze nie przechodzą walidacji |
| `build_embedder` | `(cfg: IndexingConfig) -> Embedder` | zwraca `OllamaEmbedder(model, batch_size, truncate)`; `dimensions` nie jest przekazywane do embeddera |
| `bm25` | moduł | reeksport `expert_knowledge_core.bm25` |
| `Bm25Config`, `IndexingConfig` | klasy | reeksportowane z pakietu |

`OllamaEmbedder.embed(texts) -> np.ndarray` (`backend/app/embeddings.py`) wysyła partie po `batch_size` tekstów do `/api/embed` pod adresem `ollama_base_url` z parametrem `truncate`, zgłasza `RuntimeError` przy odpowiedzi HTTP 404 (model nie został pobrany) i zwraca wiersze znormalizowane normą L2. Limit czasu jego klienta HTTP wynosi 300 sekund.

## Konfiguracja indeksowania

Plik to `config/indexing.yaml`. `app.knowledge.embedding` i `app.knowledge.ingest` czytają go z `settings.project_root / "config" / "indexing.yaml"`.

| Klucz | Typ | Domyślna w kodzie | Wartość w `config/indexing.yaml` | Opis |
|---|---|---|---|---|
| `embeddings.model` | `str` | wymagane | `bge-m3` | model embeddingów Ollama |
| `embeddings.batch_size` | `int`, > 0 | `64` | `32` | liczba tekstów na żądanie do Ollama |
| `embeddings.truncate` | `bool` | `True` | `true` | przekazywane do Ollama jako `truncate` |
| `embeddings.dimensions` | `int`, > 0 | wymagane | `1024` | oczekiwana szerokość wektora; `embed_texts` zgłasza `RuntimeError` przy innym kształcie |
| `text_field` | `contextual_text` lub `text` | `contextual_text` | `contextual_text` | wybiera kolumnę chunka do embedowania |
| `sparse.k1` | `float`, > 0 | `1.2` | `1.2` | nasycenie częstości terminu w BM25 |
| `sparse.b` | `float`, 0 do 1 | `0.75` | `0.75` | normalizacja długości w BM25 |
| `sparse.stemmer` | `str` lub `None` | `english` | `english` | język Snowball albo `null` oznaczające brak stemmingu |

`text_field` nie ma czytelnika w `backend/app`. `scripts/corpus/index_chunks.py` czyta go jako `cfg.text_field`, aby wybrać kolumnę do embedowania. Pola BM25 są zdefiniowane w `packages/expert-knowledge-core/src/expert_knowledge_core/bm25.py` (`Bm25Config`).

Modele `EmbeddingConfig`, `IndexEmbeddingConfig`, `IndexingConfig` i bazowy `Model` używają `extra="forbid"`.

## Korekta: ustawienia

| Ustawienie (nazwa zmiennej środowiskowej) | Typ | Domyślnie | Skutek |
|---|---|---|---|
| `require_compute` (`REQUIRE_COMPUTE`) | `bool` | `False` | gdy prawda, błąd transportu z LanguageTool lub Ollama kończy zadanie błędem zamiast pominięcia przebiegu |
| `classifier_model` (`CLASSIFIER_MODEL`) | `str` | `qwen3.5:9b` | model, który przypisuje zdania bez cytatu |
| `enhance_model` (`ENHANCE_MODEL`) | `str` | `qwen3.5:9b` | model przebiegu ulepszania; pusty ciąg wyłącza przebieg |
| `languagetool_url` (`LANGUAGETOOL_URL`) | `str` | `http://localhost:8010` | serwer LanguageTool |
| `languagetool_language` (`LANGUAGETOOL_LANGUAGE`) | `str` | `en-US` | pole `language` żądania sprawdzenia |
| `languagetool_timeout` (`LANGUAGETOOL_TIMEOUT`) | `float` | `60` | limit czasu żądania w sekundach |
| `ollama_base_url` (`OLLAMA_BASE_URL`) | `str` | `http://localhost:11434` | serwer Ollama |
| `ollama_request_timeout` | `float` | `600` | limit czasu czatu Ollama (komentarz w ustawieniach: jedna odpowiedź może obejmować załadowanie modelu) |

`Settings` nie ustawia prefiksu zmiennych środowiskowych; `.env.example` wymienia nazwy pisane wielkimi literami `REQUIRE_COMPUTE`, `CLASSIFIER_MODEL`, `ENHANCE_MODEL`, `LANGUAGETOOL_URL` i `OLLAMA_BASE_URL`.

## Korekta: potok (`pipeline.py`)

`proofread_answer(question: str, answer: str, quotes: dict[int, str], vignette: str) -> Proofread` wykonuje po kolei:

1. `garbage.drop_garbage` ze słownictwem winiety jako słowami chronionymi.
2. `grammar.check` (klucz przebiegu `grammar`).
3. `enhance.enhance`, gdy pozostały tekst nie jest pusty.
4. `grammar.check` ponownie na ulepszonym tekście (klucz przebiegu `grammar_after`), gdy ulepszenie zostało przyjęte.
5. `layout`, który układa jedno zdanie w wierszu za pomocą `split_sentences`.

`Proofread` to dataclass z polami `text`, `dropped` (usunięte zdania) i `passes`.

Wpisy `passes`:

| Klucz | Wartość |
|---|---|
| `dropped` | liczba usuniętych zdań |
| `grammar`, `grammar_after` | liczba zastosowanych poprawek albo `"unavailable"`, gdy sprawdzenie zostało pominięte |
| `languagetool` | wersja oprogramowania LanguageTool z odpowiedzi, gdy jest obecna |
| `enhanced` | `True`, gdy używany jest ulepszony tekst, `False`, gdy ulepszanie się nie odbyło lub zostało odrzucone, `"unavailable"`, gdy wywołanie modelu się nie powiodło |
| `enhance_rejected` | kod odrzucenia z `enhance.rejection` |

Przebieg jest pomijany i zapisywany, gdy zgłoszony zostaje wyjątek z `SERVICE_ERRORS = (httpx.HTTPError, OSError, KeyError, ValueError)`, z tym że przy `require_compute` wyjątek `httpx.TransportError` jest zgłaszany ponownie. Pozostałe wyjątki propagują się dalej.

### Usuwanie śmieci (`garbage.py`)

| Nazwa | Wartość / zachowanie |
|---|---|
| `MIN_LETTERS` | `3` |
| `UNKNOWN_SHARE` | `0.5` |
| `ACRONYM_LETTERS` | `5` |
| `unknown(word, vignette_words) -> bool` | fałsz dla słów krótszych niż `MIN_LETTERS`, słów z winiety i słów pisanych wielkimi literami o długości najwyżej `ACRONYM_LETTERS` liter; w pozostałych przypadkach prawda, gdy `wordfreq.zipf_frequency(word, "en")` wynosi `0` |
| `is_garbage(sentence, vignette_words) -> bool` | liczy słowa o co najmniej `MIN_LETTERS` literach poza chipami; prawda, gdy udział nieznanych słów wynosi co najmniej `UNKNOWN_SHARE`; fałsz dla zdania bez takich słów |
| `drop_garbage(text, vignette_words) -> (text, dropped)` | dzieli każdy wiersz na fragmenty po `.`, `!` lub `?`, odrzuca fragmenty uznane za śmieci, zachowuje podziały wierszy, usuwa wiersze, które zostały puste |

### Gramatyka (`grammar.py`)

`check(text, protected) -> Checked` zwraca `Checked(text=text)` dla pustego tekstu. W przeciwnym razie wysyła żądanie do `{languagetool_url}/v2/check` z polami `language` i `data` (tekst z adnotacjami, w którym każdy chip `⟦hN⟧` jest znacznikiem odczytywanym jako `"…"`, stała `CHIP_READS_AS`) i stosuje odpowiedź LanguageTool za pomocą `apply`.

`apply(text, reply, protected) -> Checked` przechodzi po dopasowaniach od końca tekstu wstecz, stosuje pierwszą zamianę każdego pożądanego dopasowania i pomija dopasowania sięgające poza początek zastosowanej zamiany (`end > edge`) oraz dopasowania nakładające się na chip; dopasowanie, które jedynie sąsiaduje z chipem, jest zachowywane. Przesunięcia są przeliczane z jednostek UTF-16 na punkty kodowe.

| Nazwa | Wartość / zachowanie |
|---|---|
| `APPLIED_CATEGORIES` | `GRAMMAR`, `PUNCTUATION`, `CASING`, `CONFUSED_WORDS`, `COMPOUNDING`, `TYPOS` |
| `SPELLING_CATEGORY` | `TYPOS` |
| `SPELLING_GAP` | `1.4` (skala zipf) |
| `CLINICAL_TERMS` | `frozenset` słów klinicznych (na przykład `adhd`, `ritalin`, `dopamine`), których pisownia nie jest korygowana |
| `spelling_fix_wanted(word, replacement, protected) -> bool` | fałsz dla pustych słów, słów z `protected` lub `CLINICAL_TERMS`; prawda, gdy zapisane słowo ma częstość zipf 0 albo zamiennik jest o co najmniej `SPELLING_GAP` częstszy |
| `vocabulary(text) -> set[str]` | słowa tekstu zapisane małymi literami |
| `Checked` | dataclass: `text`, `edits`, `version`, `skipped` (identyfikatory reguł, które wystąpiły i nie zostały zastosowane) |

### Ulepszanie (`enhance.py`)

| Nazwa | Wartość / zachowanie |
|---|---|
| `PROMPT` | `Answer_enhance.v2` |
| `OPTIONS` | `temperature` 0.2, `num_ctx` 8192, `num_predict` 1200; wywołanie wysyła także `seed` 1 |
| `GROWTH`, `SLACK_WORDS` | `2.5`, `40` |
| `LEAK_WORDS` | `2` |
| `enhance(question, answer, quotes) -> (text or None, refusal or None)` | `(None, None)`, gdy `enhance_model` jest pusty lub odpowiedź jest pusta; w przeciwnym razie jedno wywołanie modelu i `rejection` na wyniku |
| `rejection(raw, answer, quotes) -> str or None` | zwraca pierwszy niespełniony kod z poniższej listy |
| `leaked(reply, answer, quotes) -> list[str]` | rdzenie z wyniku modelu, które występują w cytowanym fragmencie, a nie występują w odpowiedzi |
| `narrated(text) -> int` | liczba wzorców narracji w pierwszej osobie poza cudzysłowami |

Kody odrzucenia w kolejności sprawdzania:

| Kod | Warunek |
|---|---|
| `not_json` | wynik modelu nie jest obiektem JSON z tekstowym `answer` |
| `empty` | `answer` jest pusty |
| `chips` | chipy w wyniku różnią się od chipów w odpowiedzi (liczone z powtórzeniami) |
| `too_long` | wynik ma więcej niż `GROWTH` x liczba słów odpowiedzi + `SLACK_WORDS` |
| `leak` | co najmniej `LEAK_WORDS` przeciekających rdzeni |
| `voice` | `narrated(reply)` jest większe niż `narrated(answer)` |

Prompt otrzymuje pytanie i odpowiedź; cytowane fragmenty trafiają wyłącznie do sprawdzeń.

## Korekta: powiązania (`links.py`)

Wiersz to słownik `{text, targets, assigned_by}`. `targets` zawiera identyfikatory zaznaczeń (`h1`, `i1`) i `case`; jest pusty, dopóki wiersz nie jest powiązany.

| Funkcja | Zachowanie |
|---|---|
| `lines_of(text) -> list[str]` | niepuste wiersze po obcięciu białych znaków z brzegów |
| `link_lines(answers, highlights, vignette) -> dict[str, list[Line]]` | warstwy 1 i 2 przez `findings.link_text`; dopisuje niejawne zaznaczenia do `highlights` |
| `as_sentences(linked) -> list[dict]` | wiersze w postaci zdań z identyfikatorami `Q<n>.<index>` |
| `classify_rest(linked, highlights, vignette) -> dict` | warstwa 3: wywołuje `classifier.classify` dla wierszy bez celów, stosuje wynik, aktualizuje `linked` w miejscu; zwraca `{left, attempts}` |
| `relink(old, text, overrides, highlights, vignette) -> list[Line]` | dla każdego wiersza pierwsze z zastosowalnych: nadpisanie autora (`assigned_by` `expert`), powiązania starego wiersza o tym samym tekście, `findings.link_text`; nie wywołuje modelu |
| `unlinked(lines) -> list[int]` | pozycje (liczone od zera) wierszy bez celów |

## Korekta: serwis (`service.py`)

| Funkcja | Zachowanie | Błędy |
|---|---|---|
| `view(db, assignment, actor, review_round=None) -> ProofreadView` | runda `review_round` albo bieżąca runda przydziału | 404 `not_found` dla recenzenta lub brakującej rundy |
| `save(db, assignment, actor, body: ProofreadSave) -> ProofreadView` | blokuje otwartą rundę; sprawdza `body.version`; dla każdej podanej odpowiedzi sprawdza chipy (`check_chips`); ponownie wiąże wiersze odpowiedzi podlegających powiązaniu z nadpisaniami; przelicza flagi przez `findings.check`; zwiększa `version` | 403 `forbidden` dla osoby, która nie jest autorem; 409 `not_editable` poza stanem `PROOFREAD_CHECK`; 409 `proofread_conflict` (szczegóły `current_version`); 422 `question_not_answered`, `no_target`, `unknown_target` |
| `submit_for_review(db, assignment, actor, viewer)` | sprawdza przejście `SUBMIT_FOR_REVIEW`, następnie że żadna odpowiedź nie jest pusta i żaden wiersz podlegający powiązaniu nie jest niepowiązany; ustawia `submitted_at` i wykonuje przejście przydziału | 422 `empty_answer` (szczegóły `question_ids`), 422 `links_missing` (szczegóły `lines`) oraz błędy `check_transition` i sprawdzeń możliwości edycji (403 `forbidden`, 409 `not_editable`) |
| `open_next_round(db, assignment, feedback)` | dodaje rundę o numerze `assignment.review_round`, która kopiuje zaznaczenia, flagi, przebiegi, klasyfikator, prompt oraz tekst i wiersze każdej odpowiedzi z poprzedniej rundy; `feedback` jest zapisywany w rundzie | |
| `prepare(assignment_id) -> dict` | część zadania bez transakcji: uruchamia `proofread_answer` dla każdego pytania z odpowiedzią w kolejności pytań, wiąże odpowiedzi podlegające powiązaniu (`link_lines`, następnie `classify_rest`), oblicza flagi | |
| `record(db, assignment, prepared)` | usuwa rundę dla `assignment.review_round` i wstawia rundę oraz jej wiersze `AnswerRevision` z `final` równym `proposed` | |
| `get_round`, `revisions`, `answer_hash`, `highlight_views`, `line_views` | funkcje pomocnicze: odczyt rundy, odczyt jej odpowiedzi w kolejności pytań, hash tekstu wraz z celami powiązań, budowa modeli widoku | |

`prepare` zapisuje `classifier` i `prompt` w rundzie tylko wtedy, gdy `classify_rest` zgłosiło pozostałe wiersze (`info["left"]`). `passes` zawiera jeden wpis na pytanie (`passes` potoku) oraz wpis `links`.

`view` ustawia `editable` na prawdę, gdy aktor jest osobą przypisaną do przydziału, stan przydziału to `PROOFREAD_CHECK`, a `submitted_at` jest puste.

### Powierzchnia HTTP

Router przydziałów montuje je pod `/api/v1` (`backend/app/assignments/router.py`):

| Metoda i ścieżka | Funkcja serwisowa |
|---|---|
| `GET /assignments/{assignment_id}/proofread` (parametr zapytania `review_round`) | `view` |
| `PUT /assignments/{assignment_id}/proofread` (treść żądania `ProofreadSave`) | `save` |
| `POST /assignments/{assignment_id}/submit-for-review` | `submit_for_review` |

## Korekta: schematy (`schemas.py`)

| Model | Pola |
|---|---|
| `ProofreadSave` (`extra="forbid"`) | `version: int`, `answers: dict[QuestionId, AnswerText]`, `overrides: dict[QuestionId, dict[LineText, list[TargetId]]]` (domyślnie pusty) |
| `ProofreadView` | `review_round`, `version`, `editable`, `submitted_at`, `feedback`, `highlights`, `flags`, `passes`, `items` |
| `ProofreadItem` | `question_id`, `question`, `original`, `proposed`, `final`, `linked`, `lines`, `dropped` |
| `AnswerLine` | `text`, `targets`, `assigned_by` (`chip`, `quote`, `llm`, `expert` lub `None`) |
| `LinkedHighlight` | `id`, `chip` (`None` dla niejawnego zaznaczenia), `text`, `span`, `origin`, `direction` |
| `ProofreadFlag` | `kind`, `highlight`, `message` |
| `ProofreadFeedback` | `question_id`, `comment` |

`LineText` ma maksymalną długość 5000; `TargetId` pasuje do `^(h\d+|i\d+|case)$`. `linked` jest prawdą dla pytań, które akceptuje `findings.is_filed` (pytania otwarte z wyjątkiem Q4).

## Korekta: model danych (`models.py`)

| Model | Tabela | Kolumny |
|---|---|---|
| `ProofreadRound` | `proofread_rounds` | klucz główny (`assignment_id` z kluczem obcym i kaskadowym usuwaniem, `review_round`); `version` (domyślnie 1, zwiększany przy każdym zapisie), `highlights` JSONB, `flags` JSONB, `passes` JSONB, `classifier`, `prompt`, `feedback` JSONB (`[{question_id, comment}]`), `submitted_at`, `created_at`, `updated_at` |
| `AnswerRevision` | `answer_revisions` | klucz główny (`assignment_id`, `review_round`, `question_id`) ze złożonym kluczem obcym do `proofread_rounds` (kaskadowe usuwanie); `original`, `proposed`, `final`, `lines` JSONB, `dropped` JSONB |

## Źródła w kodzie

- `backend/app/indexing/__init__.py` - reeksporty i build_embedder
- `backend/app/indexing/config.py` - modele IndexingConfig i load_indexing_config
- `backend/app/embeddings.py` - zachowanie i wartości domyślne OllamaEmbedder
- `config/indexing.yaml` - skonfigurowane wartości
- `scripts/corpus/index_chunks.py:84,193` - czytelnik text_field
- `packages/expert-knowledge-core/src/expert_knowledge_core/bm25.py:21-26` - pola i wartości domyślne Bm25Config
- `backend/app/knowledge/embedding.py` - miejsce odczytu pliku konfiguracji
- `backend/app/proofread/pipeline.py` - proofread_answer, passes, reguły pomijania
- `backend/app/proofread/garbage.py` - usuwanie śmieci
- `backend/app/proofread/grammar.py` - klient LanguageTool i reguły poprawek
- `backend/app/proofread/enhance.py` - ulepszanie i kody odrzucenia
- `backend/app/proofread/links.py` - wiązanie wierszy
- `backend/app/proofread/service.py` - view, save, submit, rundy, połówki zadania
- `backend/app/proofread/schemas.py` - modele widoku i zapisu
- `backend/app/proofread/models.py` - ProofreadRound, AnswerRevision
- `backend/app/assignments/router.py:112-138` - endpointy korekty
- `backend/app/settings.py` - pola ustawień i wartości domyślne
- `backend/app/main.py:19` - prefiks API
- `.env.example` - nazwy zmiennych środowiskowych pisane wielkimi literami
