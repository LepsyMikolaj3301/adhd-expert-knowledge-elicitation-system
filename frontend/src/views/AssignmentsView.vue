<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { api, ApiError, type AssignmentSummary } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const POLL_MS = 10_000

const auth = useAuthStore()
const router = useRouter()

const assignments = ref<AssignmentSummary[]>([])
const loading = ref(true)
const error = ref('')
let timer: ReturnType<typeof setTimeout> | undefined
let stopped = false

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

async function logout() {
  await auth.logout()
  await router.push({ name: 'login' })
}

onMounted(refresh)
onUnmounted(() => {
  stopped = true
  clearTimeout(timer)
})
</script>

<template>
  <main>
    <header>
      <h1>Assignments</h1>
      <p>
        {{ auth.user?.display_name }} ({{ auth.user?.role }})
        <button type="button" @click="logout">Log out</button>
      </p>
    </header>

    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="loading">Loading…</p>
    <p v-else-if="!assignments.length && !error" data-testid="empty">No assignments yet.</p>
    <table v-else-if="assignments.length">
      <thead>
        <tr>
          <th scope="col">Vignette</th>
          <th v-if="auth.user?.role === 'admin'" scope="col">Expert</th>
          <th scope="col">State</th>
          <th scope="col">Available actions</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="assignment in assignments" :key="assignment.id" data-testid="assignment">
          <td>{{ assignment.vignette_code }} v{{ assignment.vignette_version }}</td>
          <td v-if="auth.user?.role === 'admin'">{{ assignment.expert_pseudonym }}</td>
          <td data-testid="state">{{ assignment.state }}</td>
          <td data-testid="actions">{{ assignment.allowed_actions.join(', ') || '—' }}</td>
        </tr>
      </tbody>
    </table>
  </main>
</template>
