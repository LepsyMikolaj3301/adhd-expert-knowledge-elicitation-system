<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, RouterLink, useRouter } from 'vue-router'

import {
  addCitation,
  countWords,
  removeCitation,
  uncitedChips,
  type Answers,
} from '@/answering/highlights'
import {
  firstOpenStep,
  forSaving,
  GATE_IDS,
  REVIEW,
  gateProblem,
  stepProblem,
  wordCountLabel,
  type StepId,
} from '@/answering/steps'
import { plainText } from '@/answering/plainText'
import { useAnswerDraft } from '@/answering/useAnswerDraft'
import type { Citation, Direction, Q4Answer } from '@/api/client'
import ChipEditor from '@/components/answering/ChipEditor.vue'
import ChipText from '@/components/answering/ChipText.vue'
import CitationTable from '@/components/answering/CitationTable.vue'
import ConfirmDialog from '@/components/answering/ConfirmDialog.vue'
import Q4Step from '@/components/answering/Q4Step.vue'
import RatingStep from '@/components/answering/RatingStep.vue'
import ReviewStep from '@/components/answering/ReviewStep.vue'
import StepRail, { type RailStep } from '@/components/answering/StepRail.vue'
import UnsavedText from '@/components/answering/UnsavedText.vue'
import VignetteText from '@/components/answering/VignetteText.vue'
import {
  describeError,
  directionNeeded,
  markedPassages,
  notMentioned,
  questionLabel,
  saveRefusal,
} from '@/copy'
import { useAuthStore } from '@/stores/auth'

const props = defineProps<{ id: string }>()

const FRAMING: Record<string, string> = {
  forum_post: 'Forum post',
  personal_journal: 'Personal journal',
  email: 'Email',
}
/** How long an answer to Q1 can run with no chips before asking which fragments it is about. */
const Q1_NUDGE_WORDS = 60
const LATER_IDS = ['Q4', 'Q5', 'Q6']

const router = useRouter()
const auth = useAuthStore()
const draft = useAnswerDraft(props.id)
const { view, payload, status, saveProblem, editable } = draft

const loading = ref(true)
const loadError = ref('')
const actionError = ref('')
const notice = ref('')
const step = ref<StepId>('Q1')
const activeChip = ref<number | null>(null)
const pulseChip = ref<number | null>(null)
const dialog = ref<'lock' | 'submit' | null>(null)
const removing = ref<number | null>(null)
const busy = ref(false)
let pulseTimer: ReturnType<typeof setTimeout> | undefined

const answerBox = ref<InstanceType<typeof ChipEditor> | null>(null)
const q4Box = ref<InstanceType<typeof Q4Step> | null>(null)

const vignette = computed(() => view.value?.vignette ?? null)
const questions = computed(() => vignette.value?.questions ?? [])
const citations = computed<Citation[]>(() => payload.value.highlights)
const answers = computed<Answers>(() => payload.value.answers)
const gatePassed = computed(() => Boolean(view.value?.gate_passed_at))
const lockedCount = computed(() => view.value?.locked_highlights ?? 0)
const submitted = computed(() => Boolean(view.value?.submitted_at))

const question = computed(() => questions.value.find((q) => q.id === step.value) ?? null)
const stepIndex = computed(() => questions.value.findIndex((q) => q.id === step.value))
const isLockedQuestion = computed(
  () => !editable.value || (gatePassed.value && GATE_IDS.includes(step.value)),
)
/** Q1 to Q3 once locked in. A submitted case is just read-only, and does not look locked. */
const gateLocked = computed(
  () => editable.value && gatePassed.value && GATE_IDS.includes(step.value),
)
const isLockStep = computed(
  () => editable.value && !gatePassed.value && step.value === lastGateId.value,
)
const lastGateId = computed(
  () => questions.value.filter((q) => GATE_IDS.includes(q.id)).slice(-1)[0]?.id ?? '',
)

const activeCitation = computed(
  () => citations.value.find((c) => c.chip === activeChip.value) ?? null,
)
/** What will be saved and submitted: the screen may remember Q4 parts that are hidden right now. */
const submittable = computed(() => forSaving(payload.value))
const uncited = computed(() => uncitedChips(citations.value, submittable.value.answers))
const undirected = computed(() => citations.value.filter((c) => !c.direction).map((c) => c.chip))

const canInsert = computed(() => {
  if (!editable.value || isLockedQuestion.value) return false
  if (question.value?.kind === 'open') return true
  return question.value?.kind === 'shift' && Boolean(q4Box.value?.canInsert)
})

const currentAnswer = computed(() => answers.value[step.value] ?? '')
const currentWords = computed(() => countWords(currentAnswer.value))

/** Q4's question, with the what-if picked out as the thing to weigh. */
const heading = computed(() => {
  const text = question.value?.text ?? ''
  const match = question.value?.kind === 'shift' ? /^(.* change if )(.+)(\?)$/.exec(text) : null
  return match
    ? { before: match[1], whatIf: match[2], after: match[3] }
    : { before: text, whatIf: '', after: '' }
})

