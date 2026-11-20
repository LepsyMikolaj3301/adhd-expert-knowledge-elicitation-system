<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import { INVITE } from '@/copy'
import AuthLayout from '@/layouts/AuthLayout.vue'
import { useAuthStore } from '@/stores/auth'

const MIN_PASSWORD_LENGTH = 12

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const token = String(route.params.token)

/** A used or expired link shows no form: it could only fail. */
const link = ref<'checking' | 'usable' | 'dead'>('checking')
const password = ref('')
const error = ref('')
const busy = ref(false)
/** After a first try, the length is checked as the password is typed, in place. */
const tried = ref(false)

const tooShort = () =>
  password.value.length < MIN_PASSWORD_LENGTH
    ? INVITE.tooShort(MIN_PASSWORD_LENGTH, password.value.length)
    : ''

watch(password, () => {
  if (tried.value) error.value = tooShort()
})

function isDead(e: unknown) {
  return e instanceof ApiError && e.code === 'invalid_invite'
}

onMounted(async () => {
  try {
    await auth.checkInvite(token)
    link.value = 'usable'
  } catch (e) {
    // Can't tell: show the form, setting the password checks the link again.
    link.value = isDead(e) ? 'dead' : 'usable'
  }
})

async function submit() {
  tried.value = true
  error.value = tooShort()
  if (error.value) return
  busy.value = true
  try {
    await auth.acceptInvite(token, password.value)
    await router.push({ name: 'home' })
  } catch (e) {
    if (isDead(e)) link.value = 'dead'
    else error.value = e instanceof ApiError ? e.message : 'Something went wrong. Please try again.'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <AuthLayout>
    <p v-if="link === 'checking'" class="text-sm text-muted" role="status">
      {{ INVITE.checking }}
    </p>
    <template v-else-if="link === 'dead'">
      <h1>{{ INVITE.deadHeading }}</h1>
      <div class="mt-6 space-y-3 text-sm text-text" data-testid="invite-dead">
        <p>{{ INVITE.deadLead }}</p>
        <p class="text-muted">{{ INVITE.deadNext }}</p>
      </div>
      <RouterLink :to="{ name: 'login' }" class="btn mt-8 w-full text-center">
        {{ INVITE.signIn }}
      </RouterLink>
    </template>
    <template v-else>
      <h1>{{ INVITE.heading }}</h1>
      <!-- novalidate: the browser's own bubble covers the button; the message goes under the field. -->
      <form class="mt-8 space-y-5" novalidate @submit.prevent="submit">
        <label class="block text-sm font-medium text-ink">
          {{ INVITE.label(MIN_PASSWORD_LENGTH) }}
          <input
            v-model="password"
            class="field"
            type="password"
            autocomplete="new-password"
            :minlength="MIN_PASSWORD_LENGTH"
            required
            :aria-invalid="error ? 'true' : undefined"
            aria-describedby="password-error"
          />
        </label>
        <p
          v-if="error"
          id="password-error"
          class="-mt-3 text-sm text-danger"
          role="alert"
          data-testid="password-error"
        >
          {{ error }}
        </p>
        <button type="submit" class="btn w-full" :disabled="busy">{{ INVITE.submit }}</button>
      </form>
    </template>
  </AuthLayout>
</template>
