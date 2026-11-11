<script setup lang="ts">
import {
  computed,
  nextTick,
  onMounted,
  onUnmounted,
  ref,
  watch,
  type ComponentPublicInstance,
} from 'vue'
import { onBeforeRouteLeave, RouterLink, useRouter } from 'vue-router'

import {
  addCitation,
  citationCounts,
  removeCitation,
  uncitedChips,
  type Answers,
} from '@/answering/highlights'
import { chipFocus, markFor, provideQuoteFocus } from '@/answering/quoteFocus'
import {
  firstOpenStep,
  firstProblem,
  forSaving,
  REVIEW,
  stepProblem,
  type StepId,
} from '@/answering/steps'
import { plainText } from '@/answering/plainText'
import { useAnswerDraft } from '@/answering/useAnswerDraft'
import type { Citation, Direction, LinkedHighlight, Q4Answer, QuestionView } from '@/api/client'
import CitationTable from '@/components/answering/CitationTable.vue'
import ConfirmDialog from '@/components/answering/ConfirmDialog.vue'
import ProofreadStep from '@/components/answering/ProofreadStep.vue'
import QuestionBlock from '@/components/answering/QuestionBlock.vue'
import ReviewStep from '@/components/answering/ReviewStep.vue'
import StepRail, { type RailStep } from '@/components/answering/StepRail.vue'
import LoadingSpinner from '@/components/LoadingSpinner.vue'
import UnsavedText from '@/components/answering/UnsavedText.vue'
import VignetteText from '@/components/answering/VignetteText.vue'
import {
  describeError,
  directionNeeded,
  FRAMING_LABELS,
  notMentioned,
  removalNote,
  renumberNote,
  saveRefusal,
} from '@/copy'
import { useAuthStore } from '@/stores/auth'

const props = defineProps<{ id: string }>()

/** After proofreading: the edited answers are what the expert sees, checks and later reads. */
const PROOFREAD_STATES = [
  'proofread_check',
  'peer_review',
  'processing',
  'processing_failed',
  'ingesting',
  'ingestion_failed',
  'ingested',
  'rejected',
]
const POLL_MS = 4000

const router = useRouter()
const auth = useAuthStore()
const draft = useAnswerDraft(props.id)
const { view, payload, status, saveProblem, editable } = draft

const loading = ref(true)
const loadError = ref('')
const actionError = ref('')
const notice = ref('')
const step = ref<StepId>('Q1')
/** The quote pointed at, anywhere on this page: answers, tags and the quote table set it. */
const focus = provideQuoteFocus()
const activeChip = chipFocus(focus)
const pulseChip = ref<number | null>(null)
const dialog = ref<'submit' | null>(null)
/** The proofread round's quotes, with the words answers quoted without marking them. */
const proofHighlights = ref<LinkedHighlight[]>([])
/** Submitted before proofreading existed, or proofreading failed: there is no edited text. */
const noProofread = ref(false)
let pollTimer: ReturnType<typeof setInterval> | undefined
const removing = ref<number | null>(null)
const busy = ref(false)
/** The expert pressed the main button with something missing: from then on, show what and where. */
const attempted = ref(false)
const flashKey = ref(0)
let pulseTimer: ReturnType<typeof setTimeout> | undefined

const column = ref<HTMLElement>()
const blocks = new Map<string, InstanceType<typeof QuestionBlock>>()

const vignette = computed(() => view.value?.vignette ?? null)
const questions = computed(() => vignette.value?.questions ?? [])
const citations = computed<Citation[]>(() => payload.value.highlights)
const answers = computed<Answers>(() => payload.value.answers)
const submitted = computed(() => Boolean(view.value?.submitted_at))
const state = computed(() => view.value?.state)
const proofreading = computed(() => state.value === 'proofreading')
const showProofread = computed(
  () => PROOFREAD_STATES.includes(state.value ?? '') && !noProofread.value,
)

/** What the case text lights up: the expert's quote, or words an edited answer quotes. */
const activeMark = computed(
  () =>
    citations.value.find((c) => c.chip === activeChip.value) ??
    markFor(focus.value, proofHighlights.value),
)
/** What will be saved and submitted: the screen may remember Q4 parts that are hidden right now. */
const submittable = computed(() => forSaving(payload.value))
const uncited = computed(() => uncitedChips(citations.value, submittable.value.answers))
const undirected = computed(() => citations.value.filter((c) => !c.direction).map((c) => c.chip))