const q1Nudge = computed(
  () =>
    step.value === 'Q1' &&
    !isLockedQuestion.value &&
    currentAnswer.value.split(/\s+/).length > Q1_NUDGE_WORDS &&
    !currentAnswer.value.includes('⟦h'),
)

function directionProblem(): string | null {
  return undirected.value.length ? directionNeeded(undirected.value) : null
}

/** Why the main button can't be pressed. Word counts for open questions show under the answer. */
const blocker = computed<string | null>(() => {
  if (step.value === REVIEW) return directionProblem()
  if (isLockedQuestion.value || !question.value) return null
  // Q1 to Q3 are free to visit in any order; only locking them in needs all three answered.
  if (GATE_IDS.includes(question.value.id)) {
    return isLockStep.value
      ? (gateProblem(questions.value, payload.value) ?? directionProblem())
      : null
  }
  return stepProblem(question.value, payload.value)
})

const railSteps = computed<RailStep[]>(() => {
  const steps: RailStep[] = []
  let open = true
  for (const q of questions.value) {
    steps.push({ id: q.id, label: q.id, reachable: open })
    if (!GATE_IDS.includes(q.id)) open = open && !stepProblem(q, payload.value)
  }
  if (!gatePassed.value) {
    // Named, but not sent by the server yet: the rail shows there is more without showing what.
    for (const id of LATER_IDS) steps.push({ id, label: id, reachable: false })
    steps.push({ id: REVIEW, label: 'Review', reachable: false })
  } else {
    steps.push({ id: REVIEW, label: 'Review', reachable: open })
  }
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
    notice.value = "That's too long for one passage. Please select less."
  }
}

function onDirection(chip: number, direction: Direction) {
  payload.value.highlights = citations.value.map((c) => (c.chip === chip ? { ...c, direction } : c))
  edited()
}

function insertChip(chip: number) {
  const box = question.value?.kind === 'shift' ? q4Box.value : answerBox.value
  box?.insertChip(chip)
}

function askToRemove(chip: number) {
  if (uncited.value.includes(chip)) removeNow(chip)
  else removing.value = chip
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

function go(id: StepId) {
  actionError.value = ''
  activeChip.value = null
  saveQuietly()
  step.value = id
}

function goBack() {
  const index = step.value === REVIEW ? questions.value.length : stepIndex.value
  const previous = questions.value[index - 1]
  if (previous) go(previous.id)
}

function goNext() {
  go(questions.value[stepIndex.value + 1]?.id ?? REVIEW)
}

function explain(error: unknown): string {
  return describeError(error)
}

async function lockIn() {
  busy.value = true
  actionError.value = ''
  try {
    await draft.passGate()
    dialog.value = null
    go(firstOpenStep(questions.value, payload.value, true))
  } catch (error) {
    dialog.value = null
    actionError.value = explain(error)
  } finally {
    busy.value = false
  }
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

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    await draft.load()
    step.value = editable.value
      ? firstOpenStep(questions.value, payload.value, gatePassed.value)
      : REVIEW
  } catch (error) {
    loadError.value = explain(error)
  } finally {
    loading.value = false
  }
}

