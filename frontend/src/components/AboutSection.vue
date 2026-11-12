<script setup lang="ts">
/** One section of the About page: the anchor the contents links jump to, and its heading. */
defineProps<{ id: string; heading: string; accent?: boolean; testid?: string }>()
</script>

<template>
  <section
    :id="id"
    class="card p-6"
    :class="accent && 'border-l-2 border-l-action'"
    :aria-labelledby="`h-${id}`"
    :data-testid="testid"
  >
    <h2 :id="`h-${id}`" class="text-2xl">{{ heading }}</h2>
    <slot />
  </section>
</template>
