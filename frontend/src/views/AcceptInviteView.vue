<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import AuthLayout from '@/layouts/AuthLayout.vue'
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
    await router.push({ name: 'home' })
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Something went wrong. Please try again.'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <AuthLayout>
    <h1>Set your password</h1>
    <form class="mt-8 space-y-5" @submit.prevent="submit">
      <label class="block text-sm font-medium text-ink">
        Password (at least {{ MIN_PASSWORD_LENGTH }} characters)
        <input
          v-model="password"
          class="field"
          type="password"
          autocomplete="new-password"
          :minlength="MIN_PASSWORD_LENGTH"
          required
        />
      </label>
      <p v-if="error" class="alert" role="alert">{{ error }}</p>
      <button type="submit" class="btn w-full" :disabled="busy">Set password</button>
    </form>
  </AuthLayout>
</template>
