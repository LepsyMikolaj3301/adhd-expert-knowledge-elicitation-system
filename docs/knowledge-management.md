# Zarządzanie wiedzą ekspercką w bazie RAG

Szkielet rozdziału pracy: decyzje, alternatywy, uzasadnienia. Dotyczy punktów zakresu Z2 (architektura
pozyskiwania, przetwarzania i **zarządzania** wiedzą) i Z6 (testy scenariuszy pozyskiwania i
**aktualizacji** wiedzy). Stan na 2026-11-20. Rozdział 7 mówi wprost, czego ten dokument jeszcze nie
rozstrzyga.

## 1. Punkt wyjścia

### 1.1 Zasady, których nie zmieniamy

1. **Klasyfikuj, nie rozstrzygaj.** Podobieństwo, NLI albo LLM tylko proponują; decyduje Nadzorca.
2. **Tekst eksperta jest dosłowny.** Model go nie przepisuje.
3. **Postgres jest źródłem prawdy.** Embeddingi są indeksem pochodnym; zapisujemy model embeddingu.
4. **Dane z elicytacji nie opuszczają infrastruktury autora.**
5. **Jeden realny ekspert.** Różnorodność testujemy na osi ekspert ↔ literatura; wielu ekspertów tylko
   na danych syntetycznych.
6. **Bez grafu.** Zakres zawężono do HybridRAG (BM25 + dense, metadane przy chunkach, fuzja RRF).

### 1.2 Co system robił przed tą zmianą (audyt kodu)

Zarządzanie **jakością** było kompletne, zarządzanie **różnorodnością** i **aktualizacją** nie.

| Obszar | Stan | Gdzie |
|---|---|---|
| Przegląd i zatwierdzanie | maszyna stanów z rolami, rundy przeglądu, decyzje Nadzorcy związane z `content_hash` przeglądanego tekstu | `app.assignments`, `app.reviews` |
| Ślad zmian | `audit_events` i `submissions` tylko do dopisywania (trigger blokuje UPDATE) | migracja 0001 |
| Wejście do indeksu | do `chips` trafia tylko to, co zatwierdzone; ingestia jest idempotentna i atomowa | `app.knowledge.ingest` |
| Wycofanie wkładu | wiersze `chips` znikają w tej samej transakcji, wagi BM25 przelicza job `refit`; dane w `app` zostają | `app.knowledge.removal` |
| Cykl życia po ingestii | tylko `ingested → removed`; brak zastąpienia, wersji, `valid_from` | `UnitStatus` |
| Zestawienie ekspertów | brak; jedyny ślad to wspólny `cue_key` przy **identycznym** zakresie | `chips.cue_keys` |
| Porównanie z literaturą | brak; ekspert (`chips`) i literatura (`public.chunks`) to osobne indeksy | – |
| Model embeddingu | zapisany przy chunkach literatury, nie przy jednostkach ekspertów | `chunks.embedding_model` |

Dwa rozjazdy z opisem projektu, które warto nazwać w pracy: (a) lokalny model w `proofread/enhance.py`
może zaproponować pełniejsze zdania, więc dosłowny jest tekst **zatwierdzony przez eksperta**, nie
koniecznie tekst przez niego **napisany** (`answer_revisions` zachowuje `original`); (b) wycofanie
usuwa dane z indeksu, ale nie z tabel `app`, więc nie jest jeszcze usunięciem w rozumieniu RODO.

## 2. Aspekt systemowy: zgodność zamiast rozstrzygania

Wniosek wymaga pogodzenia spójnej bazy z różnorodnością interpretacji. Zasada 1 wyklucza
„rozstrzygnięcie” sprzeczności przez system, więc baza ma **pokazywać**, ilu ekspertów czyta
fragment tak samo i ilu inaczej. Niezgoda staje się informacją, a nie błędem do usunięcia.

### D1. Co znaczy „zgadzają się”

**Decyzja:** zgodność = **uwaga + kierunek**: ilu ekspertów, którzy odpowiedzieli na ten tekst,
zaznaczyło ten fragment, i jak go ocenili (`toward`, `away`, `neutral`, `unclear`). Liczone w kodzie,
bez modelu.

