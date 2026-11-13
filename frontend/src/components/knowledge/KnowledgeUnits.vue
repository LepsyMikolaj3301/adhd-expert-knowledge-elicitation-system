<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import { api, type KnowledgeUnit } from '@/api/client'
import ConfirmDialog from '@/components/answering/ConfirmDialog.vue'
import LoadingSpinner from '@/components/LoadingSpinner.vue'
import PseudonymChip from '@/components/PseudonymChip.vue'
import { describeError, FRAMING_LABELS } from '@/copy'

import UnitCard from './UnitCard.vue'

type IndexState = 'up_to_date' | 'queued' | 'running' | 'failed'

const units = ref<KnowledgeUnit[]>([])
const loading = ref(true)
const error = ref('')
/** Answers whose units are shown. Closed by default, so the page is an overview, not every card. */
const opened = ref(new Set<string>())
/** The answer whose "more" menu is open. */
const menuFor = ref<string | null>(null)

function toggle(assignment: string) {
  const next = new Set(opened.value)
  if (!next.delete(assignment)) next.add(assignment)
  opened.value = next
}

function setAll(assignments: string[], open: boolean) {
  const next = new Set(opened.value)
  for (const a of assignments) {
    if (open) next.add(a)
    else next.delete(a)
  }
  opened.value = next
}

const countLabel = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

// shortcut: the API's largest page. Past 500 ingested units this needs paging or a filter.
const PAGE = 500

onMounted(async () => {
  document.addEventListener('click', closeMenu)
  document.addEventListener('keydown', closeMenuOnEscape)
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
  await loadIndex()
})

onBeforeUnmount(() => {
  document.removeEventListener('click', closeMenu)
  document.removeEventListener('keydown', closeMenuOnEscape)
  if (poll) clearTimeout(poll)
})

function closeMenu() {
  menuFor.value = null
}

function closeMenuOnEscape(event: KeyboardEvent) {
  if (event.key === 'Escape') closeMenu()
}

// --- the search index: BM25 is refit by the worker after a removal ---------------------------

const index = ref<{ state: IndexState; last_error?: string | null } | null>(null)
const POLL_MS = 2000
let poll: ReturnType<typeof setTimeout> | undefined

async function loadIndex() {
  if (poll) clearTimeout(poll)
  try {
    const { data } = await api.GET('/api/v1/knowledge-units/index')
    index.value = data ?? null
  } catch {
    index.value = null // the status line is a convenience: no line rather than an error
    return
  }
  if (index.value?.state === 'queued' || index.value?.state === 'running') {
    poll = setTimeout(loadIndex, POLL_MS)
  }
}

/** Up to date is only worth saying where there is something to search; the rest always. */
const showIndex = computed(() => {
  const state = index.value?.state
  return state === 'up_to_date'
    ? units.value.length > 0
    : ['queued', 'running', 'failed'].includes(state ?? '')
})

async function refit() {
  try {
    await api.POST('/api/v1/knowledge-units/index/refit')
    index.value = { state: 'queued' }
  } catch (e) {
    error.value = describeError(e)
  }
  await loadIndex()
}

// --- removing units --------------------------------------------------------------------------

type Pending =
  | { kind: 'unit'; unit: KnowledgeUnit }
  | { kind: 'expert'; expertId: string; pseudonym: string; units: number; cases: number }

const pending = ref<Pending | null>(null)
const removing = ref(false)

function askRemoveUnit(unit: KnowledgeUnit) {
  pending.value = { kind: 'unit', unit }
}

function askRemoveExpert(expertId: string, pseudonym: string) {
  menuFor.value = null
  const theirs = units.value.filter((u) => u.expert_id === expertId)
  pending.value = {
    kind: 'expert',
    expertId,
    pseudonym,
    units: theirs.length,
    cases: new Set(theirs.map((u) => `${u.vignette_code}@${u.vignette_version}`)).size,
  }
}

