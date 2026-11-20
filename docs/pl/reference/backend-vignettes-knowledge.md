---
title: Backend winiet i wiedzy
diataxis: reference
---

# Moduły backendu `app.vignettes` i `app.knowledge`

Język: **Polski** · [English](../../reference/backend-vignettes-knowledge.md)

`app.vignettes` zawiera teksty winiet pisane przez administratorów, ich wersje i stały zestaw pytań oraz obsługuje endpointy administratora pod `/api/v1/vignettes` i `/api/v1/vignette-versions`. `app.knowledge` dzieli zatwierdzone odpowiedzi na jednostki wiedzy, tworzy ich embeddingi, zapisuje je w schemacie `chips` i obsługuje endpointy administratora pod `/api/v1/knowledge-units`. Oba routery są zamontowane w `backend/app/main.py` pod prefiksem `/api/v1`; każdy poniższy endpoint wymaga użytkownika-administratora (`AdminUser`).

Powiązane strony: [przydziały i zadania](backend-assignments-jobs.md), [recenzje](backend-reviews.md), [indeksowanie i korekta](backend-indexing-proofread.md), [wspólne pakiety](packages.md), [wyszukiwanie i indeksowanie](../explanation/retrieval-and-indexing.md), [architektura](../explanation/architecture.md).

Treści błędów używają poniższych kodów. Błędy `invalid(...)` zwracają HTTP 422, `not_found` zwraca 404, a `DomainError` bez jawnego statusu zwraca 409 (`backend/app/core/errors.py`).

## Winiety: endpointy HTTP

| Metoda i ścieżka | Body / query | Wynik | Błędy |
|---|---|---|---|
| `GET /vignettes/questions` | brak | lista `QuestionTemplate` (`id`, `kind`, `text`) dla Q1-Q6; Q4 zachowuje placeholder `{whatif}` | brak poza uwierzytelnieniem |
| `GET /vignettes` | brak | lista `VignetteAdminView` uporządkowana według `code`; każdy element zawiera wszystkie swoje wersje uporządkowane według numeru wersji | brak poza uwierzytelnieniem |
| `POST /vignettes` (201) | `VignetteCreate` | `VignetteAdminView` z winietą i wersją 1 jako szkicem; akcja audytu `vignette_created` | 409 `vignette_code_taken`; 422 kody reguł treści |
| `POST /vignettes/{vignette_id}/versions` (201) | `VersionContent` | `VersionAdminView` z kolejnym numerem wersji, wybieranym pod blokadą wiersza winiety; akcja audytu `version_created` | 404 `not_found`; 422 kody reguł treści |
| `PATCH /vignette-versions/{version_id}` | `VersionUpdate` | `VersionAdminView`; aktualizacja jest scalana z zapisaną treścią i walidowana ponownie | 409 `version_not_draft`; 422 `validation_error` (details `fields`); 422 kody reguł treści |
| `POST /vignette-versions/{version_id}/publish` | brak | `VersionAdminView` ze statusem `published` i `published_at`; akcja audytu `version_published` | 409 `version_not_draft`; 422 `word_count_out_of_range`, `summary_missing`, `construct_word_in_text` |
| `POST /vignette-versions/{version_id}/retire` | brak | `VersionAdminView` ze statusem `retired`; akcja audytu `version_retired`; wstrzymuje nowe przydziały, a już utworzone przydziały działają na tej wersji | 409 `version_not_published` |

`publish`, `retire` i `PATCH` blokują wiersz wersji, zanim odczytają jej status.

## Winiety: reguły walidacji

### Reguły treści (`validate_content`)

`validate_content(content: VersionContent) -> None` działa przy tworzeniu, dodawaniu wersji i aktualizacji, w podanej kolejności. Każda porażka to 422 ze stałym kodem.

| Kod | Warunek |
|---|---|
| `q4_without_whatif` | `q4_whatif` jest pusty lub składa się z białych znaków |
| `control_with_cues` | `design.is_control` ma wartość true, a `design.planted_cues` nie jest pusta |
| `track_without_target` | `design.track` to `text_analysis`, a `design.knowledge_target` jest pusty |
| `variant_b_without_change` | `variant.arm` to `B`, a `variant.change` jest pusty |
| `span_not_in_text` | `planted_cues[].quote` lub `confounders[].quote` nie jest podciągiem `text` (details: `quote`) |

### Reguły publikacji (`publish_version`)

