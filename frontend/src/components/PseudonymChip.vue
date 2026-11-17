<script setup lang="ts">
import { ref } from 'vue'

import { api, type PersonView } from '@/api/client'

import InfoPopover from './InfoPopover.vue'

// One lookup per pseudonym per page load; the list screens show the same few experts many times.
const known = new Map<string, PersonView>()

const props = defineProps<{ pseudonym: string }>()

const person = ref<PersonView | null>(known.get(props.pseudonym) ?? null)
const failed = ref(false)

async function load() {
  if (person.value) return
  try {
    const { data } = await api.GET('/api/v1/users/by-pseudonym/{pseudonym}', {
      params: { path: { pseudonym: props.pseudonym } },
    })
    if (data) known.set(props.pseudonym, data)
    person.value = data ?? null
    failed.value = !data
  } catch {
    failed.value = true
  }
}
</script>

<template>
  <InfoPopover mode="click" @open="load">
    <template #trigger="{ open, toggle, panelId }">
      <button
        type="button"
        class="cursor-pointer underline decoration-dotted underline-offset-4 hover:text-ink"
        :aria-expanded="open"
        :aria-controls="panelId"
        data-testid="pseudonym"
        @click="toggle"
      >
        {{ pseudonym }}
      </button>
    </template>
    <p v-if="failed" class="text-muted">Could not load this expert.</p>
    <p v-else-if="!person" class="text-muted">Loading…</p>
    <template v-else-if="person.audience === 'admin'">
      <p class="font-medium text-ink">{{ person.display_name }}</p>
      <p class="text-muted">
        {{ person.email }} | {{ person.role }}
        <template v-if="!person.is_active"> | deactivated</template>
      </p>
      <p>
        Cases: {{ person.cases.open }} open, {{ person.cases.in_review }} in review,
        {{ person.cases.done }} done, {{ person.cases.stopped }} stopped
      </p>
    </template>
    <p v-else>
      Expert <strong>{{ person.pseudonym }}</strong
      >. Names are kept private.
    </p>
  </InfoPopover>
</template>