function warnBeforeClosing(event: BeforeUnloadEvent) {
  if (status.value !== 'saved') event.preventDefault()
}

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
          <span class="pl-3 text-muted">{{ FRAMING[vignette.framing] }}</span>
        </p>
        <StepRail
          v-if="editable"
          :steps="railSteps"
          :current="step"
          :gate-after="lastGateId"
          :gate-passed="gatePassed"
          @go="go"
        />
        <p class="text-sm text-muted" aria-live="polite" data-testid="save-status">
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
            <VignetteText
              :text="vignette.text"
              :active="activeCitation"
              :can-cite="editable"
              @cite="onCite"
            />
          </div>
          <p v-if="notice" class="text-sm text-danger" role="status">{{ notice }}</p>
          <CitationTable
            class="lg:flex-1"
            :citations="citations"
            :locked-count="lockedCount"
            :editable="editable"
            :can-insert="canInsert"
            :uncited="uncited"
            :pulse-chip="pulseChip"
            @active="activeChip = $event"
            @direction="onDirection"
            @insert="insertChip"
            @remove="askToRemove"
          />
        </div>

        <section class="min-w-0">
          <template v-if="step === REVIEW">
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
                :editable-ids="editable ? LATER_IDS : []"
                @edit="go"
                @active="activeChip = $event"
              />
            </div>
            <p v-if="editable && uncited.length" class="mt-4 text-sm text-muted">
              {{ notMentioned(uncited, 'in any answer') }}
            </p>
          </template>

          <template v-else-if="question">
            <h1 class="text-[1.375rem] leading-snug tracking-normal" data-testid="question">
              <span class="mb-1 block text-sm font-semibold tracking-wide text-action uppercase">
                {{ questionLabel(question.id) }}
              </span>
              {{ heading.before
              }}<strong v-if="heading.whatIf" class="font-semibold">{{ heading.whatIf }}</strong
              >{{ heading.after }}
            </h1>

            <div class="mt-5">
              <template v-if="question.kind === 'open' && isLockedQuestion">
                <p v-if="gateLocked" class="text-sm text-muted">
                  Locked. This keeps your first reading as you wrote it.
                </p>
                <p class="mt-2 leading-relaxed">
                  <ChipText :text="currentAnswer" @active="activeChip = $event" />
                </p>
              </template>

              <template v-else-if="question.kind === 'open'">
                <ChipEditor
                  :key="step"
                  ref="answerBox"
                  :model-value="currentAnswer"
                  :label="`Your answer to ${question.id}`"
                  @update:model-value="setAnswer(step, $event)"
                  @active="activeChip = $event"
                />
                <p class="mt-1 text-sm text-muted" aria-live="polite" data-testid="word-count">
                  {{ wordCountLabel(currentWords) }}
                </p>
                <p v-if="q1Nudge" class="mt-2 text-sm text-ink">
                  Which passages is this about? Click one to add it here.
                </p>
              </template>

              <Q4Step
                v-else-if="question.kind === 'shift'"
                ref="q4Box"
                :question="question"
                :q4="payload.q4 ?? null"
                :why="answers.Q4 ?? ''"
                @update:q4="setQ4"
                @update:why="setAnswer('Q4', $event)"
                @active="activeChip = $event"
              />

              <RatingStep
                v-else
                :rating="payload.rating"
                :insufficient="payload.insufficient_information"
                @rate="
                  (value) => {
                    payload.rating = value
                    payload.insufficient_information = false
                    edited()
                  }
                "
                @insufficient="
                  () => {
                    payload.rating = null
                    payload.insufficient_information = true
                    edited()
                  }
                "
              />
            </div>
          </template>

          <p v-if="actionError" class="alert mt-4" role="alert">{{ actionError }}</p>

          <footer v-if="editable" class="mt-6">
            <p v-if="blocker" class="mb-2 text-right text-sm text-muted">
              {{ blocker }}
            </p>
            <div class="flex items-center justify-between gap-4">
              <button
                v-if="step === REVIEW || stepIndex > 0"
                type="button"
                class="btn-quiet"
                @click="goBack"
              >
                Back
              </button>
              <span v-else />

              <button
                v-if="step === REVIEW"
                type="button"
                class="btn"
                :disabled="Boolean(blocker) || busy"
                @click="dialog = 'submit'"
              >
                Submit answers
              </button>
              <button
                v-else-if="isLockStep"
                type="button"
                class="btn"
                :disabled="Boolean(blocker) || busy"
                @click="dialog = 'lock'"
              >
                Lock in results
              </button>
              <button v-else type="button" class="btn" :disabled="Boolean(blocker)" @click="goNext">
                {{ stepIndex === questions.length - 1 ? 'Review answers' : 'Next question' }}
              </button>
            </div>
          </footer>
        </section>
      </div>

      <ConfirmDialog
        v-if="dialog === 'lock'"
        title="Lock in results?"
        confirm-label="Lock in results"
        cancel-label="Keep editing"
        @confirm="lockIn"
        @cancel="dialog = null"
      >
        <p>
          You won't be able to change your answers to Q1 to Q3, or the
          {{ markedPassages(citations.length) }} you have made, including
          {{ citations.length === 1 ? 'its direction' : 'their directions' }}.
        </p>
        <p>The remaining questions open next. You can still mark new passages there.</p>
        <p v-if="!citations.length" class="font-medium">
          You haven't marked any passages. Some texts have nothing to mark, so that's fine if it's
          what you intended.
        </p>
        <p v-else-if="uncited.length" class="font-medium">
          {{ notMentioned(uncited, 'in an answer yet') }}
        </p>
      </ConfirmDialog>

      <ConfirmDialog
        v-if="dialog === 'submit'"
        title="Submit your answers?"
        confirm-label="Submit answers"
        cancel-label="Keep editing"
        @confirm="submit"
        @cancel="dialog = null"
      >
        <p>You won't be able to change your answers afterward.</p>
        <p>
          They're kept word for word under your pseudonym and reviewed before an AI assistant can
          cite them.
        </p>
        <p v-if="uncited.length" class="font-medium">
          {{ notMentioned(uncited, 'in any answer') }}
        </p>
      </ConfirmDialog>

      <ConfirmDialog
        v-if="removing !== null"
        :title="`Remove passage ${removing}?`"
        confirm-label="Remove passage"
        cancel-label="Keep it"
        @confirm="removeNow(removing as number)"
        @cancel="removing = null"
      >
        <p>It will also be removed from your answers, and later passages move up one number.</p>
      </ConfirmDialog>
    </template>
  </div>
</template>
