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

const groups = computed(() => {
  if (isAdmin.value) {
    // Oldest waiting first.
    const sorted = [...items.value].sort((a, b) => a.updated_at.localeCompare(b.updated_at))
    return [{ title: '', items: sorted }]
  }
  const mine = (r: ReviewItem) => r.relation === 'author'
  /** Votes are per answer: a review is done once every answer has the reviewer's vote. */
  const voted = (r: ReviewItem) => r.answer_count > 0 && r.my_votes >= r.answer_count
  return [
    { title: 'Waiting for your vote', items: items.value.filter((r) => !mine(r) && !voted(r)) },
    { title: "You've voted", items: items.value.filter((r) => !mine(r) && voted(r)) },
    { title: 'Your submissions', items: items.value.filter(mine) },
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
watch(status, load)
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
      <section v-for="group in groups" :key="group.title" class="mt-8" data-testid="group">
        <h2 v-if="group.title">{{ group.title }}</h2>
        <ul class="mt-2 divide-y divide-line border-y border-line">
          <li
            v-for="r in group.items"
            :key="r.assignment_id"
            class="flex flex-wrap items-center gap-x-4 gap-y-1 py-3"
            data-testid="review"
          >
            <span class="flex-1 font-serif text-xl">
              <RouterLink :to="`/reviews/${r.assignment_id}`"
                >Case {{ r.vignette_code }}</RouterLink
              >
              <span v-if="isAdmin && r.author_pseudonym" class="font-sans text-sm text-muted"
                >· <PseudonymChip :pseudonym="r.author_pseudonym"
              /></span>
            </span>
            <span class="text-sm text-muted">{{ r.answer_count }} answers</span>
            <span class="text-sm text-muted">{{ tallyLabel(r.approvals, r.disapprovals) }}</span>
            <span class="text-sm text-muted">{{ r.comment_count }} comments</span>
            <span class="text-sm text-muted capitalize">{{
              r.relation === 'author' ? 'Yours' : r.relation === 'admin' ? '' : 'To review'
            }}</span>
          </li>
        </ul>
      </section>
    </template>
  </div>
</template>