| Kod | Warunek |
|---|---|
| `word_count_out_of_range` | `len(text.split())` jest poza zakresem `MIN_WORDS, MAX_WORDS = 120, 250` (details: `words`) |
| `summary_missing` | `patient_summary` jest puste lub składa się z białych znaków |
| `construct_word_in_text` | `check_construct_words` znajduje termin konstruktu w `text`, `q4_whatif` lub `patient_summary`, sprawdzanych w tej kolejności (details: `field`, `term`) |

Terminy konstruktu to wzorzec niewrażliwy na wielkość liter: `adhd`, `attention deficit` (spacja lub myślnik), `methylphenidate`, `ritalin`, `concerta`, `medikinet`, `adderall`, `vyvanse`, `elvanse`, `lisdexamfetamine`, `dexamfetamine`, `atomoxetine`, `strattera`, `guanfacine`, `intuniv` (`_CONSTRUCT_TERMS`), a także słowo pisane wielkimi literami `ADD` (`_ADD_UPPERCASE`; czasownik pisany małymi literami przechodzi). Kontrola działa wyłącznie przy publikacji; szkic może zawierać te słowa.

### Ograniczenia schematów (`vignettes/schemas.py`)

| Model | Pole | Ograniczenie |
|---|---|---|
| `VignetteCreate` | `code` | wzorzec `^V\d{3,}$`, maksymalna długość 32 |
| `VersionContent` | `text` | długość od 1 do 20000 |
| | `framing` | `forum_post`, `personal_journal` lub `email` (`Framing`); wymagane |
| | `q4_whatif` | opcjonalne, maksymalna długość 1000 |
| | `patient_summary` | domyślnie `""`, maksymalna długość 600 |
| | `variant`, `design` | `VariantInfo` opcjonalne; `VignetteDesign` wymagane |
| `VersionUpdate` | wszystkie pola | opcjonalne; te same limity co w `VersionContent`; `design` i `variant` zastępują zapisaną wartość w całości |
| `PlantedCue` | `quote`, `trait`, `strength` | `quote` minimalna długość 1; `strength` to `weak`, `moderate` lub `strong` |
| `Confounder` | `quote`, `alternative_explanation` | `quote` minimalna długość 1 |
| `VariantInfo` | `pair_id`, `arm`, `change` | `arm` to `A` lub `B`; `change` opcjonalne |
| `VignetteDesign` | `purpose` `""`, `notes` `""`, `planted_cues` `[]`, `confounders` `[]`, `is_control` `False`, `track` `general`, `knowledge_target` `None`, `origin` `hand_written`, `population` `adult`, `source_ref` `None` | `track` to `general` lub `text_analysis`; `origin` to `llm`, `real_text` lub `hand_written` |

`VersionContent`, `VignetteCreate`, `VersionUpdate`, `PlantedCue`, `Confounder`, `VariantInfo` i `VignetteDesign` odrzucają nieznane klucze (`extra="forbid"`), więc klient nie może wysłać `question_ids`. `VersionAdminView` dodaje `id`, `vignette_id`, `version`, `status`, `content_hash`, `question_ids`, `created_at`, `published_at` oraz wyliczane `word_count`. `VignetteAdminView` zawiera `id`, `code`, `created_at` i `versions`.

## Winiety: model danych

| Model | Tabela | Kolumny |
|---|---|---|
| `Vignette` | `vignettes` | `id` UUID, `code` String(32) unikalny, `created_by` (FK `app.users.id`), `created_at` |
| `VignetteVersion` | `vignette_versions` | `id`, `vignette_id` (FK, z indeksem), `version`, `status`, `text`, `content_hash` String(64), `framing` String(32), `question_ids` ARRAY(String(8)), `q4_whatif`, `patient_summary` (domyślnie `""`), `variant` JSONB, `design` JSONB, `created_at`, `published_at`; unikalny (`vignette_id`, `version`) |

Wartości `VersionStatus`: `draft` (domyślna), `published`, `retired`. `question_ids` jest zawsze listą `Q1`..`Q6` (`QUESTION_IDS`). `content_hash` to `content_hash(text)` z `app.core.security`.

## Winiety: pytania (`questions.py`)

`QuestionId` to `Q1`..`Q6`; `QuestionKind` to `open`, `shift` lub `rating_1_5`. `Question` to zamrożona dataclass z polami `id`, `kind`, `text`, `min_words`. Komentarze w pliku stwierdzają, że `min_words` jest używane wyłącznie przez `scripts/elicitation`; API go nie wysyła ani nie wymusza.

