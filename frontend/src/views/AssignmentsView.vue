<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import { api, ApiError, type AssignmentSummary, type State } from '@/api/client'
import CreateAssignmentDialog from '@/components/admin/CreateAssignmentDialog.vue'
import ConfirmDialog from '@/components/answering/ConfirmDialog.vue'
import CaseCard from '@/components/CaseCard.vue'
import LoadingSpinner from '@/components/LoadingSpinner.vue'
import PageIntro from '@/components/PageIntro.vue'
import PseudonymChip from '@/components/PseudonymChip.vue'
import { ASSIGNMENT_STATE_LABELS, CASES_INTRO, describeAdminError } from '@/copy'
import { useAuthStore } from '@/stores/auth'

const POLL_MS = 10_000

const auth = useAuthStore()
const route = useRoute()

const assignments = ref<AssignmentSummary[]>([])
const loading = ref(true)
const error = ref('')
let timer: ReturnType<typeof setTimeout> | undefined
let stopped = false

const isAdmin = computed(() => auth.role === 'admin')
const justSubmitted = computed(() => route.query.submitted)
const justSent = computed(() => route.query.sent)
const creating = ref(false)
const NO_FILTERS = { state: '', expert: '', vignette: '' }
const filters = ref({ ...NO_FILTERS })

/** One dropdown per column: what it filters on, and the values that exist in the list. */
const FILTERS = [
  { key: 'state', label: 'Status', of: (a: AssignmentSummary) => a.state },
  { key: 'expert', label: 'Expert', of: (a: AssignmentSummary) => a.expert_pseudonym },
  { key: 'vignette', label: 'Case', of: (a: AssignmentSummary) => a.vignette_code },
] as const
const filterOptions = computed(() =>
  FILTERS.map((f) => ({
    ...f,
    options: [...new Set(assignments.value.map(f.of))].sort().map((value) => ({
      value,
      label: f.key === 'state' ? ASSIGNMENT_STATE_LABELS[value as State] : value,
    })),
  })),
)
const filtering = computed(() => Object.values(filters.value).some(Boolean))
const shown = computed(() =>
  assignments.value.filter((a) =>
    FILTERS.every((f) => !filters.value[f.key] || f.of(a) === filters.value[f.key]),
  ),
)
const clearFilters = () => (filters.value = { ...NO_FILTERS })
const cancelling = ref<AssignmentSummary | null>(null)

/** The admin's buttons are the actions an assignment allows; the rest are the expert's. */
async function run(call: () => Promise<unknown>) {
  error.value = ''
  try {
    await call()
  } catch (e) {
    error.value = describeAdminError(e)
  }
  await refresh()
}

function retry(a: AssignmentSummary) {
  return run(() =>
    api.POST('/api/v1/assignments/{assignment_id}/retry', {
      params: { path: { assignment_id: a.id } },
    }),
  )
}

function cancel() {
  const a = cancelling.value
  cancelling.value = null
  if (!a) return
  return run(() =>
    api.POST('/api/v1/assignments/{assignment_id}/cancel', {
      params: { path: { assignment_id: a.id } },
    }),
  )
}

function created() {
  creating.value = false
  return refresh()
}

/** For an expert, everything after review starts is the same thing: it's out of their hands. */
function expertStatus(state: AssignmentSummary['state']): string {
  if (state === 'assigned') return 'Not started'
  if (state === 'in_progress') return 'In progress'
  if (state === 'cancelled') return 'Cancelled'
  if (state === 'proofreading') return 'Proofreading…'
  if (state === 'proofread_check') return 'Ready to check'
  return 'In review'
}

function openLabel(state: AssignmentSummary['state']): string | null {
  if (state === 'assigned') return 'Start'
  if (state === 'in_progress') return 'Continue'
  if (state === 'cancelled') return null
  if (state === 'proofread_check') return 'Check'
  return 'View'
}

async function refresh() {
  clearTimeout(timer)
  try {
    const { data } = await api.GET('/api/v1/assignments')
    assignments.value = data ?? []
    error.value = ''
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) return
    error.value = describeAdminError(e)
  } finally {
    loading.value = false
  }
  // Only while a background job is about to change a state. A failed refresh tries again too.
  if (!stopped && (error.value || assignments.value.some((a) => a.job_running))) {
    timer = setTimeout(refresh, POLL_MS)
  }
}

onMounted(refresh)
onUnmounted(() => {
  stopped = true
  clearTimeout(timer)
})
</script>

