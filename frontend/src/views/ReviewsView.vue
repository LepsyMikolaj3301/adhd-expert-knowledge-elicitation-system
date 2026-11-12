<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'

import { api, type ReviewItem } from '@/api/client'
import PageIntro from '@/components/PageIntro.vue'
import PseudonymChip from '@/components/PseudonymChip.vue'
import SegmentedToggle from '@/components/SegmentedToggle.vue'
import { describeError, REVIEWS_INTRO, tallyLabel } from '@/copy'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const isAdmin = computed(() => auth.role === 'admin')
const STATUSES = [
  { value: 'open', label: 'Open' },
  { value: 'closed', label: 'Closed' },
] as const
const status = ref<'open' | 'closed'>('open')
const items = ref<ReviewItem[]>([])
const loading = ref(true)
const error = ref('')

/** Experts never see another author's pseudonym: the review is blind. */
const authorLabel = (r: ReviewItem) =>
  r.author_pseudonym ?? (r.relation === 'author' ? 'You' : 'Anonymous')

const NO_FILTERS = { case: '', author: '' }
const filters = ref({ ...NO_FILTERS })
const FILTERS = [
  { key: 'case', label: 'Case', of: (r: ReviewItem) => r.vignette_code },
  { key: 'author', label: 'Author', of: authorLabel },
] as const
const filterOptions = computed(() =>
  FILTERS.map((f) => ({ ...f, options: [...new Set(items.value.map(f.of))].sort() })),
)
const filtering = computed(() => Object.values(filters.value).some(Boolean))
const shown = computed(() =>
  items.value.filter((r) =>
    FILTERS.every((f) => !filters.value[f.key] || f.of(r) === filters.value[f.key]),
  ),
)
const clearFilters = () => (filters.value = { ...NO_FILTERS })

const groups = computed(() => {
  if (isAdmin.value) {
    // Oldest waiting first.
    const sorted = [...shown.value].sort((a, b) => a.updated_at.localeCompare(b.updated_at))
    return [{ title: '', items: sorted }]
  }
  const mine = (r: ReviewItem) => r.relation === 'author'
  /** Votes are per answer: a review is done once every answer has the reviewer's vote. */
  const voted = (r: ReviewItem) => r.answer_count > 0 && r.my_votes >= r.answer_count
  return [
    { title: 'Waiting for your vote', items: shown.value.filter((r) => !mine(r) && !voted(r)) },
    { title: "You've voted", items: shown.value.filter((r) => !mine(r) && voted(r)) },
    { title: 'Your submissions', items: shown.value.filter(mine) },
  ].filter((g) => g.items.length)
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await api.GET('/api/v1/reviews', {
      params: { query: { status: status.value } },
    })
    items.value = data ?? []
  } catch (e) {
    error.value = describeError(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(status, () => {
  clearFilters()
  load()
})
</script>

<template>
  <div>
    <h1>Reviews</h1>
    <PageIntro
      class="mt-2"
      :lead="REVIEWS_INTRO[auth.role].lead"
      :more-to="isAdmin ? undefined : '/about#reviews'"
      testid="page-intro"
    />
    <SegmentedToggle v-model="status" class="mt-4" label="Show" :options="STATUSES" />

    <p v-if="error" class="alert mt-6" role="alert">{{ error }}</p>
    <p v-if="loading" class="mt-6 text-muted">Loading…</p>
    <p v-else-if="!items.length && !error" class="mt-6 text-muted" data-testid="empty">
      Nothing to review right now.
    </p>

    <template v-else>
      <div class="mt-6 flex flex-wrap items-end gap-x-4 gap-y-2 text-sm" data-testid="filters">
        <label v-for="f in filterOptions" :key="f.key"
          >{{ f.label }}
          <select v-model="filters[f.key]" class="field" :data-testid="`filter-${f.key}`">
            <option value="">All</option>
            <option v-for="o in f.options" :key="o" :value="o">{{ o }}</option>
          </select>
        </label>
        <button
          v-if="filtering"
          type="button"
          class="btn-quiet"
          data-testid="clear-filters"
          @click="clearFilters"
        >
          Clear filters
        </button>
        <span class="pb-2 text-muted" data-testid="filter-count"
          >Showing {{ shown.length }} of {{ items.length }}</span
        >
      </div>
      <p v-if="!shown.length" class="mt-6 text-muted" data-testid="no-match">
        No reviews match these filters.
      </p>

      <section v-for="group in groups" :key="group.title" class="mt-8" data-testid="group">
        <h2 v-if="group.title">{{ group.title }}</h2>
        <div class="mt-2 overflow-x-auto">
          <table class="w-full min-w-[36rem] table-fixed border-collapse text-left text-sm">
            <colgroup>
              <col class="w-[28%]" />
              <col class="w-[24%]" />
              <col />
              <col />
              <col />
            </colgroup>
            <thead>
              <tr class="border-b border-line text-muted">
                <th scope="col" class="py-2 pr-4 font-medium">Case</th>
                <th scope="col" class="py-2 pr-4 font-medium">Author</th>
                <th scope="col" class="py-2 pr-4 font-medium">Answers</th>
                <th scope="col" class="py-2 pr-4 font-medium">Votes</th>
                <th scope="col" class="py-2 font-medium">Comments</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="r in group.items"
                :key="r.assignment_id"
                class="border-b border-line"
                data-testid="review"
              >
                <td class="py-3 pr-4 font-serif text-lg">
                  <RouterLink :to="`/reviews/${r.assignment_id}`">{{ r.vignette_code }}</RouterLink>
                </td>
                <td class="py-3 pr-4" data-testid="author">
                  <PseudonymChip v-if="r.author_pseudonym" :pseudonym="r.author_pseudonym" />
                  <span v-else class="text-muted">{{ authorLabel(r) }}</span>
                </td>
                <td class="py-3 pr-4 text-muted">{{ r.answer_count }} answers</td>
                <td class="py-3 pr-4 text-muted">{{ tallyLabel(r.approvals, r.disapprovals) }}</td>
                <td class="py-3 text-muted">{{ r.comment_count }} comments</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </div>
</template>
