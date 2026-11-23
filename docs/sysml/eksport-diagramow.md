# Eksport diagramów do pracy (wtyczka SysML v2 dla VS Code)

Otwórz ten plik w VS Code (jasny motyw), potem `Ctrl+Shift+P` → **SysML: Export Markdown Diagrams to SVG**
i zapisz jako `eksport-diagramow.export.md` obok. SVG trafią do `eksport-diagramow.export.diagrams/diagram-N.svg`
w kolejności bloków poniżej.

Wtyczka renderuje tylko jeden plik modelu, więc model musi być sklejony (jak w `push.sh`).
Po każdej zmianie w `src/model/` uruchom w `docs/sysml/`: `cat src/model/*.sysml > build/model.sysml`
(`build/` jest w `.gitignore` i pomijany przez skan workspace'u wtyczki, więc nie dubluje definicji).

1. kontekstSystemu → ibd-kontekst-systemu.svg

```sysmlv2-view
model: build/model.sysml
view: kontekstSystemu
```

2. przypadkiUzycia → uc-przypadki-uzycia.svg

```sysmlv2-view
model: build/model.sysml
view: przypadkiUzycia
```

3. strukturaSystemu → bdd-struktura-systemu.svg

```sysmlv2-view
model: build/model.sysml
view: strukturaSystemu
```

4. strukturaApi → bdd-struktura-api.svg

```sysmlv2-view
model: build/model.sysml
view: strukturaApi
```

5. strukturaWorkera → bdd-struktura-workera.svg

```sysmlv2-view
model: build/model.sysml
view: strukturaWorkera
```

6. wnetrzeSystemu → ibd-wnetrze-systemu.svg

```sysmlv2-view
model: build/model.sysml
view: wnetrzeSystemu
```

7. procesBiznesowy → act-proces-biznesowy.svg

```sysmlv2-view
model: build/model.sysml
view: procesBiznesowy
```

8. modelDanych → bdd-model-danych.svg

```sysmlv2-view
model: build/model.sysml
view: modelDanych
```

9. stanyPrzydzialu → stm-stany-przydzialu.svg

```sysmlv2-view
model: build/model.sysml
view: stanyPrzydzialu
```

10. stanyZadania → stm-stany-zadania.svg

```sysmlv2-view
model: build/model.sysml
view: stanyZadania
```

11. sekwencjaSesjiElicytacji → seq_sekwencja_elicytacji.svg

```sysmlv2-view
model: build/model.sysml
view: sekwencjaSesjiElicytacji
```
