# Ewaluacja końcowa: retrieval i generacja

Stan na 2026-11-22. Wszystkie liczby są **silver**: winiety, odpowiedzi „ekspertów”, pytania i
etykiety są syntetyczne (pisane przez modele językowe, nieprzejrzane przez klinicystów). To wyniki
rozwojowe, nie wynik kliniczny. Dokument zbiera dwa aspekty badawcze pracy:

1. **Architektury RAG** dla wiedzy eksperckiej (jak reprezentować i wyszukiwać odpowiedzi
   klinicystów): podsumowanie wcześniejszych eksperymentów i pomiar obecnego systemu na
   istniejących i nowych zapytaniach.
2. **Generacja** odpowiedzi z odebranych jednostek przez modele średnie (karta 24 GB VRAM) i małe
   (karta 8 GB VRAM).

Przed każdą tabelą jest opis, co dokładnie zrobiono.

---

## 1. Metodyka i dane

### 1.1 Korpus wiedzy

- **Winiety**: 24 krótkie teksty dorosłych pacjentów (wpis w dzienniku, e-mail, post na forum),
  każdy zbudowany z zaplanowanymi sygnałami cech (np. `task_initiation`, `time_estimation`,
  `working_memory`) i alternatywnymi wyjaśnieniami (sen, nastrój, stres, kofeina); część to
  kontrole bez sygnałów.
- **Eksperci**: 32 syntetycznych klinicystów. SYN-001/002 pisał Claude Sonnet, 3–20 lokalny qwen
  z jednolinijkową personą, 21–32 gpt-oss:20b, mistral-small3.2:24b i qwen3.8:27b z osobnymi plikami
  person (różny styl pisania i cytowania). Każdy odpowiadał na pytania elicytacji: Q1 (które
  fragmenty są ważne i w którą stronę), Q2 (co innego mogłoby je wyjaśnić), Q3 (czego brakuje), Q5
  (co przeczyta źle mniej doświadczony klinicysta), z zaznaczeniami fragmentów (chipy `⟦hN⟧`).
- **Proofreading**: wszystkie odpowiedzi przeszły przez pipeline aplikacji (LanguageTool +
  qwen3.5:9b, `Answer_enhance.v2`).
- **Jednostki**: odpowiedzi pocięte na jednostki „fragment” (zdania przypisane do zaznaczonego
  fragmentu winiety) i „case” (ocena całości), z nagłówkiem (rola klinicysty, rodzaj tekstu),
  wektorem bge-m3 i wektorem BM25. Grupy zgodności łączą zaznaczenia różnych klinicystów, które
  nachodzą na ten sam fragment (IoU ≥ 0,5).
- **Schematy Postgres** (budowane z `tests/fixtures/scale_answers` przy każdym teście, tak jak robi
  to aplikacja):
  - `chips_silver`: tylko SYN-001/002 (n = 2 ekspertów), 198 jednostek;
  - `chips_scale`: wszyscy 32 eksperci, 1830 jednostek, 310 grup zgodności.

### 1.2 Zestawy zapytań

| Zestaw | Liczba | Kto napisał i co widział | Etykiety (co powinno wrócić) |
|---|---|---|---|
| Istniejące pytania klinicysty | 40 | Claude, widząc winiety **i claimy** SYN-001/002 | oryginalne: claimy wskazane przy pisaniu; pooled: claimy potwierdzone przez agenta z top 8 kilku systemów |
| Istniejące teksty pacjenta | 9 | tekst winiety użyty jako tekst pacjenta (własna winieta wykluczona z wyszukiwania) | słabe: claimy o tej samej cesze z innych winiet |
| **Nowe pytania klinicysty** | 30 | Claude Sonnet, widząc tylko winiety, ich projekt i pytania elicytacji, **bez notatek ekspertów** | punkty kluczowe z jednostkami (oracle), patrz 1.3 |
| **Nowe teksty pacjenta** | 15 | j.w.; nowe sytuacje, 80–200 słów, bez nazw zaburzeń i leków | j.w. |
| **Pytania spoza zakresu** | 5 | j.w.; dawkowanie, progi skal, współchorobowość, bezpieczeństwo leków | brak (oczekiwana odmowa) |

