<script setup lang="ts">
import { FRAMING_LABELS } from '@/copy'

import InfoPopover from './InfoPopover.vue'

defineProps<{
  code: string
  version?: number
  patientSummary: string
  framing: string
  wordCount: number
  opening: string
}>()
</script>

<template>
  <!-- Opens on click: a hover popover kept appearing while the pointer crossed the list. -->
  <InfoPopover mode="click">
    <template #trigger="{ open, toggle, panelId }">
      <button
        type="button"
        class="cursor-pointer text-left underline decoration-dotted underline-offset-4 hover:text-ink"
        :aria-expanded="open"
        :aria-controls="panelId"
        data-testid="case-trigger"
        @click="toggle"
      >
        <slot>Case {{ code }}{{ version ? ` v${version}` : '' }}</slot>
      </button>
    </template>
    <p class="text-muted">{{ FRAMING_LABELS[framing] ?? framing }} | {{ wordCount }} words</p>
    <p v-if="patientSummary" class="text-ink" data-testid="case-summary">{{ patientSummary }}</p>
    <p class="font-serif text-ink" data-testid="case-opening">{{ opening }}</p>
  </InfoPopover>
</template>
