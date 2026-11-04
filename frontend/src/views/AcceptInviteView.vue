<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const MIN_PASSWORD_LENGTH = 12

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const password = ref('')
const error = ref('')
const busy = ref(false)

async function submit() {
  busy.value = true
  error.value = ''
  try {
    await auth.acceptInvite(String(route.params.token), password.value)
    await router.push({ name: 'assignments' })
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Something went wrong. Please try again.'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <main>
    <h1>Set your password</h1>
    <form @submit.prevent="submit">
      <label>
        Password (at least {{ MIN_PASSWORD_LENGTH }} characters)
        <input
          v-model="password"
          type="password"
          autocomplete="new-password"
          :minlength="MIN_PASSWORD_LENGTH"
          required
        />
      </label>
      <p v-if="error" role="alert">{{ error }}</p>
      <button type="submit" :disabled="busy">Set password</button>
    </form>
  </main>
</template>
