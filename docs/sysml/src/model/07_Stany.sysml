package StanyElicytacji {
    doc /*
     * Maszyny stanów (State Transition View). Nazwy stanów, akcji i aktorów są wartościami z kodu.
     *   AssignmentLifecycle - cykl życia przydziału, 1:1 z TRANSITIONS w
     *                         backend/app/assignments/state_machine.py (19 przejść tNN_<akcja>,
     *                         w kolejności z kodu; strażnik = aktor uprawniony do akcji)
     *   JobLifecycle        - cykl życia zadania w kolejce (backend/app/jobs/worker.py)
     * Sygnał przepływu niesie aktora (`'actor'`), strażnik sprawdza go jak check_transition().
     * Prefiks tNN_ w nazwach przejść odróżnia powtórzone akcje (cancel z czterech stanów).
     * Obie maszyny łączą się w dwie strony: wejście przydziału w stan zadania tworzy Job
     * (EnqueueJob, JOB_ON_ENTRY), a koniec zadania wysyła do przydziału sygnał *_succeeded albo
     * *_failed (ReportJobResult, SUCCESS_ACTION / FAILURE_ACTION w worker.py).
     */

    private import ScalarValues::*;
    private import BibliotekaElicytacji::*;
    private import StrukturaElicytacji::Data::Assignment;

    // =================================================================== enums (values from code)
    enum def State {
        doc /* Stan przydziału (Assignment.state). */
        @OdwolanieDoKodu { sciezka = "backend/app/assignments/states.py"; }
        enum assigned;
        enum in_progress;
        enum proofreading;          // zadanie proofread
        enum proofread_check;       // autor sprawdza korektę
        enum peer_review;
        enum processing;            // zadanie process
        enum processing_failed;     // wspólny dla nieudanej korekty i nieudanego process
        enum ingesting;             // zadanie ingest
        enum ingestion_failed;
        enum ingested;
        enum rejected;
        enum cancelled;
    }

    enum def Action {
        doc /* Akcja przepływu (argument transition()). */
        @OdwolanieDoKodu { sciezka = "backend/app/assignments/states.py"; }
        enum start;
        enum cancel;
        enum submit;
        enum proofread_succeeded;
        enum proofread_failed;
        enum submit_for_review;
        enum processing_succeeded;
        enum processing_failed;
        enum retry_proofread;
        enum retry_processing;
        enum retry_ingestion;
        enum approve_answers;
        enum request_changes;
        enum reject_all_answers;
        enum ingestion_succeeded;
        enum ingestion_failed;
    }

    enum def Actor {
        doc /* Kto wykonuje akcję: assignee (ekspert-autor), admin (inżynier wiedzy), reviewer, system (worker). */
        @OdwolanieDoKodu { sciezka = "backend/app/assignments/states.py"; }
        enum assignee;
        enum admin;
        enum reviewer;
        enum system;
    }

    enum def JobKind {
        @OdwolanieDoKodu { sciezka = "backend/app/jobs/models.py"; }
        enum proofread;
        enum process;
        enum ingest;
        enum refit;                 // zadanie korpusu, bez przydziału
    }

    enum def JobStatus {
        @OdwolanieDoKodu { sciezka = "backend/app/jobs/models.py"; }
        enum queued;
        enum running;
        enum done;
        enum failed;
    }

    // =================================================================== signals
    package Signals {
        doc /* Jeden sygnał na akcję przepływu; `'actor'` = kto ją wykonuje. */

        item def WorkflowSignal {
            attribute 'actor' : Actor;
        }
        item def Start :> WorkflowSignal;
        item def Cancel :> WorkflowSignal;
        item def Submit :> WorkflowSignal;
        item def ProofreadSucceeded :> WorkflowSignal;
        item def ProofreadFailed :> WorkflowSignal;
        item def SubmitForReview :> WorkflowSignal;
        item def ProcessingSucceeded :> WorkflowSignal;
        item def ProcessingFailed :> WorkflowSignal;
        item def RetryProofread :> WorkflowSignal;
        item def RetryProcessing :> WorkflowSignal;
        item def RetryIngestion :> WorkflowSignal;
        item def ApproveAnswers :> WorkflowSignal;
        item def RequestChanges :> WorkflowSignal;
        item def RejectAllAnswers :> WorkflowSignal;
        item def IngestionSucceeded :> WorkflowSignal;
        item def IngestionFailed :> WorkflowSignal;

        // zadania
        item def Claim {
            doc /* Worker pobiera zadanie; kind_ready = rodzaj jest w compute.ready_kinds() (albo bramka wyłączona). */
            attribute kind_ready : Boolean;
        }
        item def JobSucceeded;
        item def JobError {
            doc /*
             * permanent = PermanentJobError (np. NoUnits, UnitsNotEmbeddable);
             * compute_down = compute.is_down_for(kind) po błędzie (komputer z modelami nie działa).
             */
            attribute permanent : Boolean;
            attribute compute_down : Boolean;
        }
        item def LeaseExpired;
    }

    private import Signals::*;

    action def EnqueueJob {
        doc /* JOB_ON_ENTRY: wejście w stan zadania tworzy Job tego rodzaju w tej samej transakcji. */
        @OdwolanieDoKodu { sciezka = "backend/app/assignments/state_machine.py"; }
        in kind : JobKind;
    }

    action def ReportJobResult {
        doc /*
         * Koniec zadania -> sygnał do przydziału, w tej samej transakcji: po done worker woła
         * transition(SUCCESS_ACTION[kind], system), po failed _fail() woła
         * transition(FAILURE_ACTION[kind], system). Zadanie korpusu (refit, bez przydziału)
         * niczego nie wysyła.
         */
        @OdwolanieDoKodu { sciezka = "backend/app/jobs/worker.py"; }
        in jobKind : JobKind;
        in succeeded : Boolean;
        in item target : Assignment[0..1];   // brak dla refit

        first start then wgRodzaju;
        decide wgRodzaju;
            if succeeded and jobKind == JobKind::proofread then proofread_succeeded;
            if succeeded and jobKind == JobKind::process then processing_succeeded;
            if succeeded and jobKind == JobKind::ingest then ingestion_succeeded;
            if not succeeded and jobKind == JobKind::proofread then proofread_failed;
            if not succeeded and jobKind == JobKind::process then processing_failed;
            if not succeeded and jobKind == JobKind::ingest then ingestion_failed;
            else done;   // refit

        // SUCCESS_ACTION
        action proofread_succeeded send ProofreadSucceeded(Actor::system) to target;
        action processing_succeeded send ProcessingSucceeded(Actor::system) to target;
        action ingestion_succeeded send IngestionSucceeded(Actor::system) to target;
        // FAILURE_ACTION
        action proofread_failed send ProofreadFailed(Actor::system) to target;
        action processing_failed send ProcessingFailed(Actor::system) to target;
        action ingestion_failed send IngestionFailed(Actor::system) to target;
    }

    // =================================================================== assignment
    state def AssignmentLifecycle {
        doc /*
         * Cykl życia przydziału. W stanach zadań (proofreading, processing, ingesting) pracuje
         * worker; frontend odpytuje API, gdy widzi jeden z nich (JOB_STATES).
         * processing_failed jest wspólny dla nieudanej korekty i nieudanego process. Inżynier wiedzy
         * wybiera tylko "retry"; którą akcję dostaje przydział, rozstrzyga rodzaj ostatniego
         * nieudanego zadania (retry() i RETRY_BY_JOB w assignments/service.py) - strażnik t15/t16.
         * Z REQUIRE_COMPUTE przejście osoby do stanu zadania (t04, t10, t15, t16, t19) najpierw
         * sprawdza komputer z modelami; gdy nie jest gotowy: 503 compute_unavailable i przejście
         * nie zachodzi. Przejść systemu (np. t13) się nie sprawdza: worker sam wstrzymuje zadanie
         * (JobLifecycle).
         */
        @OdwolanieDoKodu { sciezka = "backend/app/assignments/state_machine.py"; }

        attribute last_failed_kind : JobKind[0..1] {
            doc /* Job.kind najnowszego zadania tego przydziału w stanie failed (zapytanie w retry()). */
        }

        entry; then assigned;

        state assigned;
        state in_progress {
            doc /* Odpowiadanie; autozapis szkicu. */
        }
        state proofreading {
            entry action enqueue : EnqueueJob { in kind = JobKind::proofread; }
        }
        state proofread_check {
            doc /* Autor sprawdza korektę i powiązania; wraca tu po request_changes (nowa runda). */
        }
        state peer_review {
            doc /* Komentarze i głosy recenzentów; decyduje inżynier wiedzy (admin). */
        }
        state processing {
            entry action enqueue : EnqueueJob { in kind = JobKind::process; }
        }
        state processing_failed;
        state ingesting {
            entry action enqueue : EnqueueJob { in kind = JobKind::ingest; }
        }
        state ingestion_failed;
        state ingested;
        state rejected;
        state cancelled;

        // ---------------------------------------------------- TRANSITIONS (19)
        transition t01_start
            first assigned
            accept s : Start if s.'actor' == Actor::assignee
            then in_progress;

        transition t02_cancel
            first assigned
            accept s : Cancel if s.'actor' == Actor::admin
            then cancelled;

        transition t03_cancel
            first in_progress
            accept s : Cancel if s.'actor' == Actor::admin
            then cancelled;

        transition t04_submit
            first in_progress
            accept s : Submit if s.'actor' == Actor::assignee
            then proofreading;

        transition t05_proofread_succeeded
            first proofreading
            accept s : ProofreadSucceeded if s.'actor' == Actor::system
            then proofread_check;

        transition t06_proofread_failed
            first proofreading
            accept s : ProofreadFailed if s.'actor' == Actor::system
            then processing_failed;

        transition t07_cancel
            first proofread_check
            accept s : Cancel if s.'actor' == Actor::admin
            then cancelled;

        transition t08_submit_for_review
            first proofread_check
            accept s : SubmitForReview if s.'actor' == Actor::assignee
            then peer_review;

        transition t09_cancel
            first peer_review
            accept s : Cancel if s.'actor' == Actor::admin
            then cancelled;

        transition t10_approve_answers
            first peer_review
            accept s : ApproveAnswers if s.'actor' == Actor::admin
            then processing;

        transition t11_reject_all_answers
            first peer_review
            accept s : RejectAllAnswers if s.'actor' == Actor::admin
            then rejected;

        transition t12_request_changes
            first peer_review
            accept s : RequestChanges if s.'actor' == Actor::admin
            then proofread_check;

        transition t13_processing_succeeded
            first processing
            accept s : ProcessingSucceeded if s.'actor' == Actor::system
            then ingesting;

        transition t14_processing_failed
            first processing
            accept s : ProcessingFailed if s.'actor' == Actor::system
            then processing_failed;

        transition t15_retry_proofread
            first processing_failed
            accept s : RetryProofread if s.'actor' == Actor::admin and last_failed_kind == JobKind::proofread
            then proofreading;

        transition t16_retry_processing
            first processing_failed
            accept s : RetryProcessing if s.'actor' == Actor::admin and last_failed_kind == JobKind::process
            then processing;

        transition t17_ingestion_succeeded
            first ingesting
            accept s : IngestionSucceeded if s.'actor' == Actor::system
            then ingested;

        transition t18_ingestion_failed
            first ingesting
            accept s : IngestionFailed if s.'actor' == Actor::system
            then ingestion_failed;

        transition t19_retry_ingestion
            first ingestion_failed
            accept s : RetryIngestion if s.'actor' == Actor::admin
            then ingesting;

        // stany końcowe (TERMINAL_STATES)
        transition t20_end_ingested first ingested then done;
        transition t21_end_rejected first rejected then done;
        transition t22_end_cancelled first cancelled then done;
    }

    // =================================================================== job
    state def JobLifecycle {
        doc /*
         * Zadanie w kolejce (next_job: najstarsze queued albo running z wygasłą dzierżawą,
         * SKIP LOCKED, tylko rodzaje gotowe). Błąd przejściowy wraca do kolejki; błąd przy
         * niedziałającym komputerze z modelami wraca do kolejki bez zużycia próby; błąd trwały
         * lub ostatnia próba kończy porażką. Wejście w finished / failed wysyła do przydziału
         * sygnał *_succeeded / *_failed (ReportJobResult); zadanie refit nie ma przydziału.
         * Stan `finished` = JobStatus.done (nazwa `done` zajęta przez bibliotekę SysML).
         */
        @OdwolanieDoKodu { sciezka = "backend/app/jobs/worker.py"; }

        attribute kind : JobKind;
        ref item assignment : Assignment[0..1];   // brak dla refit
        attribute attempts : Integer = 0;
        attribute MAX_ATTEMPTS : Integer = 3;     // JobQueue.MAX_ATTEMPTS

        entry; then queued;

        state queued;
        state running {
            doc /* Dzierżawa LEASE (5 min), odnawiana co 1/3 dzierżawy (_heartbeat); attempts + 1. */
        }
        state finished {
            doc /* JobStatus.done; przydział dostaje *_succeeded (SUCCESS_ACTION). */
            entry action report : ReportJobResult {
                in jobKind = kind;
                in succeeded = true;
                in item target = assignment;
            }
        }
        state failed {
            doc /* JobStatus.failed (_fail); przydział dostaje *_failed (FAILURE_ACTION). */
            entry action report : ReportJobResult {
                in jobKind = kind;
                in succeeded = false;
                in item target = assignment;
            }
        }

        transition claim
            first queued
            accept c : Claim if c.kind_ready and attempts < MAX_ATTEMPTS
            then running;

        transition claim_exhausted
            first queued
            accept c : Claim if c.kind_ready and attempts >= MAX_ATTEMPTS
            then failed;

        transition succeeded
            first running
            accept JobSucceeded
            then finished;

        // próba się nie liczy (attempts - 1); last_error zostaje zapisany
        transition wait_for_compute
            first running
            accept e : JobError if not e.permanent and e.compute_down
            then queued;

        transition transient_error
            first running
            accept e : JobError if not e.permanent and not e.compute_down and attempts < MAX_ATTEMPTS
            then queued;

        transition permanent_error
            first running
            accept e : JobError if e.permanent or (not e.compute_down and attempts >= MAX_ATTEMPTS)
            then failed;

        transition lease_expired
            first running
            accept LeaseExpired
            then queued;

        transition end_finished first finished then done;
        transition end_failed first failed then done;
    }
}
