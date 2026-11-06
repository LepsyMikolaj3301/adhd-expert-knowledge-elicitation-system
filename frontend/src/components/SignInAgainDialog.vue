<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

import { ApiError } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

const dialog = ref<HTMLDialogElement>()
const password = ref('')
const error = ref('')
const busy = ref(false)

onMounted(() => dialog.value?.showModal())
onBeforeUnmount(() => dialog.value?.close())

async function submit() {
  if (!auth.user) return
  busy.value = true
  error.value = ''
  try {
    // Always the account that was signed in: another person's session must never save this draft.
    await auth.login(auth.user.email, password.value)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Something went wrong. Please try again.'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <!-- No way to dismiss it: the page is useless until the session is back, and nothing is lost. -->
  <dialog
    ref="dialog"
    class="m-auto w-[min(28rem,calc(100vw-2rem))] rounded-sm border border-line bg-surface p-6 text-text backdrop:bg-ink/40"
    aria-labelledby="signin-title"
    @cancel.prevent
  >
    <h2 id="signin-title">Please sign in again</h2>
    <p class="mt-3 text-sm">
      Your session ended. Your text is still on this page and will be saved once you've signed in.
    </p>
    <form class="mt-5 space-y-4" @submit.prevent="submit">
      <p class="text-sm text-muted">Account: {{ auth.user?.email }}</p>
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
  </dialog>
</template>
