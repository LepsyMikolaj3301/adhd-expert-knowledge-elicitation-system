<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { acknowledgeIntro } from '@/intro'
import { DIRECTIONS, INTRO } from '@/copy'
import { safeNextPath } from '@/router/guard'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const hideAgain = ref(false)

async function carryOn() {
  if (auth.user) acknowledgeIntro(auth.user.id, hideAgain.value)
  // Sent here on the way to a case: go there. Opened from the link: back to the list of cases.
  const next = route.query.next
  await router.push(typeof next === 'string' ? safeNextPath(next) : '/assignments')
}
</script>

<template>
  <div class="max-w-[68ch]">
    <h1>{{ INTRO.title }}</h1>
    <p class="mt-2 text-muted">{{ INTRO.lead }}</p>

    <section class="mt-8" aria-labelledby="intro-what">
      <h2 id="intro-what" class="text-lg font-semibold text-ink">{{ INTRO.what.heading }}</h2>
      <p v-for="text in INTRO.what.text" :key="text" class="mt-2 leading-relaxed">{{ text }}</p>
    </section>

    <section class="mt-8" aria-labelledby="intro-aim">
      <h2 id="intro-aim" class="text-lg font-semibold text-ink">{{ INTRO.aim.heading }}</h2>
      <dl class="mt-2 space-y-3">
        <div v-for="item in INTRO.aim.items" :key="item.term">
          <dt class="font-medium text-ink">{{ item.term }}</dt>
          <dd class="leading-relaxed">{{ item.text }}</dd>
        </div>
      </dl>
    </section>

    <section
      class="mt-8 rounded-sm border-l-2 border-action bg-surface px-4 py-4"
      aria-labelledby="intro-structure"
      data-testid="intro-structure"
    >
      <h2 id="intro-structure" class="text-lg font-semibold text-ink">
        {{ INTRO.structure.heading }}
      </h2>
      <p class="mt-2 font-medium text-ink">{{ INTRO.structure.lead }}</p>

      <ol
        class="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm"
        aria-label="The order of a case"
        data-testid="intro-flow"
      >
        <template v-for="(label, i) in INTRO.structure.flow" :key="label">
          <li
            class="rounded-sm border px-2 py-1"
            :class="label === 'Lock in' ? 'border-action font-semibold text-ink' : 'border-line'"
          >
            {{ label }}
          </li>
          <li v-if="i < INTRO.structure.flow.length - 1" aria-hidden="true" class="text-muted">
            →
          </li>
        </template>
      </ol>

      <dl class="mt-4 space-y-3">
        <div v-for="item in INTRO.structure.steps" :key="item.term">
          <dt class="font-medium text-ink">{{ item.term }}</dt>
          <dd class="leading-relaxed">{{ item.text }}</dd>
        </div>
      </dl>
      <p class="mt-3 text-sm text-muted">{{ INTRO.structure.save }}</p>
    </section>

    <section class="mt-8" aria-labelledby="intro-hints">
      <h2 id="intro-hints" class="text-lg font-semibold text-ink">{{ INTRO.hints.heading }}</h2>
      <ul class="mt-2 list-disc space-y-2 pl-5 leading-relaxed">
        <li v-for="hint in INTRO.hints.items" :key="hint">{{ hint }}</li>
      </ul>
      <p class="mt-4 font-medium text-ink">{{ INTRO.hints.directionsLead }}</p>
      <dl class="mt-2 space-y-2 text-sm">
        <div v-for="d in DIRECTIONS" :key="d.value">
          <dt class="font-medium">{{ d.label }}</dt>
          <dd class="text-muted">{{ d.help }}</dd>
        </div>
      </dl>
    </section>

    <footer
      class="mt-10 flex flex-wrap items-center justify-between gap-4 border-t border-line pt-4"
    >
      <label class="flex cursor-pointer items-center gap-2 text-sm">
        <input v-model="hideAgain" type="checkbox" data-testid="intro-hide" />
        {{ INTRO.hideAgain }}
      </label>
      <button type="button" class="btn" data-testid="intro-continue" @click="carryOn">
        {{ INTRO.continue }}
      </button>
    </footer>
  </div>
</template>
