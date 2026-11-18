package PlatformaElicytacji {
    doc /*
     * Platforma wykonawcza i alokacje (SysML nie ma diagramu wdrożenia - zastępuje go struktura
     * platformy + «allocate»).
     *   PlatformaDev               - usługi docker-compose (środowisko deweloperskie i komputer z modelami)
     *   PlatformaProd              - maszyna wirtualna Azure (jeden projekt compose) + komputer
     *                                właściciela z modelami, połączone siecią Tailscale
     *   PlatformaCiCd              - GitHub Actions (CI, Deploy) i rejestr obrazów ghcr.io
     *   SrodowiskoTestowe          - gdzie i które testy działają (CI bez bazy, lokalnie z bazą)
     *   WdrozenieWydania           - czynność: od przycisku "Run workflow" do testu dymnego
     *   AlokacjaDev / AlokacjaProd - oprogramowanie -> węzły
     *   AlokacjaCzynnosci          - czynności -> wykonawcy (tory na diagramie act)
     * Do 2026-11-17 produkcją był Render (dwa kontenery) + Neon (Postgres); usunięte z kodu.
     */

    private import ScalarValues::*;
    private import ISQ::DurationValue;
    private import SI::*;
    private import BibliotekaElicytacji::*;
    private import KontekstElicytacji::kontekstElicytacji;
    private import CzynnosciElicytacji::*;

    // =================================================================== node definitions
    package Wezly {
        part def WezelKontenerowy {
            doc /* Kontener (obraz Dockera) uruchomiony na hoście. */
            attribute obraz : String;
            attribute wystawionyPort : Integer[0..*];
            attribute limitPamieciMB : Integer[0..1];        // mem_limit w compose
            attribute kontrolaZdrowia : String[0..1];        // healthcheck
        }

        part def MaszynaWirtualna {
            doc /*
             * Maszyna wirtualna Azure: Ubuntu Server 24.04, Standard_B2s (2 vCPU, 4 GB), dysk Standard
             * SSD 30 GB, swap 2 GB. setup-vm.sh: Docker, Tailscale, aktualizacje bezpieczeństwa,
             * anacron, katalog /opt/rag. Grupa NSG: tylko porty 80 i 443 z internetu (SSH przez Tailscale).
             */
            @OdwolanieDoKodu { sciezka = "infra/azure/setup-vm.sh"; }
            attribute rozmiar : String = "Standard_B2s";
            attribute pamiecGB : Integer = 4;
            attribute swapGB : Integer = 2;
            attribute dyskGB : Integer = 30;
            attribute otwartePorty : Integer[0..*] = (80, 443);
        }

        part def KomputerWlasciciela {
            doc /*
             * Komputer autora z GPU: Ollama i LanguageTool z głównego docker-compose.yml, porty
             * opublikowane tylko na 127.0.0.1; maszyna wirtualna dochodzi do nich przez
             * `tailscale serve` (adres PC_HOST w sieci Tailscale). Może być wyłączony - wtedy działa
             * bramka mocy obliczeniowej (REQUIRE_COMPUTE).
             */
            @OdwolanieDoKodu { sciezka = "docker-compose.yml"; }
        }

        part def SiecTailscale {
            doc /* Prywatna sieć (tailnet): VM (tag:vm), komputer właściciela, runner Deploy (tag:ci). */
            @OdwolanieDoKodu { sciezka = "docs/azure-setup-guide.md"; }
        }

        part def RejestrObrazow {
            doc /* ghcr.io/<właściciel>/<repozytorium>: obrazy backend i frontend, tagi sha-<7 znaków> i latest. */
            @OdwolanieDoKodu { sciezka = ".github/workflows/deploy.yml"; }
        }

        part def RunnerGithubActions {
            doc /* Maszyna GitHub Actions (ubuntu-24.04), uruchamiana ręcznie (workflow_dispatch). */
            @OdwolanieDoKodu { sciezka = ".github/workflows"; }
        }

        part def MaszynaDewelopera {
            doc /*
             * Maszyna autora: kontener dev (devcontainer), compose z Postgresem, testy z bazą
             * (`uv run pytest -m integration`) przed wdrożeniem zmian w backendzie.
             */
            @OdwolanieDoKodu { sciezka = ".devcontainer/Dockerfile"; }
        }
    }

    private import Wezly::*;

    // =================================================================== development platform
    part def PlatformaDev {
        doc /*
         * docker-compose.yml; profile: app, tools, browser, preview. Ollama i LanguageTool są
         * opublikowane tylko na 127.0.0.1 - ten sam compose działa na komputerze właściciela jako
         * dostawca modeli dla produkcji.
         */
        @OdwolanieDoKodu { sciezka = "docker-compose.yml"; }

        part ollama : WezelKontenerowy {
            attribute :>> obraz = "ollama/ollama";
            attribute :>> wystawionyPort = 11434;     // 127.0.0.1
        }
        part languagetool : WezelKontenerowy {
            attribute :>> obraz = "erikvl87/languagetool:6.8";
            attribute :>> wystawionyPort = 8010;      // 127.0.0.1
        }
        part postgres : WezelKontenerowy {
            doc /* Także bazy testów API: rag_<pid>_test, jedna na przebieg pytest, usuwana na końcu. */
            attribute :>> obraz = "pgvector/pgvector:pg16";
            attribute :>> wystawionyPort = 5432;
        }
        part pgadmin : WezelKontenerowy { attribute :>> obraz = "dpage/pgadmin4"; }          // profil tools
        part dev : WezelKontenerowy { attribute :>> obraz = ".devcontainer/Dockerfile"; }
        part migracja : WezelKontenerowy { attribute :>> obraz = "backend/Dockerfile"; }      // profil app
        part ragBackend : WezelKontenerowy { attribute :>> obraz = "backend/Dockerfile"; }   // profil app
        part worker : WezelKontenerowy { attribute :>> obraz = "backend/Dockerfile"; }       // profil app
        part frontend : WezelKontenerowy { attribute :>> obraz = "frontend/Dockerfile"; }    // profil app
        part playwright : WezelKontenerowy { attribute :>> obraz = "playwright/mcp"; }      // profil browser

        connect ragBackend to postgres;
        connect worker to postgres;
        connect worker to ollama;
        connect worker to languagetool;
        connect ragBackend to ollama;
        connect frontend to ragBackend;
        connect migracja to postgres;
        connect dev to postgres;
        connect dev to ollama;
        connect dev to languagetool;
    }

    // =================================================================== production platform
    part def PlatformaProd {
        doc /*
         * Przeglądarka --https--> Caddy :443 (certyfikat Let's Encrypt dla <etykieta>.<region>.cloudapp.azure.com)
         *   --> frontend (nginx: zbudowana aplikacja, przekazuje /api/) --> rag-backend (FastAPI)
         *   rag-backend, worker --> postgres (pgvector, niepublikowany)
         *   rag-backend, worker --Tailscale--> komputer właściciela: Ollama :11434, LanguageTool :8010
         * Ciasteczko sesji first-party, brak CORS. Środowisko w kontenerach API i workera:
         * REQUIRE_COMPUTE=true, ENVIRONMENT=production, COOKIE_SECURE=true, SESSION_TTL_HOURS=12.
         * Logi: json-file, 3 pliki po 10 MB na kontener.
         */
        @OdwolanieDoKodu { sciezka = "infra/azure/docker-compose.yml"; }

        part vm : MaszynaWirtualna {
            part caddy : WezelKontenerowy {
                doc /* TLS i reverse proxy do frontend:8080 (infra/azure/Caddyfile). */
                attribute :>> obraz = "caddy:2-alpine";
                attribute :>> wystawionyPort = (80, 443);
                attribute :>> limitPamieciMB = 64;
            }
            part frontend : WezelKontenerowy {
                attribute :>> obraz = "ghcr.io/.../frontend (infra/frontend.Dockerfile)";
                attribute :>> limitPamieciMB = 64;
                attribute :>> kontrolaZdrowia = "GET /healthz";
            }
            part ragBackend : WezelKontenerowy {
                doc /* Jeden proces uvicorn; ufa X-Forwarded-* (za nginx i Caddy). */
                attribute :>> obraz = "ghcr.io/.../backend (infra/backend.Dockerfile)";
                attribute :>> limitPamieciMB = 512;
                attribute :>> kontrolaZdrowia = "GET /api/v1/health";
            }
            part worker : WezelKontenerowy {
                doc /* Ten sam obraz co API; python -m app.jobs.worker. */
                attribute :>> obraz = "ghcr.io/.../backend (infra/backend.Dockerfile)";
                attribute :>> limitPamieciMB = 512;
                attribute :>> kontrolaZdrowia = "wiek /tmp/worker-alive <= 60 s";
            }
            part migracja : WezelKontenerowy {
                doc /* Jednorazowo: alembic upgrade head (schematy app i chips); API i worker czekają na nią. */
                attribute :>> obraz = "ghcr.io/.../backend (infra/backend.Dockerfile)";
                attribute :>> limitPamieciMB = 384;
            }
            part postgres : WezelKontenerowy {
                doc /* shared_buffers=128MB, max_connections=30, work_mem=8MB; wolumen postgres-data. */
                attribute :>> obraz = "pgvector/pgvector:pg16";
                attribute :>> limitPamieciMB = 768;
                attribute :>> kontrolaZdrowia = "pg_isready";
            }
            part cli : WezelKontenerowy[0..1] {
                doc /* Profil tools, uruchamiany ręcznie: create-admin, import-vignettes (app.cli). */
                attribute :>> obraz = "ghcr.io/.../backend (infra/backend.Dockerfile)";
                attribute :>> limitPamieciMB = 384;
            }
            part kopiaZapasowa {
                doc /* backup.sh w /etc/cron.daily (anacron: także po starcie VM): pg_dump -Fc, 7 dni. */
                @OdwolanieDoKodu { sciezka = "infra/azure/backup.sh"; }
            }
            part skryptWdrozenia {
                doc /* deploy.sh [IMAGE_TAG]: pull, up -d (najpierw migracja), czekanie na healthy (180 s), prune. */
                @OdwolanieDoKodu { sciezka = "infra/azure/deploy.sh"; }
            }

            connect caddy to frontend;
            connect frontend to ragBackend;
            connect ragBackend to postgres;
            connect worker to postgres;
            connect migracja to postgres;
            connect cli to postgres;
        }

        part pc : KomputerWlasciciela {
            part ollama : WezelKontenerowy {
                attribute :>> obraz = "ollama/ollama";
                attribute :>> wystawionyPort = 11434;
            }
            part languagetool : WezelKontenerowy {
                attribute :>> obraz = "erikvl87/languagetool:6.8";
                attribute :>> wystawionyPort = 8010;
            }
        }

        part tailnet : SiecTailscale;
        part rejestr : RejestrObrazow;

        connect vm to tailnet;
        connect pc to tailnet;
        connect vm.ragBackend to pc.ollama;           // przez tailnet: sonda mocy, osadzanie zapytań
        connect vm.ragBackend to pc.languagetool;     // przez tailnet: sonda mocy
        connect vm.worker to pc.ollama;               // przez tailnet: klasyfikator, redakcja, bge-m3
        connect vm.worker to pc.languagetool;         // przez tailnet: korekta
        connect vm to rejestr;                        // docker compose pull
    }

    // =================================================================== CI/CD
    part def PlatformaCiCd {
        doc /*
         * Nic nie uruchamia się samo (repozytorium jednej osoby, praca na main): CI i Deploy
         * uruchamia się ręcznie. Deploy: CI (opcjonalnie) -> build i push obrazów -> wdrożenie.
         */
        @OdwolanieDoKodu { sciezka = ".github/workflows"; }

        part ci : RunnerGithubActions {
            doc /*
             * ci.yml. backend: uv sync, ruff check, ruff format --check, ty check, pytest
             * -m "not integration" (bez bazy, modeli i sieci). frontend: npm ci, oxlint, eslint,
             * type-check, vitest, build-only.
             */
            @OdwolanieDoKodu { sciezka = ".github/workflows/ci.yml"; }
        }
        part budowanie : RunnerGithubActions {
            doc /* deploy.yml / build: obrazy linux/amd64 z infra/backend.Dockerfile i infra/frontend.Dockerfile. */
            @OdwolanieDoKodu { sciezka = ".github/workflows/deploy.yml"; }
        }
        part wdrozenie : RunnerGithubActions {
            doc /* deploy.yml / deploy: Tailscale (tag:ci), kopiowanie plików compose przez ssh, deploy.sh, test dymny. */
            @OdwolanieDoKodu { sciezka = ".github/workflows/deploy.yml"; }
        }
        part rejestr : RejestrObrazow;

        connect budowanie to rejestr;
    }

    // =================================================================== test environment
    part def SrodowiskoTestowe {
        doc /*
         * Gdzie działają testy (szczegóły przypadków: SledzenieElicytacji::Weryfikacja).
         *   w CI (bez Postgresa)  - tests/unit, tests/test_*.py, testy pakietów bez
         *                           znacznika `integration`, specyfikacje vitest frontendu;
         *   lokalnie (z bazą)     - `-m integration`: tests/api (własna baza rag_<pid>_test z migracji
         *                           Alembic, czyszczona przed każdym testem, usuwana na końcu;
         *                           TEST_DATABASE_URL ma pierwszeństwo, nazwa musi kończyć się _test),
         *                           tests/integration, testy integracyjne pakietu expert-knowledge-rag;
         *   `-m regression`       - regresja jakości wyszukiwania na zamrożonej migawce silver
         *                           (tests/fixtures/retrieval_silver: wektory zapytań, tabele, linia bazowa).
         * Modele (Ollama) są w testach zastępowane atrapami; kontrola mocy obliczeniowej - transportem atrapowym httpx.
         */
        @OdwolanieDoKodu { sciezka = "pyproject.toml"; }

        part ciBezBazy : RunnerGithubActions;
        part lokalnie : MaszynaDewelopera {
            part postgres : WezelKontenerowy { attribute :>> obraz = "pgvector/pgvector:pg16"; }
        }
    }

    part platformaDev : PlatformaDev;
    part platformaProd : PlatformaProd;
    part platformaCiCd : PlatformaCiCd;
    part srodowiskoTestowe : SrodowiskoTestowe;

    // =================================================================== release activity
    action def WdrozenieWydania {
        doc /*
         * Workflow Deploy (ręczny). Migracje muszą być zgodne z działającym wydaniem
         * (najpierw dodaj, usuń w późniejszym wydaniu), bo idą przed restartem API i workera.
         */
        @OdwolanieDoKodu { sciezka = ".github/workflows/deploy.yml"; }

        action testyCi {
            doc /* ci.yml (opcjonalnie, run_tests). */
        }
        action zbudujObrazy {
            doc /* buildx, push do ghcr.io: backend i frontend, tag sha-<7 znaków> oraz latest. */
        }
        action polaczTailscale {
            doc /* tailscale/github-action, tag:ci; tailscale ping VM - wyłączona VM przerywa wdrożenie. */
        }
        action skopiujPlikiCompose {
            doc /* docker-compose.yml, Caddyfile, env.example, deploy.sh, backup.sh -> /opt/rag (tar przez ssh). */
        }
        action uruchomDeploySh {
            doc /* deploy.sh <tag>: IMAGE_TAG do .env, pull, up -d (migracja najpierw), czekanie na healthy. */
        }
        action testDymny {
            doc /* curl APP_URL/api/v1/health i APP_URL/. */
        }

        first start;
        then testyCi;
        then zbudujObrazy;
        then polaczTailscale;
        then skopiujPlikiCompose;
        then uruchomDeploySh;
        then testDymny;
        then done;
    }

    // =================================================================== allocations
    allocation def OprogramowanieNaWezle {
        doc /* Element oprogramowania wykonywany na węźle platformy. */
    }

    allocation def CzynnoscDlaWykonawcy {
        doc /* Czynność wykonywana przez aktora lub część systemu (tor). */
    }

    package AlokacjaDev {
        allocation frontendDev : OprogramowanieNaWezle allocate kontekstElicytacji.system.frontend to platformaDev.frontend;
        allocation backendDev : OprogramowanieNaWezle allocate kontekstElicytacji.system.backend to platformaDev.ragBackend;
        allocation workerDev : OprogramowanieNaWezle allocate kontekstElicytacji.system.worker to platformaDev.worker;
        allocation bazaDev : OprogramowanieNaWezle allocate kontekstElicytacji.system.baza to platformaDev.postgres;
        allocation ollamaDev : OprogramowanieNaWezle allocate kontekstElicytacji.ollama to platformaDev.ollama;
        allocation languageToolDev : OprogramowanieNaWezle allocate kontekstElicytacji.languageTool to platformaDev.languagetool;
    }

    package AlokacjaProd {
        allocation frontendProd : OprogramowanieNaWezle allocate kontekstElicytacji.system.frontend to platformaProd.vm.frontend;
        allocation backendProd : OprogramowanieNaWezle allocate kontekstElicytacji.system.backend to platformaProd.vm.ragBackend;
        allocation workerProd : OprogramowanieNaWezle allocate kontekstElicytacji.system.worker to platformaProd.vm.worker;
        allocation bazaProd : OprogramowanieNaWezle allocate kontekstElicytacji.system.baza to platformaProd.vm.postgres;
        allocation ollamaProd : OprogramowanieNaWezle allocate kontekstElicytacji.ollama to platformaProd.pc.ollama;
        allocation languageToolProd : OprogramowanieNaWezle allocate kontekstElicytacji.languageTool to platformaProd.pc.languagetool;
    }

    package AlokacjaCzynnosci {
        doc /* Tory czynności OdOdpowiedziDoWiedzy oraz zadań. */

        // ekspert (autor)
        allocation a01 : CzynnoscDlaWykonawcy allocate OdOdpowiedziDoWiedzy::rozpocznijOdpowiadanie to kontekstElicytacji.ekspert;
        allocation a02 : CzynnoscDlaWykonawcy allocate OdOdpowiedziDoWiedzy::cytujFragmenty to kontekstElicytacji.ekspert;
        allocation a03 : CzynnoscDlaWykonawcy allocate OdOdpowiedziDoWiedzy::napiszOdpowiedzi to kontekstElicytacji.ekspert;
        allocation a04 : CzynnoscDlaWykonawcy allocate OdOdpowiedziDoWiedzy::sprawdzKorekte to kontekstElicytacji.ekspert;

        // system: API
        allocation a05 : CzynnoscDlaWykonawcy allocate OdOdpowiedziDoWiedzy::zapiszSzkic to kontekstElicytacji.system.backend.przydzialy;
        allocation a06 : CzynnoscDlaWykonawcy allocate OdOdpowiedziDoWiedzy::zglos to kontekstElicytacji.system.backend.przydzialy;

        // recenzenci
        allocation a07 : CzynnoscDlaWykonawcy allocate OdOdpowiedziDoWiedzy::otworzRecenzje to kontekstElicytacji.ekspert;
        allocation a08 : CzynnoscDlaWykonawcy allocate OdOdpowiedziDoWiedzy::komentujOdpowiedzi to kontekstElicytacji.ekspert;
        allocation a09 : CzynnoscDlaWykonawcy allocate OdOdpowiedziDoWiedzy::glos to kontekstElicytacji.ekspert;

        // administrator
        allocation a10 : CzynnoscDlaWykonawcy allocate OdOdpowiedziDoWiedzy::rozstrzygnijOdpowiedzi to kontekstElicytacji.administrator;

        // system: worker
        allocation a11 : CzynnoscDlaWykonawcy allocate OdOdpowiedziDoWiedzy::korekta to kontekstElicytacji.system.worker;
        allocation a12 : CzynnoscDlaWykonawcy allocate OdOdpowiedziDoWiedzy::zbudujJednostki to kontekstElicytacji.system.worker;
        allocation a13 : CzynnoscDlaWykonawcy allocate OdOdpowiedziDoWiedzy::ingestia to kontekstElicytacji.system.worker;
        allocation a17 : CzynnoscDlaWykonawcy allocate WykonanieZadania to kontekstElicytacji.system.worker;

        // usługi zewnętrzne w zadaniu korekty
        allocation a14 : CzynnoscDlaWykonawcy allocate PotokKorekty::klasyfikujReszte to kontekstElicytacji.ollama;

        // zapytanie do bazy wiedzy
        allocation a16 : CzynnoscDlaWykonawcy allocate ZapytanieRag to kontekstElicytacji.system.backend.wiedza;

        // wdrożenie
        allocation a18 : CzynnoscDlaWykonawcy allocate WdrozenieWydania::testyCi to platformaCiCd.ci;
        allocation a19 : CzynnoscDlaWykonawcy allocate WdrozenieWydania::zbudujObrazy to platformaCiCd.budowanie;
        allocation a20 : CzynnoscDlaWykonawcy allocate WdrozenieWydania::polaczTailscale to platformaCiCd.wdrozenie;
        allocation a21 : CzynnoscDlaWykonawcy allocate WdrozenieWydania::skopiujPlikiCompose to platformaCiCd.wdrozenie;
        allocation a22 : CzynnoscDlaWykonawcy allocate WdrozenieWydania::uruchomDeploySh to platformaProd.vm.skryptWdrozenia;
        allocation a23 : CzynnoscDlaWykonawcy allocate WdrozenieWydania::testDymny to platformaCiCd.wdrozenie;
    }
}
