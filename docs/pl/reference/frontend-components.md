---
title: Komponenty frontendu i pomocniki odpowiadania
diataxis: reference
---

# Komponenty frontendu i pomocniki odpowiadania

Język: **Polski** · [English](../../reference/frontend-components.md)

`frontend/src/components` zawiera jednoplikowe komponenty Vue, które montują widoki: wspólne widgety na najwyższym poziomie oraz foldery `answering/`, `knowledge/` i `admin/`. `frontend/src/answering` zawiera moduły TypeScript stojące za ekranami odpowiadania i recenzji: model cytatów, reguły kroków, zapis szkicu, różnicę słów i fokus cytatu. Żaden z folderów nie ma własnego punktu wejścia; komponenty są importowane przez widoki z `frontend/src/views` oraz `frontend/src/layouts/AppLayout.vue`. Powłokę aplikacji opisuje [frontend-app.md](frontend-app.md); miejsce frontendu w systemie opisuje [architecture.md](../explanation/architecture.md). Indeks dokumentacji to [index.md](../index.md).

Propsy są deklarowane przez `defineProps`, zdarzenia przez `defineEmits`, a `defineExpose` oznacza metody, które komponent nadrzędny wywołuje przez referencję szablonu. Etykiety tekstowe, których komponenty nie podają wprost, pochodzą z `frontend/src/copy.ts`.

## Komponenty w `components/`

| Komponent | Propsy | Zdarzenia / sloty | Przeznaczenie |
|---|---|---|---|
| `SectionCard` | `title`, `text`, `to`, `action`, `testid?` | slot domyślny | Karta strony głównej: nagłówek, tekst, opcjonalna zawartość slotu i przycisk-link routera z etykietą `action`. |
| `LoadingSpinner` | `size?` (20), `label?` | brak | Obracający się SVG. Z `label` ma rolę `img` i `aria-label`, bez niego SVG jest ukryty przed technologiami asystującymi. |
| `InfoPopover` | `mode`: `'hover'` lub `'click'` | zdarzenie `open`; slot `trigger` (otrzymuje `open`, `toggle`, `panelId`); slot domyślny to panel | Baza popovera. Tryb hover otwiera się po najechaniu myszą i po fokusie. Panel zamyka się po naciśnięciu myszy poza nim i po Escape. |
| `CaseCard` | `code`, `version?`, `patientSummary`, `framing`, `wordCount`, `opening` | slot domyślny zastępuje tekst wyzwalacza | Przycisk, który otwiera popover po kliknięciu z etykietą ujęcia, liczbą słów, streszczeniem pacjenta (gdy niepuste) i początkowymi słowami. Domyślny tekst wyzwalacza to `Case {code} v{version}`. |
| `TermGrid` | `items`: `readonly { term: string; text: string }[]` | brak | Lista definicji, dwie kolumny od punktu przełamania `sm`. |
| `SegmentedToggle` | `options`: `readonly { value: T; label: string }[]`, `label`, `disabled?`; `v-model` | brak | Generyczna (`T extends string`) grupa przycisków, w której jedna opcja jest wciśnięta. |
| `StepFlow` | `steps: readonly string[]`, `current?: string`, `testid?: string` | brak | Uporządkowana lista etykiet kroków ze strzałkami; etykieta `current` jest obrysowana. |
| `PseudonymChip` | `pseudonym` | brak | Przycisk, który otwiera popover po kliknięciu z osobą stojącą za pseudonimem. Wyszukuje osobę przy pierwszym otwarciu i trzyma wynik w `Map` na poziomie modułu, więc pseudonim jest pobierany raz na załadowanie strony. Administrator widzi imię i nazwisko, e-mail, rolę, dezaktywację i liczby przypadków (otwarte, w recenzji, zakończone, zatrzymane); pozostali użytkownicy widzą pseudonim i notatkę o prywatności. Nieudane wyszukanie pokazuje „Could not load this expert." |
| `HeroBanner` | `title`, `tagline` | brak | Przyklejony nagłówek strony głównej, który zwija się do wąskiego paska podczas przewijania. Ustawia `scroll-padding-top` na elemencie głównym dokumentu, dopóki jest zamontowany, i czyści je przy odmontowaniu. |
| `SignInAgainDialog` | brak | brak | Modalny `<dialog>` otwierany przez `showModal()`; `@cancel.prevent` utrzymuje go otwartego. Prosi o hasło zalogowanego konta i wywołuje `auth.login(auth.user.email, password)`. Przy niepowodzeniu pokazuje komunikat `ApiError`. |
| `PageIntro` | `lead: string | readonly string[]`, `moreTo?`, `testid?`, `center?` | brak | Akapity wstępne. Z `moreTo` dodaje link routera z etykietą `HOME.learnMore`. |
| `AboutSection` | `id`, `heading`, `accent?`, `testid?` | slot domyślny | Karta sekcji z kotwicą `id` i nagłówkiem `h2`. |

