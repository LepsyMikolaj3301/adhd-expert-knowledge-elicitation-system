---
title: Dokumentacja
diataxis: index
---

# Dokumentacja

Język: **Polski** · [English](../eng/index.md)

Dokumentacja platformy wiedzy eksperckiej: aplikacji webowej i API, które zbierają odpowiedzi ekspertów na winiety przypadków, poddają je korekcie i recenzji koleżeńskiej, a zatwierdzone zamieniają w przeszukiwalne jednostki wiedzy. Strony są pogrupowane według typu.

## Tutoriale

- [Uruchomienie stosu lokalnie](tutorials/run-the-stack-locally.md) - uruchom bazę danych, API i aplikację webową przez Docker Compose, wykonaj pierwsze żądanie API, utwórz konto administratora i zaloguj się.

## Przewodniki how-to

- [Jak uruchomić testy i sprawdzenia](how-to/run-tests-and-checks.md) - uruchom testy backendu, testy frontendu, lintery i sprawdzanie typów, z bazą danych lub bez niej.
- [Jak wdrożyć na VM Azure](how-to/deploy-to-azure-vm.md) - jednorazowo skonfiguruj VM Azure, udostępnij na niej Ollama i LanguageTool z komputera PC, wdróż wydanie, uruchamiaj i zatrzymuj VM oraz twórz kopię zapasową jej bazy danych skryptami z `infra/`.

## Referencja

- [Rdzeń backendu i powierzchnia API](reference/backend-core-api.md) - aplikacja FastAPI pod `/api/v1`, ustawienia, baza danych i obsługa błędów, auth, users, home, audit, sonda gotowości, klienci Ollama, loader promptów i CLI operatora.
- [Przydziały i zadania w backendzie](reference/backend-assignments-jobs.md) - trasy przepływu pracy każdego eksperta, maszyna stanów, ładunki odpowiedzi, kolejka zadań w Postgresie, handlery zadań i proces workera.
- [Recenzje koleżeńskie w backendzie](reference/backend-reviews.md) - trasy recenzji, reguły dostępu do zgłoszeń oraz tabele uczestników, komentarzy, głosów i decyzji.
- [Winiety i wiedza w backendzie](reference/backend-vignettes-knowledge.md) - endpointy administratora dla wersji winiet i zestawu pytań oraz dla jednostek wiedzy, wraz z regułami walidacji.
- [Indeksowanie i korekta w backendzie](reference/backend-indexing-proofread.md) - konfiguracja indeksowania i embedder oraz kroki korekty, powiązań i edycji ze zgłoszeniem odpowiedzi.
- [Pakiety expert-knowledge-core i expert-knowledge-rag](reference/packages.md) - wektory rzadkie BM25, pakowanie notatek, stałe wyszukiwania oraz retrievery i łańcuchy tylko do odczytu nad schematem `chips`.
- [Powłoka aplikacji frontendu](reference/frontend-app.md) - start, trasy, guard tras, obsługa sesji, klient API, store'y, widoki, stałe oraz konfiguracja Vite, Vitest i ESLint.
- [Komponenty frontendu i helpery odpowiadania](reference/frontend-components.md) - komponenty Vue z ich props i zdarzeniami oraz moduły TypeScript za ekranami odpowiadania i recenzji.
- [Środowisko uruchomieniowe i wdrożenie](reference/runtime-and-deploy.md) - lokalny plik compose i plik compose VM Azure, Dockerfile, konfiguracja bazy danych i migracje, pliki promptów oraz skrypty.

## Wyjaśnienia

- [O architekturze](explanation/architecture.md) - system na trzech poziomach (kontekst, kontenery, komponenty) i wartości, które muszą być zgodne między częściami.
- [O cyklu życia przydziału](explanation/assignment-lifecycle.md) - jak maszyna stanów, kolejka zadań w Postgresie i recenzja zamykana przez administratora prowadzą przydział od przydzielenia do ingestu.
- [O wyszukiwaniu i indeksowaniu](explanation/retrieval-and-indexing.md) - dlaczego spostrzeżenia ekspertów są przechowywane z wektorem gęstym i rzadkim BM25 oraz dlaczego pakiet core i pakiet wyszukiwania tylko do odczytu są osobne.

## Źródła w kodzie

- `backend/pyproject.toml` - metadane pakietu backendu: nazwa rag-backend, zależności, biblioteki workspace
- `frontend/package.json` - metadane pakietu frontendu, skrypty i wersja Node
- `docker-compose.yml` - lokalny stos opisany w tutorialu i na stronach referencji
