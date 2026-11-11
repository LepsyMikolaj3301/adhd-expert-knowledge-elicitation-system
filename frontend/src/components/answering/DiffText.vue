<script setup lang="ts">
import { computed } from 'vue'

import { wordDiff } from '@/answering/wordDiff'

import ChipText from './ChipText.vue'

/** A redline from one version of an answer to another: added words washed, removed ones struck. */
const props = defineProps<{ before: string; after: string }>()

const parts = computed(() => wordDiff(props.before, props.after))
</script>

<template>
  <span class="leading-relaxed" data-testid="diff">
    <template v-for="(part, index) in parts" :key="index">
      <ChipText v-if="part.kind === 'same'" :text="part.text" />
      <ins v-else-if="part.kind === 'added'" class="diff-added no-underline" data-diff="added"
        ><span class="sr-only">added: </span><ChipText :text="part.text"
      /></ins>
      <del v-else class="diff-removed" data-diff="removed"
        ><span class="sr-only">removed: </span><ChipText :text="part.text"
      /></del>
    </template>
  </span>
</template>
