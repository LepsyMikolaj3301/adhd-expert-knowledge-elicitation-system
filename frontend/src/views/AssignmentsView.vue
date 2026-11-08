<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import { api, ApiError, type AssignmentSummary } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const POLL_MS = 10_000

const auth = useAuthStore()
const route = useRoute()

const assignments = ref<AssignmentSummary[]>([])
const loading = ref(true)
const error = ref('')
let timer: ReturnType<typeof setTimeout> | undefined
let stopped = false

const isAdmin = computed(() => auth.user?.role === 'admin')
const justSubmitted = computed(() => route.query.submitted)

/** For an expert, everything after submitting is the same thing: it's out of their hands. */
function expertStatus(state: AssignmentSummary['state']): string {
  if (state === 'assigned') return 'Not started'
  if (state === 'in_progress') return 'In progress'
  if (state === 'cancelled') return 'Cancelled'
  if (state === 'expert_check') return 'Ready to check'
  return 'Submitted'
}

function openLabel(state: AssignmentSummary['state']): string | null {
  if (state === 'assigned') return 'Start'
  if (state === 'in_progress') return 'Continue'
  if (state === 'cancelled') return null
  if (state === 'expert_check') return 'Check'
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
    error.value = e instanceof ApiError ? e.message : 'Could not load the assignments.'
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
    <h1>{{ isAdmin ? 'Assignments' : 'My cases' }}</h1>
    <p v-if="!isAdmin" class="mt-1 text-sm">
      <RouterLink to="/instructions" data-testid="instructions-link"
        >Read the instructions</RouterLink
      >
    </p>

    <p v-if="justSubmitted" class="mt-4 text-ink" role="status">
      Case {{ justSubmitted }} submitted. Thank you.
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

    <table
      v-else-if="assignments.length && isAdmin"
      class="mt-8 w-full border-collapse text-left text-sm"
    >
      <thead>
        <tr class="border-b border-line text-muted">
          <th scope="col" class="py-2 pr-4 font-medium">Vignette</th>
          <th scope="col" class="py-2 pr-4 font-medium">Expert</th>
          <th scope="col" class="py-2 pr-4 font-medium">State</th>
          <th scope="col" class="py-2 font-medium">Available actions</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="assignment in assignments"
          :key="assignment.id"
          class="border-b border-line"
          data-testid="assignment"
        >
          <td class="py-3 pr-4">
            {{ assignment.vignette_code }} v{{ assignment.vignette_version }}
          </td>
          <td class="py-3 pr-4">{{ assignment.expert_pseudonym }}</td>
          <td class="py-3 pr-4" data-testid="state">{{ assignment.state }}</td>
          <td class="py-3" data-testid="actions">
            {{ assignment.allowed_actions.join(', ') || '—' }}
          </td>
        </tr>
      </tbody>
    </table>

    <ul v-else-if="assignments.length" class="mt-8 divide-y divide-line border-y border-line">
      <li
        v-for="assignment in assignments"
        :key="assignment.id"
        class="flex items-center gap-4 py-3"
        data-testid="assignment"
      >
        <span class="flex-1 font-serif text-xl text-ink">Case {{ assignment.vignette_code }}</span>
        <span class="text-sm text-muted" data-testid="state">
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
  </div>
</template>