| Id | Rodzaj | `min_words` | Początek tekstu |
|---|---|---|---|
| Q1 | `open` | 15 | "Which fragments of the text matter for your reading of ADHD-related traits…" |
| Q2 | `open` | 10 | "Which of those fragments could equally reflect something else…" |
| Q3 | `open` | 10 | "What is missing from this text…" |
| Q4 | `shift` | 5 | "Given your hypothesis about this person so far: how would it change if {whatif}?" | <!-- lint-ignore -->
| Q5 | `open` | 10 | "What would a less experienced clinician likely over- or under-interpret…" |
| Q6 | `rating_1_5` | brak | "Overall, how strongly does this text show ADHD-related traits?…" |

Pozostałe nazwy w pliku:

| Nazwa | Wartość / sygnatura | Znaczenie |
|---|---|---|
| `QUESTIONS` | `dict[str, Question]` z kluczem będącym identyfikatorem | zestaw pytań |
| `GATE` | `("Q1", "Q2", "Q3")` | Q4-Q6 są pokazywane, gdy każde zadane pytanie bramki ma niepustą odpowiedź; odpowiedzi bramki są wtedy blokowane (komentarz w pliku) |
| `HYPOTHESIS_MIN_WORDS` | `3` | tylko skrypty (komentarz w pliku) |
| `Q4_HYPOTHESIS`, `SHIFT_LEAD`, `Q4_TOWARD`, `Q4_WHY` | "Your working hypothesis, in one sentence", "With this, my hypothesis…", "Towards…", "Why?" | sformułowania kroków Q4 |
| `SHIFT_LABELS` | `-2` "is strongly reinforced", `-1` "is somewhat reinforced", `0` "is unchanged", `1` "partly changes", `2` "changes completely" | etykiety skali przesunięcia |
| `TOWARD_LABELS` | `more_adhd` "more ADHD-like", `less_adhd` "less ADHD-like", `other` "another explanation" | etykiety kierunku |
| `Q4_WORDING` | słownik z `hypothesis`, `shift_lead`, `shift_labels` (klucze tekstowe), `toward`, `toward_labels`, `why` | sformułowania wysyłane do frontendu |
| `render_question(question, q4_whatif) -> str` | | zwraca tekst; dla Q4 wstawia za `{whatif}` what-if pozbawione końcowych `?` i `.`; zgłasza `ValueError`, gdy Q4 nie ma what-if |
| `describe_shift(shift, toward=None, other=None) -> str` | | jednowierszowy opis odpowiedzi Q4, na przykład "+1 partly changes, towards less ADHD-like" |

## Winiety: funkcje serwisowe i importu

| Funkcja | Zachowanie |
|---|---|
| `opening_words(text, count=40) -> str` | pierwsze `count` słów, z końcowym "…", gdy tekst jest dłuższy |
| `create_vignette(db, code, content, admin)` | waliduje, wstawia winietę (zduplikowany kod zgłasza `vignette_code_taken`), wstawia wersję 1 |
| `add_version(db, vignette_id, content, admin)` | blokuje wiersz winiety, wstawia wersję `max(version) + 1` |
| `update_version(db, version_id, changes)` | tylko szkic; scala `changes.model_dump(exclude_unset=True)` z zapisanymi polami; jawny `null` w polu wymaganym daje `validation_error` |
| `publish_version(db, version_id, admin)`, `retire_version(db, version_id, admin)` | przejścia statusu opisane powyżej |
| `version_and_code(db, version_id) -> (VignetteVersion, str)` | wersja i kod jej winiety |
| `list_vignettes(db)` | wszystkie winiety ze wszystkimi wersjami |
| `read_whatifs(path) -> dict[str, str]` | czyta obiekt JSON odwzorowujący kod na tekst what-if; zgłasza 422 `whatifs_unreadable` dla nieczytelnego pliku, niepoprawnego JSON-a lub innego kształtu |
| `plan_import(directory, whatifs) -> dict[str, VersionContent]` | czyta każdy `V*.json` z `directory` w kolejności posortowanej; w każdym pliku pole `id` jest kodem, klucze `text`, `framing`, `variant`, `design` są zachowywane, a `q4_whatif` pochodzi z `whatifs`; uruchamia `validate_content`; zgłasza jeden 422 `import_refused` wymieniający każdy problem albo `no_vignette_files`, gdy folder ich nie ma; what-if bez pasującego pliku jest również wymieniany jako problem; plik, którego kod nie ma niepustego what-if, jest wymieniany z komunikatem "no what-if for this vignette." |
| `async import_vignettes(db, directory, whatifs, admin) -> ImportResult(created, skipped)` | najpierw wywołuje `plan_import`, więc nic nie jest zapisywane, gdy którykolwiek plik jest niepoprawny; tworzy szkic (wersja 1) dla każdego nowego kodu i pomija kody, które istnieją |

