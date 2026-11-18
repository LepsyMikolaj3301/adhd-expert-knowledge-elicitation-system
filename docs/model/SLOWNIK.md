# Słownik nazw: kod / wersja angielska → model SysML

Nazwy elementów modelu zostały przetłumaczone na polski (bez znaków diakrytycznych). Tabela pokazuje,
jak nazwa z kodu lub z wcześniejszej, angielskiej wersji modelu odpowiada nazwie w modelu. Każda nazwa
jest wymieniona raz, w pliku, w którym występuje jako pierwszym. Wygenerowano ze słownika użytego
przy tłumaczeniu; przy zmianie nazw w modelu trzeba go zaktualizować.

Identyfikatory wymagań: `REQ-F-xx` → `WYM-F-xx`, `REQ-N-xx` → `WYM-N-xx`, `C-xx` → `ZAG-xx`.

## `00_Biblioteka.sysml`

| Kod / angielska nazwa | Nazwa w modelu |
|---|---|
| `CodeRef` | `OdwolanieDoKodu` |
| `ElicitationLibrary` | `BibliotekaElicytacji` |
| `Implemented` | `Zaimplementowane` |
| `path` | `sciezka` |
| `Planned` | `Planowane` |
| `Proposed` | `Propozycja` |
| `QuestionId` | `IdPytania` |
| `TBD` | `DoUzupelnienia` |
| `Timestamp` | `ZnacznikCzasu` |

## `01_Wymagania.sysml`

| Kod / angielska nazwa | Nazwa w modelu |
|---|---|
| `accessibility` | `dostepnoscInterfejsu` |
| `Actors` | `Aktorzy` |
| `admin` | `administrator` |
| `Admin` | `Administrator` |
| `adminDecides` | `administratorDecyduje` |
| `allowedActions` | `dozwoloneAkcje` |
| `allQuestionsVisible` | `wszystkiePytaniaWidoczne` |
| `answerQuality` | `jakoscOdpowiedzi` |
| `assignPublishedOnly` | `przydzialTylkoOpublikowanych` |
| `auditTrail` | `sladAudytowy` |
| `auth` | `uwierzytelnianie` |
| `authorChecksProofread` | `autorSprawdzaKorekte` |
| `automaticProofreading` | `automatycznaKorekta` |
| `availability` | `dostepnosc` |
| `boundedJobRetry` | `ograniczonePonawianieZadan` |
| `citationDirection` | `kierunekCytatu` |
| `citationsMatchVignette` | `cytatyZgodneZWinieta` |
| `completeSubmission` | `kompletneZgloszenie` |
| `Concerns` | `Zagadnienia` |
| `consumer` | `odbiorca` |
| `contextBudget` | `budzetKontekstu` |
| `controlOverKnowledgeBase` | `kontrolaNadBazaWiedzy` |
| `dataSubject` | `podmiotDanych` |
| `DataSubject` | `PodmiotDanych` |
| `draftAutosave` | `autozapisSzkicu` |
| `ElicitationContext` | `KontekstElicytacji` |
| `ElicitationRequirements` | `WymaganiaElicytacji` |
| `ElicitationStructure` | `StrukturaElicytacji` |
| `ElicitationSystem` | `SystemElicytacji` |
| `engineer` | `inzynier` |
| `expert` | `ekspert` |
| `Expert` | `Ekspert` |
| `Functional` | `Funkcjonalne` |
| `gdprErasure` | `usuwanieDanychRodo` |
| `hiddenVignetteDesign` | `ukrytyProjektWiniety` |
| `immutableSubmission` | `niezmienneZgloszenie` |
| `ingestion` | `ingestiaJednostek` |
| `inviteOnlyAccounts` | `kontaTylkoZZaproszen` |
| `inviteTtl` | `waznoscZaproszenia` |
| `KnowledgeEngineer` | `InzynierWiedzy` |
| `knowledgeFidelity` | `wiernoscWiedzy` |
| `knowledgeRemoval` | `usuwanieWiedzy` |
| `knowledgeSearch` | `wyszukiwanieWiedzy` |
| `lease` | `dzierzawa` |
| `localModels` | `modeleLokalne` |
| `loginProtection` | `ochronaLogowania` |
| `lowCostHosting` | `tanieHostowanie` |
| `lowExpertBurden` | `malyNakladEksperta` |
| `maxAttempts` | `maksymalnaLiczbaProb` |
| `maxFailedLogins` | `maksymalnaLiczbaNieudanychLogowan` |
| `maxK` | `maksymalneK` |
| `minJudgeScore` | `minimalnaOcenaSedziow` |
| `minRecallAtK` | `minimalnaPelnoscAtK` |
| `NonFunctional` | `Niefunkcjonalne` |
| `numCtx` | `rozmiarKontekstu` |
| `openPeerReview` | `otwartaRecenzja` |
| `p95ResponseTime` | `czasOdpowiedziP95` |
| `privacy` | `prywatnosc` |
| `pseudonymisation` | `pseudonimizacja` |
| `ragAnswering` | `odpowiedziRag` |
| `RagConsumer` | `OdbiorcaRag` |
| `responsiveness` | `szybkoscDzialania` |
| `retrievalQuality` | `jakoscWyszukiwania` |
| `retryFailedJobs` | `ponawianieNieudanychZadan` |
| `roleBasedAccess` | `dostepWgRol` |
| `safeMigrations` | `bezpieczneMigracje` |
| `scalableWorkers` | `skalowalneWorkery` |
| `sessionLifetime` | `czasZyciaSesji` |
| `sessionTtl` | `waznoscSesji` |
| `singleTransitionPoint` | `jedenPunktPrzejsc` |
| `SystemRequirement` | `WymaganieSystemowe` |
| `targetAvailability` | `docelowaDostepnosc` |
| `traceability` | `sladowalnosc` |
| `unbiasedAnswers` | `odpowiedziBezWplywu` |
| `unitBuilding` | `budowaJednostek` |
| `vignetteVersioning` | `wersjonowanieWiniet` |

## `02_Kontekst.sysml`