Istniejące pytania pisano z claimów, więc mają przeciek słownictwa (pytanie parafrazuje to, co ma
znaleźć). Nowe pytania tego przecieku nie mają: autor nie widział notatek, a skrypt odrzuca pozycje,
które powtarzają 6 lub więcej kolejnych słów z winiety, i teksty pacjenta z terminami z
`leak_terms.py`. Wszystkie 50 nowych pozycji przeszło te kontrole bez poprawek.
Spośród 30 pytań klinicysty 18 jest „zakotwiczonych” (dotyczy zjawiska z konkretnej winiety, ale
sformułowane ogólnie), 12 przekrojowych (cecha lub konfuzor w wielu winietach).

### 1.3 Etykiety oracle dla nowych zapytań

1. **Pula kandydatów** (TREC-style pooling): dla każdej pozycji suma top 10 jednostek z sześciu
   systemów (hybrid, dense, bm25, każdy z grupowaniem fragmentów i bez) oraz do 20 jednostek
   „z projektu”: tych, których zaznaczenie nachodzi na fragment kotwicy lub na zaplanowany sygnał
   cech pozycji, najbliższe zapytaniu w bge-m3. Najwyżej 60 kandydatów, pokazanych w kolejności
   haszowanej (etykietujący nie widzi rankingu).
2. **Etykietowanie** (Claude Sonnet, 8 części po ~7 pozycji): etykietujący zapisuje **punkty
   kluczowe**, czyli to, co dobra odpowiedź powinna powiedzieć na podstawie not. Każdy punkt ma
   kierunek (`raises`/`lowers`/`neutral`/`mixed`), warunek, listę jednostek, które go niosą, i wagę
   (2 = odpowiada wprost, 1 = tło). Ocenia też, czy noty w ogóle pozwalają odpowiedzieć
   (`yes`/`partly`/`no`). Część 1 była przeetykietowana po tym, jak agent przyznał, że filtrował pulę
   słowami kluczowymi.
3. **Wynik**: 321 punktów kluczowych, średnio 6,5 na pytanie klinicysty i 8,5 na tekst pacjenta,
   ok. 9 jednostek na punkt (wielu klinicystów mówi to samo). Odpowiadalność: 29 `yes`,
   15 `partly`, 6 `no` (5 pytań spoza zakresu i C30 o hipomanii). Zapis:
   `tests/fixtures/final_eval/queries.json` (+ `manifest.json`), skrypt
   `scripts/rag/make_final_queries.py`, prompty `prompts/Final_eval_questions.v1.md` i
   `prompts/Final_eval_oracle.v1.md`.

Punkt kluczowy pełni rolę claimu: jest „odnaleziony”, gdy co najmniej jedna z jego jednostek jest w
wynikach. Dzięki temu metryki liczy ten sam kod co wcześniej (`scripts/rag/expert_metrics.py`).

### 1.4 Retriever i konfiguracje

Wyszukiwanie wyłącznie przez pakiet `expert-knowledge-rag` (to samo co aplikacja):
`ExpertQuestionRetriever` dla pytań, `PatientTextRetriever` dla tekstów pacjenta. Konfiguracje:

- `hybrid+group`: bge-m3 + BM25 łączone RRF, fragmenty zaznaczone przez kilku klinicystów złożone
  w jedną notę z linią zgodności (kandydat do produkcji);
- `hybrid`: to samo bez grupowania (dzisiejsza domyślna);
- `dense`, `bm25`: każda ścieżka osobno.

Ranking ma 10 not; jednostki sesji, które dzielą zdanie, są łączone w jedną notę (jak w aplikacji).

### 1.5 Metryki retrievalu

Wszystkie liczone po pytaniach, średnia z 95% przedziałem bootstrap (1000 prób); różnice
sparowane na tych samych pytaniach („≠0”: przedział nie obejmuje zera).