| Alternatywa | Dlaczego nie |
|---|---|
| tylko uwaga (czy zaznaczyli) | nie odróżnia „wszyscy widzą cechę” od „wszyscy widzą coś, ale przeciwnie” |
| interpretacja (NLI/LLM porównuje treść komentarzy) | wymaga modelu i decyzji Nadzorcy; odłożona (D9) |

### D2. Co to jest „ten sam fragment”

**Decyzja:** zaznaczenia **jednej wersji winiety** łączą się, gdy ich zakresy pokrywają się z
**IoU ≥ 0,5**, a powiązania są przechodnie (a–b i b–c wrzuca wszystkich trzech do jednej grupy). To
dopasowanie przybliżone po **pozycji**, nie po znaczeniu. Próg jest parametrem (`IOU_THRESHOLD`).

Pomiar na schemacie `chips_scale` (24 winiety, 1415 zaznaczeń eksperckich, 32 ekspertów na 4
winietach kotwicznych):

| Reguła | Grup | Ekspertów na grupę (mediana / maks.) | Uwaga |
|---|---|---|---|
| identyczny zakres (dotychczasowy `cue_key`) | 561 | 1 / 28 | ponad połowa par nakładających się zaznaczeń (4624 z 8269) nie ma identycznego zakresu: zgodność zaniżona |
| dowolne nakładanie, łańcuchowo | 213 | 4 / 32 | skleja sąsiednie wskazówki w grupy do 32% tekstu |
| **IoU ≥ 0,5, łańcuchowo** | **310** | **3 / 32** | grupy do 20% tekstu |
| zdanie winiety | 247 | 4 / 32 | zlewa dwie wskazówki z jednego zdania; 8% zaznaczeń przekracza granicę zdania |

Analiza wrażliwości progu (`scripts/rag/eval_agreement.py`): przy 0,3 / 0,5 / 0,7 grup jest 238 / 310 /
405, a mediana ekspertów na grupę 4 / 3 / 2. Wniosek jakościowy (zgodność umiarkowana, niezgoda częsta)
nie zależy od progu.

### D3. Mianownik „z n”

**Decyzja:** n = eksperci, którzy mają jednostki dla tej wersji winiety w bazie (nie ci, którzy
zacytowali fragment; inaczej zawsze wychodziłoby „k z k”). Ekspert odrzucony w przeglądzie lub
wycofany nie liczy się ani do k, ani do n. Brak zaznaczenia **nie jest niezgodą**: ekspert mógł
fragmentu po prostu nie komentować.

### D4. Dane pochodne, przeliczane atomowo

**Decyzja:** grupy żyją w `chips.fragment_groups` i `chips.fragment_group_members`, a źródłem prawdy
zostają `highlights`. Grupy danej wersji winiety są przeliczane w tej samej transakcji i pod tą samą
blokadą (`BM25_LOCK`), która zmienia zaznaczenia: przy ingestii i przy wycofaniu. Wycofany ekspert
znika więc z licznika i z mianownika jednocześnie; nikt nie przeczyta liczby z kimś, kogo już nie ma.

| Alternatywa | Dlaczego nie |
|---|---|
| widok SQL liczony przy zapytaniu | łańcuchowe IoU wymaga rekurencyjnego CTE, trudnego do przetestowania; liczone przy każdym wyszukiwaniu |
| przeliczanie asynchroniczne (job) | okno, w którym liczby obejmują wycofanego eksperta |

Starsze dane uzupełnia `python -m app.cli recompute-agreement`.

### D5. Etykieta grupy

`single` (jeden ekspert), `split` (wśród zaznaczeń są i `toward`, i `away`), `agreed` (≥ ¾ ekspertów w
jednym, niemieszanym kierunku), `leaning` (reszta). Ekspert, który w jednej grupie sam sobie
przeczy, ma kierunek `mixed`. Progi i reguła mają numer wersji (`RULE_VERSION`).

## 3. Wpływ na wyszukiwanie

### D6. Zgodność informuje, nie przesuwa wyniku