| Kod / angielska nazwa | Nazwa w modelu |
|---|---|
| `AcceptInvite` | `PrzyjmijZaproszenie` |
| `AnswerVignette` | `OdpowiedzNaWiniete` |
| `AskKnowledgeBase` | `ZapytajBazeWiedzy` |
| `AssignExpert` | `PrzydzielEksperta` |
| `AuthorVignette` | `NapiszWiniete` |
| `BuildLiteratureCorpus` | `ZbudujKorpusLiteratury` |
| `BuildUnits` | `ZbudujJednostki` |
| `CancelAssignment` | `AnulujPrzydzial` |
| `CheckProofread` | `SprawdzKorekte` |
| `CitePassage` | `CytujFragment` |
| `citePassage` | `cytujFragment` |
| `client` | `klient` |
| `CommentOnAnswer` | `SkomentujOdpowiedz` |
| `commentOnAnswer` | `skomentujOdpowiedz` |
| `DecideAnswers` | `RozstrzygnijOdpowiedzi` |
| `elicitationContext` | `kontekstElicytacji` |
| `ElicitationInterfaces` | `InterfejsyElicytacji` |
| `EvaluateRag` | `OcenRag` |
| `ExternalSystems` | `SystemyZewnetrzne` |
| `IngestUnits` | `IngestujJednostki` |
| `InterfaceDefinitions` | `DefinicjeInterfejsow` |
| `InviteExpert` | `ZaprosEksperta` |
| `LanguageToolPort` | `PortLanguageTool` |
| `LanguageToolService` | `UslugaLanguageTool` |
| `literature` | `literatura` |
| `LiteratureSources` | `ZrodlaLiteratury` |
| `LogIn` | `Zaloguj` |
| `OllamaPort` | `PortOllama` |
| `OllamaService` | `UslugaOllama` |
| `Person` | `Osoba` |
| `Ports` | `Porty` |
| `ProofreadAnswers` | `KorygujOdpowiedzi` |
| `PublishVignette` | `OpublikujWiniete` |
| `RedditPool` | `PulaReddit` |
| `RefitIndex` | `PrzeliczIndeks` |
| `RemoveKnowledge` | `UsunWiedze` |
| `research` | `badania` |
| `RetryJob` | `PonowZadanie` |
| `ReviewAnswers` | `RecenzujOdpowiedzi` |
| `Reviewer` | `Recenzent` |
| `reviewer` | `recenzent` |
| `SaveDraft` | `ZapiszSzkic` |
| `saveDraft` | `zapiszSzkic` |
| `SearchKnowledge` | `WyszukajWiedze` |
| `server` | `serwer` |
| `SubmitAnswers` | `ZglosOdpowiedzi` |
| `submitAnswers` | `zglosOdpowiedzi` |
| `SubmitForReview` | `OddajDoRecenzji` |
| `systemToLanguageTool` | `systemDoLanguageTool` |
| `systemToOllama` | `systemDoOllama` |
| `UseCases` | `PrzypadkyUzycia` |
| `user` | `uzytkownik` |
| `VoteOnAnswer` | `ZaglosujNaOdpowiedz` |
| `voteOnAnswer` | `zaglosujNaOdpowiedz` |

## `03_Interfejsy.sysml`

| Kod / angielska nazwa | Nazwa w modelu |
|---|---|
| `AnswerContent` | `TrescOdpowiedzi` |
| `AppSchema` | `SchematApp` |
| `body` | `tresc` |
| `ChatRequest` | `ZapytanieCzatu` |
| `chatRequest` | `zapytanieCzatu` |
| `check` | `sprawdzenie` |
| `Completion` | `OdpowiedzModelu` |
| `completion` | `odpowiedzModelu` |
| `dimensions` | `wymiary` |
| `ElicitationDomain` | `DziedzinaElicytacji` |
| `Embedding` | `Osadzenie` |
| `embedding` | `osadzenie` |
| `EmbedRequest` | `ZapytanieOsadzenia` |
| `embedRequest` | `zapytanieOsadzenia` |
| `get` | `pobierz` |
| `GrammarCheckRequest` | `ZapytanieSprawdzeniaGramatyki` |
| `GrammarMatches` | `DopasowaniaGramatyczne` |
| `hits` | `trafienia` |
| `HttpPort` | `PortHttp` |
| `HttpRequest` | `ZapytanieHttp` |
| `HttpResponse` | `OdpowiedzHttp` |
| `Items` | `Elementy` |
| `key` | `klucz` |
| `language` | `jezyk` |
| `matches` | `dopasowania` |
| `method` | `metoda` |
| `mode` | `tryb` |
| `put` | `zapisz` |
| `query` | `zapytanie` |
| `request` | `zapytanie` |
| `response` | `odpowiedz` |
| `RestApi` | `ApiRest` |
| `result` | `wynik` |
| `S3Api` | `ApiS3` |
| `S3Port` | `PortS3` |
| `SearchQuery` | `ZapytanieWyszukiwania` |
| `SearchResult` | `WynikWyszukiwania` |
| `SqlConnection` | `PolaczenieSql` |
| `SqlPort` | `PortSql` |
| `SqlResult` | `WynikSql` |
| `SqlStatement` | `InstrukcjaSql` |
| `statement` | `instrukcja` |
| `StoredObject` | `ObiektWMagazynie` |
| `temperature` | `temperatura` |
| `text` | `tekst` |
| `texts` | `teksty` |

## `04_Struktura.sysml`

| Kod / angielska nazwa | Nazwa w modelu |
|---|---|
| `access` | `dostep` |
| `adminViews` | `widokiAdministratora` |
| `answerValidation` | `walidacjaOdpowiedzi` |
| `ApiBackend` | `BackendApi` |
| `apiClient` | `klientApi` |
| `apiClientModule` | `modulKlientaApi` |
| `apiToDb` | `apiDoBd` |
| `appSchema` | `schematApp` |
| `assignmentLifecycle` | `cyklZyciaPrzydzialu` |
| `AssignmentLifecycle` | `CyklZyciaPrzydzialu` |
| `assignments` | `przydzialy` |
| `AssignmentsModule` | `ModulPrzydzialow` |
| `assignmentsUsesAudit` | `przydzialyUzywajaAudytu` |
| `assignmentsUsesJobs` | `przydzialyUzywajaZadan` |
| `assignmentsUsesProofread` | `przydzialyUzywajaKorekty` |
| `assignmentsUsesVignettes` | `przydzialyUzywajaWiniet` |
| `audit` | `audyt` |
| `AuditModule` | `ModulAudytu` |
| `AuthModule` | `ModulUwierzytelniania` |
| `authUsesUsers` | `uwierzytelnianieUzywaUzytkownikow` |
| `authViews` | `widokiLogowania` |
| `BackendModules` | `ModulyBackendu` |
| `buildCorpus` | `zbudujKorpus` |
| `chains` | `lancuchy` |
| `chipsSchema` | `schematChips` |
| `classifier` | `klasyfikator` |
| `core` | `rdzen` |
| `CoreModule` | `ModulRdzenia` |
| `CorpusIngestion` | `IngestiaKorpusu` |
| `corpusScripts` | `skryptyKorpusu` |
| `corpusTables` | `tabeleKorpusu` |
| `database` | `baza` |
| `db` | `bd` |
| `dbScripts` | `skryptyBd` |
| `ElicitationActivities` | `CzynnosciElicytacji` |
| `elicitationScripts` | `skryptyElicytacji` |
| `ElicitationStates` | `StanyElicytacji` |
| `enhance` | `redakcja` |
| `evaluateRag` | `ocenRag` |
| `ExpertKnowledgeCore` | `RdzenWiedzyEksperckiej` |
| `ExpertKnowledgeRag` | `RagWiedzyEksperckiej` |
| `expertViews` | `widokiEksperta` |
| `findings` | `ustalenia` |
| `garbage` | `smieci` |
| `grammar` | `gramatyka` |
| `handlers` | `handlery` |
| `home` | `stronaGlowna` |
| `HomeModule` | `ModulStronyGlownej` |
| `homeUsesAssignments` | `stronaGlownaUzywaPrzydzialow` |
| `homeUsesReviews` | `stronaGlownaUzywaRecenzji` |
| `ingest` | `ingestia` |
| `ingestJob` | `zadanieIngestii` |
| `jobLifecycle` | `cyklZyciaZadania` |
| `JobLifecycle` | `CyklZyciaZadania` |
| `jobs` | `zadania` |
| `JobsModule` | `ModulZadan` |
| `jobsUsesAssignments` | `zadaniaUzywajaPrzydzialow` |
| `jobsUsesKnowledge` | `zadaniaUzywajaWiedzy` |
| `jobsUsesProofread` | `zadaniaUzywajaKorekty` |
| `jobsUsesReviews` | `zadaniaUzywajaRecenzji` |
| `JobWorker` | `WorkerZadan` |
| `knowledge` | `wiedza` |
| `KnowledgeModule` | `ModulWiedzy` |
| `knowledgeUsesCore` | `wiedzaUzywaRdzenia` |
| `knowledgeUsesRag` | `wiedzaUzywaRag` |
| `knowledgeView` | `widokWiedzy` |
| `leaseMinutes` | `dzierzawaMinuty` |
| `Libraries` | `Biblioteki` |
| `links` | `powiazania` |
| `ModuleDependencies` | `ZaleznosciModulow` |
| `nginxToApi` | `nginxDoApi` |
| `notes` | `notatki` |
| `ObjectStore` | `MagazynObiektow` |
| `objectStore` | `magazynObiektow` |
| `patientTextRetriever` | `wyszukiwaczTekstuPacjenta` |
| `pipeline` | `potok` |
| `pollSeconds` | `odpytywanieSekundy` |
| `PostgresDatabase` | `BazaPostgres` |
| `processJob` | `zadaniePrzetwarzania` |
| `prompts` | `prompty` |
| `proofread` | `korekta` |
| `proofreadJob` | `zadanieKorekty` |
| `ProofreadModule` | `ModulKorekty` |
| `ProofreadPipeline` | `PotokKorekty` |
| `questionRetriever` | `wyszukiwaczPytan` |
| `queue` | `kolejka` |
| `ragEvalScripts` | `skryptyEwaluacjiRag` |
| `RagQuery` | `ZapytanieRag` |
| `records` | `rekordy` |
| `removal` | `usuwanie` |
| `researchToDb` | `badaniaDoBd` |
| `ResearchToolchain` | `NarzedziaBadawcze` |
| `researchToStore` | `badaniaDoMagazynu` |
| `reviews` | `recenzje` |
| `ReviewsModule` | `ModulRecenzji` |
| `reviewsUsesAssignments` | `recenzjeUzywajaPrzydzialow` |
| `reviewViews` | `widokiRecenzji` |
| `search` | `wyszukiwanie` |
| `sqlBuilder` | `budowniczySql` |
| `stateMachine` | `maszynaStanow` |
| `store` | `magazyn` |
| `users` | `uzytkownicy` |
| `UsersModule` | `ModulUzytkownikow` |
| `versionLifecycle` | `cyklZyciaWersji` |
| `vignettes` | `winiety` |
| `VignettesModule` | `ModulWiniet` |
| `VignetteVersionLifecycle` | `CyklZyciaWersjiWiniety` |
| `WebFrontend` | `FrontendWebowy` |
| `workerToDb` | `workerDoBd` |
| `WorkflowStateMachine` | `MaszynaStanowPrzeplywu` |