- **recall@k**: odsetek claimów / punktów kluczowych, z których co najmniej jedna jednostka jest
  w pierwszych k notach.
- **hit@4**: czy w top 4 jest cokolwiek trafnego.
- **MRR**: odwrotność pozycji pierwszej trafnej noty.
- **nDCG@10**: jakość kolejności pierwszych 10 jednostek (trafna jednostka = zysk 1).
- **recall@500t**: recall, gdy generator dostaje tyle not, ile zmieści się w 500 tokenach.
- **recall@4/ceiling**: recall@4 podzielony przez najlepszy możliwy recall 4 jednostek.
- **vignette precision@4**: odsetek not z top 4 pochodzących z winiety, która ma trafną jednostkę.
- **clinicians@4**: ilu różnych klinicystów niosą noty top 4.
- **tokens/note**: średni rozmiar noty.

Nota grupy pokazuje słowa najwyżej trzech klinicystów, a niesie identyfikatory wszystkich członków
grupy (do 32). Metryki liczone są więc w dwóch wariantach: `shown` (tylko jednostki, których słowa
są w nocie; główny wariant) i `carried` (wszystkie identyfikatory noty).

### 1.6 Ograniczenia

- Dane są syntetyczne; ten sam rodzaj modelu (Claude) pisał część ekspertów, pytania, etykiety i ocenia
  odpowiedzi, więc możliwe są wspólne ślepe plamki.
- Etykiety z poolingu faworyzują systemy, które były w puli; systemy spoza puli byłyby niedoszacowane.
- Na `chips_scale` oryginalne etykiety 40 pytań obejmują tylko claimy SYN-001/002, więc są dolną
  granicą (inni eksperci mówią to samo, ale nie są oznaczeni).

---

## 2. Aspekt 1: architektury RAG (wcześniejsze eksperymenty)

**Co zrobiono.** Każdy wiersz to osobny eksperyment z wcześniejszych notatek; liczby przepisane z
nich, nie liczone ponownie (dane wejściowe starych reprezentacji nie są już w `data/`). Wszystkie na
silver, z etykietami pooled i 95% przedziałami bootstrap. Różnica jest „realna”, gdy przedział
sparowany nie obejmuje zera.

| Pytanie badawcze | Porównanie | Wynik | Źródło |
|---|---|---|---|
| Jak reprezentować odpowiedź eksperta? | A surowe odpowiedzi, B jednostki dosłowne, B1 jednostki „lean”, C reguły z LLM, D/D1 jednostki + klucze z LLM (40 pytań, qwen3.5:9b, Haiku) | Nic nie bije B ponad szum (B: recall@4 0,218, nDCG@10 0,590, hit@4 1,00); klucze i reguły z LLM nie pomagają; `cap`/`mmr` obniżają nDCG. Wybrano B1 (bez LLM przy indeksowaniu). | [expert-knowledge.md](expert-knowledge.md), 2026-11-01 |
| Generacja: jednostki czy reguły? | ten sam generator 9B na kontekście jednostek / reguł / oracle / bez not | jednostki ≥ reguły (pass +0,20, na granicy szumu); oracle nie lepszy od jednostek → ograniczeniem jest generator 9B, nie retrieval | j.w. |
| Wolny tekst z chipami (I1) zamiast regexowych jednostek (B1)? | 14 nowych winiet, 2 ekspertów, 40 pytań | pytania: I1 − B1 recall@4 **+0,14** [+0,08, +0,21], nDCG@10 **+0,12**; merge jednostek sesji **+0,11** recall; teksty pacjenta: brak zysku (9 zapytań, słabe etykiety); downweighting bez efektu | [chips-test-findings.md](chips-test-findings.md), 2026-11-04 |
| Czy silniejszy generator pomaga? | qwen3.5:9b vs qwen3.6:35b-a3b na tych samych notach, 2 przejścia Sonnet | 35b: fidelity **+0,5**, attribution **+0,3–0,4**, oracle pass 0,57–0,65 vs 0,30; na prawdziwym retrievalu pass nie wyraźnie wyższy | j.w. |
| Co się dzieje przy wielu ekspertach? | 1–32 ekspertów na winietę (`chips_scale`) | tłok (crowding@8) dochodzi do ~0,5 od n ≈ 10; tłok robią głównie noty `case`; downweighting nic nie zmienia (odpowiedzi różnych ekspertów nie są prawie-duplikatami); grupowanie fragmentów zmniejsza tłok i mieści wielokrotnie więcej klinicystów w tych samych 8 notach | [downweighting-do-przegladu.md](downweighting-do-przegladu.md), 2026-11-21 |

