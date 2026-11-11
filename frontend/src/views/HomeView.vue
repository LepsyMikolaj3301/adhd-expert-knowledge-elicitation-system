<script setup lang="ts">
import { computed, nextTick, onMounted, watch } from 'vue'
import { RouterLink } from 'vue-router'

import { api, type ActivityItem, type NextUpItem } from '@/api/client'
import PseudonymChip from '@/components/PseudonymChip.vue'
import { activityText, tallyLabel, TRUST_SENTENCE } from '@/copy'
import { navFor } from '@/navigation'
import { useAuthStore } from '@/stores/auth'
import { useHomeStore } from '@/stores/home'

const auth = useAuthStore()
const home = useHomeStore()
const sections = computed(() =>
  auth.user ? navFor(auth.user.role).filter((item) => item.to !== '/') : [],
)
const data = computed(() => home.data)

const ACTION = { start: 'Start', continue: 'Continue', check: 'Check', retry: 'Retry' } as const

async function retry(item: NextUpItem) {
  try {
    await api.POST('/api/v1/assignments/{assignment_id}/retry', {
      params: { path: { assignment_id: item.assignment_id } },
    })
  } finally {
    await home.load()
  }
}

function linkFor(a: ActivityItem): string {
  if (a.kind === 'case_assigned' || a.kind === 'check_ready')
    return `/assignments/${a.assignment_id}`
  if (a.kind === 'job_failed') return '/assignments'
  return `/reviews/${a.assignment_id}${a.question_id ? `#answer-${a.question_id}` : ''}`
}

onMounted(home.load)
// Marks the feed as read once it is on the screen.
watch(
  () => data.value?.unread_activity,
  async (unread) => {
    if (!unread) return
    await nextTick()
    await home.markSeen()
  },
)
</script>

<template>
  <div>
    <h1>Welcome, {{ auth.user?.display_name }}</h1>
    <p v-if="home.failed" class="alert mt-4" role="alert">
      We couldn't load your latest updates. The links below still work.
    </p>

    <template v-if="data">
      <section class="mt-8" aria-labelledby="next-up" data-testid="next-up">
        <h2 id="next-up">Next up</h2>
        <p v-if="!data.next_up.length" class="mt-2 text-muted">Nothing to do right now.</p>
        <ul v-else class="mt-2 divide-y divide-line border-y border-line">
          <li v-for="n in data.next_up" :key="n.assignment_id" class="flex items-center gap-4 py-3">
            <span class="flex-1 font-serif text-xl text-ink">
              Case {{ n.vignette_code }}
              <span v-if="n.expert_pseudonym" class="font-sans text-sm text-muted"
                >· <PseudonymChip :pseudonym="n.expert_pseudonym"
              /></span>
            </span>
            <button v-if="n.action === 'retry'" type="button" class="btn" @click="retry(n)">
              Retry
            </button>
            <RouterLink
              v-else
              :to="`/assignments/${n.assignment_id}`"
              class="btn hover:no-underline"
            >
              {{ ACTION[n.action] }}
            </RouterLink>
          </li>
        </ul>
        <RouterLink
          v-if="data.next_up_total > data.next_up.length"
          to="/assignments"
          class="mt-2 inline-block text-sm"
        >
          See all {{ data.next_up_total }}
        </RouterLink>
      </section>

      <section class="mt-8" aria-labelledby="waiting" data-testid="waiting">
        <h2 id="waiting">Reviews waiting</h2>
        <p v-if="!data.reviews_waiting.length" class="mt-2 text-muted">
          Nothing is waiting for you.
        </p>
        <ul v-else class="mt-2 divide-y divide-line border-y border-line">
          <li
            v-for="r in data.reviews_waiting"
            :key="r.assignment_id"
            class="flex flex-wrap items-center gap-x-4 py-3"
          >
            <RouterLink :to="`/reviews/${r.assignment_id}`" class="flex-1 font-serif text-xl"
              >Case {{ r.vignette_code }}</RouterLink
            >
            <span class="text-sm text-muted">{{ tallyLabel(r.approvals, r.disapprovals) }}</span>
            <span class="text-sm text-muted">{{ r.comment_count }} comments</span>
          </li>
        </ul>
      </section>

      <section class="mt-8" aria-labelledby="recent" data-testid="recent">
        <h2 id="recent">Recent reviews</h2>
        <p v-if="!data.recent_reviews.length" class="mt-2 text-muted">No reviews yet.</p>
        <ul v-else class="mt-2 flex gap-3 overflow-x-auto pb-2 max-sm:flex-wrap">
          <li
            v-for="r in data.recent_reviews"
            :key="r.assignment_id"
            class="min-w-44 rounded-md border border-line bg-surface p-3"
          >
            <RouterLink :to="`/reviews/${r.assignment_id}`" class="font-serif text-lg"
              >Case {{ r.vignette_code }}</RouterLink
            >
            <p class="text-sm text-muted">
              {{ r.state === 'peer_review' ? 'Open' : 'Closed' }} · {{ r.answer_count }} answers
            </p>
            <p class="text-sm text-muted">{{ tallyLabel(r.approvals, r.disapprovals) }}</p>
          </li>
        </ul>
      </section>

      <section class="mt-8" aria-labelledby="news" data-testid="news">
        <h2 id="news">What's new</h2>
        <p v-if="!data.activity.length" class="mt-2 text-muted">Nothing new yet.</p>
        <ul v-else class="mt-2 divide-y divide-line border-y border-line">
          <li v-for="(a, i) in data.activity" :key="i" class="py-3" :data-unread="a.unread">
            <span
              v-if="a.unread"
              class="mr-2 inline-block h-2 w-2 rounded-full bg-action"
              role="img"
              aria-label="New"
            />
            <RouterLink :to="linkFor(a)">{{ activityText(a) }}</RouterLink>
            <p v-if="a.excerpt" class="mt-1 text-sm text-muted">“{{ a.excerpt }}”</p>
          </li>
        </ul>
      </section>
    </template>

    <nav
      aria-label="Sections"
      class="mt-10 flex flex-wrap gap-x-6 gap-y-1 text-sm"
      data-testid="sections"
    >
      <RouterLink
        v-for="item in sections"
        :key="item.to + item.label"
        :to="item.to"
        :title="item.blurb"
      >
        {{ item.label }}
      </RouterLink>
    </nav>
    <p
      v-if="auth.user?.role === 'expert'"
      class="mt-8 max-w-xl text-sm text-muted"
      data-testid="trust"
    >
      {{ TRUST_SENTENCE }}
    </p>
  </div>
</template>