Polecenie CLI `python -m app.cli import-vignettes --dir DIR --whatifs FILE --admin-email EMAIL` wywołuje import (`backend/app/cli.py`).

## Wiedza: endpointy HTTP

| Metoda i ścieżka | Parametry | Wynik | Błędy |
|---|---|---|---|
| `GET /knowledge-units` | query `status` (`UnitStatus`), `limit` 1-500 (domyślnie 100), `offset` >= 0 (domyślnie 0) | lista `KnowledgeUnitListItem`, od najnowszych (`created_at` malejąco, potem `ordinal`, `id`) | brak poza uwierzytelnieniem |
| `POST /knowledge-units/search` | body `KnowledgeSearchRequest` | `KnowledgeSearchResponse` (`hits`) | 503 `embedding_unavailable` |
| `GET /knowledge-units/index` | brak | `IndexStatus`; `up_to_date`, gdy nie istnieje zadanie refit albo ostatnie jest zakończone, w przeciwnym razie wartość statusu ostatniego zadania refit i jego `last_error` | brak poza uwierzytelnieniem |
| `POST /knowledge-units/index/refit` (202) | brak | `IndexStatus` ze stanem `queued`; kolejkuje zadanie refit, chyba że jedno już czeka w kolejce | brak poza uwierzytelnieniem |
| `DELETE /knowledge-units/{unit_id}` (204) | brak | usuwa jedną jednostkę | 404 `not_found`, gdy jednostki brak lub nie ma statusu `ingested` |
| `DELETE /knowledge-units/by-expert/{expert_id}` | brak | `UnitsRemoved` (`removed`); usuwa każdą jednostkę `ingested` z przydziałów eksperta; gdy usunęła jakąkolwiek, zapisuje w audycie `knowledge_withdrawn` dla użytkownika z liczbą `units` | 404 `not_found`, gdy brak użytkownika |

`KnowledgeSearchRequest`: `query` (długość 1-4000), `mode` (`question` domyślnie albo `patient_text`), `k` (1-20, domyślnie 8). `KnowledgeHit`: `rank`, `score`, `similarity`, `matched_sentence`, `unit`. `score` to wynik fuzji mechanizmów wyszukiwania i porządkuje trafienia; `similarity` to podobieństwo kosinusowe między embeddingiem zapytania a zapisanym i ma wartość `None`, gdy nie można go obliczyć.

## Wiedza: model danych

| Model | Tabela | Kolumny |
|---|---|---|
| `KnowledgeUnit` | `knowledge_units` | `id`, `assignment_id` (FK), `submission_id` (FK), `ordinal`, `review_round` (domyślnie 1), `text`, `content_hash` String(64), `kind` (`fragment` lub `case`), `highlight_id` (`h1`, `i1`; `None` dla jednostki case), `direction` (`toward`, `away`, `neutral`, `unclear`), `patient_words`, `sentence_ids` ARRAY, `context` ARRAY (wyróżnienia cytowane razem), `embed_text` (I1), `embed_text_combined` (I3), `status` (z indeksem, domyślnie `pending`), `created_at`; unikalny (`assignment_id`, `review_round`, `ordinal`) |
| `AnswerFindings` | `answer_findings` | `assignment_id` (PK, FK, kaskadowe usuwanie), `record` JSONB, `version` (domyślnie 1), `check_outcome` (`completed` lub `skipped`), `classifier`, `prompt`, `findings_version`, `created_at`, `updated_at` |

Wartości `UnitStatus`: `pending`, `approved`, `rejected`, `ingested`, `superseded`, `removed`. Jednostka superseded została wycięta w rundzie recenzji poprzedzającej bieżącą. Jednostka removed została wyjęta z bazy wiedzy po ingeście.

