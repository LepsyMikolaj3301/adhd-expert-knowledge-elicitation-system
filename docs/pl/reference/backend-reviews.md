---
title: Recenzje koleżeńskie w backendzie
diataxis: reference
---

# Backend: `app.reviews`

Język: **Polski** · [English](../../eng/reference/backend-reviews.md)

`app.reviews` implementuje recenzję koleżeńską przesłanego przydziału: recenzenci otwierają recenzję, komentują i głosują nad każdą odpowiedzią, a decyzja administratora dla każdej odpowiedzi zamyka recenzję. Moduł udostępnia poniższe trasy, reguły dostępu określające, kto może czytać zgłoszenie, oraz tabele `review_participants`, `answer_comments`, `answer_votes` i `answer_decisions`. Stany i przejścia, przez które przechodzi recenzja, opisuje [backend-assignments-jobs.md](backend-assignments-jobs.md); kontekst jest w [assignment-lifecycle.md](../explanation/assignment-lifecycle.md).

Trasy są zamontowane pod `/api/v1` z tagiem `reviews`. Błędy mają postać `{code, message, details}`; `DomainError` domyślnie zwraca HTTP 409, `not_found` to 404, `invalid` to 422, a `forbidden` to 403.

## Trasy HTTP

W trasach przyjmujących `assignment_id` przeglądający jest odwzorowywany na aktora przez `assignments.service.actor_for`: `admin`, `assignee` (autor) lub `reviewer`; niezwiązany przeglądający dostaje 404 `not_found`. Recenzent, który nie otworzył recenzji, dostaje 409 `review_not_opened` z każdej poniższej trasy poza `POST .../review/open`.

| Trasa | Kto | Zachowanie |
|---|---|---|
| `GET /reviews` | każdy | Zapytanie `status` (`open` lub `closed`, domyślnie oba) i `limit` (1..500, domyślnie 100). Zwraca listę `ReviewItem`. |
| `POST /assignments/{assignment_id}/review/open` | recenzent | 204. Wstawia wiersz `ReviewParticipant` i zapisuje zdarzenie audytu `review_opened`. Idempotentne. Bez efektu dla autora i administratora. |
| `GET /assignments/{assignment_id}/answers` | administrator, wykonawca, recenzent | Zapytanie `review_round`. Zwraca `ReviewAnswersView`. |
| `POST /assignments/{assignment_id}/answers/{question_id}/comments` | administrator, wykonawca, recenzent | Treść `CommentCreate`. 201 z `CommentView`. |
| `PUT /assignments/{assignment_id}/answers/{question_id}/vote` | recenzent | Treść `VoteInput`. Zwraca `ReviewAnswersView` dla bieżącej rundy. |
| `POST /assignments/{assignment_id}/answer-decisions` | administrator | Treść `AnswerDecisionsRequest`. Zwraca administratorski `AssignmentView`. |

### `GET /reviews`

Filtr stanu pochodzi z `access`: `open` to `OPEN_REVIEW_STATES`, `closed` to `CLOSED_REVIEW_STATES`, brak filtra to `REVIEW_VISIBLE_STATES`. Pojawiają się tylko przydziały z przesłaną rundą (`was_submitted`). Lista jest uporządkowana malejąco według `updated_at`, a potem według `id`.

- Administrator: każdy pasujący przydział.
- Pozostali przeglądający: przydziały, których autorem jest przeglądający, przydziały, których recenzję przeglądający otworzył, oraz przydziały winiet, których nie ma w `blocked_vignettes(viewer)`.

Dla każdej pozycji `relation` to `admin`, `author` lub `reviewer`; `opened` jest prawdą, chyba że relacja to `reviewer`, a przeglądający nie otworzył recenzji; `author_pseudonym` jest ustawiony tylko dla administratora. Liczniki (`answer_count`, `approvals`, `disapprovals`, `comment_count`, `my_votes`) odnoszą się do bieżącego `review_round` przydziału.

### `POST .../review/open`

Przydział jest blokowany bez wymagania „otwarcia”. Niezwiązany przeglądający, recenzja bez przesłanej rundy, przydział spoza `REVIEW_VISIBLE_STATES` lub przeglądający, który wciąż musi odpowiedzieć na winietę, dostaje z `actor_for` 404 `not_found` (zob. `may_review` poniżej).

### `GET .../answers`

