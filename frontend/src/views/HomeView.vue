<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'

import { api, type ActivityItem, type NextUpItem } from '@/api/client'
import HeroBanner from '@/components/HeroBanner.vue'
import PageIntro from '@/components/PageIntro.vue'
import PseudonymChip from '@/components/PseudonymChip.vue'
import SectionCard from '@/components/SectionCard.vue'
import { activityText, HOME, tallyLabel, TRUST_SENTENCE } from '@/copy'
import { navFor } from '@/navigation'
import { SITE_NAME } from '@/site'
import { useAuthStore } from '@/stores/auth'
import { useHomeStore } from '@/stores/home'

const auth = useAuthStore()
const home = useHomeStore()
const role = computed(() => auth.role)
/** The sections other than the two with live content on this page: they show their own blurb. */
const otherSections = computed(() =>
  auth.user
    ? navFor(auth.user.role).filter((i) => !['/', '/assignments', '/reviews'].includes(i.to))
    : [],
)
const SHOWN = 3
const data = computed(() => home.data)
const nextUp = computed(() => data.value?.next_up.slice(0, SHOWN) ?? [])
const waiting = computed(() => data.value?.reviews_waiting.slice(0, SHOWN) ?? [])
/** What the lists above cut off: the card's own button leads to all of it. */
const moreCases = computed(() => (data.value?.next_up_total ?? 0) - nextUp.value.length)
const moreReviews = computed(() => (data.value?.reviews_waiting_total ?? 0) - waiting.value.length)
const recent = computed(() => data.value?.recent_reviews.slice(0, SHOWN) ?? [])
/** "What's new" shows five at first and five more on each "Show more". */
const NEWS_STEP = 5
const newsShown = ref(NEWS_STEP)
const news = computed(() => data.value?.activity.slice(0, newsShown.value) ?? [])

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
    <!-- Full width of the page, up to the edges the layout pads around the content. -->
    <HeroBanner class="-mx-4 -mt-6 md:-mx-8" :title="SITE_NAME" :tagline="HOME.tagline" />

    <div class="mx-auto max-w-7xl pt-10 text-lg">
      <section aria-labelledby="about" class="text-center" data-testid="about">
        <h2 id="about" class="text-2xl">{{ HOME.about.heading }}</h2>
        <PageIntro class="mt-3" :lead="HOME.about.text[role]" more-to="/about" center />
      </section>

      <p v-if="home.failed" class="alert mt-6" role="alert">
        We couldn't load your latest updates. The links below still work.
      </p>

      <section class="mt-10" aria-labelledby="sections-heading" data-testid="sections">
        <h2 id="sections-heading" class="eyebrow text-base">
          {{ HOME.sectionsHeading }}
        </h2>
        <div class="mt-3 grid gap-4 md:grid-cols-2">
          <SectionCard
            to="/assignments"
            testid="card-assignments"
            :title="HOME.cards.cases.title[role]"
            :text="HOME.cards.cases.text[role]"
            :action="HOME.cards.cases.action[role]"
          >
            <div v-if="data && role === 'expert'" data-testid="next-up">
              <p v-if="!data.next_up.length" class="text-base text-muted">
                Nothing to do right now.
              </p>
              <template v-else>
                <p class="text-base font-medium text-ink">
                  {{ data.next_up_total }}
                  {{ data.next_up_total === 1 ? 'case needs' : 'cases need' }} you
                </p>
                <ul class="mt-1 divide-y divide-line border-y border-line">
                  <li
                    v-for="n in nextUp"
                    :key="n.assignment_id"
                    class="flex items-center gap-3 py-2"
                  >
                    <span class="flex-1 font-serif text-xl text-ink">
                      Case {{ n.vignette_code }}
                      <span v-if="n.expert_pseudonym" class="font-sans text-base text-muted"
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
              </template>
              <p v-if="moreCases" class="mt-2 text-base text-muted" data-testid="more-cases">
                and {{ moreCases }} more {{ moreCases === 1 ? 'case' : 'cases' }}
              </p>
            </div>
          </SectionCard>

          <SectionCard
            to="/reviews"
            testid="card-reviews"
            :title="HOME.cards.reviews.title[role]"
            :text="HOME.cards.reviews.text[role]"
            :action="HOME.cards.reviews.action[role]"
          >
            <template v-if="data">
              <div data-testid="waiting">
                <p v-if="!data.reviews_waiting.length" class="text-base text-muted">
                  Nothing is waiting for you.
                </p>
                <template v-else>
                  <p class="text-base font-medium text-ink">
                    {{ data.reviews_waiting_total }} waiting for your vote
                  </p>
                  <ul class="mt-1 divide-y divide-line border-y border-line">
                    <li
                      v-for="r in waiting"
                      :key="r.assignment_id"
                      class="flex flex-wrap items-center gap-x-3 py-2"
                    >
                      <RouterLink
                        :to="`/reviews/${r.assignment_id}`"
                        class="flex-1 font-serif text-xl whitespace-nowrap"
                        >Case {{ r.vignette_code }}</RouterLink
                      >
                      <span class="text-base text-muted">{{
                        tallyLabel(r.approvals, r.disapprovals)
                      }}</span>
                      <span class="text-base text-muted">{{ r.comment_count }} comments</span>
                    </li>
                  </ul>
                  <p
                    v-if="moreReviews"
                    class="mt-2 text-base text-muted"
                    data-testid="more-reviews"
                  >
                    and {{ moreReviews }} more
                  </p>
                </template>
              </div>
              <div
                v-if="!data.reviews_waiting.length && recent.length"
                class="mt-3"
                data-testid="recent"
              >
                <p class="text-base font-medium text-ink">Recent reviews</p>
                <ul class="mt-1 divide-y divide-line border-y border-line">
                  <li
                    v-for="r in recent"
                    :key="r.assignment_id"
                    class="flex flex-wrap gap-x-3 py-2"
                  >
                    <RouterLink
                      :to="`/reviews/${r.assignment_id}`"
                      class="flex-1 font-serif text-xl whitespace-nowrap"
                      >Case {{ r.vignette_code }}</RouterLink
                    >
                    <span class="text-base text-muted">
                      {{ r.state === 'peer_review' ? 'Open' : 'Closed' }} ·
                      {{ r.answer_count }} answers
                    </span>
                  </li>
                </ul>
              </div>
            </template>
          </SectionCard>
        </div>

        <div v-if="otherSections.length" class="mt-4 grid gap-4 md:grid-cols-3">
          <SectionCard
            v-for="item in otherSections"
            :key="item.to"
            :to="item.to"
            :testid="`card-${item.to.slice(1)}`"
            :title="item.label"
            :text="item.blurb"
            :action="`Open ${item.label}`"
          />
        </div>
      </section>

      <section v-if="data" class="mt-10" aria-labelledby="news" data-testid="news">
        <h2 id="news" class="text-2xl">What's new</h2>
        <p v-if="!data.activity.length" class="mt-2 text-muted">Nothing new yet.</p>
        <ul v-else class="mt-2 divide-y divide-line border-y border-line">
          <li v-for="(a, i) in news" :key="i" class="py-3" :data-unread="a.unread">
            <span
              v-if="a.unread"
              class="mr-2 inline-block h-2 w-2 rounded-full bg-action"
              role="img"
              aria-label="New"
            />
            <RouterLink :to="linkFor(a)">{{ activityText(a) }}</RouterLink>
            <p v-if="a.excerpt" class="mt-1 text-base text-muted">“{{ a.excerpt }}”</p>
          </li>
        </ul>
        <button
          v-if="data.activity.length > newsShown"
          type="button"
          class="btn-quiet mt-3"
          data-testid="news-more"
          @click="newsShown += NEWS_STEP"
        >
          Show more
        </button>
      </section>

      <p
        v-if="auth.user?.role === 'expert'"
        class="mt-8 max-w-xl text-base text-muted"
        data-testid="trust"
      >
        {{ TRUST_SENTENCE }}
      </p>

      <!-- Placeholder until the privacy notice is written. -->
      <section aria-labelledby="privacy" class="mt-12 card p-5" data-testid="gdpr">
        <h2 id="privacy">{{ HOME.privacy.heading }}</h2>
        <p class="mt-2 text-muted">{{ HOME.privacy.text }}</p>
      </section>
    </div>
  </div>
</template>