**Decyzja:** pozycja notatki w rankingu = pozycja jej **najlepszego** członka. Premia za konsensus
(suma) odrzucona: zdanie jednego eksperta przegrywałoby z większością tylko dlatego, że jest w
mniejszości, a to dokładnie ta różnorodność, którą baza ma zachować.

### D7. Jedna notatka na grupę, z głosem mniejszości

Przy włączonym `group_fragments` jednostki fragmentów jednej grupy zwijają się w **jedną notatkę**.
Notatka zawiera słowa pacjenta, linię z liczbami i dosłowne wypowiedzi **najwyżej trzech** ekspertów
(`GROUP_VOICES`): najlepiej trafionego, potem po jednym z każdego innego kierunku, żeby głos
mniejszości był zawsze widoczny, potem najlepsi z reszty. Liczby obejmują wszystkich, nie tylko
cytowanych. Eksperci są numerowani, nigdy nazywani. Schemat notatki:

```
Teaching case V001: an adult's journal entry
Patient's words: "<słowa pacjenta z zaznaczeń grupy>"
Agreement: 3 of 4 clinicians who answered this text cited it; 2 toward, 1 away (split).
Clinician 1 (marked: toward; overall 3/5):
Q1: <zdania eksperta, dosłownie>
Clinician 2 (marked: away; overall 2/5):
Q2: <zdania eksperta, dosłownie>
```

Jednostki case i fragmenty bez grupy są pakowane jak dotąd. Zwolnione miejsca w top-k zajmują inne
fragmenty (istniejący `overfetch`), co jest odpowiedzią na zatłoczenie top-k, w którym ten sam fragment
mówiony przez wielu ekspertów zajmuje większość wyników.

### D8. Liczby liczy kod, nie model

Linia `Agreement:` powstaje w kodzie (`render_agreement`). Prompt systemowy dostaje jedną regułę:
przepisz liczby dokładnie, sam nie licz, rozbieżne odczytania podaj obok siebie z numerami notatek.
Po generacji `agreement_claims` sprawdza każde „k z n” w odpowiedzi względem notatki, którą zdanie
cytuje (albo wszystkich notatek, gdy zdanie nie cytuje żadnej); cytat nieistniejącej notatki jest
niewierny. To metryka wierności liczb do Z6.

### D9. Zgodność interpretacji (inny fragment, to samo znaczenie) poza odpowiedzią

**Decyzja:** kandydaci pozostają tylko w raporcie, nie w odpowiedzi RAG. Powód pomiarowy: cosinus
wektorów I1 **nie widzi kierunku**. Dla par jednostek różnych ekspertów o nakładających się
fragmentach mediana cosinusa wynosi 0,809 przy tym samym kierunku i 0,800 przy przeciwnym; dla
fragmentów rozłącznych 0,675 i 0,652. To jest para minimalna z negacją (scenariusz 8) potwierdzona
na danych. Kandydatów jest niewiele: na `chips_scale` 145 par o cosinusie ≥ 0,85 w różnych grupach.

| Alternatywa | Dlaczego nie |
|---|---|
| tylko potwierdzone przez Nadzorcę | zgodne z zasadą 1, ale ręczna praca nad każdą parą |
| z etykietą „niezweryfikowane” | model mógłby przedstawić to jako zgodę |

### D10. Funkcja jest opcjonalna

`group_fragments` jest domyślnie **wyłączone**, bo zmienia zewaluowany format notatek i prompt.
Włączenie wymaga ponownej ewaluacji generacji (rozdział 7). Ignorowane, gdy filtr wskazuje
ekspertów: liczby obejmowałyby wtedy więcej osób, niż pokazuje notatka.

## 4. Pozostałe decyzje o danych

- **Usunięcie I3.** Indeks „wyjaśnienie + pełne słowa pacjenta” był liczony i przechowywany, ale
  nieużywany: pytania szukają po I1, tekst pacjenta po cue keys (I2). W ewaluacji trybu tekstu
  pacjenta (silver, 9 zapytań) I3 miał recall@4 0,059 [0,034; 0,084], ale produkcyjny retriever go nie
  używa. Usunięto kolumny w `app` i `chips` (migracja 0010), jeden embedding na jednostkę i jedno
  dopasowanie BM25 mniej. Wyniki dawnych porównań zostały w `data/eval/chip_units/`.
