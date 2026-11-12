<script setup lang="ts">
import { RouterLink } from 'vue-router'

import { HOME } from '@/copy'

/**
 * What a page is for, in a sentence or two that is always visible. "Learn more" leads to the
 * fuller explanation on its own page; without `moreTo` there is nothing more to say.
 */
defineProps<{
  lead: string | readonly string[]
  moreTo?: string
  testid?: string
  center?: boolean
}>()
</script>

<template>
  <div :data-testid="testid">
    <p
      v-for="text in typeof lead === 'string' ? [lead] : lead"
      :key="text"
      class="mt-2 max-w-[68ch] leading-relaxed text-muted first:mt-0"
      :class="center && 'mx-auto text-center'"
    >
      {{ text }}
    </p>
    <p v-if="moreTo" class="mt-2 text-sm font-medium" :class="center && 'text-center'">
      <RouterLink :to="moreTo" data-testid="learn-more"
        >{{ HOME.learnMore }} <span aria-hidden="true">→</span></RouterLink
      >
    </p>
  </div>
</template>
