package AnalizaElicytacji {
    doc /*
     * Analiza i parametryka (diagram par).
     *   SkladnikFuzjiRrf                               - składnik fuzji RRF (RRF_K = 60)
     *   BudzetKontekstu                                - mieszczenie się wywołania LLM w num_ctx
     *   BudzetKontekstuEkspertow                       - budżet tokenów notatek eksperckich dla generatora (300/500/800)
     *   JakoscWyszukiwania / JakoscOdpowiedziWgSedziow - progi jakości (wartości do uzupełnienia)
     *   EwaluacjaRag                                   - przypadek analizy odpowiadający scripts/rag/eval_*.py
     *   BudzetPamieciVm                                - limity pamięci kontenerów mieszczą się w VM
     *   OdnowienieDzierzawy, SwiezoscSondy             - puls dzierżawy i wiek sondy mocy obliczeniowej
     *   budzetWywolanLlm, jakoscRag, budzetPamieciVm, niezawodnoscZadan
     *                                                  - konteksty parametryczne wiążące parametry z ograniczeniami
     */

    private import ScalarValues::*;
    private import BibliotekaElicytacji::*;

    // =================================================================== calculations
    calc def SkladnikFuzjiRrf {
        doc /* score = suma po rankingach 1 / (RRF_K + rank); tu jeden składnik sumy. */
        @OdwolanieDoKodu { sciezka = "packages/expert-knowledge-core/src/expert_knowledge_core/retrieval.py"; }
        in pozycja : Integer;
        in rrfK : Integer default 60;
        return wynik : Real = 1.0 / (rrfK + pozycja);
    }

    calc def WynikWazonyKontekstem {
        doc /* Wskazówka współcytowana (context) liczy się z wagą CONTEXT_BONUS = 0.5. */
        @OdwolanieDoKodu { sciezka = "packages/expert-knowledge-core/src/expert_knowledge_core/retrieval.py"; }
        in wynikWskazowki : Real;
        in wynikKontekstu : Real;
        in premiaKontekstu : Real default 0.5;
        return wynik : Real = wynikWskazowki + premiaKontekstu * wynikKontekstu;
    }

    // =================================================================== constraints
    constraint def BudzetKontekstu {
        doc /* Prompt + kontekst + wyjście mieszczą się w oknie kontekstu modelu. */
        in rozmiarKontekstu : Integer;
        in tokenyPromptu : Integer;
        in tokenyKontekstu : Integer;
        in tokenyWyjscia : Integer;
        tokenyPromptu + tokenyKontekstu + tokenyWyjscia <= rozmiarKontekstu
    }

    constraint def BudzetKontekstuEkspertow {
        doc /* Notatki eksperckie przekazane generatorowi nie przekraczają budżetu (BUDGETS w expert_metrics.py). */
        @OdwolanieDoKodu { sciezka = "scripts/rag/expert_metrics.py"; }
        in budzetTokenow : Integer;
        in pokazaneTokeny : Integer;
        pokazaneTokeny <= budzetTokenow
    }

    constraint def JakoscWyszukiwania {
        doc /* Progi jakości wyszukiwania - wartości do ustalenia (WYM-N-13). */
        in pelnoscAt4 : Real;
        in mrr : Real;
        in minimalnaPelnoscAt4 : Real;
        in minimalneMrr : Real;
        pelnoscAt4 >= minimalnaPelnoscAt4 and mrr >= minimalneMrr
    }

    constraint def JakoscOdpowiedziWgSedziow {
        doc /* Średnia ocena sędziów LLM nie niższa niż próg (WYM-N-14). */
        in sredniaOcenaSedziow : Real;
        in minimalnaOcenaSedziow : Real;
        sredniaOcenaSedziow >= minimalnaOcenaSedziow
    }

    constraint def BudzetPamieciVm {
        doc /* Suma limitów pamięci kontenerów + rezerwa systemu mieści się w pamięci VM (WYM-N-09). */
        @OdwolanieDoKodu { sciezka = "infra/azure/docker-compose.yml"; }
        in pamiecVmMB : Integer;
        in rezerwaSystemuMB : Integer;
        in postgresMB : Integer;
        in backendMB : Integer;
        in workerMB : Integer;
        in migracjaMB : Integer;
        in frontendMB : Integer;
        in caddyMB : Integer;
        postgresMB + backendMB + workerMB + migracjaMB + frontendMB + caddyMB + rezerwaSystemuMB <= pamiecVmMB
    }

    constraint def OdnowienieDzierzawy {
        doc /* Puls odnawia dzierżawę, zanim wygaśnie - długie zadanie nie zostanie przejęte (WYM-N-03). */
        @OdwolanieDoKodu { sciezka = "backend/app/jobs/worker.py"; }
        in odstepOdnowieniaS : Real;
        in dzierzawaS : Real;
        odstepOdnowieniaS < dzierzawaS
    }

    constraint def SwiezoscSondy {
        doc /* Żądanie korzysta z sondy nie starszej niż próg; starszą wykonuje samo (WYM-N-16). */
        @OdwolanieDoKodu { sciezka = "backend/app/compute.py"; }
        in wiekSondyS : Real;
        in maksymalnyWiekS : Real;
        wiekSondyS <= maksymalnyWiekS
    }

    // =================================================================== evaluation subject
    attribute def MetrykiWyszukiwania {
        doc /* Metryki z score_query(): recall@k, hit@k, MRR, nDCG@10, recall przy budżecie tokenów. */
        @OdwolanieDoKodu { sciezka = "scripts/rag/expert_metrics.py"; }
        attribute pelnoscAt1 : Real;
        attribute pelnoscAt4 : Real;
        attribute pelnoscAt8 : Real;
        attribute trafienieAt4 : Real;
        attribute sufitAt4 : Real;
        attribute mrr : Real;
        attribute ndcgAt10 : Real;
        attribute pelnoscPrzy500Tokenach : Real;
        attribute tezyNa100Tokenow : Real;
    }

    part def UruchomienieEwaluacji {
        doc /* Jedno uruchomienie ewaluacji (konfiguracja retrievera, generator, sędziowie, wyniki z przedziałami bootstrap). */
        @OdwolanieDoKodu { sciezka = "scripts/rag/report_eval.py"; }
        attribute wyszukiwacz : String;
        attribute modelGeneratora : String;
        attribute modeleSedziow : String[1..*];
        attribute metryki : MetrykiWyszukiwania;
        attribute sredniaOcenaSedziow : Real;
        attribute probyBootstrap : Integer = 1000;
    }

    analysis def EwaluacjaRag {
        doc /* Ewaluacja wyszukiwania i generowania (umiejętność rag-eval). Progi do uzupełnienia. */
        @OdwolanieDoKodu { sciezka = "scripts/rag/eval_expert_units.py"; }
        subject uruchomienie : UruchomienieEwaluacji;
        in attribute progPelnosci : Real;
        in attribute progMrr : Real;
        in attribute progOcenySedziow : Real;

        objective celJakosci {
            doc /* Spełnić WYM-N-13 i WYM-N-14. */
            require constraint wymogWyszukiwania : JakoscWyszukiwania {
                in pelnoscAt4 = uruchomienie.metryki.pelnoscAt4;
                in mrr = uruchomienie.metryki.mrr;
                in minimalnaPelnoscAt4 = progPelnosci;
                in minimalneMrr = progMrr;
            }
            require constraint odpowiedzi : JakoscOdpowiedziWgSedziow {
                in sredniaOcenaSedziow = uruchomienie.sredniaOcenaSedziow;
                in minimalnaOcenaSedziow = progOcenySedziow;
            }
        }

        return attribute zaliczone : Boolean;
    }

    // =================================================================== parametric contexts
    part budzetWywolanLlm {
        doc /* Kontekst parametryczny dla wywołań LLM w korekcie i klasyfikacji (num_ctx 8192). */
        attribute rozmiarKontekstu : Integer = 8192;
        attribute tokenyWyjsciaRedakcji : Integer = 1200;     // enhance.py num_predict
        attribute tokenyWyjsciaKlasyfikatora : Integer = 600;   // classifier.py num_predict
        attribute tokenyPromptu : Integer;                   // do uzupełnienia - z pomiaru
        attribute tokenyOdpowiedzi : Integer;                   // do uzupełnienia - z pomiaru

        constraint redakcjaSieMiesci : BudzetKontekstu;
        bind redakcjaSieMiesci.rozmiarKontekstu = rozmiarKontekstu;
        bind redakcjaSieMiesci.tokenyPromptu = tokenyPromptu;
        bind redakcjaSieMiesci.tokenyKontekstu = tokenyOdpowiedzi;
        bind redakcjaSieMiesci.tokenyWyjscia = tokenyWyjsciaRedakcji;

        constraint klasyfikatorSieMiesci : BudzetKontekstu;
        bind klasyfikatorSieMiesci.rozmiarKontekstu = rozmiarKontekstu;
        bind klasyfikatorSieMiesci.tokenyPromptu = tokenyPromptu;
        bind klasyfikatorSieMiesci.tokenyKontekstu = tokenyOdpowiedzi;
        bind klasyfikatorSieMiesci.tokenyWyjscia = tokenyWyjsciaKlasyfikatora;
    }

    part jakoscRag {
        doc /* Kontekst parametryczny dla odpowiedzi RAG: budżet notatek i progi jakości. */
        part uruchomienie : UruchomienieEwaluacji;
        attribute budzetTokenow : Integer = 500;
        attribute pokazaneTokeny : Integer;          // do uzupełnienia
        attribute minimalnaPelnoscAt4 : Real;            // do uzupełnienia
        attribute minimalneMrr : Real;                  // do uzupełnienia

        constraint budzet : BudzetKontekstuEkspertow;
        bind budzet.budzetTokenow = budzetTokenow;
        bind budzet.pokazaneTokeny = pokazaneTokeny;

        constraint jakosc : JakoscWyszukiwania;
        bind jakosc.pelnoscAt4 = uruchomienie.metryki.pelnoscAt4;
        bind jakosc.mrr = uruchomienie.metryki.mrr;
        bind jakosc.minimalnaPelnoscAt4 = minimalnaPelnoscAt4;
        bind jakosc.minimalneMrr = minimalneMrr;
    }

    part budzetPamieciVm {
        doc /*
         * Kontekst parametryczny wdrożenia na VM Standard_B2s. Migracja działa jednorazowo przed
         * startem API i workera, ale jej limit jest liczony (najgorszy przypadek). Kontener cli
         * (profil tools) nie jest liczony - uruchamia się ręcznie.
         */
        attribute pamiecVmMB : Integer = 4096;
        attribute rezerwaSystemuMB : Integer;      // do uzupełnienia - system, cache stron (swap 2 GB poza RAM)
        attribute postgresMB : Integer = 768;
        attribute backendMB : Integer = 512;
        attribute workerMB : Integer = 512;
        attribute migracjaMB : Integer = 384;
        attribute frontendMB : Integer = 64;
        attribute caddyMB : Integer = 64;

        constraint miesciSie : BudzetPamieciVm;
        bind miesciSie.pamiecVmMB = pamiecVmMB;
        bind miesciSie.rezerwaSystemuMB = rezerwaSystemuMB;
        bind miesciSie.postgresMB = postgresMB;
        bind miesciSie.backendMB = backendMB;
        bind miesciSie.workerMB = workerMB;
        bind miesciSie.migracjaMB = migracjaMB;
        bind miesciSie.frontendMB = frontendMB;
        bind miesciSie.caddyMB = caddyMB;
    }

    part niezawodnoscZadan {
        doc /* Kontekst parametryczny workera i bramki mocy obliczeniowej (wartości z kodu). */
        attribute dzierzawaS : Real = 300.0;              // LEASE = 5 min
        attribute odstepOdnowieniaS : Real = 100.0;       // LEASE / 3
        attribute odstepSondowaniaApiS : Real = 10.0;     // WATCH_EVERY
        attribute limitCzasuSondyS : Real = 3.0;          // TIMEOUT
        attribute najstarszaSondaApiS : Real = odstepSondowaniaApiS + limitCzasuSondyS;
        attribute waznoscSondyApiS : Real = 30.0;         // API_TRUSTS

        constraint pulsZdazy : OdnowienieDzierzawy;
        bind pulsZdazy.odstepOdnowieniaS = odstepOdnowieniaS;
        bind pulsZdazy.dzierzawaS = dzierzawaS;

        constraint obserwatorWystarcza : SwiezoscSondy;
        bind obserwatorWystarcza.wiekSondyS = najstarszaSondaApiS;
        bind obserwatorWystarcza.maksymalnyWiekS = waznoscSondyApiS;
    }
}