- **Model embeddingu przy jednostce.** `chips.finding_units.embedding_model` (migracja 0011),
  zapisywany przy ingestii z `config/indexing.yaml`; istniejące wiersze uzupełnione wartością `bge-m3`.
  Domyka zasadę 3 dla jednostek tak, jak `chunks.embedding_model` robił to dla literatury.
- **Migracje nie kasują danych `chips`.** Downgrade migracji 0011 niczego nie usuwa (jak 0003).

## 5. Pomiary na danych syntetycznych

Źródło: `scripts/rag/eval_agreement.py`, schemat `chips_scale`, wynik w
`data/eval/agreement/20261120-chips-scale/` (`report.md`, `results.json`,
`level2_candidates.csv`).

| IoU | Grup | Etykiety (agreed / leaning / single / split) | Pary ekspertów w grupie czytające różnie |
|---|---|---|---|
| 0,3 | 238 | 79 / 81 / 48 / 30 | 0,49 |
| **0,5** | **310** | **98 / 91 / 94 / 27** | **0,48** |
| 0,7 | 405 | 118 / 103 / 159 / 25 | 0,45 |

Krippendorff α nominalne (przedział 95% z bootstrapu po winietach), IoU 0,5:

| Zakres | Uwaga | Kierunek (grupy z ≥ 2 ekspertami) |
|---|---|---|
| wszystkie winiety (24) | 0,29 [0,23; 0,34] | 0,36 [0,28; 0,45] |
| kotwice, 32 ekspertów (4) | 0,37 [0,32; 0,43] | 0,34 [0,18; 0,50] |

Implementacja α jest sprawdzona na klasycznym przykładzie Krippendorffa (α = 0,743).

**Jak to czytać.** (1) Eksperci 3–32 są generowani przez modele językowe i zgadzają się ze sobą
bardziej niż klinicyści, więc liczby pokazują działanie miary, nie wynik o klinicystach. (2) α uwagi
jest zaniżone: grupa istnieje tylko dlatego, że ktoś ją zaznaczył. Wariant z jednostkowaniem (αᵤ)
tego nie ma i nie został zaimplementowany. (3) Zgodność jest umiarkowana (α ≈ 0,3), a prawie
połowa par ekspertów w tej samej grupie czyta ją różnie: niezgoda jest zjawiskiem częstym, nie
marginesem, co uzasadnia pokazywanie jej zamiast usuwania. (4) Na danych realnych n = 1, więc α
nie istnieje.

Zatłoczenie top-k po włączeniu grupowania **nie zostało jeszcze zmierzone na `chips_scale`**
(schemat testowy nie ma jeszcze tabel grup); na zatłoczonej kopii silver test integracyjny potwierdza
tylko mechanizm (grupa jest jedną notatką, miejsca zajmują inne fragmenty), a liczb z tych kopii nie
cytujemy.

## 6. Testy Z6 (pozyskiwanie i aktualizacja wiedzy)

Pokrycie ośmiu scenariuszy z założeń, co jest przetestowane dziś:

| # | Scenariusz | Stan |
|---|---|---|
| 1 | nowa jednostka zgodna z istniejącą | **tak**: kolejny ekspert zaznaczający ten sam fragment zwiększa k i n (`tests/api/test_api_agreement.py`) |
| 2 | rozszerzająca (dodaje warunek lub zakres) | nie: wymaga relacji `extends` (rozdział 7) |
| 3 | sprzeczna z literaturą przy tym samym zakresie | nie: wymaga porównania z `chunks` (rozdział 7) |
| 4 | pozornie sprzeczna, inny zakres | częściowo: grupowanie jest po pozycji w tekście, więc inne fragmenty nie dostają wspólnej flagi; zakres populacji/typu tekstu jako filtr nie jest zrobiony |
| 5 | nowa, bez pokrycia | **tak**: fragment zaznaczony przez jednego eksperta ma etykietę `single` (k = 1) |
| 6 | ekspert poprawia własną odpowiedź (zastąpienie) | nie: po ingestii brak ścieżki zmiany (rozdział 7) |
| 7 | wycofanie wkładu | **tak**: wycofanie zmniejsza k i n, grupa jedynego eksperta znika, pusta baza nie ma grup |
| 8 | para minimalna różniąca się negacją | **tak, jako pomiar**: cosinus I1 nie rozróżnia kierunku (rozdział 3, D9), dlatego kierunek liczymy z pola `direction`, a nie z podobieństwa |

