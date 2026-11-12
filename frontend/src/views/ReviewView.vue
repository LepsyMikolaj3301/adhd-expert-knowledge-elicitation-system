<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import { provideCommentSink, quoted } from '@/answering/commentSink'
import { chipFocus, markFor, provideQuoteFocus, provideQuotePin } from '@/answering/quoteFocus'
import {
  api,
  ApiError,
  type AnswerVote,
  type Citation,
  type QuestionId,
  type ReviewAnswer,
  type ReviewAnswersView,
} from '@/api/client'
import CasePanel from '@/components/answering/CasePanel.vue'
import CitationTable from '@/components/answering/CitationTable.vue'
import ConfirmDialog from '@/components/answering/ConfirmDialog.vue'
import DecisionButtons, { type Decision } from '@/components/answering/DecisionButtons.vue'
import ReviewAnswerCard from '@/components/answering/ReviewAnswerCard.vue'
import VignetteText from '@/components/answering/VignetteText.vue'
import { CASE_TEXT, describeError, reviewOutcome } from '@/copy'

const REFRESH_MS = 30_000

const props = defineProps<{ id: string }>()
const route = useRoute()
const focus = provideQuoteFocus()
const pin = provideQuotePin()
const sink = provideCommentSink()

type AssignmentView = NonNullable<Awaited<ReturnType<typeof fetchView>>>
const view = ref<AssignmentView | null>(null)
const review = ref<ReviewAnswersView | null>(null)
const selectedRound = ref<number | null>(null)
const needsOpening = ref(false)
const loading = ref(true)
const error = ref('')
const choices = ref<Record<string, { decision: Decision | ''; comment: string }>>({})
const confirming = ref(false)
let timer: ReturnType<typeof setInterval> | undefined

const path = { params: { path: { assignment_id: props.id } } }
const fetchView = async () => (await api.GET('/api/v1/assignments/{assignment_id}', path)).data

const actions = computed(() => view.value?.allowed_actions ?? [])
const answers = computed(() => review.value?.answers ?? [])
const highlights = computed(() => review.value?.highlights ?? [])
const rounds = computed(() => review.value?.rounds ?? [])
const latest = computed(() => rounds.value[rounds.value.length - 1] ?? 1)
const shownRound = computed(() => review.value?.review_round ?? latest.value)
const viewingOld = computed(() => shownRound.value !== latest.value)
const audience = computed(() => view.value?.audience)
const code = computed(() => view.value?.vignette.code ?? '')
const caseText = computed(() => view.value?.vignette.text ?? '')
const summary = computed(() => view.value?.vignette.patient_summary ?? '')
/** Pointing at a quote shows it; otherwise the one clicked on stays lit. */
const activeMark = computed(() => markFor(focus.value ?? pin.value, highlights.value))
const activeChip = chipFocus(focus)
const pinnedChip = chipFocus(pin)
const authorName = computed(() => {
  if (audience.value === 'expert') return 'You'
  if (audience.value === 'admin' && view.value && 'expert_pseudonym' in view.value)
    return String(view.value.expert_pseudonym)
  return 'Author'
})
const linkedAnswer = route.hash.startsWith('#answer-') ? route.hash.slice('#answer-'.length) : null

function citeFromCase(start: number, end: number) {
  sink.value?.insertText(quoted(caseText.value.slice(start, end)))
}

function onKey(event: KeyboardEvent) {
  if (event.key === 'Escape') pin.value = null
}
/** The author's own numbered quotes, as the table showed them while answering. */
const citations = computed<Citation[]>(() =>
  highlights.value
    .filter((h) => h.chip !== null)
    .map((h) => ({
      chip: h.chip as number,
      span: h.span,
      text: h.text,
      direction: h.direction,
    })),
)
const canComment = computed(() => actions.value.includes('comment') && !viewingOld.value)
const canVote = computed(() => actions.value.includes('vote') && !viewingOld.value)
const canDecide = computed(() => actions.value.includes('decide_answers') && !viewingOld.value)
const outcome = computed(() =>
  view.value ? reviewOutcome(view.value.state, view.value.review_round) : null,
)

