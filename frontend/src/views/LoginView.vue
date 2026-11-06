<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import { TRUST_SENTENCE } from '@/copy'
import AuthLayout from '@/layouts/AuthLayout.vue'
import { safeNextPath } from '@/router/guard'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const email = ref('')
const password = ref('')
const error = ref('')
const busy = ref(false)

async function submit() {
  busy.value = true
  error.value = ''
  try {
    await auth.login(email.value, password.value)
    await router.push(safeNextPath(route.query.next))
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Something went wrong. Please try again.'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <AuthLayout>
    <h1>Sign in</h1>
    <form class="mt-8 space-y-5" @submit.prevent="submit">
      <label class="block text-sm font-medium text-ink">
        Email
        <input v-model="email" class="field" type="email" autocomplete="username" required />
      </label>
      <label class="block text-sm font-medium text-ink">
        Password
        <input
          v-model="password"
          class="field"
          type="password"
          autocomplete="current-password"
          required
        />
      </label>
      <p v-if="error" class="alert" role="alert">{{ error }}</p>
      <button type="submit" class="btn w-full" :disabled="busy">Sign in</button>
    </form>
    <p class="mt-8 text-sm text-muted" data-testid="trust">{{ TRUST_SENTENCE }}</p>
  </AuthLayout>
</template>
