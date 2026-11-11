<script setup lang="ts">
/** A loading circle. The words next to it say what is happening; this only shows that it is. */
withDefaults(defineProps<{ size?: number; label?: string }>(), { size: 20, label: undefined })
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    class="shrink-0 animate-spin text-action motion-reduce:animate-[spin_3s_linear_infinite]"
    :role="label ? 'img' : undefined"
    :aria-label="label"
    :aria-hidden="label ? undefined : 'true'"
    data-testid="spinner"
  >
    <circle cx="12" cy="12" r="9" stroke="currentColor" stroke-opacity="0.2" stroke-width="3" />
    <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" stroke-width="3" stroke-linecap="round" />
  </svg>
</template>
