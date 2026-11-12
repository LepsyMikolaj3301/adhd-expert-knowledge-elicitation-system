<script setup lang="ts">
/** The order of a case as a strip of steps. `current` is outlined, e.g. the step the page is about. */
defineProps<{ steps: readonly string[]; current?: string; testid?: string }>()
</script>

<template>
  <ol
    class="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm"
    aria-label="The order of a case"
    :data-testid="testid"
  >
    <template v-for="(label, i) in steps" :key="label">
      <li
        class="rounded-sm border px-2 py-1"
        :class="label === current ? 'border-action font-semibold text-ink' : 'border-line'"
      >
        {{ label }}
      </li>
      <li v-if="i < steps.length - 1" aria-hidden="true" class="text-muted">→</li>
    </template>
  </ol>
</template>