`KnowledgeUnitListItem` zawiera powyższe kolumny jednostki oraz `vignette_code`, `vignette_version`, `expert_id`, `expert_pseudonym`, `sentences` (`UnitSentence`: `id`, `question_id`, `assigned_by`), `context` (`CitedTogether`: `id`, `text`), `framing`, `classifier`, `prompt`, `findings_version`. `unit_items` buduje go, łącząc przydział, wersję, winietę i eksperta oraz odczytując `record` ustaleń przydziału; identyfikator zdania nieobecny w rekordzie jest pomijany. `IndexStatus.state` to `up_to_date`, `queued`, `running` lub `failed`.

## Wiedza: funkcje

### Spostrzeżenia (`findings.py`, bez modeli)

| Funkcja | Zachowanie |
|---|---|
| `is_filed(question_id) -> bool` | prawda dla pytań otwartych z wyjątkiem Q4 |
| `response_from_submission(payload, vignette_code, vignette_version) -> Response` | zachowuje odpowiedzi na pytania klasyfikowane, wyróżnienia, ocenę i `insufficient_information` |
| `match_in_text(piece, text) -> (start, end, ratio) or None` | wymaga co najmniej `MIN_QUOTE_WORDS = 2` słów; najpierw dokładne dopasowanie bez rozróżniania wielkości liter, potem najlepsze okno słów ze współczynnikiem difflib co najmniej `QUOTE_RATIO = 0.6` |
| `expert_highlights(highlights) -> list[dict]` | rekordy wyróżnień z id `h<chip>` i origin `expert` |
| `link_text(text, highlights, vignette) -> (targets, assigned_by)` | chipy w zdaniu dają `chip`; w przeciwnym razie cytowane fragmenty, które nakładają się na wyróżnienie (co najmniej połowa krótszego zakresu) lub pasują do winiety, dają `quote`, z dopisaniem niejawnego wyróżnienia `i<n>`, gdy żadne się nie nakłada; w pozostałych przypadkach `([], None)` |
| `unresolved(sentences) -> list[str]` | identyfikatory zdań bez celów |
| `apply_classification(sentences, labels) -> list[str]` | stosuje etykiety klasyfikatora; `prev` kopiuje cele poprzedniego zdania w tej samej odpowiedzi; brakująca lub niepoprawna etykieta staje się `case`; zwraca identyfikatory zastępcze; ustawia `assigned_by` na `llm` |
| `check(highlights, sentences) -> list[dict]` | flagi rodzaju `coverage` (wyróżnienie eksperta bez zdania) i `direction` (wzorce regex `LOWERING` i `RAISING` zestawione z zaznaczonym kierunkiem); niczego nie zmienia |
| `build_units(rec) -> list[dict]` | jedna jednostka fragment na każde wyróżnienie będące celem co najmniej jednego zdania, plus jednostka `case`, gdy co najmniej jedno zdanie ma cel `case`; ustawia `body`, `i1` (nagłówek i zdania) oraz `i3` (nagłówek, wiersz `Patient: "<highlight text>"`, zdania; równe `i1` dla jednostki case) |
| `record_from_lines(resp, lines, highlights, session_id, expert_id, role, framing, population) -> dict` | buduje zdania z już powiązanych wierszy, następnie `flags` i `units`; niczego nie wiąże ponownie |

`Highlight` (`chip`, `text`, `span`, `direction`) i `Response` (`vignette_id`, `vignette_version`, `answers`, `highlights`, `rating`, `insufficient_information`) to zamrożone dataclassy. Moduł reeksportuje funkcje pomocnicze z `expert_knowledge_core.notes` oraz `CASE`, `FINDINGS_VERSION` z `expert_knowledge_core.records` (zob. [pakiety](packages.md)).

### Klasyfikator (`classifier.py`)

| Nazwa | Wartość / zachowanie |
|---|---|
| `PROMPT` | `Expert_sentence_targets.v1` |
| `OPTIONS` | `temperature` 0.2, `num_predict` 600, `num_ctx` 8192 |
| `RETRIES` | 3 |
| `classify(vignette, highlights, sentences, left, *, retries=RETRIES, seed=1) -> (labels, info)` | jedno wywołanie Ollamy w trybie JSON na próbę, do `retries + 1` prób z ziarnem `seed + attempt * 7919`; zachowuje odpowiedź z największą liczbą poprawnych etykiet; kończy na pierwszej odpowiedzi bez błędów; zwraca `({}, info)` bez wywołania, gdy `left` jest puste; `info` to `{attempts, errors}`; model, z którym nie można się połączyć, powoduje wyjątek |
| `check_labels(raw, sentences, left, allowed) -> (good, errors)` | akceptuje niepustą listę łańcuchów na identyfikator zdania; odrzuca nieznane identyfikatory, `prev` połączone z innymi identyfikatorami oraz `prev` przy pierwszym zdaniu odpowiedzi; odpowiedź niebędąca obiektem JSON to jeden błąd |
| `ask(system, user, seed)` | wywołuje `chat_json` z `settings.classifier_model` |

