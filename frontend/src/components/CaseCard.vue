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
  <InfoPopover mode="hover">
    <template #trigger="{ panelId }">
      <span
        class="cursor-help underline decoration-dotted underline-offset-4"
        tabindex="0"
        :aria-describedby="panelId"
        data-testid="case-trigger"
      >
        <slot>Case {{ code }}{{ version ? ` v${version}` : '' }}</slot>
      </span>
    </template>
    <p class="text-muted">{{ FRAMING_LABELS[framing] ?? framing }} · {{ wordCount }} words</p>
    <p v-if="patientSummary" class="text-ink" data-testid="case-summary">{{ patientSummary }}</p>
    <p class="font-serif text-ink" data-testid="case-opening">{{ opening }}</p>
  </InfoPopover>
</template>