Obecny system to wynik tych decyzji: jednostki chips (I1) z merge, hybryda bge-m3 + BM25 (RRF),
opcjonalnie grupowanie fragmentów. Części 3–5 mierzą go na końcowym kodzie.

## 3. Obecny system na istniejących zapytaniach

**Co zrobiono.** 40 istniejących pytań klinicysty i 9 istniejących tekstów pacjenta wyszukano
pakietem w czterech konfiguracjach (1.4), na `chips_silver` (2 ekspertów) i `chips_scale`
(32 ekspertów). Metryki według 1.5, wariant `shown`. Komenda:
`python scripts/rag/eval_final_retrieval.py --run-dir data/eval/final/20261122-retrieval --questions tests/fixtures/final_eval/queries.json`
(pełny raport ze wszystkimi metrykami: `data/eval/final/20261122-retrieval/report.md`).

**40 pytań, etykiety pooled** (claimy SYN-001/002):

| Konfiguracja | n=2 recall@4 | n=2 nDCG@10 | n=2 hit@4 | n=32 recall@4 | n=32 nDCG@10 | n=32 hit@4 |
|---|---|---|---|---|---|---|
| hybrid+group | 0,461 [0,39, 0,55] | 0,600 [0,52, 0,69] | 0,95 | 0,247 [0,18, 0,32] | 0,296 [0,22, 0,38] | 0,68 |
| hybrid | 0,450 [0,39, 0,53] | 0,606 [0,53, 0,68] | 0,95 | 0,213 [0,15, 0,30] | 0,285 [0,21, 0,37] | 0,65 |
| dense | 0,372 [0,30, 0,45] | 0,500 [0,42, 0,58] | 0,90 | 0,124 [0,07, 0,19] | 0,186 [0,12, 0,26] | 0,40 |
| bm25 | 0,356 [0,28, 0,44] | 0,483 [0,40, 0,56] | 0,83 | 0,184 [0,12, 0,26] | 0,261 [0,19, 0,35] | 0,60 |

- **Hybryda jest najlepsza**: dense − hybrid recall@4 −0,08 (n=2) i −0,09 (n=32), nDCG −0,10,
  przedziały poniżej zera; bm25 − hybrid na n=2 też poniżej zera.
- **Grupowanie** na n=2 nic nie zmienia (dwóch ekspertów rzadko tworzy grupę); na n=32 daje
  recall@4 **+0,035** [+0,00, +0,07], nDCG w granicach szumu.
- Spadek n=2 → n=32 (0,45 → 0,21) to głównie efekt etykiet: na `chips_scale` oznaczone są tylko
  claimy 2 z 32 ekspertów, a inni eksperci mówiący to samo zajmują miejsca w top 4 (dolna granica,
  1.6). Część 4 mierzy to samo z etykietami obejmującymi wszystkich ekspertów.
- Oryginalne etykiety dają ten sam obraz (n=2: hybrid recall@4 0,519, hybrid+group 0,555; n=32:
  0,296 i 0,351).

**9 istniejących tekstów pacjenta** (słabe etykiety): recall@4 ≤ 0,05 we wszystkich
konfiguracjach, hit@4 0,22–0,56. Ten tryb na tych etykietach nie jest mierzalny: winieta jako tekst
pacjenta + „wszystkie claimy o tej samej cesze” to zbyt luźna definicja trafności. Dlatego w części 4
są nowe teksty pacjenta z punktami kluczowymi.

