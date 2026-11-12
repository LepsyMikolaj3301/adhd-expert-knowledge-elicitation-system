<script setup lang="ts">
import { CASE_TEXT, FRAMING_LABELS } from '@/copy'

/**
 * The patient's side of the page, shared by answering and reviewing: a summary of the patient and
 * the case text with what kind of text it is. The text itself goes in the slot. Renders two
 * sections, so the page decides how they are laid out; `textClass` is for the text's own box.
 */
defineProps<{
  summary?: string | null
  framing: string
  /** The one line under the heading: what to do with the text on this page. */
  lead: string
  textClass?: string
}>()
</script>

<template>
  <section
    v-if="summary"
    class="shrink-0 rounded-sm border border-line bg-surface px-5 py-3"
    aria-labelledby="h-patient-summary"
    data-testid="patient-summary"
  >
    <h2 id="h-patient-summary" class="eyebrow">{{ CASE_TEXT.summaryHeading }}</h2>
    <p class="mt-1 text-sm text-ink">{{ summary }}</p>
  </section>
  <section
    class="rounded-sm border border-line bg-surface"
    :class="textClass"
    aria-labelledby="h-patient-text"
  >
    <header class="border-b border-line px-5 py-3">
      <div class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5">
        <h2 id="h-patient-text" class="eyebrow">{{ CASE_TEXT.heading }}</h2>
        <p class="text-xs text-muted" data-testid="text-type">
          {{ CASE_TEXT.textType }}:
          <span class="font-medium text-ink">{{ FRAMING_LABELS[framing] ?? framing }}</span>
        </p>
      </div>
      <p class="mt-1 text-sm text-muted">{{ lead }}</p>
    </header>
    <slot />
  </section>
</template>