async function confirmRemove() {
  const what = pending.value
  if (!what || removing.value) return
  removing.value = true
  error.value = ''
  try {
    if (what.kind === 'unit') {
      await api.DELETE('/api/v1/knowledge-units/{unit_id}', {
        params: { path: { unit_id: what.unit.id } },
      })
      units.value = units.value.filter((u) => u.id !== what.unit.id)
    } else {
      await api.DELETE('/api/v1/knowledge-units/by-expert/{expert_id}', {
        params: { path: { expert_id: what.expertId } },
      })
      units.value = units.value.filter((u) => u.expert_id !== what.expertId)
    }
    index.value = { state: 'queued' }
    await loadIndex()
  } catch (e) {
    error.value = describeError(e)
  } finally {
    removing.value = false
    pending.value = null
  }
}

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
        {
          assignment: string
          expertId: string
          pseudonym: string
          synthetic: boolean
          units: KnowledgeUnit[]
        }
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
        expertId: u.expert_id,
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
        quotes: e.units.filter((u) => u.kind !== 'case').length,
      })),
    }))
})

const allOpen = (assignments: string[]) => assignments.every((a) => opened.value.has(a))
</script>

<template>
  <div>
    <p v-if="error" class="alert mt-6" role="alert">{{ error }}</p>
    <p v-if="loading" class="mt-6 text-muted">Loading…</p>

    <template v-else>
      <div
        v-if="index && showIndex"
        class="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm"
        data-testid="index-status"
        aria-live="polite"
      >
        <template v-if="index.state === 'queued' || index.state === 'running'">
          <LoadingSpinner :size="16" />
          <span class="text-muted">Refitting the search index after a removal…</span>
        </template>
        <template v-else-if="index.state === 'failed'">
          <span class="text-danger"
            >The search index could not be refit<template v-if="index.last_error">
              ({{ index.last_error }})</template
            >.</span
          >
          <button type="button" class="btn-quiet !px-3 !py-1" @click="refit">Try again</button>
        </template>
        <template v-else>
          <span class="inline-flex items-center gap-1.5 text-muted">
            <svg viewBox="0 0 16 16" width="14" height="14" fill="none" aria-hidden="true">
              <path
                d="M3 8.5l3 3 7-7"
                stroke="var(--color-success)"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
            Search index up to date
          </span>
          <button
            type="button"
            class="text-action underline-offset-2 hover:text-action-hover hover:underline"
            @click="refit"
          >
            Refit now
          </button>
        </template>
      </div>

      <p v-if="!units.length && !error" class="mt-6 text-muted" data-testid="empty">
        Nothing has been ingested yet.
      </p>

      <template v-else>
        <p class="mt-2 text-sm text-muted" data-testid="summary">
          {{ units.length }} {{ units.length === 1 ? 'unit' : 'units' }} from
          {{ cases.reduce((n, c) => n + c.experts.length, 0) }} accepted answers in
          {{ cases.length }} {{ cases.length === 1 ? 'case' : 'cases' }}. Open an answer to see its
          units.
        </p>
        <section v-for="c in cases" :key="c.key" class="mt-8" data-testid="case">
          <div class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <h2>
              Case {{ c.code }}
              <span class="font-sans text-sm text-muted"
                >v{{ c.version
                }}<template v-if="c.framing">
                  | {{ FRAMING_LABELS[c.framing] ?? c.framing }}</template
                ></span
              >
            </h2>
            <button
              v-if="c.experts.length > 1"
              type="button"
              class="text-sm text-action underline-offset-2 hover:text-action-hover hover:underline"
              data-testid="case-toggle-all"
              @click="
                setAll(
                  c.experts.map((e) => e.assignment),
                  !allOpen(c.experts.map((e) => e.assignment)),
                )
              "
            >
              {{ allOpen(c.experts.map((e) => e.assignment)) ? 'Collapse all' : 'Expand all' }}
            </button>
          </div>

          <ul class="card mt-3 divide-y divide-line">
            <li
              v-for="e in c.experts"
              :key="e.assignment"
              class="min-w-0 first:rounded-t-md last:rounded-b-md"
              data-testid="expert"
            >
              <div class="flex items-stretch">
                <button
                  type="button"
                  class="group flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1 rounded-md px-4 py-3 text-left text-sm hover:bg-page"
                  :aria-expanded="opened.has(e.assignment)"
                  :aria-controls="`units-${e.assignment}`"
                  data-testid="expert-toggle"
                  @click="toggle(e.assignment)"
                >
                  <svg
                    viewBox="0 0 16 16"
                    width="14"
                    height="14"
                    fill="none"
                    aria-hidden="true"
                    class="shrink-0 text-muted transition-transform duration-150 group-hover:text-action motion-reduce:transition-none"
                    :class="opened.has(e.assignment) ? 'rotate-90' : ''"
                  >
                    <path
                      d="M6 3.5L10.5 8 6 12.5"
                      stroke="currentColor"
                      stroke-width="2"
                      stroke-linecap="round"
                      stroke-linejoin="round"
                    />
                  </svg>
                  <PseudonymChip :pseudonym="e.pseudonym" />
                  <span v-if="e.synthetic" class="quote-tag">synthetic</span>
                  <span class="text-muted" data-testid="expert-counts"
                    >{{ countLabel(e.units.length, 'unit', 'units') }} ({{
                      countLabel(e.quotes, 'quote', 'quotes')
                    }}, {{ e.units.length - e.quotes }} whole-case)</span
                  >
                  <span class="ml-auto text-xs font-medium text-action">{{
                    opened.has(e.assignment) ? 'Hide' : 'Show'
                  }}</span>
                </button>

                <div class="relative flex items-center pr-2" @click.stop>
                  <button
                    type="button"
                    class="rounded-md px-2 py-1 text-lg leading-none text-muted hover:bg-page hover:text-text"
                    :aria-expanded="menuFor === e.assignment"
                    aria-haspopup="menu"
                    :aria-label="`More for ${e.pseudonym}'s answer`"
                    data-testid="expert-menu"
                    @click="menuFor = menuFor === e.assignment ? null : e.assignment"
                  >
                    ⋯
                  </button>
                  <div
                    v-if="menuFor === e.assignment"
                    role="menu"
                    class="card absolute top-full right-2 z-10 mt-1 w-72 p-1 text-sm shadow-lg"
                  >
                    <RouterLink
                      role="menuitem"
                      class="block rounded-sm px-3 py-2 text-text no-underline hover:bg-page"
                      :to="`/reviews/${e.assignment}`"
                      >Open review</RouterLink
                    >
                    <button
                      type="button"
                      role="menuitem"
                      class="block w-full rounded-sm px-3 py-2 text-left text-danger hover:bg-danger/5"
                      data-testid="remove-expert"
                      @click="askRemoveExpert(e.expertId, e.pseudonym)"
                    >
                      Remove all of {{ e.pseudonym }}'s knowledge…
                      <span class="block text-xs text-muted">In every case, not only this one</span>
                    </button>
                  </div>
                </div>
              </div>

              <div
                v-if="opened.has(e.assignment)"
                :id="`units-${e.assignment}`"
                class="grid min-w-0 gap-3 border-t border-line bg-page/60 p-3"
              >
                <UnitCard
                  v-for="u in e.units"
                  :key="u.id"
                  :unit="u"
                  removable
                  @remove="askRemoveUnit(u)"
                />
              </div>
            </li>
          </ul>
        </section>
      </template>
    </template>

    <ConfirmDialog
      v-if="pending"
      :title="
        pending.kind === 'unit'
          ? 'Remove this unit?'
          : `Remove all of ${pending.pseudonym}'s knowledge?`
      "
      :confirm-label="removing ? 'Removing…' : 'Remove'"
      cancel-label="Keep"
      danger
      @confirm="confirmRemove"
      @cancel="pending = null"
    >
      <p v-if="pending.kind === 'unit'">
        {{
          pending.unit.kind === 'case'
            ? 'The whole-case unit'
            : `Quote ${pending.unit.highlight_id}`
        }}
        of {{ pending.unit.expert_pseudonym }} in case {{ pending.unit.vignette_code }} leaves the
        knowledge base.
      </p>
      <p v-else data-testid="remove-expert-summary">
        {{ countLabel(pending.units, 'unit', 'units') }} from
        {{ countLabel(pending.cases, 'case', 'cases') }} leave the knowledge base.
      </p>
      <p class="text-muted">
        Retrieval stops using it at once, and the search index is refit in the background. This
        can't be undone.
      </p>
    </ConfirmDialog>
  </div>
</template>
