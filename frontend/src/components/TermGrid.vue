<script setup lang="ts">
/** Short terms with what each one means, two to a row. */
defineProps<{ items: readonly { term: string; text: string }[] }>()
</script>

<template>
  <dl class="grid gap-3 sm:grid-cols-2">
    <div
      v-for="item in items"
      :key="item.term"
      class="rounded-sm border border-line bg-page px-3 py-2"
    >
      <dt class="font-medium text-ink">{{ item.term }}</dt>
      <dd class="mt-0.5 text-sm leading-relaxed text-muted">{{ item.text }}</dd>
    </div>
  </dl>
</template>