## `05_Dziedzina.sysml`

| Kod / angielska nazwa | Nazwa w modelu |
|---|---|
| `action` | `akcja` |
| `activitySeenAt` | `aktywnoscWidzianaO` |
| `actor` | `aktor` |
| `AnswerComment` | `KomentarzDoOdpowiedzi` |
| `AnswerDecision` | `DecyzjaOOdpowiedzi` |
| `AnswerDraft` | `SzkicOdpowiedzi` |
| `AnswerFindings` | `UstaleniaOdpowiedzi` |
| `AnswerPayload` | `TrescZgloszenia` |
| `AnswerRevision` | `RewizjaOdpowiedzi` |
| `answers` | `odpowiedzi` |
| `AnswerSentence` | `ZdanieOdpowiedzi` |
| `AnswerVote` | `GlosNaOdpowiedz` |
| `AnswerVoteValue` | `WartoscGlosu` |
| `approve` | `zatwierdz` |
| `approve_answers` | `zatwierdzOdpowiedzi` |
| `approved` | `zatwierdzona` |
| `assigned` | `przydzielony` |
| `assignedBy` | `przydzielonyPrzez` |
| `assignee` | `wykonawca` |
| `Assignment` | `Przydzial` |
| `assignment` | `przydzial` |
| `AssignmentState` | `StanPrzydzialu` |
| `at` | `chwila` |
| `attempts` | `proby` |
| `AuditEvent` | `ZdarzenieAudytowe` |
| `author` | `autor` |
| `AuthSession` | `SesjaLogowania` |
| `away` | `przeciwny` |
| `cancel` | `anuluj` |
| `cancelled` | `anulowany` |
| `case` | `przypadek` |
| `challenge` | `zastrzezenie` |
| `checkOutcome` | `wynikSprawdzenia` |
| `ChipsSchema` | `SchematChips` |
| `Chunk` | `Fragment` |
| `chunkIndex` | `numerFragmentu` |
| `code` | `kod` |
| `comment` | `komentarz` |
| `contentHash` | `skrotTresci` |
| `context` | `kontekst` |
| `contextualText` | `tekstKontekstowy` |
| `Corpus` | `Korpus` |
| `createdAt` | `utworzonoO` |
| `createdBy` | `utworzonyPrzez` |
| `CueKey` | `KluczWskazowki` |
| `cueKey` | `kluczWskazowki` |
| `cues` | `wskazowki` |
| `decidedAt` | `rozstrzygnietoO` |
| `decision` | `decyzja` |
| `DecisionValue` | `WartoscDecyzji` |
| `DenseVector` | `WektorGesty` |
| `design` | `projekt` |
| `Direction` | `Kierunek` |
| `direction` | `kierunek` |
| `directionChangedAfterFlag` | `kierunekZmienionyPoFladze` |
| `disapprove` | `sprzeciw` |
| `displayName` | `nazwaWyswietlana` |
| `document` | `dokument` |
| `Document` | `Dokument` |
| `DocumentStatus` | `StatusDokumentu` |
| `draft` | `szkic` |
| `dropped` | `odrzucone` |
| `ElicitationSession` | `SesjaElicytacji` |
| `embeddingCombined` | `osadzenieZlaczone` |
| `embeddingModel` | `modelOsadzen` |
| `embedText` | `tekstDoOsadzenia` |
| `embedTextCombined` | `tekstDoOsadzeniaZlaczony` |
| `entityId` | `idEncji` |
| `entityType` | `typEncji` |
| `Enumerations` | `TypyWyliczeniowe` |
| `expiresAt` | `wygasaO` |
| `failed` | `nieudane` |
| `failedLogins` | `nieudaneLogowania` |
| `feedback` | `informacjaZwrotna` |
| `final` | `wersjaKoncowa` |
| `findingsVersion` | `wersjaUstalen` |
| `FindingUnit` | `JednostkaUstalen` |
| `flags` | `flagi` |
| `framing` | `kontekstowanie` |
| `fromState` | `zStanu` |
| `headingPath` | `sciezkaNaglowkow` |
| `Highlight` | `Cytat` |
| `highlight` | `cytat` |
| `highlightId` | `idCytatu` |
| `highlights` | `cytaty` |
| `hypothesis` | `hipoteza` |
| `idx` | `indeks` |
| `in_progress` | `wToku` |
| `indexConfig` | `konfiguracjaIndeksu` |
| `indexed` | `zaindeksowany` |
| `ingested` | `zaingestowany` |
| `ingesting` | `ingestiaWToku` |
| `ingestion_failed` | `ingestiaNieudana` |
| `ingestion_succeeded` | `ingestiaUdana` |
| `insufficientInformation` | `zaMaloInformacji` |
| `Invite` | `Zaproszenie` |
| `isActive` | `czyAktywny` |
| `Job` | `Zadanie` |
| `JobKind` | `RodzajZadania` |
| `JobStatus` | `StatusZadania` |
| `kind` | `rodzaj` |
| `KnowledgeUnit` | `JednostkaWiedzy` |
| `lastError` | `ostatniBlad` |
| `less_adhd` | `mniejAdhd` |
| `lines` | `linie` |
| `lockedUntil` | `zablokowanyDo` |
| `meta` | `metadane` |
| `more_adhd` | `bardziejAdhd` |
| `neutral` | `neutralny` |
| `nTokens` | `liczbaTokenow` |
| `openedAt` | `otwartoO` |
| `ordinal` | `numerPorzadkowy` |
| `origin` | `pochodzenie` |
| `original` | `oryginal` |
| `other` | `inny` |
| `otherExplanation` | `innyKomentarz` |
| `parent` | `rodzic` |
| `parsed` | `sparsowany` |
| `parsing` | `parsowanie` |
| `passes` | `przebiegi` |
| `passwordHash` | `skrotHasla` |
| `patientSummary` | `streszczeniePacjenta` |
| `patientWords` | `slowaPacjenta` |
| `payload` | `tresc` |
| `payloadFormat` | `formatTresci` |
| `peer_review` | `recenzjaKolezenska` |
| `pending` | `oczekujaca` |
| `population` | `populacja` |
| `process` | `przetwarzanie` |
| `processing` | `przetwarzanieWToku` |
| `processing_failed` | `przetwarzanieNieudane` |
| `processing_succeeded` | `przetwarzanieUdane` |
| `proofread_check` | `sprawdzenieKorekty` |
| `proofread_failed` | `korektaNieudana` |
| `proofread_succeeded` | `korektaUdana` |
| `proofreading` | `korektaWToku` |
| `ProofreadRound` | `RundaKorekty` |
| `proposed` | `propozycja` |
| `pseudonym` | `pseudonim` |
| `published` | `opublikowany` |
| `publishedAt` | `opublikowanoO` |
| `Q4Answer` | `OdpowiedzQ4` |
| `Q4Toward` | `KierunekZmianyQ4` |
| `q4Whatif` | `q4CoJesli` |
| `question` | `pytanie` |
| `questionId` | `idPytania` |
| `questionIds` | `idPytan` |
| `queued` | `wKolejce` |
| `rating` | `ocena` |
| `record` | `rekord` |
| `refit` | `przeliczenie` |
| `reject` | `odrzuc` |
| `reject_all_answers` | `odrzucWszystkieOdpowiedzi` |
| `rejected` | `odrzucony` |
| `removed` | `usunieta` |
| `request_changes` | `zazadajPoprawek` |
| `retired` | `wycofany` |
| `retry_ingestion` | `ponowIngestie` |
| `retry_processing` | `ponowPrzetwarzanie` |
| `retry_proofread` | `ponowKorekte` |
| `ReviewEvent` | `ZdarzenieRecenzji` |
| `ReviewParticipant` | `UczestnikRecenzji` |
| `reviewRound` | `rundaRecenzji` |
| `Role` | `Rola` |
| `role` | `rola` |
| `running` | `uruchomione` |
| `s3Key` | `s3Klucz` |
| `sentenceIds` | `idZdan` |
| `sentences` | `zdania` |
| `session` | `sesja` |
| `shift` | `przesuniecie` |
| `shiftRange` | `zakresPrzesuniecia` |
| `sourceId` | `idZrodla` |
| `sourceUrl` | `urlZrodla` |
| `spanEnd` | `koniecZakresu` |
| `spanStart` | `poczatekZakresu` |
| `sparse` | `rzadki` |
| `SparseVector` | `WektorRzadki` |
| `Stance` | `Stanowisko` |
| `stance` | `stanowisko` |
| `startedAt` | `rozpoczetoO` |
| `state` | `stan` |
| `Submission` | `Zgloszenie` |
| `submission` | `zgloszenie` |
| `submit` | `zglos` |
| `submit_for_review` | `oddajDoRecenzji` |
| `submittedAt` | `zgloszonoO` |
| `superseded` | `zastapiona` |
| `support` | `poparcie` |
| `targets` | `cele` |
| `tier` | `poziom` |
| `title` | `tytul` |
| `tokenHash` | `skrotTokenu` |
| `toState` | `doStanu` |
| `toward` | `zgodny` |
| `track` | `sciezkaBadawcza` |
| `unclear` | `niejasny` |
| `UnitKind` | `RodzajJednostki` |
| `UnitStatus` | `StatusJednostki` |
| `updatedAt` | `zaktualizowanoO` |
| `uploaded` | `przeslany` |
| `usedAt` | `wykorzystanoO` |
| `User` | `Uzytkownik` |
| `variant` | `wariant` |
| `version` | `wersja` |
| `versions` | `wersje` |
| `VersionStatus` | `StatusWersji` |
| `Vignette` | `Winieta` |
| `vignette` | `winieta` |
| `vignetteHash` | `skrotWiniety` |
| `vignetteId` | `idWiniety` |
| `VignetteVersion` | `WersjaWiniety` |
| `vignetteVersion` | `wersjaWiniety` |
| `vote` | `glos` |
| `voter` | `glosujacy` |
| `WorkflowAction` | `AkcjaPrzeplywu` |
| `WorkflowActor` | `AktorPrzeplywu` |

