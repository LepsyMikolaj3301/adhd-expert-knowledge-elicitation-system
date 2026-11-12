<script setup lang="ts">
import { RouterLink } from 'vue-router'

import type { KnowledgeUnit } from '@/api/client'
import PseudonymChip from '@/components/PseudonymChip.vue'
import { directionLabel, FILED_BY_LABELS, FRAMING_LABELS } from '@/copy'

/** One knowledge unit: what the experts' sentences were cut into, and what gets embedded. */
defineProps<{
  unit: KnowledgeUnit
  /** Search results are out of their case's context, so they say whose and which case. */
  showCase?: boolean
}>()
</script>

<template>
  <article class="card p-4" data-testid="unit">
    <header class="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">
      <span class="quote-tag" data-testid="unit-kind">{{
        unit.kind === 'case' ? 'Whole case' : `Quote ${unit.highlight_id}`
      }}</span>
      <span v-if="unit.direction" data-testid="unit-direction">{{
        directionLabel(unit.direction)
      }}</span>
      <template v-if="showCase">
        <span>
          Case {{ unit.vignette_code }} v{{ unit.vignette_version }}
          <template v-if="unit.framing"
            >· {{ FRAMING_LABELS[unit.framing] ?? unit.framing }}</template
          >
        </span>
        <span class="flex items-center gap-2">
          <PseudonymChip :pseudonym="unit.expert_pseudonym" />
          <span v-if="unit.expert_is_synthetic" class="quote-tag" data-testid="synthetic"
            >synthetic</span
          >
        </span>
        <RouterLink :to="`/reviews/${unit.assignment_id}`">Open review</RouterLink>
      </template>
    </header>

    <p v-if="unit.patient_words" class="mt-3 text-sm text-muted">
      Patient's words:
      <span class="patient-text !inline text-text">“{{ unit.patient_words }}”</span>
    </p>
    <p class="mt-3 font-serif text-lg whitespace-pre-wrap" data-testid="unit-text">
      {{ unit.text }}
    </p>

    <ul v-if="unit.sentences.length" class="mt-3 flex flex-wrap gap-1.5" aria-label="Sentences">
      <li v-for="s in unit.sentences" :key="s.id" class="quote-tag" data-testid="sentence">
        {{ s.id }}<template v-if="s.assigned_by"> · {{ FILED_BY_LABELS[s.assigned_by] }}</template>
      </li>
    </ul>
    <p v-if="unit.context.length" class="mt-2 text-sm text-muted" data-testid="context">
      Cited together with:
      <span v-for="c in unit.context" :key="c.id" class="mr-2">{{ c.id }} “{{ c.text }}”</span>
    </p>

    <details class="mt-3 text-sm" data-testid="embedded">
      <summary class="cursor-pointer text-muted">What is embedded</summary>
      <p class="mt-2 font-medium">Reviewed text (what questions are matched against)</p>
      <pre class="mt-1 font-sans whitespace-pre-wrap text-muted">{{ unit.embed_text }}</pre>
      <p class="mt-2 font-medium">With the patient's words</p>
      <pre class="mt-1 font-sans whitespace-pre-wrap text-muted">{{
        unit.embed_text_combined
      }}</pre>
      <p class="mt-2 text-muted">
        Filed by {{ unit.classifier ?? 'rules alone (no sentence needed the model)'
        }}<template v-if="unit.prompt"> · prompt {{ unit.prompt }}</template
        ><template v-if="unit.findings_version">
          · cutting rules v{{ unit.findings_version }}</template
        >
      </p>
    </details>
  </article>
</template>
