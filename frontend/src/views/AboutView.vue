<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'

import AboutSection from '@/components/AboutSection.vue'
import StepFlow from '@/components/StepFlow.vue'
import TermGrid from '@/components/TermGrid.vue'
import { CASES_INTRO, HOME, INTRO, REVIEWS_INTRO, TRUST_SENTENCE } from '@/copy'
import { SITE_NAME } from '@/site'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const role = computed(() => auth.role)
const isExpert = computed(() => role.value === 'expert')

const section = (id: string) => HOME.more.sections.find((s) => s.id === id)!
const aim = section('aim')
const vignettes = section('vignettes')
const answer = section('answer')
const flow = section('flow')
const review = section('review')
const answers = section('answers')

/** The page in the order it is read. The same list builds the jump links at the top. */
const contents = computed(() => [
  { id: 'aim', label: aim.heading },
  { id: 'vignettes', label: vignettes.heading },
  { id: 'answer', label: answer.heading },
  { id: 'flow', label: flow.heading },
  ...(isExpert.value
    ? [
        { id: 'my-cases', label: 'My cases' },
        { id: 'reviews', label: 'Reviews' },
      ]
    : [{ id: 'review', label: review.heading }]),
  { id: 'answers', label: answers.heading },
])

const lead = computed(() => HOME.about.text[role.value][0])
const rest = computed(() => HOME.about.text[role.value].slice(1))
</script>

<template>
  <div class="max-w-3xl">
    <RouterLink to="/" class="text-sm">← Home</RouterLink>

    <header class="mt-3">
      <p class="eyebrow text-sm">{{ SITE_NAME }}</p>
      <h1 class="mt-1 text-4xl">{{ HOME.about.heading }}</h1>
      <p class="mt-4 max-w-[60ch] font-serif text-xl leading-relaxed text-ink">{{ lead }}</p>
      <p v-for="text in rest" :key="text" class="mt-3 max-w-[68ch] leading-relaxed text-muted">
        {{ text }}
      </p>
    </header>

    <nav aria-label="On this page" class="mt-6 flex flex-wrap gap-2" data-testid="about-contents">
      <RouterLink
        v-for="item in contents"
        :key="item.id"
        :to="{ hash: `#${item.id}` }"
        class="btn-quiet !rounded-full !px-3 !py-1 hover:no-underline"
      >
        {{ item.label }}
      </RouterLink>
    </nav>

    <div class="mt-8 space-y-6">
      <AboutSection id="aim" :heading="aim.heading">
        <p v-for="text in aim.text" :key="text" class="mt-2 max-w-[68ch] leading-relaxed">
          {{ text }}
        </p>
      </AboutSection>

      <AboutSection id="vignettes" :heading="vignettes.heading">
        <p v-for="text in vignettes.text" :key="text" class="mt-2 max-w-[68ch] leading-relaxed">
          {{ text }}
        </p>
        <h3 class="eyebrow mt-5 text-base">{{ HOME.more.referencesHeading }}</h3>
        <ul class="mt-2 space-y-2">
          <li
            v-for="source in HOME.more.references"
            :key="source.url"
            class="max-w-[68ch] text-sm leading-relaxed text-muted"
          >
            {{ source.cite }}
            <a :href="source.url" target="_blank" rel="noopener">{{ source.url }}</a>
          </li>
        </ul>
      </AboutSection>

      <AboutSection id="answer" :heading="answer.heading">
        <p v-for="text in answer.text" :key="text" class="mt-2 max-w-[68ch] leading-relaxed">
          {{ text }}
        </p>
        <TermGrid class="mt-5" :items="HOME.more.questions" />
      </AboutSection>

      <AboutSection id="flow" :heading="flow.heading">
        <p v-for="text in flow.text" :key="text" class="mt-2 max-w-[68ch] leading-relaxed">
          {{ text }}
        </p>
        <StepFlow class="mt-4" :steps="INTRO.structure.flow" testid="about-flow" />
        <ol class="mt-5 space-y-4">
          <li
            v-for="(step, i) in INTRO.structure.steps"
            :key="step.term"
            class="grid grid-cols-[2rem_1fr] gap-x-3"
          >
            <span
              class="flex h-8 w-8 items-center justify-center rounded-full bg-ink text-sm font-medium text-white"
              aria-hidden="true"
              >{{ i + 1 }}</span
            >
            <div>
              <p class="font-medium text-ink">{{ step.term }}</p>
              <p class="mt-0.5 max-w-[64ch] leading-relaxed text-muted">{{ step.text }}</p>
            </div>
          </li>
        </ol>
        <p class="mt-5 text-sm text-muted">{{ INTRO.structure.save }}</p>
      </AboutSection>

      <template v-if="isExpert">
        <AboutSection id="my-cases" heading="My cases" testid="about-cases">
          <p class="mt-2 max-w-[68ch] leading-relaxed">{{ CASES_INTRO.expert.lead }}</p>
          <h3 class="eyebrow mt-5 text-base">{{ CASES_INTRO.expert.more.statusHeading }}</h3>
          <TermGrid class="mt-3" :items="CASES_INTRO.expert.more.statuses" />
          <p class="mt-5 text-sm">
            <RouterLink to="/instructions">{{ HOME.more.instructions }}</RouterLink>
          </p>
        </AboutSection>

        <AboutSection id="reviews" heading="Reviews" testid="about-reviews">
          <p class="mt-2 max-w-[68ch] leading-relaxed">{{ REVIEWS_INTRO.expert.lead }}</p>
          <TermGrid class="mt-5" :items="REVIEWS_INTRO.expert.more" />
        </AboutSection>
      </template>

      <AboutSection v-else id="review" :heading="review.heading">
        <p v-for="text in review.text" :key="text" class="mt-2 max-w-[68ch] leading-relaxed">
          {{ text }}
        </p>
      </AboutSection>

      <AboutSection id="answers" :heading="answers.heading" accent>
        <p v-for="text in answers.text" :key="text" class="mt-2 max-w-[68ch] leading-relaxed">
          {{ text }}
        </p>
        <p v-if="isExpert" class="mt-2 max-w-[68ch] leading-relaxed text-muted">
          {{ TRUST_SENTENCE }}
        </p>
      </AboutSection>
    </div>
  </div>
</template>