## `06_Stany.sysml`

| Kod / angielska nazwa | Nazwa w modelu |
|---|---|
| `ApproveAnswers` | `ZatwierdzOdpowiedzi` |
| `Cancel` | `Anuluj` |
| `Claim` | `Przejmij` |
| `claim` | `przejmij` |
| `claimExhausted` | `przejecieWyczerpane` |
| `endFailed` | `koniecNieudane` |
| `endRetired` | `koniecWycofane` |
| `endSucceeded` | `koniecUdane` |
| `enqueue` | `zakolejkuj` |
| `EnqueueJob` | `ZakolejkujZadanie` |
| `IngestionFailed` | `IngestiaNieudana` |
| `IngestionSucceeded` | `IngestiaUdana` |
| `JobErrored` | `ZadanieZBledem` |
| `JobSucceeded` | `ZadanieUdane` |
| `LeaseExpired` | `DzierzawaWygasla` |
| `leaseExpired` | `dzierzawaWygasla` |
| `performedBy` | `wykonujeAktor` |
| `permanent` | `trwaly` |
| `permanentError` | `bladTrwaly` |
| `ProcessingFailed` | `PrzetwarzanieNieudane` |
| `ProcessingSucceeded` | `PrzetwarzanieUdane` |
| `ProofreadFailed` | `KorektaNieudana` |
| `ProofreadSucceeded` | `KorektaUdana` |
| `Publish` | `Opublikuj` |
| `publish` | `opublikuj` |
| `RecordAuditEvent` | `ZapiszZdarzenieAudytowe` |
| `RejectAllAnswers` | `OdrzucWszystkieOdpowiedzi` |
| `RequestChanges` | `ZazadajPoprawek` |
| `Retire` | `Wycofaj` |
| `retire` | `wycofaj` |
| `RetryIngestion` | `PonowIngestie` |
| `RetryProcessing` | `PonowPrzetwarzanie` |
| `RetryProofread` | `PonowKorekte` |
| `Signals` | `Sygnaly` |
| `Start` | `Rozpocznij` |
| `Submit` | `Zglos` |
| `succeeded` | `udane` |
| `success` | `powodzenie` |
| `t01_start` | `t01_rozpoczecie` |
| `t02_cancelAssigned` | `t02_anulowaniePrzydzielonego` |
| `t03_cancelInProgress` | `t03_anulowanieWToku` |
| `t04_submit` | `t04_zgloszenie` |
| `t05_proofreadSucceeded` | `t05_korektaUdana` |
| `t06_proofreadFailed` | `t06_korektaNieudana` |
| `t07_cancelProofreadCheck` | `t07_anulowaniePrzySprawdzeniu` |
| `t08_submitForReview` | `t08_oddanieDoRecenzji` |
| `t09_cancelPeerReview` | `t09_anulowaniePrzyRecenzji` |
| `t10_approveAnswers` | `t10_zatwierdzenieOdpowiedzi` |
| `t11_rejectAllAnswers` | `t11_odrzucenieWszystkich` |
| `t12_requestChanges` | `t12_zadaniePoprawek` |
| `t13_processingSucceeded` | `t13_przetwarzanieUdane` |
| `t14_processingFailed` | `t14_przetwarzanieNieudane` |
| `t15_retryProofread` | `t15_ponowienieKorekty` |
| `t16_retryProcessing` | `t16_ponowieniePrzetwarzania` |
| `t17_ingestionSucceeded` | `t17_ingestiaUdana` |
| `t18_ingestionFailed` | `t18_ingestiaNieudana` |
| `t19_retryIngestion` | `t19_ponowienieIngestii` |
| `t20_endIngested` | `t20_koniecZaingestowany` |
| `t21_endRejected` | `t21_koniecOdrzucony` |
| `t22_endCancelled` | `t22_koniecAnulowany` |
| `transientError` | `bladPrzejsciowy` |
| `WorkflowSignal` | `SygnalPrzeplywu` |

