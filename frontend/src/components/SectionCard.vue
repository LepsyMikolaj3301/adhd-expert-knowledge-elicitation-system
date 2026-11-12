<script setup lang="ts">
import { RouterLink } from 'vue-router'

/** One section of the app on the home page: what it is for, what is waiting, and the way in. */
defineProps<{ title: string; text: string; to: string; action: string; testid?: string }>()
</script>

<template>
  <article class="flex flex-col card p-6" :data-testid="testid" :aria-labelledby="`card-${to}`">
    <h2 :id="`card-${to}`" class="text-2xl">{{ title }}</h2>
    <p class="mt-2 text-base leading-relaxed text-muted">{{ text }}</p>
    <div v-if="$slots.default" class="mt-4">
      <slot />
    </div>
    <div class="mt-auto pt-5">
      <RouterLink :to="to" class="btn hover:no-underline">{{ action }}</RouterLink>
    </div>
  </article>
</template>