## Komponenty w `components/answering/`

| Komponent | Propsy | Zdarzenia / sloty / udostępniane | Przeznaczenie |
|---|---|---|---|
| `AnswerThread` | `assignmentId`, `questionId`, `questionName`, `comments`, `highlights`, `canComment`, `canStance`, `startOpen?` | zdarzenie `posted`; udostępnia `addQuote(target)` | Zwijana dyskusja pod jedną odpowiedzią: komentarze z odpowiedziami na jeden poziom w głąb, opcjonalne stanowisko (wysyłane tylko przy `canStance`) i pole komentarza. Gdy jest otwarta i `canComment`, rejestruje swoje pole jako ujście komentarzy strony. `addQuote` otwiera wątek i wstawia chip albo cytowany fragment dla zaznaczenia bez chipa. Wysyła komentarz; przy niepowodzeniu tekst zostaje w polu. |
| `CasePanel` | `summary?`, `framing`, `lead`, `textClass?` | slot domyślny zawiera tekst | Dwie sekcje: streszczenie pacjenta (renderowane, gdy ustawiono `summary`) i ramka z tekstem przypadku z rodzajem tekstu i wierszem wprowadzającym. |
| `ChipEditor` | `modelValue`, `label`, `compact?` | zdarzenia `update:modelValue`, `active(chip or null)`, `focus`; udostępnia `insertChip(n)`, `insertText(text)`, `focusEnd()` | Edytor TipTap nad zapisanym tekstem. Chip to węzeł-atom w linii; wiersze list są wcięte, a Enter kontynuuje listę (Enter na pustej pozycji kończy ją). Zmiana `modelValue` z zewnątrz zastępuje zawartość bez wpisu w historii. `compact` ustawia `min-h-24`. |
| `ChipText` | `text` | zdarzenie `active(chip or null)` | Renderer zapisanego tekstu tylko do odczytu: chipy, wiersze list, łamania wierszy. Wskazanie chipa ustawia fokus cytatu; kliknięcie przypina go, gdy pin jest dostępny. |
| `CitationTable` | `citations`, `editable`, `canInsert`, `counts`, `pulseChip`, `marked?`, `flashKey?`, `insertInto?` (`'answer'`), `pinnedChip?` | zdarzenia `active`, `direction(chip, direction)`, `insert(chip)`, `remove(chip)`, `pin(chip)` | Tabela cytatów z listą wyboru kierunku, przyciskiem usuwania, popoverem pomocy i licznikami odwołań dla każdego cytatu. Kliknięcie wiersza emituje `insert`, gdy `canInsert`, w przeciwnym razie `active` i `pin`. Najechanie na wiersz lub fokus emituje `active`. |
| `CiteHelp` | brak | brak | Popover po najechaniu „How to add a quote" (`InfoPopover`, tryb hover) z demonstracją animowaną w CSS. |
| `ConfirmDialog` | `title`, `confirmLabel`, `cancelLabel`, `danger?` | zdarzenia `confirm`, `cancel`; slot domyślny to treść | Modalny `<dialog>` otwierany przez `showModal()` i zamykany przy odmontowaniu. Escape emituje `cancel`. `danger` wybiera styl `btn-danger` dla przycisku potwierdzenia. |
| `DecisionButtons` | `questionId` | `v-model:decision` (`'approve'`, `'reject'`, `'request_changes'` lub `''`), `v-model:comment` | Trójstanowa decyzja administratora o jednej odpowiedzi, z polem komentarza pod wyborem. |
| `DiffText` | `before`, `after` | brak | Redline z `wordDiff(before, after)`: części niezmienione jako `ChipText`, części dodane w `<ins>`, części usunięte w `<del>`, każda z prefiksem dla czytnika ekranu. |
| `ProofreadStep` | `id` (id przydziału) | zdarzenia `submitted`, `missing`, `highlights(highlights)`; udostępnia `flush()` | Sprawdzenie korekty. Dla każdej odpowiedzi pokazuje różnicę i edytowalny tekst, ze zdaniami oznaczonymi cytatami (przełączniki `QuoteTag`) i stanem autozapisu. Wysłanie do recenzji przechodzi przez `ConfirmDialog`. Emituje `missing`, gdy ładowanie korekty zwraca 404, i `submitted` po wywołaniu wysłania. Zobacz [Zapis i wysłanie korekty](#zapis-i-wysłanie-korekty). |
| `Q4Step` | `question`, `q4`, `why` | zdarzenia `update:q4`, `update:why`, `active`; udostępnia `insertChip`, `focusEnd` | Pola Q4: pole tekstowe hipotezy (`maxlength` 2000), grupa radio skali z punktami od -2 do 2, radia kierunku (pokazywane, gdy skala jest powyżej 0), pole „other explanation" (gdy kierunek to `other`) i `ChipEditor` „why" z liczbą słów (pokazywany, gdy skala nie wynosi 0). |
| `QuestionBlock` | `question`, `payload`, `problem?`, `flashKey?` | zdarzenia `answer(text)`, `q4(Q4Answer)`, `rate(n)`, `insufficient`, `active`; udostępnia `insertChip`, `focusEnd` | Nagłówek pytania plus pole dla jego rodzaju: `Q4Step` dla pytania o przesunięcie, `RatingStep` dla oceny, w pozostałych przypadkach `ChipEditor` z liczbą słów. Nagłówek Q4 pogrubia część po „change if ". Podpowiedź pojawia się, gdy odpowiedź na Q1 ma ponad 60 słów i nie ma chipa. |
| `QuoteTag` | `target`, `highlights`, `pressed?`, `toggle?`, `disabled?` | zdarzenie `toggle` | Znacznik cytatu lub `case`. Z `toggle` jest przyciskiem przełącznika; w przeciwnym razie jest przyciskiem przypięcia, gdy pin jest dostępny, a cel nie jest `case`, albo statycznym span. Najechanie i fokus ustawiają fokus cytatu (nie dla `case`). |
| `RatingStep` | `rating`, `insufficient` | zdarzenia `rate(n)`, `insufficient` | Radia od 1 do 5 i opcja niewystarczającej informacji. |
| `ReviewAnswerCard` | `answer`, `highlights`, `assignmentId`, `authorName`, `canVote`, `canComment`, `showVoters`, `startOpen` | zdarzenia `vote(AnswerVote)`, `posted`; slot `decide` | Jedna odpowiedź w recenzji: pytanie, podsumowanie głosów (imiona głosujących dla administratorów przy `showVoters`), przyciski zatwierdzenia i odrzucenia, etykieta decyzji, zdania ze znacznikami cytatów i `AnswerThread`. |
| `ReviewStep` | `questions`, `payload`, `editable` | zdarzenia `edit(id)`, `active(chip or null)` | Podsumowanie odpowiedzi tylko do odczytu, z przyciskiem Edit przy każdej odpowiedzi, gdy `editable`; pokazuje wiersz skali Q4. |
| `StepRail` | `steps: RailStep[]`, `current`, `flashKey?` | zdarzenie `go(id)` | Pasek nawigacji po pytaniach. Krok z `problem` dostaje klasę `flag-shake` i miga ponownie, gdy zmieni się `flashKey`. |
| `UnsavedText` | `text` | brak | Przycisk kopiowania (`navigator.clipboard.writeText`) i ramka `<details>` z polem textarea tylko do odczytu. Gdy kopiowanie się nie powiedzie, ramka się otwiera. |
| `VignetteText` | `text`, `active`, `canCite`, `citeLabel?` (`CITE.add`) | zdarzenie `cite(start, end)` | Tekst przypadku z zaznaczonym przedziałem `active`. Przy `canCite` zaznaczenie tekstu pokazuje przycisk „+ label" przeniesiony przez teleport do `body`; jego naciśnięcie emituje `cite` z przesunięciami przeglądarki (UTF-16) i czyści zaznaczenie. Znacznik nie jest rysowany podczas zaznaczania. |

`RailStep` jest eksportowany z `StepRail.vue`: `{id, label, reachable, problem?}`. `Decision` jest eksportowany z `DecisionButtons.vue`.

## Komponenty w `components/knowledge/` i `components/admin/`

| Komponent | Propsy | Zdarzenia | Przeznaczenie |
|---|---|---|---|
| `KnowledgeSearch` | brak | brak | Wyszukiwanie wśród jednostek wiedzy. Dwa tryby (`question`, `patient_text`) przez `SegmentedToggle`; pole zapytania ma `maxlength` 4000. Przełączenie trybu czyści wyniki i błędy. Wyniki są renderowane jako `UnitCard` z `showCase`. |
| `KnowledgeUnits` | brak | brak | Lista bazy wiedzy pogrupowana według przypadku, a potem według odpowiedzi eksperta; jednostki odpowiedzi są zwinięte do czasu otwarcia. Pokazuje stan indeksu wyszukiwania, odpytuje go, gdy jest w stanie queued lub running, i usuwa jedną jednostkę albo wszystkie jednostki eksperta po `ConfirmDialog`. Usunięcie ustawia stan indeksu na `queued` i przeładowuje go. |
| `UnitCard` | `unit`, `showCase?`, `removable?` | `remove` | Jedna jednostka wiedzy: rodzaj („Whole case" lub `Quote {highlight_id}`), etykieta kierunku, a przy `showCase` także kod i wersja przypadku. |
| `CreateAssignmentDialog` (admin) | `assignments` | `done`, `cancel` | `ConfirmDialog`, który przydziela ostatnio opublikowaną wersję winiety jednemu aktywnemu ekspertowi. Wersja, którą wybrany ekspert już ma w stanie innym niż `cancelled`, jest wyłączona i oznaczona „already assigned". Błędy z API są objaśniane nazwami zainteresowanych ekspertów. |

`KnowledgeUnits` wywołuje `GET /api/v1/knowledge-units` z `status: 'ingested'` i `limit: 500`. Komentarz w źródle stwierdza, że ponad 500 jednostek wymaga stronicowania albo filtra.

## Wywołania HTTP wykonywane przez komponenty i pomocniki

| Źródło | Wywołania |
|---|---|
| `useAnswerDraft` | `GET /api/v1/assignments/{assignment_id}`; `POST .../start`; `GET .../submission`; `PUT .../draft`; `POST .../submit` |
| `ProofreadStep` | `GET` i `PUT /api/v1/assignments/{assignment_id}/proofread`; `POST .../submit-for-review` |
| `AnswerThread` | `POST /api/v1/assignments/{assignment_id}/answers/{question_id}/comments` |
| `KnowledgeSearch` | `POST /api/v1/knowledge-units/search` z `{query, mode, k}` |
| `KnowledgeUnits` | `GET /api/v1/knowledge-units`; `GET /api/v1/knowledge-units/index`; `POST /api/v1/knowledge-units/index/refit`; `DELETE /api/v1/knowledge-units/{unit_id}`; `DELETE /api/v1/knowledge-units/by-expert/{expert_id}` |
| `CreateAssignmentDialog` | `GET /api/v1/users`; `GET /api/v1/vignettes`; `POST /api/v1/vignette-versions/{version_id}/assignments` z `{expert_ids}` |
| `PseudonymChip` | `GET /api/v1/users/by-pseudonym/{pseudonym}` |
| `SignInAgainDialog` | `auth.login` z `@/stores/auth` |

## Pomocniki w `frontend/src/answering`

### `highlights.ts`: cytaty

Cytat jest zapisany w tekście odpowiedzi jako token `⟦hN⟧`. API liczy przedziały w punktach kodowych; przeglądarka liczy w jednostkach UTF-16. Moduł przelicza jedno na drugie i nie dotyka DOM.

| Nazwa | Opis |
|---|---|
| `CHIP_RE` | `/⟦h(\d+)⟧/g`, token chipa. |
| `INK_COUNT` | 8, liczba kolorów tuszu. |
| `Answers` | `Record<string, string or undefined>`, tekst odpowiedzi według id pytania. |
| `utf16ToCodePoint(text, index)`, `codePointToUtf16(text, index)` | Przeliczanie przesunięć. |
| `snapToWords(text, start, end)` | Przycina spacje na brzegach, rozszerza zakres do całych słów, zwraca `[from, to]` albo `null`, gdy nic nie zostaje. Słowo to litery, cyfry, znaki łączone i `_`, połączone przez `'`, `’` lub `-`. |
| `addCitation(citations, text, start, end)` | Wyrównuje zaznaczenie z przeglądarki i zwraca `{kind: 'added', citations}` (numer chipa to liczba + 1, `direction: null`), `{kind: 'duplicate', chip}` dla identycznego przedziału, `{kind: 'too_long'}` powyżej 2000 punktów kodowych albo `{kind: 'empty'}`. |
| `removeCitation(citations, answers, chip)` | Usuwa token chipa z każdej odpowiedzi (z sąsiednimi spacjami, zależnie od sąsiadów) i renumeruje późniejsze chipy w cytatach i odpowiedziach. Zwraca `{citations, answers}`. |
| `countWords(text)` | Liczy słowa, pomijając znaczniki list i chipy. Komentarz w źródle stwierdza, że `count_words` po stronie serwera liczy inaczej. |
| `citationCounts(citations, answers)` | Odwołania na numer chipa w odpowiedziach. |
| `citedChips(answers)` | `Set` numerów chipów, które występują w odpowiedziach. |
| `uncitedChips(citations, answers)` | Numery chipów cytatów, do których nie odwołuje się żadna odpowiedź. |
| `inkFor(chip)` | Od `var(--ink-1)` do `var(--ink-8)`, powtarzane po 8. |
| `segmentsFor(text, active)` | Dzieli tekst na `before`, `marked`, `after` według przedziału `active`, przeliczonego na UTF-16. |

`AddResult` to unia zwracana przez `addCitation`. Limit 2000 to prywatna dla modułu stała `MAX_CITATION_LENGTH`.

### Pomocniki formatu tekstu

| Moduł i funkcja | Opis |
|---|---|
| `chipDoc.ts`: `textToDoc(text)`, `docToText(doc)` | Dokładna konwersja między zapisanym tekstem a dokumentem TipTap: jeden akapit na wiersz, węzły `chip` z atrybutem `n`. |
| `listLines.ts`: `listMarker(line)` | Znacznik listy z otaczającymi spacjami albo `null`. Znacznik to liczba, po której następuje `.` lub `)`, albo jeden ze znaków `-`, `–`, `•`, `*`, a potem spacja (`^\s*(?:\d+[.)]\|[-–•*])\s`). |
| `listLines.ts`: `nextMarker(marker)` | Znacznik z numerem zwiększonym o jeden. |
| `plainText.ts`: `readable(text)` | Zastępuje każdy `⟦hN⟧` przez `[N]`. |
| `plainText.ts`: `plainText(payload, questions)` | Zwykły tekst odpowiedzi w kolejności pytań. Każdy blok zaczyna się od id pytania; pytania o przesunięcie dodają `Hypothesis:`, `Other explanation:` (gdy kierunek to `other`) i `Why:`; pytania z oceną dają `Insufficient information` albo `Rating: n of 5`. Pytania bez treści są pomijane. |
| `wordDiff.ts`: `tokens(text)` | Słowa z końcowymi spacjami; każde łamanie wiersza to osobny token. |
| `wordDiff.ts`: `wordDiff(before, after)` | Najdłuższy wspólny podciąg po tokenach, porównywanych bez końcowych spacji. Zwraca `DiffPart[]` rodzaju `same`, `added` lub `removed`. Koszt jest kwadratowy. |
| `wordDiff.ts`: `changed(before, after)` | `true`, gdy słowa różnią się po normalizacji białych znaków. |

### `steps.ts`: reguły kroków

| Nazwa | Opis |
|---|---|
| `StepId`, `REVIEW` | Id pytania albo `'review'` dla ostatniej strony. |
| `Q4Wording` | `{hypothesis, shift_lead, shift_labels, toward, toward_labels, why}`; typowany ręcznie, bo API typuje `wording` jako słownik. |
| `q4Wording(question)` | Rzutuje `question.wording` na `Q4Wording`. |
| `wordCountLabel(words)` | `"1 word"` albo `"n words"`. |
| `stepProblem(question, payload)` | Pierwszy brakujący element pytania albo `null`. Przesunięcie: hipoteza, punkt skali, kierunek (gdy skala powyżej 0), inne wyjaśnienie (gdy kierunek to `other`), a potem tekst „why" (chyba że skala wynosi 0). Ocena: ocena albo niewystarczająca informacja. W pozostałych przypadkach: niepusta odpowiedź. Długość nigdy się nie liczy. |
| `firstProblem(questions, payload)` | Pierwszy problem w kolejności pytań albo `null`. |
| `firstOpenStep(questions, payload)` | Id pierwszego pytania z problemem, w przeciwnym razie `REVIEW`. |
| `forSaving(payload)` | Payload dla serwera: pomija `toward`, chyba że skala jest powyżej 0, `other_explanation`, chyba że `toward` to `other`, oraz odpowiedź `Q4`, gdy skala wynosi 0. |

### `useAnswerDraft.ts`: ładowanie i zapis szkicu

`useAnswerDraft(id)` zarządza szkicem jednego eksperta dla jednego przydziału. Zwraca `view`, `payload`, `status`, `saveProblem`, `editable`, `load`, `changed`, `flush`, `resume`, `submit` i `stop`.

| Składnik | Zachowanie |
|---|---|
| `load()` | Pobiera przydział (widok nie-eksperta zgłasza `ApiError` 404). Gdy `allowed_actions` zawiera `start`, wysyła start i pobiera ponownie. Ładuje payload zgłoszenia, gdy ustawiono `submitted_at`, w przeciwnym razie payload szkicu. |
| `editable` | `true`, gdy `allowed_actions` zawiera `save_draft`. |
| `changed()` | Oznacza szkic jako zmieniony i planuje zapis po `SAVE_AFTER_MS`. Status zmienia się na `unsaved`, chyba że zapis trwa. Nie wpływa na status w `conflict` i `signin`. |
| `flush()` | Kończy się, gdy wszystko jest zapisane. Zapisy przebiegają pojedynczo i wysyłają wersję zwróconą przez ostatni zapis. Odrzuca z `draft_conflict` (409) w statusie `conflict` i z `not_authenticated` (401) w statusie `signin`. |
| `resume()` | Po ponownym zalogowaniu: opuszcza `signin` i wykonuje flush. |
| `submit()` | Wykonuje flush, potem wysyła zgłoszenie i stosuje zwrócony przydział. |
| `stop()` | Anuluje timer i wyłącza ponowienia. |

Wynik zapisu w `saveOnce`: kod błędu `draft_conflict` daje `conflict`; HTTP 401 daje `signin`; pozostałe 4xx poza 408 i 429 dają `rejected` (błąd jest zachowany w `saveProblem`); wszystko inne daje `failed` i ponowienie po `RETRY_AFTER_MS`, chyba że zatrzymano. `SaveStatus` to `saved`, `unsaved`, `saving`, `failed`, `rejected`, `signin` lub `conflict`. `EMPTY_PAYLOAD` to `{answers: {}, highlights: [], insufficient_information: false}`.

### Zapis i wysłanie korekty

`ProofreadStep` prowadzi własną pętlę zapisu o tym samym kształcie: `SAVE_AFTER_MS` po edycji lub zmianie znacznika, jeden zapis naraz z wersją z widoku, status `saved`, `unsaved`, `saving`, `failed`, `conflict` lub `rejected`. Kod błędu `proofread_conflict` daje `conflict`; każde inne 4xx daje `rejected`; pozostałe błędy dają `failed` i ponowienie po `RETRY_AFTER_MS`. Zdanie zachowuje co najmniej jeden cel cytatu: usunięcie ostatniego jest ignorowane. Przycisk wysłania jest zablokowany (i oznacza problemy), gdy odpowiedź jest pusta albo zdanie powiązanej odpowiedzi nie ma celu; błąd `links_missing` z serwera także je oznacza.

### Fokus cytatu i ujście komentarzy

| Moduł | Nazwy | Opis |
|---|---|---|
| `quoteFocus.ts` | `provideQuoteFocus()`, `useQuoteFocus()` | Udostępniają i wstrzykują `Ref<QuoteId or null>` dla wskazywanego cytatu. Bez dostawcy `useQuoteFocus` zwraca prywatny ref. |
| `quoteFocus.ts` | `provideQuotePin()`, `useQuotePin()`, `togglePin(pin, id)` | Pin dla klikniętego cytatu. `useQuotePin` zwraca `null` bez dostawcy. `togglePin` przypina id albo czyści je, gdy jest już przypięte. |
| `quoteFocus.ts` | `chipFocus(focus)` | Zapisywalny computed między id `h<N>` a numerami chipów. |
| `quoteFocus.ts` | `markFor(id, highlights)`, `inkOf(chip)` | `Mark` (`{span, chip}`) dla zaznaczenia i jego kolor (`var(--ink-0)` dla braku chipa). |
| `commentSink.ts` | `provideCommentSink()`, `useCommentSink()` | Udostępniają i wstrzykują `ShallowRef<CommentSink or null>`; `CommentSink` to `{questionId, insertChip, insertText}`. |
| `commentSink.ts` | `quoted(words)` | Fragment w cudzysłowie drukarskim ze zwiniętymi białymi znakami i końcową spacją. |

`QuoteId` to napis: `h3` dla cytatu 3 eksperta, `i1` dla słów cytowanych bez chipa.

## Stałe

| Nazwa | Wartość | Gdzie | Znaczenie |
|---|---|---|---|
| `SAVE_AFTER_MS` | 2000 | `useAnswerDraft.ts` | Opóźnienie autozapisu szkicu. |
| `RETRY_AFTER_MS` | 5000 | `useAnswerDraft.ts` | Opóźnienie ponowienia po nieudanym zapisie szkicu. |
| `SAVE_AFTER_MS` | 1500 | `ProofreadStep.vue` | Opóźnienie autozapisu korekty. |
| `RETRY_AFTER_MS` | 5000 | `ProofreadStep.vue` | Opóźnienie ponowienia po nieudanym zapisie korekty. |
| `Q1_NUDGE_WORDS` | 60 | `QuestionBlock.vue` | Liczba słów Q1 bez chipa, po której pojawia się podpowiedź. |
| `HITS` | 8 | `KnowledgeSearch.vue` | `k` wysyłane z wyszukiwaniem wiedzy. |
| `PAGE` | 500 | `KnowledgeUnits.vue` | `limit` żądania listy jednostek. |
| `POLL_MS` | 2000 | `KnowledgeUnits.vue` | Interwał odpytywania stanu indeksu w stanie `queued` lub `running`. |
| `FULL`, `COMPACT` | 176, 56 (px) | `HeroBanner.vue` | Wysokość banera i wysokość po zwinięciu; dystans zwijania to 120 px. |
| `MAX_CITATION_LENGTH` | 2000 | `highlights.ts` | Najdłuższy cytat w punktach kodowych. |
| `INK_COUNT` | 8 | `highlights.ts` | Kolory tuszu przypisywane cyklicznie według numeru chipa. |
| `STOPS`, `TOWARD` | -2 do 2; `more_adhd`, `less_adhd`, `other` | `Q4Step.vue` | Punkty skali i opcje kierunku. |
| `RATINGS` | 1 do 5 | `RatingStep.vue` | Opcje oceny. |

## Źródła w kodzie

- `frontend/src/answering/chipDoc.ts` - konwersja tekstu i dokumentu TipTap
- `frontend/src/answering/commentSink.ts` - provide/inject ujścia komentarzy, quoted
- `frontend/src/answering/highlights.ts` - model cytatów, przesunięcia, liczniki, kolory tuszu
- `frontend/src/answering/listLines.ts` - wykrywanie znacznika listy
- `frontend/src/answering/plainText.ts` - eksport zwykłego tekstu, readable
- `frontend/src/answering/quoteFocus.ts` - fokus i pin cytatu, Mark
- `frontend/src/answering/steps.ts` - reguły kroków, sformułowanie Q4, forSaving
- `frontend/src/answering/useAnswerDraft.ts` - ładowanie szkicu i pętla zapisu, status, opóźnienia
- `frontend/src/answering/wordDiff.ts` - różnica słów i sprawdzenie changed
- `frontend/src/components/AboutSection.vue` - propsy
- `frontend/src/components/CaseCard.vue` - propsy, zawartość popovera
- `frontend/src/components/HeroBanner.vue` - stałe zwijania i scroll padding
- `frontend/src/components/InfoPopover.vue` - tryby, sloty, zdarzenie open
- `frontend/src/components/LoadingSpinner.vue` - propsy
- `frontend/src/components/PageIntro.vue` - propsy, link learn-more
- `frontend/src/components/PseudonymChip.vue` - wyszukiwanie i pamięć podręczna
- `frontend/src/components/SectionCard.vue` - propsy
- `frontend/src/components/SegmentedToggle.vue` - generyczne opcje i v-model
- `frontend/src/components/SignInAgainDialog.vue` - okno logowania, którego nie można zamknąć
- `frontend/src/components/StepFlow.vue` - propsy
- `frontend/src/components/TermGrid.vue` - propsy
- `frontend/src/components/admin/CreateAssignmentDialog.vue` - okno przydziału i wywołania
- `frontend/src/components/answering/AnswerThread.vue` - propsy dyskusji, zdarzenia, addQuote
- `frontend/src/components/answering/CasePanel.vue` - propsy i slot
- `frontend/src/components/answering/ChipEditor.vue` - edytor TipTap, rozszerzenia, udostępniane metody
- `frontend/src/components/answering/ChipText.vue` - renderer chipów tylko do odczytu
- `frontend/src/components/answering/CitationTable.vue` - propsy i zdarzenia tabeli cytatów
- `frontend/src/components/answering/CiteHelp.vue` - popover pomocy
- `frontend/src/components/answering/ConfirmDialog.vue` - okno modalne
- `frontend/src/components/answering/DecisionButtons.vue` - model decyzji
- `frontend/src/components/answering/DiffText.vue` - renderowanie redline
- `frontend/src/components/answering/ProofreadStep.vue` - pętla zapisu korekty, blokada, stałe
- `frontend/src/components/answering/Q4Step.vue` - pola Q4, STOPS, TOWARD
- `frontend/src/components/answering/QuestionBlock.vue` - pole pytania według rodzaju, podpowiedź
- `frontend/src/components/answering/QuoteTag.vue` - warianty znacznika
- `frontend/src/components/answering/RatingStep.vue` - radia oceny
- `frontend/src/components/answering/ReviewAnswerCard.vue` - propsy karty recenzji, zdarzenia, slot
- `frontend/src/components/answering/ReviewStep.vue` - propsy podsumowania, zdarzenia
- `frontend/src/components/answering/StepRail.vue` - RailStep i nawigacja
- `frontend/src/components/answering/UnsavedText.vue` - zapasowe kopiowanie
- `frontend/src/components/answering/VignetteText.vue` - zaznaczenie do cytatu
- `frontend/src/components/knowledge/KnowledgeSearch.vue` - tryby wyszukiwania, HITS
- `frontend/src/components/knowledge/KnowledgeUnits.vue` - lista jednostek, odpytywanie indeksu, usuwanie
- `frontend/src/components/knowledge/UnitCard.vue` - propsy karty jednostki
