<script setup lang="ts" generic="T extends string">
/** A row of buttons of which exactly one is on, like tabs that filter one list. */
defineProps<{
  options: readonly { value: T; label: string }[]
  /** What the group is for, said by a screen reader. */
  label: string
  disabled?: boolean
}>()

const model = defineModel<T>({ required: true })
</script>

<template>
  <div class="flex flex-wrap gap-2" role="group" :aria-label="label">
    <button
      v-for="o in options"
      :key="o.value"
      type="button"
      :class="model === o.value ? 'btn' : 'btn-quiet'"
      :aria-pressed="model === o.value"
      :disabled="disabled"
      @click="model = o.value"
    >
      {{ o.label }}
    </button>
  </div>
</template>