async function fetchAll() {
  view.value = (await fetchView()) ?? null
  const { data } = await api.GET('/api/v1/assignments/{assignment_id}/answers', {
    params: {
      path: { assignment_id: props.id },
      query: selectedRound.value ? { review_round: selectedRound.value } : {},
    },
  })
  // openapi-fetch's types widen the `span` tuple to an array, though the API sends two numbers.
  review.value = (data as ReviewAnswersView | undefined) ?? null
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    await fetchAll()
    needsOpening.value = false
    await nextTick()
    document.getElementById(route.hash.slice(1))?.scrollIntoView?.({ block: 'center' })
  } catch (e) {
    if (e instanceof ApiError && e.code === 'review_not_opened') needsOpening.value = true
    else error.value = describeError(e)
  } finally {
    loading.value = false
  }
}

/** Quietly, so that nothing being typed is touched: the threads keep their own text. */
async function refresh() {
  if (document.visibilityState !== 'visible' || needsOpening.value || loading.value) return
  try {
    await fetchAll()
  } catch {
    // The next tick tries again.
  }
}

async function openReview() {
  try {
    await api.POST('/api/v1/assignments/{assignment_id}/review/open', path)
    await load()
  } catch (e) {
    error.value = describeError(e)
  }
}

async function vote(answer: ReviewAnswer, choice: AnswerVote) {
  error.value = ''
  try {
    const { data } = await api.PUT(
      '/api/v1/assignments/{assignment_id}/answers/{question_id}/vote',
      {
        params: {
          path: { assignment_id: props.id, question_id: answer.question_id as QuestionId },
        },
        body: { vote: choice, review_round: shownRound.value },
      },
    )
    if (data) review.value = data as ReviewAnswersView
  } catch (e) {
    error.value = describeError(e)
    if (e instanceof ApiError && e.code === 'stale_round') await load()
  }
}

async function pickRound(event: Event) {
  const n = Number((event.target as HTMLSelectElement).value)
  selectedRound.value = n === latest.value ? null : n
  await load()
}

const choice = (a: ReviewAnswer) => (choices.value[a.question_id] ??= { decision: '', comment: '' })
const decided = computed(
  () =>
    answers.value.length > 0 &&
    answers.value.every((a) => {
      const c = choices.value[a.question_id]
      return c?.decision && (c.decision !== 'request_changes' || c.comment.trim())
    }),
)
const count = (d: Decision) =>
  answers.value.filter((a) => choices.value[a.question_id]?.decision === d).length
const undecided = computed(
  () => answers.value.filter((a) => !choices.value[a.question_id]?.decision).length,
)

async function submitDecisions() {
  confirming.value = false
  error.value = ''
  try {
    await api.POST('/api/v1/assignments/{assignment_id}/answer-decisions', {
      ...path,
      body: {
        decisions: answers.value.map((a) => ({
          question_id: a.question_id as QuestionId,
          decision: choice(a).decision as Decision,
          comment: choice(a).comment.trim() || null,
        })),
      },
    })
    choices.value = {}
    await load()
  } catch (e) {
    error.value = describeError(e)
  }
}

onMounted(() => {
  void load()
  timer = setInterval(refresh, REFRESH_MS)
  document.addEventListener('keydown', onKey)
})
onUnmounted(() => {
  clearInterval(timer)
  document.removeEventListener('keydown', onKey)
})
</script>