const counts = computed(() => citationCounts(citations.value, submittable.value.answers))

/** Whether a question has a box on screen that a reference can go into. */
function hasAnswerBox(question: QuestionView): boolean {
  if (!editable.value) return false
  if (question.kind === 'open') return true
  return question.kind === 'shift' && Boolean(payload.value.q4?.shift)
}

/** The box a clicked quote goes into: the question being worked on, or else the first with a box. */
const insertTarget = computed(() => {
  if (step.value === REVIEW) return null
  const open = questions.value.filter(hasAnswerBox)
  return (open.find((q) => q.id === step.value) ?? open[0])?.id ?? null
})
const canInsert = computed(() => insertTarget.value !== null)

/** The first thing missing from any question. */
const anyProblem = computed(() => firstProblem(questions.value, payload.value))

function directionProblem(): string | null {
  return undirected.value.length ? directionNeeded(undirected.value) : null
}

/** Why the main button can't be pressed. */
const blocker = computed<string | null>(() => {
  if (step.value === REVIEW) return anyProblem.value ?? directionProblem()
  return anyProblem.value
})

/** What is missing, by question, for the questions that can still be changed. */
const stepProblems = computed<Record<string, string>>(() => {
  const found: Record<string, string> = {}
  if (!editable.value) return found
  for (const q of questions.value) {
    const problem = stepProblem(q, payload.value)
    if (problem) found[q.id] = problem
  }
  return found
})

/** What to show on a question once the expert has tried to go on without it. */
function shownProblem(id: string): string | null {
  return attempted.value ? (stepProblems.value[id] ?? null) : null
}

const railSteps = computed<RailStep[]>(() => {
  const steps: RailStep[] = questions.value.map((q) => ({
    id: q.id,
    label: q.id,
    reachable: true,
    problem: shownProblem(q.id),
  }))
  steps.push({ id: REVIEW, label: 'Review', reachable: !anyProblem.value })
  return steps
})

const saveLabel = computed(() => {
  if (submitted.value) return 'Submitted'
  return {
    saved: 'Saved',
    unsaved: 'Not saved yet',
    saving: 'Saving…',
    failed: "Can't reach the server. Your text is still here, and we keep trying.",
    rejected: 'Not saved',
    signin: 'Not saved. Please sign in again.',
    conflict: 'Not saved',
  }[status.value]
})

/** Everything written so far, to keep when it can't be saved. */
const myText = computed(() => plainText(payload.value, questions.value))

function edited() {
  actionError.value = ''
  draft.changed()
}

function setAnswer(id: string, text: string) {
  payload.value.answers = { ...payload.value.answers, [id]: text }
  edited()
}

function setQ4(q4: Q4Answer) {
  payload.value.q4 = q4
  edited()
}

function pulse(chip: number) {
  clearTimeout(pulseTimer)
  pulseChip.value = null
  // The next tick restarts the animation when the same row pulses twice.
  requestAnimationFrame(() => {
    pulseChip.value = chip
    pulseTimer = setTimeout(() => (pulseChip.value = null), 900)
  })
}

function onCite(start: number, end: number) {
  if (!editable.value || !vignette.value) return
  notice.value = ''
  const result = addCitation(citations.value, vignette.value.text, start, end)
  if (result.kind === 'added') {
    payload.value.highlights = result.citations
    edited()
    pulse(result.citations.length)
  } else if (result.kind === 'duplicate') {
    pulse(result.chip)
  } else if (result.kind === 'too_long') {
    notice.value = "That's too long for one quote. Please select less."
  }
}

function onDirection(chip: number, direction: Direction) {
  payload.value.highlights = citations.value.map((c) => (c.chip === chip ? { ...c, direction } : c))
  edited()
}

function insertChip(chip: number) {
  if (insertTarget.value) blocks.get(insertTarget.value)?.insertChip(chip)
}

function setBlock(id: string, block: Element | ComponentPublicInstance | null) {
  if (block) blocks.set(id, block as InstanceType<typeof QuestionBlock>)
  else blocks.delete(id)
}

