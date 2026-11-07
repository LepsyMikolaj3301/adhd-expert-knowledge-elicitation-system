<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import { api, ApiError, type UnitView, type Vote } from '@/api/client'
import ConfirmDialog from '@/components/answering/ConfirmDialog.vue'
import UnitThread from '@/components/answering/UnitThread.vue'
import VignetteText from '@/components/answering/VignetteText.vue'
import { describeError, directionLabel, reviewOutcome, STATEMENT, tallyLabel } from '@/copy'

const REFRESH_MS = 30_000
type Decision = 'approve' | 'reject' | 'request_changes'
const DECISIONS: [Decision, string][] = [
  ['approve', 'Approve'],
  ['reject', 'Reject'],
  ['request_changes', 'Request changes'],
]

const props = defineProps<{ id: string }>()
const route = useRoute()

type AssignmentView = NonNullable<Awaited<ReturnType<typeof fetchView>>>
const view = ref<AssignmentView | null>(null)
const units = ref<UnitView[]>([])
const votes = ref<{ accepts: number; declines: number; my_vote: Vote | null } | null>(null)
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
const round = computed(() => view.value?.review_round ?? 1)
const viewingOld = computed(
  () => selectedRound.value !== null && selectedRound.value !== round.value,
)
const audience = computed(() => view.value?.audience)
const code = computed(() =>
  view.value && 'vignette' in view.value
    ? view.value.vignette.code
    : view.value && 'vignette_code' in view.value
      ? view.value.vignette_code
      : '',
)
// Admins get no case text from the API, only the statements.
const caseText = computed(() =>
  view.value && 'vignette' in view.value ? view.value.vignette.text : '',
)
const canComment = computed(() => actions.value.includes('comment') && !viewingOld.value)
const canVote = computed(() => actions.value.includes('vote') && !viewingOld.value)
const canDecide = computed(() => actions.value.includes('decide_units') && !viewingOld.value)
const outcome = computed(() => (view.value ? reviewOutcome(view.value.state, round.value) : null))

