<script setup lang="ts">
import { computed } from 'vue'

import { CHIP_RE, inkFor } from '@/answering/highlights'
import { listMarker } from '@/answering/listLines'

const props = defineProps<{ text: string }>()
const emit = defineEmits<{ active: [chip: number | null] }>()

function partsOf(line: string) {
  const found: { text: string; chip: number | null }[] = []
  let at = 0
  for (const match of line.matchAll(CHIP_RE)) {
    if (match.index > at) found.push({ text: line.slice(at, match.index), chip: null })
    found.push({ text: match[1] as string, chip: Number(match[1]) })
    at = match.index + match[0].length
  }
  if (at < line.length) found.push({ text: line.slice(at), chip: null })
  return found
}

/**
 * An answer that can't be edited any more, line by line: plain runs of text with chips between them.
 * A list item is its own block, indented like in the editor. Other lines stay inline, so that a label
 * in front of the answer ("Why: …") still flows into it.
 */
const lines = computed(() =>
  props.text.split('\n').map((line, index, all) => {
    const list = listMarker(line) !== null
    return { parts: partsOf(line), list, end: list || index === all.length - 1 ? '' : '\n' }
  }),
)
</script>

<template>
  <span class="whitespace-pre-wrap">
    <template v-for="(line, lineIndex) in lines" :key="lineIndex">
      <span :class="line.list ? 'list-line block' : undefined">
        <template v-for="(part, index) in line.parts" :key="index">
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
        </template></span
      >{{ line.end }}
    </template>
  </span>
</template>