## `07_Czynnosci.sysml`

| Kod / angielska nazwa | Nazwa w modelu |
|---|---|
| `answer` | `odpowiedz` |
| `answeringFork` | `rozwidlenieOdpowiadania` |
| `answeringJoin` | `zlaczenieOdpowiadania` |
| `AnswerToKnowledge` | `OdOdpowiedziDoWiedzy` |
| `BuildContext` | `ZbudujKontekst` |
| `buildContext` | `zbudujKontekst` |
| `BuildFindingsRecord` | `ZbudujRekordUstalen` |
| `buildRecord` | `zbudujRekord` |
| `buildUnits` | `zbudujJednostki` |
| `checkMerge` | `scalenieSprawdzenia` |
| `checkProofread` | `sprawdzKorekte` |
| `chunk` | `dziel` |
| `ChunkDocuments` | `DzielDokumenty` |
| `chunked` | `podzielone` |
| `CitePassages` | `CytujFragmenty` |
| `citePassages` | `cytujFragmenty` |
| `ClassifyRest` | `KlasyfikujReszte` |
| `classifyRest` | `klasyfikujReszte` |
| `cleaned` | `oczyszczony` |
| `CommentOnAnswers` | `KomentujOdpowiedzi` |
| `commentOnAnswers` | `komentujOdpowiedzi` |
| `comments` | `komentarze` |
| `corrected` | `poprawiony` |
| `cut` | `potnij` |
| `CutUnits` | `PotnijNaJednostki` |
| `decideAnswers` | `rozstrzygnijOdpowiedzi` |
| `decisions` | `decyzje` |
| `DropGarbage` | `OdrzucSmieci` |
| `dropGarbage` | `odrzucSmieci` |
| `embed` | `osadz` |
| `EmbedQuery` | `OsadzZapytanie` |
| `embedQuery` | `osadzZapytanie` |
| `EmbedUnits` | `OsadzJednostki` |
| `Enhance` | `Zredaguj` |
| `enhanced` | `zredagowany` |
| `fetch` | `pobierzZrodla` |
| `FetchSources` | `PobierzZrodla` |
| `FlagFindings` | `OznaczUstalenia` |
| `flagFindings` | `oznaczUstalenia` |
| `formatted` | `uporzadkowany` |
| `generate` | `generuj` |
| `GenerateAnswer` | `WygenerujOdpowiedz` |
| `grammarAfter` | `gramatykaPonownie` |
| `GrammarCheck` | `SprawdzGramatyke` |
| `index` | `indeksuj` |
| `IndexChunks` | `IndeksujFragmenty` |
| `labelled` | `oznaczone` |
| `Layout` | `Uloz` |
| `layout` | `uklad` |
| `LinkLines` | `PowiazLinie` |
| `linkLines` | `powiazLinie` |
| `OpenReview` | `OtworzRecenzje` |
| `openReview` | `otworzRecenzje` |
| `outcome` | `rozstrzygniecie` |
| `outcomeDecision` | `decyzjaWgWyniku` |
| `parse` | `parsuj` |
| `ParseDocuments` | `ParsujDokumenty` |
| `participant` | `uczestnik` |
| `perAnswer` | `dlaKazdejOdpowiedzi` |
| `queryFork` | `rozwidlenieZapytania` |
| `queryJoin` | `zlaczenieZapytania` |
| `RankAndFuse` | `RankujIFuzjuj` |
| `rankAndFuse` | `rankujIFuzjuj` |
| `raw` | `surowe` |
| `RecordRound` | `ZapiszRunde` |
| `recordRound` | `zapiszRunde` |
| `RefreshSparse` | `OdswiezWektoryRzadkie` |
| `refreshSparse` | `odswiezWektoryRzadkie` |
| `RefuseIngestion` | `OdmowyIngestii` |
| `refuseIngestion` | `odmowyIngestii` |
| `reviewFork` | `rozwidlenieRecenzji` |
| `reviewJoin` | `zlaczenieRecenzji` |
| `revisions` | `rewizje` |
| `round` | `runda` |
| `selectApproved` | `wybierzZatwierdzone` |
| `SelectApprovedAnswers` | `WybierzZatwierdzoneOdpowiedzi` |
| `SparseQuery` | `ZapytanieRzadkie` |
| `sparseQuery` | `zapytanieRzadkie` |
| `StartAnswering` | `RozpocznijOdpowiadanie` |
| `startAnswering` | `rozpocznijOdpowiadanie` |
| `Steps` | `Kroki` |
| `units` | `jednostki` |
| `upload` | `przeslij` |
| `UploadRaw` | `PrzeslijSurowe` |
| `ValidateAndSubmit` | `WalidujIZglos` |
| `vector` | `wektor` |
| `vectors` | `wektory` |
| `VoteOnAnswers` | `GlosujNaOdpowiedzi` |
| `votes` | `glosy` |
| `WriteAnswers` | `NapiszOdpowiedzi` |
| `writeAnswers` | `napiszOdpowiedzi` |
| `WriteChips` | `ZapiszChips` |
| `writeChips` | `zapiszChips` |

## `08_Interakcje.sysml`