Testy zgodności: rdzeń (`packages/expert-knowledge-core/tests/test_agreement.py`: grupowanie,
łańcuch, próg, jeden ekspert z dwoma zaznaczeniami, `mixed`, etykiety, niezależność od kolejności,
kontrola liczb), API (`tests/api/test_api_agreement.py`: ingestia tworzy grupy, wycofanie przelicza je
atomowo, ponowne przeliczenie jest idempotentne, uzupełnienie starszych danych, wyszukiwanie Nadzorcy
zwraca zgodność), pakiet (`test_documents.py`, `test_crowded_vignette.py`: notatka grupowa, wybór
głosów, brak zmian dla jednostek case, powrót do zwykłej notatki przy nieczytelnym rekordzie),
ewaluacja (`tests/scripts/test_eval_agreement.py`: α na przykładzie Krippendorffa).

Metryki do Z6: **poprawność stanu bazy po scenariuszu** (asercje na `fragment_groups`: liczniki,
mianownik, etykieta), **wierność liczb** (`agreement_claims`: odsetek zdań z „k z n” zgodnych z
cytowaną notatką; jeszcze niemierzona na odpowiedziach modelu) oraz **zgodność ekspertów** (α z
przedziałem).

## 7. Czego ten dokument jeszcze nie rozstrzyga

Poniższe elementy pierwotnego założenia **nie są zaprojektowane ani zaimplementowane** i wymagają
decyzji autora, zanim wejdą do pracy:

1. **Cykl życia po ingestii i aktualizacja.** Dziś `ingested` jest stanem końcowym, a ponowne
   przesłanie tej samej wersji winiety przez tego samego eksperta jest zablokowane indeksem
   `uq_assignments_active`. Brak `supersedes`, `valid_from`, `superseded_by` i zapisu
   append-only. To jest główna luka w Z6 („aktualizacja”): scenariusz 6.
2. **Tabela relacji** (`consistent`, `extends`, `contradicts`, `novel`, `supersedes`, `duplicate`)
   z pochodzeniem propozycji i decyzją Nadzorcy. Dziś jedyną relacją jest zgodność ekspertów (D1–D5),
   liczona deterministycznie i bez decyzji człowieka.
3. **Relacje ekspert ↔ literatura** (scenariusze 2–4): porównanie jednostki z `chunks` przez
   wyszukiwanie hybrydowe, klasyfikacja relacji i zakres jako filtr fałszywych sprzeczności.
   Rekomendacja z rozmowy: opisać jako kierunek rozwoju; kosztowne i trudne do oceny
   (odsetek fałszywych sprzeczności).
4. **Pełne usunięcie danych eksperta (RODO).** Wycofanie usuwa dane z indeksu, ale tekst zostaje w
   `app.knowledge_units`, `submissions`, `answer_revisions`, `answer_findings`, komentarzach i
   decyzjach.
5. **Ewaluacja generacji** z nowym formatem notatki i promptem (skill `rag-eval`), w tym wierność
   liczb. Do tego czasu `group_fragments` zostaje wyłączone.
6. **Pomiar zatłoczenia top-k** po włączeniu grupowania na `chips_scale` (wymaga zasilenia grup w tym
   schemacie).
7. **Trzy tabele historyczne** (`unit_decisions`, `unit_comments`, `submission_votes`) zostały po
   migracji 0006 bez modeli; alembic je pomija (`HISTORY_TABLES`). Warto zdecydować, czy je usunąć.