Zwraca odpowiedzi jednej rundy. Rundy to wartości `review_round` wierszy `ProofreadRound` z ustawionym `submitted_at`. Administrator i autor mogą przekazać `review_round` dla rundy o niższym numerze; dla recenzenta parametr jest ignorowany i zwracana jest ostatnia runda. 404 `not_found`, gdy żadna runda nie została przesłana lub żądanej rundy nie ma wśród nich.

`ReviewAnswersView` zawiera `review_round`, `rounds`, `state` przydziału, `highlights` i `answers`. Każdy `ReviewAnswer` ma `question_id`, `question`, `text` (końcowy tekst autora), `lines`, `comments`, `approvals`, `disapprovals`, `my_vote`, `votes` i `decision` (decyzja administratora dla tej odpowiedzi, jeśli istnieje).

### `POST .../comments`

Kontrole w kolejności: przydział jest w stanie `peer_review` (inaczej 409 `review_closed`); `stance` podaje tylko recenzent (inaczej 422 `stance_not_allowed`); odpowiedź dla `question_id` istnieje w bieżącej rundzie (inaczej 404 `not_found`); `parent_id` wskazuje komentarz najwyższego poziomu tego samego przydziału, rundy i pytania (inaczej 422 `invalid_parent`). Zapisuje zdarzenie audytu `comment_added` z `question_id`, `comment_id` i `stance`.

### `PUT .../vote`

Głosować może tylko recenzent (inaczej 403 `forbidden`). Przydział musi być w stanie `peer_review` (409 `review_closed`), a `review_round` w treści żądania musi być równe bieżącej rundzie przydziału (409 `stale_round`, `details.current_round`). Odpowiedź musi istnieć (404 `not_found`). Dla każdej czwórki (przydział, runda, pytanie, głosujący) istnieje jeden głos; drugie żądanie zastępuje głos i ustawia `updated_at`. Zapisuje zdarzenie audytu `vote_cast`. Głosy mają charakter doradczy.

### `POST .../answer-decisions`

1. `check_transition(state, approve_answers, actor)`: 409 `illegal_transition` poza `peer_review`, 403 `forbidden` dla nie-administratora.
2. Każda decyzja `request_changes` wymaga niepustego `comment` (422 `comment_required`).
3. Zbiór `question_id` musi być równy zbiorowi odpowiedzi bieżącej rundy, każdy raz (422 `decisions_incomplete`).
4. Wstawiany jest jeden wiersz `AnswerDecision` na odpowiedź, z `content_hash = proofread.answer_hash(...)` recenzowanego tekstu i powiązań.
5. Wynik wynika z decyzji:

| Decyzje | Efekt |
|---|---|
| co najmniej jedna `request_changes` | `review_round` jest zwiększane; `transition` z `request_changes` przenosi do `proofread_check` (meta: liczby według wartości decyzji i numer nowej rundy); `proofread.open_next_round` tworzy następną rundę z tekstu, powiązań, flag i przebiegów poprzedniej rundy, z komentarzami jako `feedback`. |
| brak `request_changes`, co najmniej jedna `approve` dla odpowiedzi, dla której is_filed jest prawdą | `transition` z `approve_answers` przenosi do `processing`. |
| w pozostałych przypadkach | `transition` z `reject_all_answers` przenosi do `rejected`. |

Odpowiedź jest „filed”, gdy `findings.is_filed(question_id)` jest prawdą: to pytanie otwarte inne niż Q4 (część „dlaczego” w Q4 i ocena nie są cięte na jednostki).

## Reguły dostępu (`access.py`)

| Nazwa | Wartość / znaczenie |
|---|---|
| `PRE_SUBMISSION_STATES` | `assigned`, `in_progress`, `proofreading`, `proofread_check` |
| `OPEN_REVIEW_STATES` | `peer_review` |
| `CLOSED_REVIEW_STATES` | `processing`, `processing_failed`, `ingesting`, `ingestion_failed`, `ingested`, `rejected` |
| `REVIEW_VISIBLE_STATES` | suma zbiorów otwartych i zamkniętych |

| Funkcja | Opis |
|---|---|
| `was_submitted()` | Warunek SQL: przydział ma `ProofreadRound` z ustawionym `submitted_at`. Odróżnia `processing_failed` po recenzji od `processing_failed` po nieudanej korekcie. |
| `blocked_vignettes(db, expert_id) -> set[UUID]` | Identyfikatory winiet (dowolna wersja), dla których ekspert ma przydział w `PRE_SUBMISSION_STATES`. |
| `vignette_id_of(db, assignment) -> UUID` | Winieta wersji przydziału. |
| `has_opened(db, assignment_id, expert_id) -> bool` | Istnieje wiersz `ReviewParticipant`. |
| `may_review(db, assignment, viewer) -> bool` | Fałsz, chyba że przeglądający jest aktywnym ekspertem. Prawda, gdy przeglądający otworzył recenzję. W przeciwnym razie prawda, gdy przydział jest w `REVIEW_VISIBLE_STATES`, ma przesłaną rundę, a jego winiety nie ma w `blocked_vignettes(viewer)`. |

