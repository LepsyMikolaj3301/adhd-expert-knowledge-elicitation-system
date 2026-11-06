<script setup lang="ts">
import { computed } from 'vue'

import { CHIP_RE, inkFor } from '@/answering/highlights'

const props = defineProps<{ text: string }>()
const emit = defineEmits<{ active: [chip: number | null] }>()

/** An answer that can't be edited any more: plain runs of text, and chips between them. */
const parts = computed(() => {
  const found: { text: string; chip: number | null }[] = []
  let at = 0
  for (const match of props.text.matchAll(CHIP_RE)) {
    if (match.index > at) found.push({ text: props.text.slice(at, match.index), chip: null })
    found.push({ text: match[1] as string, chip: Number(match[1]) })
    at = match.index + match[0].length
  }
  if (at < props.text.length) found.push({ text: props.text.slice(at), chip: null })
  return found
})
</script>

<template>
  <span class="whitespace-pre-wrap">
    <template v-for="(part, index) in parts" :key="index">
      <span
        v-if="part.chip !== null"
        class="chip"
        :data-chip="part.chip"
        :style="{ '--ink': inkFor(part.chip) }"
        :aria-label="`reference ${part.chip}`"
        @mouseover="emit('active', part.chip)"
        @mouseout="emit('active', null)"
        >{{ part.text }}</span
      >
      <template v-else>{{ part.text }}</template>
    </template>
  </span>
</template>