### Embedding (`embedding.py`)

`embed_texts(texts: list[str]) -> list[list[float]]` zwraca `[]` dla braku tekstów. W przeciwnym razie tworzy embeddingi w wątku za pomocą embeddera zbudowanego z `config/indexing.yaml` (buforowanego przez `lru_cache`) i zgłasza `RuntimeError`, gdy kształt wyniku różni się od (liczba tekstów, `embeddings.dimensions`). Konfigurację opisuje [indeksowanie i korekta](backend-indexing-proofread.md#konfiguracja-indeksowania).

### Ingest (`ingest.py`)

| Nazwa | Zachowanie |
|---|---|
| `TIER` | `"app"`, wartość `tier` zapisywana w `chips.vignettes` |
| `BM25_LOCK` | `4_715_331_001`, klucz blokady advisory współdzielony przez `write`, `remove_units` i zadanie refit |
| `load(db, assignment_id) -> Ingestion` | czyta jednostki przydziału o statusie `approved` lub `ingested`; zgłasza `NoUnits`, gdy ich brak, `UnitsNotEmbeddable`, gdy jednostce brakuje `embed_text` lub `embed_text_combined`, oraz `NoFindings`, gdy brak wiersza `answer_findings`; przycina zapisany rekord do wyróżnień i zdań jednostek |
| `embed(data) -> Ingestion` | tworzy embeddingi tekstów I1 jednostek, tekstów wyróżnień (I2) i tekstów I3 w jednym wywołaniu; zgłasza `RuntimeError`, jeśli liczba wektorów różni się od 2 x jednostki + wyróżnienia |
| `write(db, data)` | bierze blokadę advisory, usuwa wiersz `chips.elicitation_sessions` przydziału, następnie wstawia do `chips.experts`, `chips.vignettes`, `chips.elicitation_sessions`, `chips.cue_keys`, `chips.highlights`, `chips.answer_sentences`, `chips.finding_units`, `chips.finding_unit_sentences`, `chips.unit_cues` i `chips.review_events`, po czym wywołuje `refresh_sparse`; działa w transakcji wywołującego |
| `refresh_sparse(db)` | dopasowuje BM25 ponownie do tekstów jednostek I1 i I3 oraz tekstów kluczy cue, każdy zbiór z własnymi statystykami, używając sekcji `sparse` z `config/indexing.yaml`; zapisuje `sparse`, `sparse_combined` i `chips.cue_keys.sparse` |
| `Ingestion` | dataclass: `session_id`, `expert_id`, `created_at`, `vignette`, `document`, `events`, `segmenter`, `meta`, `track`, `vectors` |

`load` buduje zdarzenia recenzji z `record` spostrzeżeń: wpisy `record["flags_shown"]` stają się zdarzeniami `flag_shown`, a wpisy `record["corrections"]` rodzaju `sentence_moved` lub `toggle_changed` stają się zdarzeniami o tej samej nazwie; `check_outcome` równe `skipped` dodaje zdarzenie `skipped`. Zadanie korekty zapisuje `flags_shown` i pustą listę `corrections`, gdy rejestruje ustalenia (`backend/app/jobs/handlers.py:79-88`); żaden kod w `backend/app` nie wypełnia `corrections` wpisami.

### Usuwanie i wyszukiwanie

| Funkcja | Zachowanie |
|---|---|
| `removal.enqueue_refit(db)` | dodaje zadanie `REFIT`, chyba że istnieje zadanie w kolejce; zadanie w toku się nie liczy |
| `removal.remove_units(db, units, actor_id) -> int` | pomija jednostki, które nie są `ingested`; bierze blokadę advisory `BM25_LOCK`; usuwa wiersze `chips.finding_units` tych jednostek; usuwa wiersz sesji, gdy nie zostały w niej żadne jednostki, w przeciwnym razie usuwa jednostki z `document` sesji; usuwa `chips.cue_keys`, na które nie wskazuje żadne wyróżnienie ani cue jednostki, oraz `chips.experts` bez sesji; ustawia status `removed`; zapisuje w audycie `unit_removed` dla każdej jednostki; kolejkuje refit; zwraca liczbę |
| `search.search(db, request) -> KnowledgeSearchResponse` | uruchamia `PatientTextRetriever` (tryb `patient_text`) lub `ExpertQuestionRetriever` (tryb `question`) z `merge_shared=False` na `ExpertKnowledgeStore`; odwzorowuje każdą notatkę na jednostkę `ingested` i pomija notatki, których jednostka zmieniła się w międzyczasie; tryb question liczy podobieństwo kosinusowe względem zapisanego wektora I1 (`chips.finding_units.embedding`), tryb patient bierze najlepsze podobieństwo kosinusowe między wpisanym zdaniem a embeddingiem cue jednostki i zwraca to zdanie jako `matched_sentence`; błąd embeddingu (`httpx.HTTPError`, `OSError`, `RuntimeError`) staje się 503 `embedding_unavailable` |

Rodzaje zadań w tle, które używają tych modułów, są zarejestrowane w `backend/app/jobs/handlers.py`: `PROOFREAD`, `INGEST` (`prepare_ingest`, potem `ingest`, który oznacza jednostki `approved` jako `ingested`) i `REFIT` (bierze `BM25_LOCK`, uruchamia `refresh_sparse`).

## Konfiguracja

| Ustawienie (nazwa env) | Typ | Wartość domyślna | Używane przez |
|---|---|---|---|
| `classifier_model` (`CLASSIFIER_MODEL`) | `str` | `qwen3.5:9b` | `classifier.ask` |
| `project_root` | `Path` | katalog nadrzędny `backend/` | lokalizacja `config/indexing.yaml` dla `embedding` i `refresh_sparse` |
| `ollama_base_url` (`OLLAMA_BASE_URL`) | `str` | `http://localhost:11434` | embedder i `chat_json` |
| `ollama_request_timeout` | `float` | `600` | wywołania czatu Ollamy (komentarz w ustawieniach: jedna odpowiedź może obejmować załadowanie modelu) |

`Settings` nie ustawia prefiksu zmiennych środowiskowych, a `.env.example` wymienia nazwy pisane wielkimi literami. Model embeddingów, rozmiar batcha, wymiary i parametry BM25 pochodzą z `config/indexing.yaml` i są wymienione na [stronie o indeksowaniu](backend-indexing-proofread.md#konfiguracja-indeksowania).

## Źródła w kodzie

- `backend/app/vignettes/router.py` - endpointy winiet
- `backend/app/vignettes/service.py` - reguły treści, reguły publikacji, cykl życia wersji, listowanie
- `backend/app/vignettes/schemas.py` - modele żądań i widoków oraz ich ograniczenia
- `backend/app/vignettes/models.py` - Vignette, VignetteVersion, VersionStatus
- `backend/app/vignettes/questions.py` - zestaw pytań, sformułowania Q4, render_question, describe_shift
- `backend/app/vignettes/importing.py` - read_whatifs, plan_import, import_vignettes
- `backend/app/knowledge/router.py` - endpointy wiedzy
- `backend/app/knowledge/schemas.py` - modele żądań i odpowiedzi
- `backend/app/knowledge/models.py` - KnowledgeUnit, AnswerFindings, UnitStatus
- `backend/app/knowledge/service.py` - unit_items
- `backend/app/knowledge/findings.py` - wiązanie, kontrole, budowanie jednostek
- `backend/app/knowledge/classifier.py` - klasyfikator zdań
- `backend/app/knowledge/embedding.py` - embed_texts
- `backend/app/knowledge/ingest.py` - load, embed, write, refresh_sparse
- `backend/app/knowledge/removal.py` - remove_units, enqueue_refit
- `backend/app/knowledge/search.py` - testowe wyszukiwanie administratora
- `backend/app/jobs/handlers.py:79-168` - rekord ustaleń, jednostki, handlery zadań
- `backend/app/main.py:19,53-62` - prefiks API i montowanie routerów
- `backend/app/core/errors.py:23-49` - kody statusu funkcji pomocniczych błędów
- `backend/app/settings.py` - pola ustawień i wartości domyślne
- `backend/app/cli.py` - polecenie import-vignettes
- `.env.example` - nazwy zmiennych środowiskowych pisane wielkimi literami