Uwaga do porównań z wcześniejszymi runami: `chips_silver` przebudowano z obecnego fixture'a
(`tests/fixtures/scale_answers`); claim recall@4 hybrydy na 40 pytaniach to teraz 0,515, a w runie
`20261117-langchain-silver-27b` było 0,568. Różnica pochodzi ze zmiany danych/kodu między tymi dniami,
nie z ewaluacji (ten sam pomiar przez `try_expert_rag` i przez nowy skrypt daje 0,515 i 0,519).

## 4. Nowe zapytania bez przecieku (główny wynik retrievalu)

**Co zrobiono.** 30 nowych pytań klinicysty i 15 nowych tekstów pacjenta (1.2) wyszukano na
`chips_scale` (32 ekspertów) w czterech konfiguracjach. Trafność = punkty kluczowe z etykiet oracle
(1.3); recall@4 to odsetek punktów kluczowych pytania, które ma co najmniej jedna z pierwszych
4 not. Pytanie C30 (hipomania) ma etykietę `no` (brak punktów) i nie wchodzi do średnich, stąd n=29.

**Pytania klinicysty** (n=29):

| Konfiguracja | recall@4 | recall@8 | hit@4 | MRR | nDCG@10 | recall@500t | tokeny / nota | klinicyści w top 4 |
|---|---|---|---|---|---|---|---|---|
| hybrid+group | **0,783** [0,72, 0,84] | 0,907 | 1,00 | 0,95 | 0,709 [0,62, 0,79] | 0,443 [0,35, 0,52] | 406 | 13,8 |
| hybrid | 0,703 [0,64, 0,77] | 0,812 | 1,00 | 0,93 | 0,720 [0,65, 0,79] | **0,515** [0,43, 0,58] | 258 | 3,8 |
| dense | 0,630 [0,54, 0,71] | 0,795 | 0,97 | 0,90 | 0,681 [0,60, 0,76] | 0,470 [0,40, 0,53] | 241 | 3,7 |
| bm25 | 0,593 [0,49, 0,69] | 0,742 | 0,93 | 0,85 | 0,606 [0,50, 0,70] | 0,428 [0,33, 0,53] | 229 | 3,5 |

**Nowe teksty pacjenta** (n=15):

| Konfiguracja | recall@4 | hit@4 | MRR | nDCG@10 | recall@500t | tokeny / nota |
|---|---|---|---|---|---|---|
| hybrid+group | **0,465** [0,35, 0,60] | 1,00 | 0,76 | 0,540 [0,38, 0,69] | 0,183 | 414 |
| hybrid | 0,379 [0,27, 0,51] | 0,93 | 0,69 | 0,566 [0,41, 0,72] | 0,201 | 253 |
| dense | 0,190 [0,11, 0,28] | 0,73 | 0,69 | 0,569 [0,38, 0,76] | 0,147 | 177 |
| bm25 | 0,244 [0,17, 0,33] | 0,87 | 0,73 | 0,465 [0,34, 0,58] | 0,177 | 182 |

Różnice sparowane (względem `hybrid`):
- hybrid+group: recall@4 **+0,080** [+0,04, +0,12] (klinicysta), **+0,086** [+0,02, +0,15]
  (pacjent); nDCG@10 w granicach szumu (−0,01 i −0,03).
- dense: recall@4 **−0,07** (klinicysta) i **−0,19** (pacjent); bm25: **−0,11** i **−0,14**.

Co to znaczy:
1. **Retrieval działa na pytaniach, których autor nie widział notatek.** Przy 4 notach w każdym
   pytaniu klinicysty jest coś trafnego (hit@4 = 1,00), pierwsza trafna nota jest zwykle na 1. miejscu
   (MRR 0,93–0,95), a 70–78% punktów kluczowych jest w top 4. Wyniki są wyższe niż na starych
   pytaniach, bo etykiety obejmują wszystkich 32 ekspertów (nie tylko 2) i punkty kluczowe łączą
   jednostki mówiące to samo. Część tej przewagi to też efekt poolingu (etykietowano kandydatów z tych
   samych retrieverów, 1.6).