<template>
  <div>
    <!-- The nav calls an expert's assignments "My cases": they only ever see their own. -->
    <div class="flex flex-wrap items-baseline justify-between gap-4">
      <h1>{{ isAdmin ? 'Assignments' : 'My cases' }}</h1>
      <button
        v-if="isAdmin"
        type="button"
        class="btn"
        data-testid="create-assignment"
        @click="creating = true"
      >
        Create new assignment
      </button>
    </div>
    <PageIntro
      class="mt-2"
      :lead="CASES_INTRO[auth.role].lead"
      :more-to="isAdmin ? undefined : '/about#my-cases'"
      testid="page-intro"
    />

    <p v-if="justSubmitted" class="mt-4 text-ink" role="status">
      Case {{ justSubmitted }} submitted for proofreading. In a minute or two it is ready for you to
      check: you then see the edited text, can change it, and submit it for review.
    </p>
    <p v-if="justSent" class="mt-4 text-ink" role="status">
      Case {{ justSent }} sent for review. Thank you.
    </p>
    <p v-if="error" class="alert mt-6" role="alert">{{ error }}</p>
    <p v-if="loading" class="mt-6 text-muted">Loading…</p>
    <p v-else-if="!assignments.length && !error" class="mt-6 text-muted" data-testid="empty">
      {{
        isAdmin
          ? 'No assignments yet.'
          : "No cases yet. You'll see them here once the study team assigns them."
      }}
    </p>

    <div
      v-if="!loading && assignments.length && isAdmin"
      class="mt-8 flex flex-wrap items-end gap-x-4 gap-y-2 text-sm"
      data-testid="filters"
    >
      <label v-for="f in filterOptions" :key="f.key"
        >{{ f.label }}
        <select v-model="filters[f.key]" class="field" :data-testid="`filter-${f.key}`">
          <option value="">All</option>
          <option v-for="o in f.options" :key="o.value" :value="o.value">{{ o.label }}</option>
        </select>
      </label>
      <button
        v-if="filtering"
        type="button"
        class="btn-quiet"
        data-testid="clear-filters"
        @click="clearFilters"
      >
        Clear filters
      </button>
      <span class="pb-2 text-muted" data-testid="filter-count"
        >Showing {{ shown.length }} of {{ assignments.length }}</span
      >
    </div>
    <p
      v-if="!loading && assignments.length && isAdmin && !shown.length"
      class="mt-6 text-muted"
      data-testid="no-match"
    >
      No assignments match these filters.
    </p>

    <table
      v-if="!loading && shown.length && isAdmin"
      class="mt-4 w-full border-collapse text-left text-sm"
    >
      <thead>
        <tr class="border-b border-line text-muted">
          <th scope="col" class="py-2 pr-4 font-medium">Case</th>
          <th scope="col" class="py-2 pr-4 font-medium">Expert</th>
          <th scope="col" class="py-2 pr-4 font-medium">Status</th>
          <th scope="col" class="py-2 font-medium">Actions</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="assignment in shown"
          :key="assignment.id"
          class="border-b border-line"
          data-testid="assignment"
        >
          <td class="py-3 pr-4">
            <CaseCard
              :code="assignment.vignette_code"
              :version="assignment.vignette_version"
              :patient-summary="assignment.patient_summary"
              :framing="assignment.framing"
              :word-count="assignment.word_count"
              :opening="assignment.opening"
            />
          </td>
          <td class="py-3 pr-4"><PseudonymChip :pseudonym="assignment.expert_pseudonym" /></td>
          <td class="py-3 pr-4" data-testid="state">
            <span class="flex items-center gap-2">
              <LoadingSpinner v-if="assignment.job_running" :size="16" />
              {{ ASSIGNMENT_STATE_LABELS[assignment.state] }}
            </span>
          </td>
          <td class="py-3" data-testid="actions">
            <span class="flex flex-wrap items-center gap-2">
              <RouterLink
                v-if="assignment.allowed_actions.includes('decide_answers')"
                :to="`/reviews/${assignment.id}`"
                class="btn !px-3 !py-1 hover:no-underline"
                data-testid="decide"
              >
                Decide
              </RouterLink>
              <button
                v-if="assignment.allowed_actions.includes('retry')"
                type="button"
                class="btn-quiet !px-3 !py-1"
                data-testid="retry"
                @click="retry(assignment)"
              >
                Retry
              </button>
              <button
                v-if="assignment.allowed_actions.includes('cancel')"
                type="button"
                class="btn-quiet !px-3 !py-1"
                data-testid="cancel"
                @click="cancelling = assignment"
              >
                Cancel
              </button>
              <span
                v-if="
                  !['decide_answers', 'retry', 'cancel'].some((a) =>
                    assignment.allowed_actions.includes(a),
                  )
                "
                class="text-muted"
                >-</span
              >
            </span>
          </td>
        </tr>
      </tbody>
    </table>

    <ul
      v-else-if="assignments.length && !isAdmin"
      class="mt-8 divide-y divide-line border-y border-line"
    >
      <li
        v-for="assignment in assignments"
        :key="assignment.id"
        class="flex items-center gap-4 py-3"
        data-testid="assignment"
      >
        <span class="flex-1 font-serif text-xl text-ink">
          <CaseCard
            :code="assignment.vignette_code"
            :patient-summary="assignment.patient_summary"
            :framing="assignment.framing"
            :word-count="assignment.word_count"
            :opening="assignment.opening"
          />
        </span>
        <span class="flex items-center gap-2 text-sm text-muted" data-testid="state">
          <LoadingSpinner v-if="assignment.state === 'proofreading'" :size="16" />
          {{ expertStatus(assignment.state) }}
        </span>
        <span class="w-24 text-right">
          <RouterLink
            v-if="openLabel(assignment.state)"
            :to="`/assignments/${assignment.id}`"
            class="hover:no-underline"
            :class="openLabel(assignment.state) === 'View' ? 'btn-quiet' : 'btn'"
            data-testid="open"
          >
            {{ openLabel(assignment.state) }}
          </RouterLink>
        </span>
      </li>
    </ul>

    <CreateAssignmentDialog
      v-if="creating"
      :assignments="assignments"
      @done="created"
      @cancel="creating = false"
    />
    <ConfirmDialog
      v-if="cancelling"
      title="Cancel this assignment?"
      confirm-label="Cancel assignment"
      cancel-label="Keep assignment"
      danger
      @confirm="cancel"
      @cancel="cancelling = null"
    >
      <p>
        {{ cancelling.expert_pseudonym }} will no longer work on case
        {{ cancelling.vignette_code }}. Anything written or submitted so far won't be used.
      </p>
    </ConfirmDialog>
  </div>
</template>
