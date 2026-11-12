<script setup lang="ts">
import { ref } from 'vue'

import { api, type KnowledgeHit, type KnowledgeSearchMode } from '@/api/client'
import SegmentedToggle from '@/components/SegmentedToggle.vue'
import { describeError } from '@/copy'

import UnitCard from './UnitCard.vue'

const MODES: { value: KnowledgeSearchMode; label: string; help: string; placeholder: string }[] = [
  {
    value: 'question',
    label: "A clinician's question",
    help: 'Searches what the clinicians wrote, the way the platform finds notes for a question.',
    placeholder: 'How do I tell sleep deprivation from attention problems in a patient’s text?',
  },
  {
    value: 'patient_text',
    label: "A patient's text",
    help: "Paste a patient's text. Each sentence is compared with the patient's words that experts highlighted, and the units about them come back.",
    placeholder: 'Paste the patient’s text here.',
  },
]

/** How many units come back: enough to see the ranking fall off. */
const HITS = 8

const mode = ref<KnowledgeSearchMode>('question')
const query = ref('')
const hits = ref<KnowledgeHit[] | null>(null)
const loading = ref(false)
const error = ref('')

const current = () => MODES.find((m) => m.value === mode.value) ?? MODES[0]!

async function run() {
  const text = query.value.trim()
  if (!text) return
  loading.value = true
  error.value = ''
  try {
    const { data } = await api.POST('/api/v1/knowledge-units/search', {
      body: { query: text, mode: mode.value, k: HITS },
    })
    hits.value = data?.hits ?? []
  } catch (e) {
    hits.value = null
    error.value = describeError(e)
  } finally {
    loading.value = false
  }
}

function pick(value: KnowledgeSearchMode) {
  mode.value = value
  // Results of the other kind of search would be read wrongly under the new one.
  hits.value = null
  error.value = ''
}
</script>

<template>
  <div>
    <SegmentedToggle
      class="mt-4"
      label="Search for"
      :options="MODES"
      :disabled="loading"
      :model-value="mode"
      @update:model-value="pick"
    />
    <p class="mt-2 max-w-2xl text-sm text-muted" data-testid="mode-help">{{ current().help }}</p>

    <form class="mt-4 max-w-3xl" @submit.prevent="run">
      <label class="text-sm" for="knowledge-query">Text to search with</label>
      <textarea
        v-if="mode === 'patient_text'"
        id="knowledge-query"
        v-model="query"
        class="field min-h-32"
        maxlength="4000"
        required
        :placeholder="current().placeholder"
      />
      <input
        v-else
        id="knowledge-query"
        v-model="query"
        class="field"
        maxlength="4000"
        required
        :placeholder="current().placeholder"
      />
      <button class="btn mt-3" :disabled="loading || !query.trim()">
        {{ loading ? 'Searching…' : 'Search' }}
      </button>
    </form>

    <p v-if="error" class="alert mt-6" role="alert" data-testid="search-error">{{ error }}</p>

    <p v-if="hits && !hits.length" class="mt-6 text-muted" data-testid="no-hits">
      Nothing in the knowledge base matches.
    </p>
    <section v-else-if="hits" class="mt-6" aria-label="Results" data-testid="hits">
      <p class="text-sm text-muted">
        {{ hits.length }} {{ hits.length === 1 ? 'unit' : 'units' }}, best first. Similarity is how
        close the embeddings are (1 is identical); the platform score only orders the list.
      </p>
      <ol class="mt-3 grid gap-4">
        <li v-for="h in hits" :key="h.unit.id" data-testid="hit">
          <p class="mb-1 flex flex-wrap items-baseline gap-x-4 text-sm">
            <span class="font-medium text-ink">#{{ h.rank }}</span>
            <span data-testid="similarity"
              >Similarity {{ h.similarity === null ? '-' : h.similarity.toFixed(2) }}</span
            >
            <span class="text-muted">Platform score {{ h.score.toFixed(4) }}</span>
          </p>
          <p v-if="h.matched_sentence" class="mb-1 text-sm text-muted" data-testid="matched">
            Best matched your sentence: “{{ h.matched_sentence }}”
          </p>
          <UnitCard :unit="h.unit" show-case />
        </li>
      </ol>
    </section>
  </div>
</template>