async function fetchAll() {
  view.value = (await fetchView()) ?? null
  const wanted = viewingOld.value ? selectedRound.value : null
  const [u, v] = await Promise.all([
    api.GET('/api/v1/assignments/{assignment_id}/units', {
      params: { path: { assignment_id: props.id }, query: wanted ? { review_round: wanted } : {} },
    }),
    viewingOld.value ? null : api.GET('/api/v1/assignments/{assignment_id}/votes', path),
  ])
  units.value = u.data ?? []
  votes.value = v?.data ?? null
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

async function vote(choice: Vote) {
  error.value = ''
  try {
    await api.PUT('/api/v1/assignments/{assignment_id}/vote', {
      ...path,
      body: { vote: choice, review_round: round.value },
    })
    await fetchAll()
  } catch (e) {
    error.value = describeError(e)
    if (e instanceof ApiError && e.code === 'stale_round') await load()
  }
}

async function pickRound(event: Event) {
  const n = Number((event.target as HTMLSelectElement).value)
  selectedRound.value = n === round.value ? null : n
  await load()
}

const choice = (u: UnitView) => (choices.value[u.id] ??= { decision: '', comment: '' })
const decided = computed(
  () =>
    units.value.length > 0 &&
    units.value.every((u) => {
      const c = choices.value[u.id]
      return c?.decision && (c.decision !== 'request_changes' || c.comment.trim())
    }),
)
const count = (d: Decision) => units.value.filter((u) => choices.value[u.id]?.decision === d).length

async function submitDecisions() {
  confirming.value = false
  error.value = ''
  try {
    await api.POST('/api/v1/assignments/{assignment_id}/unit-decisions', {
      ...path,
      body: {
        decisions: units.value.map((u) => ({
          unit_id: u.id,
          decision: choice(u).decision as Decision,
          comment: choice(u).comment.trim() || null,
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
})
onUnmounted(() => clearInterval(timer))
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
        <label v-if="audience !== 'peer' && round > 1" class="text-sm">
          Round
          <select
            class="field !mt-0 !inline-block !w-auto"
            :value="selectedRound ?? round"
            @change="pickRound"
          >
            <option v-for="n in round" :key="n" :value="n">
              {{ n === round ? `${n} (current)` : n }}
            </option>
          </select>
        </label>
      </header>

      <p v-if="error" class="alert mt-3" role="alert">{{ error }}</p>
      <p
        v-if="outcome"
        class="mt-3 rounded-md border border-line bg-surface px-3 py-2"
        data-testid="outcome"
      >
        {{ outcome }}
      </p>
      <p v-if="viewingOld" class="mt-3 text-sm text-muted">
        You are reading an earlier round. It can't be changed.
      </p>
      <p v-if="audience === 'expert'" class="mt-3 text-sm">
        This is your submission. You can read and comment, but not vote.
      </p>

      <section
        v-if="votes && !viewingOld"
        class="mt-4 rounded-md border border-line bg-surface p-3"
        data-testid="votes"
      >
        <p class="text-sm">
          {{ tallyLabel(votes.accepts, votes.declines) }}. This is advice: the study team makes the
          final decision.
        </p>
        <div v-if="canVote" class="mt-2 flex items-center gap-3">
          <button
            v-for="v in ['accept', 'decline'] as const"
            :key="v"
            type="button"
            :class="votes.my_vote === v ? 'btn' : 'btn-quiet'"
            :aria-pressed="votes.my_vote === v"
            @click="vote(v)"
          >
            {{ v === 'accept' ? 'Accept' : 'Decline' }}
          </button>
          <span class="text-sm text-muted">You can change your vote until the review closes.</span>
        </div>
      </section>

      <div class="mt-4 grid gap-8 lg:items-start" :class="caseText ? 'lg:grid-cols-2' : ''">
        <div
          v-if="caseText"
          class="rounded-sm border border-line bg-surface lg:sticky lg:top-4 lg:max-h-[calc(100vh-6rem)] lg:overflow-y-auto"
        >
          <VignetteText :text="caseText" :active="null" :can-cite="false" />
        </div>

        <ol class="min-w-0 space-y-6">
          <li
            v-for="u in units"
            :id="`unit-${u.id}`"
            :key="u.id"
            class="rounded-md border border-line bg-surface p-4"
            data-testid="unit"
          >
            <p class="text-xs font-semibold tracking-wide text-action uppercase">
              {{ STATEMENT }} {{ u.ordinal }}
              <span v-if="'status' in u" class="ml-2 text-muted normal-case">{{ u.status }}</span>
            </p>
            <p v-if="u.patient_words" class="mt-2 text-sm text-muted">
              Quote: “{{ u.patient_words }}”
            </p>
            <p v-if="u.direction" class="text-sm text-muted">
              {{ directionLabel(u.direction as never) }}
            </p>
            <p class="mt-2 whitespace-pre-wrap">{{ u.text }}</p>

            <template v-if="'decisions' in u && u.decisions.length">
              <p v-for="d in u.decisions" :key="d.decided_at" class="mt-2 text-sm">
                Decision: {{ d.decision.replace('_', ' ')
                }}<template v-if="d.comment"> — {{ d.comment }}</template>
              </p>
            </template>

            <fieldset v-if="canDecide" class="mt-3 text-sm">
              <legend class="font-medium">Your decision</legend>
              <label
                v-for="[value, label] in DECISIONS"
                :key="value"
                class="mr-4 inline-flex items-center gap-1.5"
              >
                <input
                  v-model="choice(u).decision"
                  type="radio"
                  :name="`d-${u.id}`"
                  :value="value"
                />
                {{ label }}
              </label>
              <textarea
                v-if="choice(u).decision === 'request_changes'"
                v-model="choice(u).comment"
                rows="2"
                class="field"
                aria-label="What should change"
                placeholder="What should change?"
              />
            </fieldset>

            <UnitThread
              :assignment-id="id"
              :unit="u"
              :can-comment="canComment"
              :can-stance="canVote"
              @posted="refresh"
            />
          </li>
        </ol>
      </div>

      <p v-if="!units.length" class="mt-6 text-muted">There are no statements to read here.</p>

      <div v-if="canDecide" class="mt-6 flex justify-end">
        <button type="button" class="btn" :disabled="!decided" @click="confirming = true">
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
          Asking for changes sends the whole set back to the author, and a new round begins.
        </p>
        <p v-else-if="count('approve')">Approved statements go into the knowledge base.</p>
        <p v-else>Every statement is rejected, so nothing enters the knowledge base.</p>
      </ConfirmDialog>
    </template>
  </div>
</template>