<template>
  <div>
    <p v-if="loading" class="text-muted">Loading…</p>

    <div v-else-if="needsOpening" class="max-w-xl" data-testid="gate">
      <h1>Before you read this case</h1>
      <p class="mt-3">
        Reading this means you can't be assigned this case later. Your reading would colour your own
        answer.
      </p>
      <div class="mt-5 flex gap-3">
        <button type="button" class="btn" @click="openReview">Continue</button>
        <RouterLink to="/reviews" class="btn-quiet hover:no-underline">Back</RouterLink>
      </div>
      <p v-if="error" class="alert mt-4" role="alert">{{ error }}</p>
    </div>

    <p v-else-if="error && !view" class="alert" role="alert">{{ error }}</p>

    <template v-else-if="view">
      <header class="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
        <p class="text-sm">
          <RouterLink to="/reviews">Reviews</RouterLink>
          <span class="px-1.5 text-muted">/</span>
          <span class="font-medium text-ink">Case {{ code }}</span>
        </p>
        <label v-if="audience !== 'peer' && rounds.length > 1" class="text-sm">
          Round
          <select class="field !mt-0 !inline-block !w-auto" :value="shownRound" @change="pickRound">
            <option v-for="n in rounds" :key="n" :value="n">
              {{ n === latest ? `${n} (latest)` : n }}
            </option>
          </select>
        </label>
      </header>

      <p v-if="error" class="alert mt-3" role="alert">{{ error }}</p>
      <p v-if="outcome" class="mt-3 card px-3 py-2" data-testid="outcome">
        {{ outcome }}
      </p>
      <p v-if="viewingOld" class="mt-3 text-sm text-muted">
        You are reading an earlier round. It can't be changed.
      </p>
      <p v-if="audience === 'expert'" class="mt-3 text-sm">
        These are your answers. You can read and comment, but not vote.
      </p>
      <p v-if="canVote" class="mt-3 text-sm text-muted">
        Approve or disapprove each answer, and say why in a comment. Votes are advice: the study
        team makes the final decision. You can change a vote until the review closes.
      </p>

      <div class="mt-4 grid gap-8 lg:items-start" :class="caseText ? 'lg:grid-cols-2' : ''">
        <div
          v-if="caseText"
          class="flex flex-col gap-4 lg:sticky lg:top-4 lg:max-h-[calc(100vh-6rem)] lg:overflow-y-auto"
        >
          <CasePanel
            :summary="summary"
            :framing="view.vignette.framing"
            :lead="CASE_TEXT.reviewLead"
          >
            <VignetteText
              :text="caseText"
              :active="activeMark"
              :can-cite="sink !== null"
              @cite="citeFromCase"
            />
          </CasePanel>
          <CitationTable
            :citations="citations"
            :editable="false"
            :can-insert="sink !== null"
            insert-into="comment"
            :counts="{}"
            :pulse-chip="null"
            :pinned-chip="pinnedChip"
            @active="activeChip = $event"
            @pin="pinnedChip = pinnedChip === $event ? null : $event"
            @insert="sink?.insertChip($event)"
          />
        </div>

        <ol class="min-w-0 space-y-6">
          <ReviewAnswerCard
            v-for="a in answers"
            :key="a.question_id"
            :answer="a"
            :highlights="highlights"
            :assignment-id="id"
            :author-name="authorName"
            :can-vote="canVote"
            :can-comment="canComment"
            :show-voters="audience === 'admin'"
            :start-open="linkedAnswer === a.question_id"
            @vote="vote(a, $event)"
            @posted="refresh"
          >
            <template v-if="canDecide" #decide>
              <DecisionButtons
                v-model:decision="choice(a).decision"
                v-model:comment="choice(a).comment"
                :question-id="a.question_id"
              />
            </template>
          </ReviewAnswerCard>
        </ol>
      </div>

      <p v-if="!answers.length" class="mt-6 text-muted">There are no answers to read here.</p>

      <div
        v-if="canDecide && answers.length"
        class="sticky bottom-0 z-10 mt-6 flex flex-wrap items-center justify-end gap-x-5 gap-y-2 border-t border-line bg-surface/95 px-4 py-3 shadow-[0_-4px_12px_rgb(0_0_0/0.05)] backdrop-blur"
        data-testid="decision-bar"
      >
        <p class="flex flex-wrap gap-x-3 gap-y-1 text-sm">
          <span class="font-medium text-success">{{ count('approve') }} approve</span>
          <span class="font-medium text-warn">{{ count('request_changes') }} changes</span>
          <span class="font-medium text-danger">{{ count('reject') }} reject</span>
          <span v-if="undecided" class="text-muted">{{ undecided }} to go</span>
        </p>
        <button type="button" class="btn !px-6" :disabled="!decided" @click="confirming = true">
          Submit decisions
        </button>
      </div>

      <ConfirmDialog
        v-if="confirming"
        title="Submit your decisions?"
        confirm-label="Submit decisions"
        cancel-label="Keep deciding"
        @confirm="submitDecisions"
        @cancel="confirming = false"
      >
        <p>
          {{ count('approve') }} approved, {{ count('reject') }} rejected,
          {{ count('request_changes') }} sent back for changes. Decisions can't be changed
          afterwards.
        </p>
        <p v-if="count('request_changes')" class="font-medium">
          Asking for changes sends every answer back to the author, and a new round begins.
        </p>
        <p v-else-if="count('approve')">
          Approved answers are cut into statements and go into the knowledge base.
        </p>
        <p v-else>Every answer is rejected, so nothing enters the knowledge base.</p>
      </ConfirmDialog>
    </template>
  </div>
</template>