| Kod / angielska nazwa | Nazwa w modelu |
|---|---|
| `callLlm` | `wywolajLlm` |
| `callTransition` | `wywolajPrzejscie` |
| `checkGrammar` | `sprawdzGramatyke` |
| `clickSubmit` | `klikZglos` |
| `DraftConflictInteraction` | `InterakcjaKonfliktuSzkicu` |
| `ElicitationInteractions` | `InterakcjeElicytacji` |
| `enterQuery` | `wpiszZapytanie` |
| `hybridSearch` | `wyszukiwanieHybrydowe` |
| `JobExecutionInteraction` | `InterakcjaWykonaniaZadania` |
| `KnowledgeSearchInteraction` | `InterakcjaWyszukiwaniaWiedzy` |
| `lockAssignment` | `zablokujPrzydzial` |
| `lockRow` | `zablokujWiersz` |
| `m01_click` | `m01_klik` |
| `m01_nextJob` | `m01_nastepneZadanie` |
| `m01_putDraft` | `m01_putSzkic` |
| `m01_query` | `m01_zapytanie` |
| `m02_conflict` | `m02_konflikt` |
| `m02_grammar` | `m02_gramatyka` |
| `m02_postSubmit` | `m02_postZgloszenie` |
| `m02_search` | `m02_wyszukanie` |
| `m03_embed` | `m03_osadzenie` |
| `m03_enhance` | `m03_redakcja` |
| `m03_lockAssignment` | `m03_blokadaPrzydzialu` |
| `m04_loadDraft` | `m04_wczytanieSzkicu` |
| `m04_vector` | `m04_wektor` |
| `m05_lock` | `m05_blokada` |
| `m05_transition` | `m05_przejscie` |
| `m06_record` | `m06_zapis` |
| `m06_rows` | `m06_wiersze` |
| `m06_stateAuditJob` | `m06_stanAudytZadanie` |
| `m07_hits` | `m07_trafienia` |
| `m07_transition` | `m07_przejscie` |
| `m08_show` | `m08_pokazanie` |
| `m08_stateAudit` | `m08_stanAudyt` |
| `m08_view` | `m08_widok` |
| `m09_show` | `m09_pokazanie` |
| `nextJob` | `nastepneZadanie` |
| `persistTransition` | `zapiszPrzejscie` |
| `querySearch` | `zapytajWyszukiwanie` |
| `readDraft` | `odczytajSzkic` |
| `receiveClick` | `odbierzKlik` |
| `receiveConflict` | `odbierzKonflikt` |
| `receiveDraft` | `odbierzSzkic` |
| `receiveEmbedding` | `odbierzOsadzenie` |
| `receiveHits` | `odbierzTrafienia` |
| `receiveQuery` | `odbierzZapytanie` |
| `receiveRows` | `odbierzWiersze` |
| `receiveSearch` | `odbierzWyszukiwanie` |
| `receiveSubmit` | `odbierzZgloszenie` |
| `receiveTransition` | `odbierzPrzejscie` |
| `receiveView` | `odbierzWidok` |
| `recordResult` | `zapiszWynik` |
| `renderView` | `wyswietlWidok` |
| `renewLease` | `odnowDzierzawe` |
| `requestCommit` | `zazadajCommit` |
| `requestDraft` | `zazadajSzkicu` |
| `requestEmbedding` | `zazadajOsadzenia` |
| `requestLock` | `zazadajBlokady` |
| `returnEmbedding` | `zwrocOsadzenie` |
| `returnRows` | `zwrocWiersze` |
| `seeHits` | `widziTrafienia` |
| `seeProofreading` | `widziKorekte` |
| `sendConflict` | `wyslijKonflikt` |
| `sendDraft` | `wyslijSzkic` |
| `sendHits` | `wyslijTrafienia` |
| `sendSearch` | `wyslijWyszukiwanie` |
| `sendSubmit` | `wyslijZgloszenie` |
| `sendView` | `wyslijWidok` |
| `SubmitAnswerInteraction` | `InterakcjaZgloszeniaOdpowiedzi` |
| `TransitionCall` | `WywolaniePrzejscia` |
| `UserIntent` | `ZamiarUzytkownika` |
| `writeRound` | `zapiszRundeWBazie` |
| `writeStateAudit` | `zapiszStanAudyt` |
| `writeStateAuditJob` | `zapiszStanAudytIZadanie` |

## `09_Analiza.sysml`

| Kod / angielska nazwa | Nazwa w modelu |
|---|---|
| `answerTokens` | `tokenyOdpowiedzi` |
| `bootstrapSamples` | `probyBootstrap` |
| `budget` | `budzet` |
| `budgetTokens` | `budzetTokenow` |
| `ceilingAt4` | `sufitAt4` |
| `claimsPer100Tokens` | `tezyNa100Tokenow` |
| `classifierFits` | `klasyfikatorSieMiesci` |
| `classifierOutputTokens` | `tokenyWyjsciaKlasyfikatora` |
| `contextBonus` | `premiaKontekstu` |
| `ContextBudget` | `BudzetKontekstu` |
| `contextScore` | `wynikKontekstu` |
| `contextTokens` | `tokenyKontekstu` |
| `ContextWeightedScore` | `WynikWazonyKontekstem` |
| `cueScore` | `wynikWskazowki` |
| `ElicitationAnalysis` | `AnalizaElicytacji` |
| `enhanceFits` | `redakcjaSieMiesci` |
| `enhanceOutputTokens` | `tokenyWyjsciaRedakcji` |
| `EvalRun` | `UruchomienieEwaluacji` |
| `ExpertContextBudget` | `BudzetKontekstuEkspertow` |
| `generatorModel` | `modelGeneratora` |
| `hitAt4` | `trafienieAt4` |
| `JudgedAnswerQuality` | `JakoscOdpowiedziWgSedziow` |
| `judgeModels` | `modeleSedziow` |
| `judgeThreshold` | `progOcenySedziow` |
| `llmCallBudget` | `budzetWywolanLlm` |
| `meanJudgeScore` | `sredniaOcenaSedziow` |
| `metrics` | `metryki` |
| `minMrr` | `minimalneMrr` |
| `minRecallAt4` | `minimalnaPelnoscAt4` |
| `mrrThreshold` | `progMrr` |
| `outputTokens` | `tokenyWyjscia` |
| `passed` | `zaliczone` |
| `promptTokens` | `tokenyPromptu` |
| `quality` | `jakosc` |
| `qualityObjective` | `celJakosci` |
| `RagEvaluation` | `EwaluacjaRag` |
| `ragQuality` | `jakoscRag` |
| `rank` | `pozycja` |
| `recallAt1` | `pelnoscAt1` |
| `recallAt4` | `pelnoscAt4` |
| `recallAt500Tokens` | `pelnoscPrzy500Tokenach` |
| `recallAt8` | `pelnoscAt8` |
| `recallThreshold` | `progPelnosci` |
| `ReciprocalRankFusionTerm` | `SkladnikFuzjiRrf` |
| `retrieval` | `wymogWyszukiwania` |
| `RetrievalMetrics` | `MetrykiWyszukiwania` |
| `RetrievalQuality` | `JakoscWyszukiwania` |
| `retriever` | `wyszukiwacz` |
| `run` | `uruchomienie` |
| `score` | `wynik` |
| `shownTokens` | `pokazaneTokeny` |

## `10_Platforma.sysml`

| Kod / angielska nazwa | Nazwa w modelu |
|---|---|
| `ActionAllocation` | `AlokacjaCzynnosci` |
| `ActionToPerformer` | `CzynnoscDlaWykonawcy` |
| `ContainerNode` | `WezelKontenerowy` |
| `databaseDev` | `bazaDev` |
| `databaseProd` | `bazaProd` |
| `DevAllocation` | `AlokacjaDev` |
| `DeveloperMachine` | `MaszynaDewelopera` |
| `DevPlatform` | `PlatformaDev` |
| `devPlatform` | `platformaDev` |
| `ElicitationPlatform` | `PlatformaElicytacji` |
| `exposedPort` | `wystawionyPort` |
| `image` | `obraz` |
| `migrate` | `migracja` |
| `Nodes` | `Wezly` |
| `objectStoreDev` | `magazynObiektowDev` |
| `ProdAllocation` | `AlokacjaProd` |
| `ProdPlatform` | `PlatformaProd` |
| `prodPlatform` | `platformaProd` |
| `researchDev` | `badaniaDev` |
| `SoftwareToNode` | `OprogramowanieNaWezle` |

## `11_Sledzenie.sysml`

