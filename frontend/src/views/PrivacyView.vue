<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { describeError, PRIVACY } from '@/copy'
import { privacyNeeded } from '@/privacy'
import { safeNextPath } from '@/router/guard'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

/** Only experts are asked to confirm: they are the ones whose answers the study collects. */
const asksToConfirm = computed(() => auth.user?.role === 'expert')
const done = computed(() => (auth.user ? !privacyNeeded(auth.user) : false))
const saving = ref(false)
const error = ref('')

async function carryOn() {
  if (!auth.user) return
  saving.value = true
  error.value = ''
  try {
    await auth.acceptPrivacy(PRIVACY.version)
  } catch (e) {
    error.value = describeError(e)
    return
  } finally {
    saving.value = false
  }
  // Sent here on the way to a case: go on (the instructions may come next). Otherwise stay.
  const next = route.query.next
  if (typeof next === 'string') await router.push(safeNextPath(next))
}
</script>

<template>
  <article class="max-w-[68ch]" data-testid="privacy-notice">
    <h1>{{ PRIVACY.title }}</h1>
    <p class="mt-2 text-muted">{{ PRIVACY.lead }}</p>

    <section
      v-for="section in PRIVACY.sections"
      :key="section.id"
      class="mt-8"
      :aria-labelledby="`privacy-${section.id}`"
    >
      <h2 :id="`privacy-${section.id}`" class="text-lg font-semibold text-ink">
        {{ section.heading }}
      </h2>
      <dl v-if="'items' in section" class="mt-2 space-y-3">
        <div v-for="item in section.items" :key="item.term">
          <dt class="font-medium text-ink">{{ item.term }}</dt>
          <dd class="leading-relaxed">{{ item.text }}</dd>
        </div>
      </dl>
      <template v-else>
        <p v-for="text in section.paragraphs" :key="text" class="mt-2 leading-relaxed">
          {{ text }}
        </p>
      </template>
    </section>

    <p class="mt-8 text-sm text-muted">{{ PRIVACY.updated }}: {{ PRIVACY.version }}</p>

    <footer
      v-if="asksToConfirm"
      class="mt-6 flex flex-wrap items-center justify-between gap-4 border-t border-line pt-4"
    >
      <p v-if="done" class="text-sm text-success" role="status" data-testid="privacy-done">
        {{ PRIVACY.confirmed }}
      </p>
      <template v-else>
        <p class="text-sm text-muted">{{ PRIVACY.confirm }}</p>
        <p v-if="error" class="alert w-full" role="alert">{{ error }}</p>
        <button
          type="button"
          class="btn"
          :disabled="saving"
          data-testid="privacy-understand"
          @click="carryOn"
        >
          {{ PRIVACY.understand }}
        </button>
      </template>
    </footer>
  </article>
</template>