function removeNow(chip: number) {
  removing.value = null
  activeChip.value = null
  const result = removeCitation(citations.value, answers.value, chip)
  payload.value.highlights = result.citations
  payload.value.answers = result.answers
  edited()
}

function saveQuietly() {
  void draft.flush().catch(() => {})
}

async function showStep(id: StepId) {
  await nextTick()
  if (id === REVIEW) column.value?.scrollTo?.(0, 0)
  else column.value?.querySelector(`[data-question="${id}"]`)?.scrollIntoView?.({ block: 'start' })
}

function go(id: StepId) {
  actionError.value = ''
  activeChip.value = null
  saveQuietly()
  step.value = id
  void showStep(id)
}

/**
 * The main button, pressed while something is missing. It does not go on: it marks what is missing
 * and takes the expert to the first of it. The marks stay until each thing is put right.
 */
function attempt() {
  if (!blocker.value) return
  attempted.value = true
  flashKey.value += 1
  const first = questions.value.find((q) => stepProblems.value[q.id])
  if (first) go(first.id)
  else
    void nextTick(() =>
      document.querySelector('[data-missing="true"]')?.scrollIntoView?.({ block: 'nearest' }),
    )
}

function goBack() {
  const last = questions.value[questions.value.length - 1]
  if (last) go(last.id)
}

function setRating(rating: number) {
  payload.value.rating = rating
  payload.value.insufficient_information = false
  edited()
}

function setInsufficient() {
  payload.value.rating = null
  payload.value.insufficient_information = true
  edited()
}

function explain(error: unknown): string {
  return describeError(error)
}

async function submit() {
  busy.value = true
  actionError.value = ''
  try {
    await draft.submit()
    dialog.value = null
    await router.push({ path: '/assignments', query: { submitted: vignette.value?.code } })
  } catch (error) {
    dialog.value = null
    actionError.value = explain(error)
  } finally {
    busy.value = false
  }
}

async function sentForReview() {
  await router.push({ path: '/assignments', query: { sent: vignette.value?.code } })
}

/** While the answers are proofread, look again now and then: the check opens by itself. */
function pollWhileProofreading() {
  clearInterval(pollTimer)
  if (!proofreading.value) return
  pollTimer = setInterval(async () => {
    try {
      await draft.load()
    } catch {
      // The next tick tries again.
    }
    if (!proofreading.value) clearInterval(pollTimer)
  }, POLL_MS)
}

async function load() {
  loading.value = true
  loadError.value = ''
  noProofread.value = false
  try {
    await draft.load()
    step.value = editable.value ? firstOpenStep(questions.value, payload.value) : REVIEW
    pollWhileProofreading()
  } catch (error) {
    loadError.value = explain(error)
  } finally {
    loading.value = false
  }
  // Only where the questions scroll by themselves: on a narrow screen they come after the case text,
  // and opening the page must not jump past it.
  await nextTick()
  if (column.value && getComputedStyle(column.value).overflowY === 'auto') void showStep(step.value)
}

function warnBeforeClosing(event: BeforeUnloadEvent) {
  if (status.value !== 'saved') event.preventDefault()
}

// The marks belong to one stage: reaching the review starts clean.
watch(step, (now) => {
  if (now === REVIEW) attempted.value = false
})

// After signing in again over this page: carry on where the session ended.
watch(
  () => auth.sessionEnded,
  (ended, was) => {
    if (!was || ended || !auth.user) return
    if (loadError.value) void load()
    else void draft.resume()
  },
)

onMounted(() => {
  void load()
  window.addEventListener('beforeunload', warnBeforeClosing)
})

onUnmounted(() => {
  draft.stop()
  clearTimeout(pulseTimer)
  clearInterval(pollTimer)
  window.removeEventListener('beforeunload', warnBeforeClosing)
})

onBeforeRouteLeave(async () => {
  try {
    await draft.flush()
    return true
  } catch {
    return window.confirm('Your latest changes are not saved. Leave anyway?')
  }
})
</script>