| Kod / angielska nazwa | Nazwa w modelu |
|---|---|
| `apiAnswers` | `apiOdpowiedzi` |
| `ApiAnswersTest` | `TestApiOdpowiedzi` |
| `apiAuth` | `apiUwierzytelnianie` |
| `ApiAuthTest` | `TestApiUwierzytelniania` |
| `apiFoundation` | `apiPodstawy` |
| `ApiFoundationTest` | `TestApiPodstaw` |
| `apiKnowledge` | `apiWiedza` |
| `apiKnowledgeRemoval` | `apiUsuwanieWiedzy` |
| `ApiKnowledgeRemovalTest` | `TestApiUsuwaniaWiedzy` |
| `ApiKnowledgeTest` | `TestApiWiedzy` |
| `apiPipeline` | `apiPotok` |
| `ApiPipelineTest` | `TestApiPotoku` |
| `apiReviews` | `apiRecenzje` |
| `ApiReviewsTest` | `TestApiRecenzji` |
| `apiRevisions` | `apiRewizje` |
| `ApiRevisionsTest` | `TestApiRewizji` |
| `apiVignettes` | `apiWiniety` |
| `ApiVignettesTest` | `TestApiWiniet` |
| `ApiWorkerTest` | `TestApiWorkera` |
| `apiWorkflow` | `apiPrzeplyw` |
| `ApiWorkflowTest` | `TestApiPrzeplywu` |
| `ClassifierTest` | `TestKlasyfikatora` |
| `ElicitationTraceability` | `SledzenieElicytacji` |
| `expertRagContract` | `kontraktRagEksperckiego` |
| `ExpertRagContractTest` | `TestKontraktuRagEksperckiego` |
| `FindingsTest` | `TestUstalen` |
| `ProofreadTest` | `TestKorekty` |
| `ragEvaluation` | `ewaluacjaRag` |
| `RagEvaluationRun` | `UruchomienieEwaluacjiRag` |
| `RankingTest` | `TestRankingu` |
| `Satisfaction` | `Spelnianie` |
| `Verification` | `Weryfikacja` |
| `VerificationPlan` | `PlanWeryfikacji` |
| `workflowStates` | `stanyPrzeplywu` |
| `WorkflowStatesTest` | `TestStanowPrzeplywu` |

## `12_Widoki.sysml`

| Kod / angielska nazwa | Nazwa w modelu |
|---|---|
| `ActionView` | `WidokCzynnosci` |
| `allocationMatrix` | `macierzAlokacji` |
| `answerToKnowledge` | `odOdpowiedziDoWiedzy` |
| `asActionFlowDiagram` | `jakoDiagramCzynnosci` |
| `asPackageDiagram` | `jakoDiagramPakietow` |
| `asParametricDiagram` | `jakoDiagramParametryczny` |
| `asRequirementDiagram` | `jakoDiagramWymagan` |
| `asSequenceDiagram` | `jakoDiagramSekwencji` |
| `assignmentStates` | `stanyPrzydzialu` |
| `asStateTransitionDiagram` | `jakoDiagramStanow` |
| `asUseCaseDiagram` | `jakoDiagramPrzypadkowUzycia` |
| `backendDecomposition` | `dekompozycjaBackendu` |
| `corpusIngestion` | `ingestiaKorpusu` |
| `DefinitionView` | `WidokDefinicji` |
| `developmentDeployment` | `wdrozenieDeweloperskie` |
| `domainModel` | `modelDziedziny` |
| `ElicitationViews` | `WidokiElicytacji` |
| `InterconnectionView` | `WidokPolaczen` |
| `interfaces` | `interfejsy` |
| `jobSequence` | `sekwencjaZadania` |
| `jobStates` | `stanyZadania` |
| `llmBudget` | `budzetLlm` |
| `modelOrganisation` | `organizacjaModelu` |
| `PackageView` | `WidokPakietow` |
| `ParametricView` | `WidokParametryczny` |
| `productionDeployment` | `wdrozenieProdukcyjne` |
| `proofreadPipeline` | `potokKorekty` |
| `ragDataModel` | `modelDanychRag` |
| `ragQualityParametrics` | `parametrykaJakosciRag` |
| `ragQuery` | `zapytanieRag` |
| `Renderings` | `Renderowania` |
| `requirements` | `wymagania` |
| `RequirementView` | `WidokWymagan` |
| `searchSequence` | `sekwencjaWyszukiwania` |
| `SequenceView` | `WidokSekwencji` |
| `StateView` | `WidokStanow` |
| `submitSequence` | `sekwencjaZgloszenia` |
| `systemContext` | `kontekstSystemu` |
| `systemDecomposition` | `dekompozycjaSystemu` |
| `systemInternal` | `wnetrzeSystemu` |
| `TableView` | `WidokTabelaryczny` |
| `traceabilityMatrix` | `macierzSledzenia` |
| `unitsAndIngestion` | `jednostkiIIngestia` |
| `useCases` | `przypadkiUzycia` |
| `UseCaseView` | `WidokPrzypadkowUzycia` |
| `vignetteStates` | `stanyWiniety` |

## Elementy dodane 2026-11-17 (kod → model)

Elementy, które nie miały angielskiej wersji modelu. Kolumna lewa to nazwa w kodzie (lub plik, gdy
element odpowiada plikowi albo konfiguracji).

### `13_SciezkaPrzetwarzania.sysml`

