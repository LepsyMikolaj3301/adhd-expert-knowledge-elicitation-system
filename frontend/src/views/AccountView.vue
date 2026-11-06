<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import { TRUST_SENTENCE } from '@/copy'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()

const error = ref('')
const busy = ref(false)

async function logout() {
  busy.value = true
  error.value = ''
  try {
    await auth.logout()
    await router.push({ name: 'login' })
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Could not sign out. Please try again.'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div>
    <h1>Account</h1>
    <dl v-if="auth.user" class="mt-8 grid max-w-md grid-cols-[8rem_1fr] gap-y-3">
      <dt class="text-muted">Name</dt>
      <dd>{{ auth.user.display_name }}</dd>
      <dt class="text-muted">Email</dt>
      <dd>{{ auth.user.email }}</dd>
      <dt class="text-muted">Role</dt>
      <dd class="capitalize">{{ auth.user.role }}</dd>
      <template v-if="auth.user.pseudonym">
        <dt class="text-muted">Pseudonym</dt>
        <dd>{{ auth.user.pseudonym }}</dd>
      </template>
    </dl>

    <template v-if="auth.user?.role === 'expert'">
      <p v-if="auth.user.pseudonym" class="mt-6 max-w-md text-sm">
        Your answers are stored under this pseudonym.
      </p>
      <p class="mt-2 max-w-md text-sm text-muted" data-testid="trust">{{ TRUST_SENTENCE }}</p>
    </template>

    <p v-if="error" class="alert mt-6 max-w-md" role="alert">{{ error }}</p>
    <button type="button" class="btn-quiet mt-8" :disabled="busy" @click="logout">Sign out</button>
  </div>
</template>
