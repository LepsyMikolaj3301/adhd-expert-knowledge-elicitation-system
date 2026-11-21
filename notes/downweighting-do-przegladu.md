# Downweighting a grupowanie fragmentów: wyniki pomiaru

Zmierzone 2026-11-21 na danych scale (32 ekspertów), `tests/integration/test_scale_regression.py`,
baseline `tests/fixtures/retrieval_scale/baseline.json`. Logika produkcyjna bez zmian
(`group_fragments` nadal domyślnie wyłączone, backend nietknięty).

## Co dodano do pomiaru

- Ewaluacja skali liczy pytania `fixed` w czterech wariantach: downweighting {on, off} × grupowanie
  fragmentów {off, on}. Grupy zgodności są przeliczane **dla puli** (n = 2, 10, 20, 32), więc nota
  liczy tylko ekspertów puli (`chips_fixture.set_agreement_pool`, `fit_agreement(experts=...)`).
- `groups_match_filter=True` w retrieverze pozwala na grupowanie przy `filter.experts` (tylko dla
  ewaluacji, domyślnie `False`).
- Tłok rozbity na tłok z powtórzonych fragmentów i z not `case`, plus tłok liczony po grupach zgodności
  (`crowding_passage`: ten sam fragment zaznaczony innymi słowami to jedno miejsce).

## Wyniki (anchory V001/V004/V006/V012, średnie po 12 pytaniach)

crowding@8, downweighting włączony:

| n | bez grupowania | z grupowaniem | po grupach, bez | po grupach, z |
|---|---|---|---|---|
| 2 | 0.290 | 0.125 | 0.378 | 0.167 |
| 10 | 0.510 | 0.458 | 0.646 | 0.542 |
| 20 | 0.521 | 0.479 | 0.656 | 0.542 |
| 32 | 0.469 | 0.375 | 0.625 | 0.417 |

Z czego składa się tłok bez grupowania (k=8): z powtórzonych fragmentów 0.14 / 0.12 / 0.09 (n = 10 / 20 / 32),
z powtórzonych not `case` 0.38 / 0.41 / 0.38. Noty `case` to 50–53% top 8.

## Odpowiedzi na pytania z poprzedniej wersji notatki

1. **Downweighting nie robi nic na scale.** Krzywe on i off są identyczne w każdym punkcie, także z
   grupowaniem. Przyczyna: cosine między odpowiedziami `case` różnych ekspertów do jednej winiety ma
   medianę 0.74, p90 0.81, a 2 z 2500 par przekracza 0.9 (obie w V018, nie ma ich na anchorach).
   Przypięte testem `test_case_answers_of_different_experts_are_almost_never_near_duplicates`.
2. **Hipoteza „tłok tworzą fragmenty” była błędna.** Na anchorach to noty `case` (patrz rozbicie wyżej).
   Grupowanie fragmentów i tak pomaga (tabela), ale `case` zostaje nietknięte.
3. **Dlaczego `case` nie jest grupowane:** grupy zgodności łączą highlighty po nakładaniu spanów
   (IoU ≥ 0.5 w tekście winiety). Jednostka `case` nie ma highlightu ani spanu, więc nie ma klucza.
   Nie da się też użyć podobieństwa treści, bo odpowiedzi `case` nie są prawie duplikatami (pkt 1).
   Jedyny naturalny klucz to winieta. Uwaga do metryki: odpowiedzi `case` różnych ekspertów różnią się
   treścią, więc „powtórzone noty `case`” to raczej wiele ogólnych ocen jednej winiety niż duplikaty;
   `crowding` traktuje je jako powtórzenie, bo oba mają klucz `case:<winieta>`.
4. **Luka 3 zamknięta:** `build_documents` składa trafienia grupy w jedną notę na miejscu najlepszego,
   a `[:k]` liczy noty. Przypięte testem `test_the_other_hits_of_a_group_take_no_places_in_the_top_k`.
5. **Co zwolniłoby grupowanie `case` per winieta** (symulacja, bez implementacji; `case_freed`):
   1.0–1.25 miejsca z 4 i 3.0–3.25 z 8 na anchorach przy n ≥ 10.

## Uwagi do metryk

- Przy n = 2, k = 4 grupowanie wygląda gorzej po tekście (0.146 vs 0.083): nota grupy niesie słowa kilku
  ekspertów, więc częściej pokrywa się z następną. Po grupach zgodności jest remis (0.146).
- `expert_coverage` liczy pierwszego eksperta noty, więc nota grupy nie dostaje punktów za pozostałych;
  spadek do 0.76–0.85 (z 0.81–0.94) jest artefaktem. Liczba klinicjanów, których słowa niesie top k
  (`clinicians_anchor`): k=8 przy n = 32 rośnie z 7.4 do 29.6.

## Do decyzji

- Włączyć `group_fragments` w backendzie (`backend/app/knowledge/search.py`)? Pomiar to wspiera
  (mniej tłoku, wielokrotnie więcej klinicjanów w tej samej liczbie not), ale pozostaje pytanie o
  generację (grupa to dłuższa nota z linią zgodności) i nie ma jeszcze oceny jakości odpowiedzi.
- Usunąć `downweight_duplicate_cases` (nic nie robi na tych danych), czy zostawić na wypadek prawdziwych
  kopii? Test `test_down_weighting_changes_nothing_on_these_answers` przypina dzisiejszy stan.
- Czy grupować noty `case` per winieta (pkt 5), czy zostawić jako odrębne oceny ekspertów.

## Pokrewne (ten sam obszar rankingu)

W trybie pacjenta `CONTEXT_BONUS` (0.5) przeważa dokładne dopasowanie, bo wyniki RRF przy
`RRF_K = 60` są prawie płaskie. Fragment z V003 podany dosłownie trafia na 5. miejsce, a wyżej
są niezwiązane jednostki z V010. Zapisane jako strict `xfail` w `tests/integration/test_ingest_e2e.py`.