2. **Teksty pacjenta są trudniejsze** (recall@4 0,38–0,47 wobec 0,70–0,78): tekst pacjenta opisuje
   sytuację, a noty mówią o innych tekstach; trafność wymaga przeniesienia odczytu. Nowe etykiety
   pokazują jednak, że ten tryb działa (hit@4 0,93–1,00), czego nie dało się zobaczyć na starych,
   słabych etykietach.
3. **Grupowanie: więcej treści w 4 notach, mniej w 500 tokenach.** Nota grupy jest ~1,6 razy dłuższa
   (406 vs 258 tokenów), więc przy stałej liczbie not podnosi recall (+0,08), ale przy stałym budżecie
   tokenów hybryda bez grupowania jest lepsza (recall@500t 0,515 vs 0,443). Dla generatora z kontekstem
   8k tokenów i k = 4 notami liczy się pierwsze; część 6 sprawdza, czy dłuższe noty nie szkodzą
   odpowiedziom.
4. **Pytania spoza zakresu**: najbliższa jednostka ma cosine bge-m3 0,46–0,67 (średnio 0,55), pytania
   w zakresie 0,57–0,72 (średnio 0,64). Rozkłady na siebie zachodzą, więc progu podobieństwa nie
   da się użyć do odrzucania pytań spoza bazy; musi to robić generator (część 6).

## 5. Skala: wielu ekspertów

**Co zrobiono.** `eval_scale_retrieval.py` (bez zmian w skrypcie) buduje osobny schemat ze wszystkich
32 ekspertów i ocenia pule pierwszych n ekspertów (n = 1, 2, 5, 10, 15, 20, 25, 32), filtrując po
ekspertach. Pytania: 40 istniejących (bez filtra winiety), pytania „topic” per winieta i 3 stałe
pytania per winieta ograniczone do tej winiety (przypadek „wielu ekspertów o jednym tekście”) na
4 winietach-kotwicach z 32 ekspertami. Wyniki:
`data/eval/scale_retrieval/20261122-final/report.md`.

| n | crowding@8 bez grupowania | crowding@8 z grupowaniem | klinicyści w top 8 bez / z grupowaniem | pokrycie ekspertów@8 | oryg. recall@4 (40 pytań) | precyzja winiety@4 |
|---|---|---|---|---|---|---|
| 2 | 0,29 | 0,13 | 2,0 / 2,0 | 1,00 | 0,49 | 0,68 |
| 5 | 0,45 | 0,38 | 4,5 / 5,0 | 0,90 | 0,47 | 0,69 |
| 10 | 0,51 | 0,46 | 6,5 / 9,3 | 0,81 | 0,39 | 0,64 |
| 20 | 0,52 | 0,48 | 7,3 / 17,5 | 0,91 | 0,30 | 0,69 |
| 32 | 0,47 | 0,38 | 7,4 / 29,6 | 0,93 | 0,30 | 0,68 |

- **crowding@k**: odsetek not w top k, które powtarzają fragment już obecny na liście. Przekracza
  0,5 przy k = 8 od n = 10. Grupowanie obniża go na każdym n (0,47 → 0,38 przy n = 32) i sprawia, że
  8 not niesie słowa 29,6 zamiast 7,4 klinicystów.
- **Precyzja winiety** nie spada z liczbą ekspertów (0,64–0,69): więcej ekspertów nie wypycha
  właściwego tekstu.
- **Oryginalny recall** spada o ćwierć do n = 10–15. To dolna granica (etykiety tylko 2 ekspertów);
  część 4 pokazuje, że z etykietami wszystkich ekspertów recall przy n = 32 jest wysoki.
- Downweighting nadal nic nie zmienia (tabele „on” i „off” identyczne).
- Czas wyszukiwania w bazie: p50 28–35 ms, p95 ≤ 52 ms przy 1830 jednostkach.

## 6. Aspekt 2: generacja na modelach średnich i małych

_(uzupełniane po teście generacji)_