| Kod | Nazwa w modelu |
|---|---|
| ścieżka od zgłoszenia do `chips` | `SciezkaPrzetwarzania`, `SciezkaPrzetwarzaniaWiniety`, `sciezka` |
| `assigned_by` (`chip`, `quote`, `llm`, `expert`) | `ZrodloPowiazania` (`chip`, `cytat`, `model`, `ekspert`) |
| odpowiedź na pytanie w trakcie korekty | `TekstOdpowiedzi` |
| `Proofread` (pipeline.py) | `WynikKorektyOdpowiedzi` |
| linia `{text, targets, assigned_by}` | `LiniaOdpowiedzi` (`tekst`, `cele`, `zrodlo`) |
| flaga `findings.check` | `FlagaUstalen` |
| wynik `proofread.service.prepare` | `PrzygotowanaKorekta` |
| `Ingestion` (ingest.py) | `PakietIngestii` |
| wiersze sesji w `chips` | `WierszeChips` |
| `Probe` (compute.py) | `ProbaMocy` |
| `transition()` z `require_compute` | `BramkaPrzejsc` |
| `app/compute.py` | `BramkaMocyObliczeniowej` (w 04: `ModulMocyObliczeniowej`, część `mocObliczeniowa`) |
| `watch()` | `obserwator` |
| `require_compute()` | `sprawdzenieDlaApi` |
| `ready_kinds()` | `gotoweRodzaje` |
| `is_down_for()` | `awariaPoBledzie` |
| `REQUIRE_COMPUTE` | `wymaganaMoc` |
| `TIMEOUT`, `WATCH_EVERY`, `API_TRUSTS`, `WORKER_TRUSTS` | `limitCzasuSondy`, `odstepSondowania`, `waznoscSondyDlaApi`, `waznoscSondyDlaWorkera` |
| tabela `jobs` + `next_job()` | `KolejkaZadan` |
| `main()` / `run_once()` (worker.py) | `PetlaWorkera` |
| `PREPARE`, `HANDLERS`, `CORPUS_HANDLERS` | `rozdzielacz` |
| `_heartbeat()` | `pulsDzierzawy` |
| `_alive()`, `ALIVE_FILE` | `sygnalZycia`, `plikZycia` |
| `PermanentJobError` + `is_down_for` + `MAX_ATTEMPTS` | `politykaPonowien` |
| `assignments.service.submit` | `PrzyjecieZgloszenia` |
| `proofread.service.save`, `submit_for_review` | `SprawdzenieAutora` |
| `reviews.service.submit_decisions` | `RozstrzygniecieAdministratora` |
| `garbage.drop_garbage` | `FiltrSmieci` |
| `grammar.check` | `KorektorGramatyki` |
| `enhance.enhance` | `RedaktorLlm` |
| `layout()` | `UkladZdan` |
| `proofread_answer()` | `KorektaOdpowiedzi` |
| `response_from_submission` + `expert_highlights` | `RozbiorZgloszenia` |
| `links.link_lines` | `WiazanieLinii` |
| `classifier.classify` (`classify_rest`) | `KlasyfikatorZdan` |
| `findings.check` | `KontrolaUstalen` |
| `proofread.service.prepare` | `PrzygotowanieKorekty` |
| `proofread.service.record` | `ZapisRundy` |
| zadanie `proofread` | `EtapKorekty` |
| wybór zatwierdzonych odpowiedzi (`handlers.process`) | `WyborZatwierdzonych` |
| `findings.record_from_lines` | `BudowaRekorduUstalen` |
| `findings.build_units` | `PodzialNaJednostki` |
| zapis `AnswerFindings` + `KnowledgeUnit` | `ZapisJednostek` |
| zadanie `process` | `EtapCiecia` |
| `ingest.load` | `WczytanieDoIngestii` |
| `ingest.embed`, `embedding.embed_texts` | `OsadzanieJednostek` |
| `ingest.write` | `ZapisChips` |
| `BM25_LOCK`, `TIER` | `kluczBlokadyBm25`, `poziomWiniet` |
| `ingest.refresh_sparse` | `OdswiezenieBm25` |
| zadanie `ingest` | `EtapIngestii` |
| tabele `app` na ścieżce | `MagazynStanuPrzeplywu` (`magazynStanu`) |
| schemat `chips` | `MagazynWiedzyRag` (`magazynWiedzy`) |
| porty artefaktów | `PortSygnalu`, `PortZgloszenia`, `PortZadania`, `PortStanuMocy`, `PortTekstu`, `PortCytatow`, `PortWynikuKorekty`, `PortLinii`, `PortFlag`, `PortPrzygotowanejKorekty`, `PortRewizji`, `PortRundy`, `PortDecyzji`, `PortUstalen`, `PortPakietuIngestii`, `PortWierszyChips`, `PortZdarzen` |
| alokacja części ścieżki | `AlokacjaSciezki`, `CzescSciezkiWModule`, `p01`..`p17` |

### Zmiany w pozostałych plikach

| Kod | Nazwa w modelu | Plik |
|---|---|---|
| `GET /api/tags` / lista modeli | `ZapytanieListyModeli` / `ListaModeli` | `03` |
| `GET /v2/languages` | `ZapytanieListyJezykow` / `ListaJezykow` | `03` |
| `filters.py` (`ExpertFilter`) | `filtry` | `04` |
| `prompts/expert_personas` | `personyEkspertow` | `04` |
| `ready_kinds` przy pobraniu | `Przejmij.rodzajGotowy` | `06` |
| `is_down_for` po błędzie | `ZadanieZBledem.mocNiedostepna`, przejście `czekanieNaMoc` | `06` |
| `run_once()` | `WykonanieZadania` | `07` |
| `/assignments/{id}/submit` przy wyłączonym PC | `InterakcjaOdmowyBezMocy` | `08` |
| `require_compute` / `details.missing` | `WywolanieSprawdzeniaMocy` / `BrakiMocy` | `08` |
| `mem_limit` (infra/azure/docker-compose.yml) | `BudzetPamieciVm`, `budzetPamieciVm` | `09` |
| `LEASE / 3` vs `LEASE`; wiek sondy | `OdnowienieDzierzawy`, `SwiezoscSondy`, `niezawodnoscZadan` | `09` |
| Azure VM (Standard_B2s) | `MaszynaWirtualna`, `vm` | `10` |
| komputer właściciela (PC_HOST) | `KomputerWlasciciela`, `pc` | `10` |
| tailnet | `SiecTailscale`, `tailnet` | `10` |
| ghcr.io | `RejestrObrazow`, `rejestr` | `10` |
| GitHub Actions (ci.yml, deploy.yml) | `RunnerGithubActions`, `PlatformaCiCd`, `platformaCiCd` | `10` |
| `backup.sh`, `deploy.sh` | `kopiaZapasowa`, `skryptWdrozenia` | `10` |
| `pytest -m integration`, `rag_<pid>_test` | `SrodowiskoTestowe`, `srodowiskoTestowe` | `10` |
| workflow Deploy | `WdrozenieWydania` | `10` |
| wymagania wdrożeniowe | `gotowoscMocyPrzedZadaniem` (WYM-N-16), `zadaniaCzekajaNaMoc` (WYM-N-17), `kontrolaZdrowiaUslug` (WYM-N-18), `kopieZapasoweBazy` (WYM-N-19), `ograniczonaEkspozycjaSieci` (WYM-N-20) | `01` |
| workflow Deploy (przypadek użycia) | `WdrozWydanie` | `02` |
| katalogi / znaczniki testów | `PoziomTestu`, `PrzypadekTestowy` (`poziom`, `wCi`) | `11` |
| tests/unit/test_answers_rules.py | `TestRegulOdpowiedzi` | `11` |
| tests/api/test_api_schema.py | `TestApiSchematu` | `11` |
| tests/api/test_api_gaps.py | `TestApiLuk` | `11` |
| tests/test_links.py | `TestPowiazanLinii` | `11` |
| tests/api/test_api_silver_workflow.py | `TestApiSrebrnegoPrzeplywu` | `11` |
| tests/test_load_chips_guard.py | `TestStrazyLadowaniaChips` | `11` |
| tests/unit/test_jobs_unit.py | `TestTabelZadan` | `11` |
| tests/unit/test_compute.py | `TestMocyObliczeniowej` | `11` |
| tests/api/test_api_compute.py | `TestApiMocy` | `11` |
| tests/api/test_api_expert_rag.py | `TestApiRagEksperckiego` | `11` |
| .../integration/test_silver_database.py | `TestSrebrnejBazy` | `11` |
| .../integration/test_crowded_vignette.py | `TestZatloczonejWiniety` | `11` |
| tests/integration/test_retrieval_regression.py | `TestRegresjiWyszukiwania` | `11` |
| frontend/src/__tests__ | `TestyFrontenduPrzeplywu`, `TestyFrontenduDostepu`, `TestyFrontenduWiedzy` | `11` |
| test dymny (deploy.yml) | `TestDymnyWdrozenia` | `11` |
| nowe widoki | `sciezkaPrzetwarzaniaBdd`, `sciezkaPrzetwarzaniaIbd`, `wnetrzeKorekty`, `wnetrzeCieciaIIngestii`, `alokacjaSciezki`, `wykonanieZadania`, `sekwencjaOdmowyBezMocy`, `parametrykaWdrozenia`, `platformaCiCd`, `potokWdrozenia`, `planTestow` | `12` |

Usunięte razem z Render i Neon: `BazaZarzadzana`, `punktZPula`, `punktBezposredni`, `wezelWorkera`,
`wezelOllama`, `deweloper`, `TestUrlBazy` (`tests/unit/test_db_url.py` sprawdza już tylko nazwę sterownika).
