# System pozyskiwania wiedzy eksperckiej o ADHD

Język: **Polski** · [English](README.md)

Platforma webowa, która zbiera pisemne odpowiedzi ekspertów na winiety przypadków, poddaje je korekcie i recenzji koleżeńskiej, a zatwierdzone zamienia w przeszukiwalne jednostki wiedzy. Składa się z jednostronicowej aplikacji Vue (wyświetlanej jako "PsyKnowHow"), backendu FastAPI pod `/api/v1`, workera w tle wykonującego powolne kroki, bazy PostgreSQL z pgvector oraz Ollama i LanguageTool dla modeli językowych i sprawdzania gramatyki.

## Szybki start

Lokalny stos działa z Docker Compose z katalogu głównego repozytorium. Usługa `ollama` rezerwuje karty NVIDIA GPU, więc host musi je mieć.

```bash
cp .env.example .env
docker compose --profile app up -d --build rag-backend frontend
curl http://localhost:8000/api/v1/health
```

Pierwsze polecenie kopiuje lokalne wartości domyślne, drugie buduje i uruchamia API, aplikację webową i usługi, od których zależą, a trzecie wywołuje endpoint health API. Aplikacja webowa jest pod `http://localhost:5173`. Tutorial dodaje konto administratora i logowanie.

## Dokumentacja

- [Indeks dokumentacji](docs/pl/index.md)
- [Tutorial: uruchomienie stosu lokalnie](docs/pl/tutorials/run-the-stack-locally.md)
- [O architekturze](docs/pl/explanation/architecture.md)

## Źródła w kodzie

- `backend/pyproject.toml` - nazwa backendu rag-backend, opis i zależności
- `frontend/package.json` - skrypty frontendu i wersja Node
- `frontend/src/site.ts` - SITE_NAME wyświetlane w aplikacji webowej
- `backend/app/main.py` - tytuł API, prefiks i endpoint health
- `docker-compose.yml` - usługi, profile, porty i rezerwacja GPU przez ollama
- `.env.example` - lokalne wartości domyślne kopiowane do .env
