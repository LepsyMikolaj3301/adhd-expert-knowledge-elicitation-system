<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { api, ApiError, type AssignmentSummary, type User } from '@/api/client'
import ConfirmDialog from '@/components/answering/ConfirmDialog.vue'

const props = defineProps<{
  versionId: string
  /** A retired version keeps its assignments, but takes no new ones. */
  canAssign: boolean
}>()

const STATE_LABELS: Partial<Record<AssignmentSummary['state'], string>> = {
  assigned: 'Not started',
  in_progress: 'In progress',
  processing: 'Submitted, processing',
  processing_failed: 'Processing failed',
  expert_check: 'Submitted, waiting for the expert check',
  building_units: 'Submitted, processing',
  peer_review: 'In review, waiting for your decision',
  ingesting: 'Entering the knowledge base',
  ingestion_failed: 'Entering the knowledge base failed',
  ingested: 'In the knowledge base',
  rejected: 'Rejected',
}

const users = ref<User[]>([])
const assignments = ref<AssignmentSummary[]>([])
const chosen = ref<string[]>([])
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const cancelling = ref<AssignmentSummary | null>(null)

/** A cancelled assignment doesn't stop the expert being assigned the version again. */
const active = computed(() => assignments.value.filter((a) => a.state !== 'cancelled'))
const taken = computed(() => new Set(active.value.map((a) => a.expert_pseudonym)))
const offered = computed(() =>
  users.value.filter((u) => u.role === 'expert' && u.is_active && !taken.value.has(u.pseudonym)),
)

function nameOf(pseudonym: string): string {
  const user = users.value.find((u) => u.pseudonym === pseudonym)
  return user ? `${user.display_name} (${pseudonym})` : pseudonym
}

function explain(e: unknown): string {
  if (!(e instanceof ApiError)) return 'Something went wrong. Please try again.'
  const ids = (e.details?.expert_ids ?? []) as string[]
  const names = ids.map((id) => users.value.find((u) => u.id === id)?.display_name ?? id)
  return names.length ? `${e.message} ${names.join(', ')}.` : e.message
}

async function load() {
  loading.value = true
  try {
    const [people, rows] = await Promise.all([
      api.GET('/api/v1/users'),
      api.GET('/api/v1/assignments', {
        params: { query: { vignette_version_id: props.versionId, limit: 500 } },
      }),
    ])
    users.value = people.data ?? []
    assignments.value = rows.data ?? []
    chosen.value = chosen.value.filter((id) => offered.value.some((u) => u.id === id))
  } catch (e) {
    error.value = explain(e)
  } finally {
    loading.value = false
  }
}

async function assign() {
  busy.value = true
  error.value = ''
  try {
    await api.POST('/api/v1/vignette-versions/{version_id}/assignments', {
      params: { path: { version_id: props.versionId } },
      body: { expert_ids: chosen.value },
    })
    chosen.value = []
  } catch (e) {
    error.value = explain(e)
  } finally {
    busy.value = false
  }
  await load()
}

/** Skip the author's check, or run a failed job again. */
async function run(call: () => Promise<unknown>) {
  error.value = ''
  try {
    await call()
  } catch (e) {
    error.value = explain(e)
  }
  await load()
}

async function cancel() {
  const assignment = cancelling.value
  cancelling.value = null
  if (!assignment) return
  error.value = ''
  try {
    await api.POST('/api/v1/assignments/{assignment_id}/cancel', {
      params: { path: { assignment_id: assignment.id } },
    })
  } catch (e) {
    error.value = explain(e)
  }
  await load()
}

onMounted(load)
watch(() => props.versionId, load)
</script>

<template>
  <section class="mt-10 border-t border-line pt-6" data-testid="assign-panel">
    <h2>Experts on this version</h2>

    <p v-if="error" class="alert mt-3" role="alert">{{ error }}</p>
    <p v-if="loading" class="mt-3 text-sm text-muted">Loading…</p>

    <template v-else>
      <ul v-if="active.length" class="mt-3 divide-y divide-line border-y border-line text-sm">
        <li
          v-for="assignment in active"
          :key="assignment.id"
          class="flex flex-wrap items-center gap-x-4 gap-y-1 py-2"
          data-testid="assigned"
        >
          <span class="flex-1 font-medium">{{ nameOf(assignment.expert_pseudonym) }}</span>
          <span class="text-muted">{{ STATE_LABELS[assignment.state] ?? assignment.state }}</span>
          <button
            v-if="assignment.allowed_actions.includes('skip_expert_check')"
            type="button"
            class="btn-quiet !px-3 !py-1"
            @click="
              run(() =>
                api.POST('/api/v1/assignments/{assignment_id}/expert-check/skip', {
                  params: { path: { assignment_id: assignment.id } },
                }),
              )
            "
          >
            Skip the expert check
          </button>
          <button
            v-if="assignment.allowed_actions.includes('retry')"
            type="button"
            class="btn-quiet !px-3 !py-1"
            @click="
              run(() =>
                api.POST('/api/v1/assignments/{assignment_id}/retry', {
                  params: { path: { assignment_id: assignment.id } },
                }),
              )
            "
          >
            Retry
          </button>
          <button
            v-if="assignment.allowed_actions.includes('cancel')"
            type="button"
            class="btn-quiet !px-3 !py-1"
            @click="cancelling = assignment"
          >
            Cancel
          </button>
        </li>
      </ul>
      <p v-else class="mt-3 text-sm text-muted">Nobody has this version yet.</p>

      <template v-if="canAssign">
        <h3 class="mt-6 text-sm font-semibold text-ink">Assign to</h3>
        <p v-if="!offered.length" class="mt-2 text-sm text-muted">
          Every active expert already has this version.
        </p>
        <template v-else>
          <ul class="mt-2 space-y-1.5 text-sm">
            <li v-for="user in offered" :key="user.id" data-testid="offer">
              <label class="flex items-center gap-2">
                <input v-model="chosen" type="checkbox" :value="user.id" />
                {{ user.display_name }} ({{ user.pseudonym }})
              </label>
            </li>
          </ul>
          <button type="button" class="btn mt-4" :disabled="!chosen.length || busy" @click="assign">
            Assign
          </button>
        </template>
      </template>
    </template>

    <ConfirmDialog
      v-if="cancelling"
      title="Cancel this assignment?"
      confirm-label="Cancel assignment"
      cancel-label="Keep assignment"
      @confirm="cancel"
      @cancel="cancelling = null"
    >
      <p>
        {{ nameOf(cancelling.expert_pseudonym) }} will no longer be able to answer this version.
        Anything written so far won't be submitted.
      </p>
    </ConfirmDialog>
  </section>
</template>
