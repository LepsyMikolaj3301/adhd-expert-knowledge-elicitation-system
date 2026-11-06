<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'

import { api, type ReviewItem } from '@/api/client'
import { describeError, STATEMENT, tallyLabel } from '@/copy'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const isAdmin = computed(() => auth.user?.role === 'admin')
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
  return [
    { title: 'Waiting for your vote', items: items.value.filter((r) => !mine(r) && !r.my_vote) },
    { title: "You've voted", items: items.value.filter((r) => !mine(r) && r.my_vote) },
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
    <div class="mt-4 flex gap-2" role="group" aria-label="Show">
      <button
        v-for="s in ['open', 'closed'] as const"
        :key="s"
        type="button"
        :class="status === s ? 'btn' : 'btn-quiet'"
        :aria-pressed="status === s"
        @click="status = s"
      >
        {{ s === 'open' ? 'Open' : 'Closed' }}
      </button>
    </div>

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
            <RouterLink :to="`/reviews/${r.assignment_id}`" class="flex-1 font-serif text-xl">
              Case {{ r.vignette_code }}
              <span v-if="isAdmin && r.author_pseudonym" class="font-sans text-sm text-muted"
                >· {{ r.author_pseudonym }}</span
              >
            </RouterLink>
            <span class="text-sm text-muted">{{ r.unit_count }} {{ STATEMENT }}s</span>
            <span class="text-sm text-muted">{{ tallyLabel(r.accepts, r.declines) }}</span>
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