<template>
  <div>
    <p v-if="loading" class="text-muted">Loading…</p>
    <div v-else-if="loadError">
      <p class="alert" role="alert">{{ loadError }}</p>
      <RouterLink to="/assignments" class="mt-4 inline-block">Back to My cases</RouterLink>
    </div>

    <template v-else-if="vignette">
      <header class="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
        <p class="text-sm">
          <RouterLink to="/assignments">My cases</RouterLink>
          <span class="px-1.5 text-muted">/</span>
          <span class="font-medium text-ink">Case {{ vignette.code }}</span>
          <span class="pl-3 text-muted">{{ FRAMING_LABELS[vignette.framing] }}</span>
        </p>
        <StepRail
          v-if="editable"
          :steps="railSteps"
          :current="step"
          :flash-key="flashKey"
          @go="go"
        />
        <!-- The proofread check says for itself whether the edited answers are saved. -->
        <p
          v-if="!showProofread"
          class="text-sm text-muted"
          aria-live="polite"
          data-testid="save-status"
        >
          {{ saveLabel }}
        </p>
      </header>

      <div v-if="status === 'conflict'" class="alert mt-3" role="alert" data-testid="conflict">
        <p>
          <strong>This case was changed in another tab or device.</strong>
          Copy anything you want to keep, then load the saved version.
        </p>
        <div class="mt-3 flex flex-wrap items-start gap-x-6 gap-y-2">
          <UnsavedText :text="myText" class="min-w-0 flex-1" />
          <button type="button" class="btn" @click="load">Load saved version</button>
        </div>
      </div>

      <div
        v-else-if="status === 'rejected' && saveProblem"
        class="alert mt-3"
        role="alert"
        data-testid="save-problem"
      >
        <p>This change couldn't be saved. {{ saveRefusal(saveProblem) }}</p>
        <UnsavedText :text="myText" class="mt-3" />
      </div>

      <div
        class="mt-4 grid gap-8 lg:grid-cols-2 lg:items-start xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]"
      >
        <!-- The patient's words and the citations stay in view while the expert writes. -->
        <div class="flex flex-col gap-4 lg:sticky lg:top-4 lg:h-[calc(100vh-6rem)]">
          <div
            class="min-h-0 overflow-y-auto rounded-sm border border-line bg-surface lg:max-h-[60%] lg:shrink-0"
          >
            <p
              v-if="vignette.patient_summary"
              class="px-5 pt-4 text-sm text-muted"
              data-testid="patient-summary"
            >
              About the patient: {{ vignette.patient_summary }}
            </p>
            <VignetteText
              :text="vignette.text"
              :active="activeMark"
              :can-cite="editable"
              @cite="onCite"
            />
          </div>
          <p v-if="notice" class="text-sm text-danger" role="status">{{ notice }}</p>
          <CitationTable
            class="lg:flex-1"
            :citations="citations"
            :editable="editable"
            :can-insert="canInsert"
            :counts="counts"
            :pulse-chip="pulseChip"
            :marked="attempted"
            :flash-key="flashKey"
            @active="activeChip = $event"
            @direction="onDirection"
            @insert="insertChip"
            @remove="removing = $event"
          />
        </div>

        <section class="flex min-w-0 flex-col lg:sticky lg:top-4 lg:h-[calc(100vh-6rem)]">
          <!-- Scrolls by itself, so that the review or submit button below stays in view. Relative,
               because the hidden radio inputs are positioned: otherwise they would escape this box
               and make the whole page scroll. -->
          <div
            ref="column"
            class="relative min-h-0 lg:flex-1 lg:overflow-y-auto lg:px-1 lg:pb-2"
            data-testid="question-column"
          >
            <div
              v-if="proofreading"
              class="flex items-start gap-3 rounded-sm border border-line bg-surface px-4 py-4"
              role="status"
              data-testid="proofreading"
            >
              <LoadingSpinner class="mt-1" />
              <div>
                <h1 class="text-2xl">Proofreading your answers</h1>
                <p class="mt-2 text-muted">
                  We are checking spelling, grammar and punctuation, and writing short notes out in
                  full. This takes a minute or two. You can leave this page: the case waits for you
                  under My cases.
                </p>
                <p class="mt-2 text-muted">
                  Next, you check the edited text, change anything you like, and submit it for
                  review.
                </p>
              </div>
            </div>
            <ProofreadStep
              v-else-if="showProofread"
              :id="id"
              :key="`${state}-${view?.review_round}`"
              @submitted="sentForReview"
              @missing="noProofread = true"
              @highlights="proofHighlights = $event"
            />
            <template v-else-if="step === REVIEW">
              <h1 class="text-2xl" data-testid="question">
                {{ editable ? 'Review your answers' : 'Your answers' }}
              </h1>
              <p v-if="view?.state === 'cancelled'" class="mt-2 text-muted">
                This assignment was cancelled, so these answers were not submitted.
              </p>
              <div class="mt-5">
                <ReviewStep
                  :questions="questions"
                  :payload="submittable"
                  :editable="editable"
                  @edit="go"
                  @active="activeChip = $event"
                />
              </div>
              <p v-if="editable && uncited.length" class="mt-4 text-sm text-muted">
                {{ notMentioned(uncited, 'in any answer') }}
              </p>
            </template>

            <template v-else>
              <div class="divide-y divide-line">
                <QuestionBlock
                  v-for="q in questions"
                  :key="q.id"
                  :ref="(block) => setBlock(q.id, block)"
                  :data-question="q.id"
                  :question="q"
                  :payload="payload"
                  :problem="shownProblem(q.id)"
                  :flash-key="flashKey"
                  @focusin="step = q.id"
                  @answer="setAnswer(q.id, $event)"
                  @q4="setQ4"
                  @rate="setRating"
                  @insufficient="setInsufficient"
                  @active="activeChip = $event"
                />
              </div>
            </template>

            <p v-if="actionError" class="alert mt-4" role="alert">{{ actionError }}</p>
          </div>

          <footer v-if="editable" class="mt-4">
            <p
              v-if="blocker"
              class="mb-2 text-right text-sm"
              :class="attempted ? 'font-medium text-danger' : 'text-muted'"
              :role="attempted ? 'alert' : undefined"
              data-testid="blocker"
            >
              {{ blocker }}
            </p>
            <div class="flex items-center justify-between gap-4">
              <button v-if="step === REVIEW" type="button" class="btn-quiet" @click="goBack">
                Back
              </button>
              <span v-else />

              <button
                v-if="step === REVIEW"
                type="button"
                class="btn"
                :class="blocker ? 'opacity-60' : ''"
                :aria-disabled="blocker ? 'true' : undefined"
                :disabled="busy"
                @click="blocker ? attempt() : (dialog = 'submit')"
              >
                Submit for proofreading
              </button>
              <button
                v-else
                type="button"
                class="btn"
                :class="blocker ? 'opacity-60' : ''"
                :aria-disabled="blocker ? 'true' : undefined"
                @click="blocker ? attempt() : go(REVIEW)"
              >
                Review answers
              </button>
            </div>
          </footer>
        </section>
      </div>

      <ConfirmDialog
        v-if="dialog === 'submit'"
        title="Submit for proofreading?"
        confirm-label="Submit for proofreading"
        cancel-label="Keep editing"
        @confirm="submit"
        @cancel="dialog = null"
      >
        <p>
          We check spelling, grammar and punctuation, leave out anything unreadable, and write short
          notes out as full sentences.
        </p>
        <p>
          You then see your answers next to the edited ones, can change anything, and submit them
          for review. Your quotes can't be changed after this.
        </p>
        <p v-if="uncited.length" class="font-medium">
          {{ notMentioned(uncited, 'in any answer') }}
        </p>
      </ConfirmDialog>

      <ConfirmDialog
        v-if="removing !== null"
        :title="`Remove quote ${removing}?`"
        confirm-label="Remove quote"
        cancel-label="Keep it"
        danger
        @confirm="removeNow(removing as number)"
        @cancel="removing = null"
      >
        <p>{{ removalNote(counts[removing] ?? 0) }}</p>
        <p
          v-if="renumberNote(removing, citations.length)"
          class="alert flex items-start gap-2"
          data-testid="renumber-note"
        >
          <svg
            viewBox="0 0 16 16"
            width="16"
            height="16"
            fill="none"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linecap="round"
            stroke-linejoin="round"
            class="mt-px shrink-0"
            aria-hidden="true"
          >
            <path d="M8 2 1.5 13.5h13L8 2ZM8 6.5v3.25M8 11.75v.01" />
          </svg>
          {{ renumberNote(removing, citations.length) }}
        </p>
      </ConfirmDialog>
    </template>
  </div>
</template>