Docstring modułu stwierdza, że reguła jest oceniana przy każdym żądaniu, a nie raz w chwili przesłania, oraz że czytanie jest jawne: tekst jest wysyłany dopiero po otwarciu recenzji.

## Mówcy

`speaker_for(assignment, actor, user_id, role, pseudonym)` zwraca `Speaker(kind, pseudonym)`. `kind` to `author`, gdy użytkownik jest właścicielem przydziału, w przeciwnym razie `admin` dla użytkownika-administratora, w przeciwnym razie `reviewer`. `pseudonym` jest ustawiony dla recenzenta albo dla dowolnego mówcy, gdy przeglądający działa jako `admin`; w pozostałych przypadkach ma wartość `None`.

## Tabele

| Tabela (`Model`) | Klucz | Kolumny |
|---|---|---|
| `review_participants` (`ReviewParticipant`) | `assignment_id`, `expert_id` | `opened_at` |
| `answer_comments` (`AnswerComment`) | `id` | `assignment_id`, `review_round`, `question_id` (8 znaków), `author_id`, `parent_id` (odwołanie do samej siebie, jeden poziom), `stance`, `body`, `created_at` |
| `answer_votes` (`AnswerVote`) | `assignment_id`, `review_round`, `question_id`, `voter_id` | `vote`, `created_at`, `updated_at` |
| `answer_decisions` (`AnswerDecision`) | `assignment_id`, `review_round`, `question_id` | `reviewer_id` (administrator podejmujący decyzję), `decision`, `comment`, `content_hash` (64 znaki), `decided_at` |

`answer_comments` ma indeks `ix_answer_comments_answer` na (`assignment_id`, `review_round`). Docstring modelu stwierdza, że komentarze nie są edytowane.

Enumeracje: `DecisionValue` (`approve`, `reject`, `request_changes`), `Stance` (`support`, `challenge`, `question`), `AnswerVoteValue` (`approve`, `disapprove`).

## Modele żądań i odpowiedzi (`schemas.py`)

| Model | Pola i limity |
|---|---|
| `CommentCreate` | `body` (po obcięciu białych znaków, 1..5000 znaków), `stance` (opcjonalne), `parent_id` (opcjonalne) |
| `VoteInput` | `vote`, `review_round` (>= 1) |
| `AnswerDecisionInput` | `question_id`, `decision`, `comment` (opcjonalne, maks. 5000 znaków) |
| `AnswerDecisionsRequest` | `decisions` (maks. 20 pozycji) |
| `CommentView` | `id`, `question_id`, `parent_id`, `stance`, `body`, `created_at`, `speaker`, `is_mine` |
| `VoteEntry` | `speaker`, `vote`, `at` |
| `DecisionView` | `decision`, `comment`, `decided_at` |
| `Speaker` | `kind` (`author`, `reviewer`, `admin`), `pseudonym` |
| `ReviewItem` | `assignment_id`, `vignette_code`, `vignette_version`, `review_round`, `state`, `relation`, `opened`, `answer_count`, `approvals`, `disapprovals`, `comment_count`, `my_votes`, `updated_at`, `author_pseudonym` |

Wszystkie modele żądań zabraniają dodatkowych pól.

## Źródła w kodzie

- `backend/app/reviews/router.py` - trasy i wzorzec blokowania
- `backend/app/reviews/service.py` - list_reviews, list_answers, open_review, add_comment, cast_vote, submit_decisions, speaker_for
- `backend/app/reviews/access.py` - grupy stanów, may_review, blocked_vignettes, was_submitted
- `backend/app/reviews/models.py` - tabele i enumeracje
- `backend/app/reviews/schemas.py` - modele żądań i odpowiedzi
- `backend/app/assignments/service.py:68-107` - actor_for, load i lock, które odwzorowują przeglądających na aktorów i wymuszają review_not_opened
- `backend/app/knowledge/findings.py:76-79` - is_filed
- `backend/app/proofread/service.py:65-69,247-286` - answer_hash i open_next_round, wywoływane w kroku decyzji
