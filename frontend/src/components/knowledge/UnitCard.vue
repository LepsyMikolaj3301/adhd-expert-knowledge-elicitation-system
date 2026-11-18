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
  /** The units list offers to take a unit out of the knowledge base; search results don't. */
  removable?: boolean
}>()
const emit = defineEmits<{ remove: [] }>()
</script>

<template>
  <article class="card min-w-0 p-4" data-testid="unit">
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
            >| {{ FRAMING_LABELS[unit.framing] ?? unit.framing }}</template
          >
        </span>
        <span class="flex items-center gap-2">
          <PseudonymChip :pseudonym="unit.expert_pseudonym" />
        </span>
        <RouterLink :to="`/reviews/${unit.assignment_id}`">Open review</RouterLink>
      </template>
      <button
        v-if="removable"
        type="button"
        class="ml-auto inline-flex items-center gap-1.5 rounded-md border border-transparent px-2 py-1 text-xs font-medium text-muted hover:border-danger/40 hover:bg-danger/5 hover:text-danger"
        data-testid="remove-unit"
        @click="emit('remove')"
      >
        <svg
          viewBox="0 0 16 16"
          width="14"
          height="14"
          fill="none"
          stroke="currentColor"
          stroke-width="1.6"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
        >
          <path d="M2.5 4h11M6 4V2.5h4V4M4 4l.7 9.5h6.6L12 4M6.75 6.5v4.5M9.25 6.5v4.5" />
        </svg>
        Remove
      </button>
    </header>

    <p v-if="unit.patient_words" class="mt-3 text-sm text-muted">
      Patient's words:
      <span class="patient-text !inline text-text [overflow-wrap:anywhere]"
        >“{{ unit.patient_words }}”</span
      >
    </p>
    <p
      class="mt-3 font-serif text-lg whitespace-pre-wrap [overflow-wrap:anywhere]"
      data-testid="unit-text"
    >
      {{ unit.text }}
    </p>

    <ul v-if="unit.sentences.length" class="mt-3 flex flex-wrap gap-1.5" aria-label="Sentences">
      <li v-for="s in unit.sentences" :key="s.id" class="quote-tag" data-testid="sentence">
        {{ s.id }}<template v-if="s.assigned_by"> | {{ FILED_BY_LABELS[s.assigned_by] }}</template>
      </li>
    </ul>
    <p
      v-if="unit.context.length"
      class="mt-2 text-sm text-muted [overflow-wrap:anywhere]"
      data-testid="context"
    >
      Cited together with:
      <span v-for="c in unit.context" :key="c.id" class="mr-2">{{ c.id }} “{{ c.text }}”</span>
    </p>

    <!-- Shown in full: the exact strings that were embedded, nothing clipped or folded away. -->
    <section class="mt-4 border-t border-line pt-3" data-testid="embedded">
      <h3 class="eyebrow">Exactly what is embedded</h3>
      <div class="mt-2 grid gap-2">
        <figure class="min-w-0 rounded-sm border-l-2 border-action/60 bg-page px-3 py-2">
          <figcaption class="text-xs font-medium text-muted">
            Reviewed text: what clinicians' questions are matched against
          </figcaption>
          <p
            class="mt-1 text-sm leading-relaxed whitespace-pre-wrap text-text [overflow-wrap:anywhere]"
            data-testid="embed-text"
          >
            {{ unit.embed_text }}
          </p>
        </figure>
        <figure class="min-w-0 rounded-sm border-l-2 border-line bg-page px-3 py-2">
          <figcaption class="text-xs font-medium text-muted">
            The same with the patient's words
          </figcaption>
          <p
            class="mt-1 text-sm leading-relaxed whitespace-pre-wrap text-text [overflow-wrap:anywhere]"
            data-testid="embed-text-combined"
          >
            {{ unit.embed_text_combined }}
          </p>
        </figure>
      </div>
      <p class="mt-2 text-xs text-muted">
        Filed by {{ unit.classifier ?? 'rules alone (no sentence needed the model)'
        }}<template v-if="unit.prompt"> | prompt {{ unit.prompt }}</template
        ><template v-if="unit.findings_version">
          | cutting rules v{{ unit.findings_version }}</template
        >
      </p>
    </section>
  </article>
</template>
