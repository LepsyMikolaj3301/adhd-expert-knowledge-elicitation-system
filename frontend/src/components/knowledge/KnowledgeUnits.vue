<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import { api, type KnowledgeUnit } from '@/api/client'
import PseudonymChip from '@/components/PseudonymChip.vue'
import { describeError, FRAMING_LABELS } from '@/copy'

import UnitCard from './UnitCard.vue'

const units = ref<KnowledgeUnit[]>([])
const loading = ref(true)
const error = ref('')

// shortcut: the API's largest page. Past 500 ingested units this needs paging or a filter.
const PAGE = 500

onMounted(async () => {
  try {
    const { data } = await api.GET('/api/v1/knowledge-units', {
      params: { query: { status: 'ingested', limit: PAGE } },
    })
    units.value = data ?? []
  } catch (e) {
    error.value = describeError(e)
  } finally {
    loading.value = false
  }
})

/** Case by case; within a case, expert by expert; within an expert, in the order of the cut. */
const cases = computed(() => {
  const byCase = new Map<
    string,
    {
      key: string
      code: string
      version: number
      framing: string | null
      experts: Map<
        string,
        { assignment: string; pseudonym: string; synthetic: boolean; units: KnowledgeUnit[] }
      >
    }
  >()
  for (const u of units.value) {
    const key = `${u.vignette_code}@${u.vignette_version}`
    let c = byCase.get(key)
    if (!c) {
      c = {
        key,
        code: u.vignette_code,
        version: u.vignette_version,
        framing: u.framing ?? null,
        experts: new Map(),
      }
      byCase.set(key, c)
    }
    let e = c.experts.get(u.assignment_id)
    if (!e) {
      e = {
        assignment: u.assignment_id,
        pseudonym: u.expert_pseudonym,
        synthetic: u.expert_is_synthetic,
        units: [],
      }
      c.experts.set(u.assignment_id, e)
    }
    e.units.push(u)
  }
  return [...byCase.values()]
    .sort((a, b) => a.code.localeCompare(b.code) || a.version - b.version)
    .map((c) => ({
      ...c,
      experts: [...c.experts.values()].map((e) => ({
        ...e,
        units: [...e.units].sort((a, b) => a.ordinal - b.ordinal),
      })),
    }))
})
</script>

<template>
  <div>
    <p v-if="error" class="alert mt-6" role="alert">{{ error }}</p>
    <p v-if="loading" class="mt-6 text-muted">Loading…</p>
    <p v-else-if="!units.length && !error" class="mt-6 text-muted" data-testid="empty">
      Nothing has been ingested yet.
    </p>

    <template v-else>
      <p class="mt-4 text-sm text-muted" data-testid="summary">
        {{ units.length }} {{ units.length === 1 ? 'unit' : 'units' }} from
        {{ cases.reduce((n, c) => n + c.experts.length, 0) }} accepted answers in {{ cases.length }}
        {{ cases.length === 1 ? 'case' : 'cases' }}.
      </p>
      <section v-for="c in cases" :key="c.key" class="mt-8" data-testid="case">
        <h2>
          Case {{ c.code }}
          <span class="font-sans text-sm text-muted"
            >v{{ c.version
            }}<template v-if="c.framing">
              | {{ FRAMING_LABELS[c.framing] ?? c.framing }}</template
            ></span
          >
        </h2>
        <div v-for="e in c.experts" :key="e.assignment" class="mt-4" data-testid="expert">
          <p class="flex flex-wrap items-center gap-x-3 text-sm text-muted">
            <PseudonymChip :pseudonym="e.pseudonym" />
            <span v-if="e.synthetic" class="quote-tag">synthetic</span>
            <span>{{ e.units.length }} {{ e.units.length === 1 ? 'unit' : 'units' }}</span>
            <RouterLink :to="`/reviews/${e.assignment}`">Open review</RouterLink>
          </p>
          <div class="mt-2 grid gap-3">
            <UnitCard v-for="u in e.units" :key="u.id" :unit="u" />
          </div>
        </div>
      </section>
    </template>
  </div>
</template>
