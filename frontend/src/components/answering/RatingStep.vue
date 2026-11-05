<script setup lang="ts">
defineProps<{ rating: number | null | undefined; insufficient: boolean }>()
defineEmits<{ rate: [rating: number]; insufficient: [] }>()

const RATINGS = [1, 2, 3, 4, 5]
</script>

<template>
  <fieldset>
    <legend class="sr-only">Your rating</legend>
    <div class="flex flex-wrap items-center gap-2">
      <label v-for="value in RATINGS" :key="value" class="cursor-pointer">
        <input
          class="peer sr-only"
          type="radio"
          name="q6"
          :value="value"
          :checked="rating === value"
          @change="$emit('rate', value)"
        />
        <span
          class="flex h-11 w-11 items-center justify-center rounded-sm border border-line bg-surface font-serif text-lg hover:border-action peer-checked:border-action peer-checked:bg-action peer-checked:text-white peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-action"
        >
          {{ value }}
        </span>
      </label>
      <label class="ml-2 cursor-pointer">
        <input
          class="peer sr-only"
          type="radio"
          name="q6"
          :checked="insufficient"
          @change="$emit('insufficient')"
        />
        <span
          class="flex h-11 items-center rounded-sm border border-line bg-surface px-4 text-sm hover:border-action peer-checked:border-action peer-checked:bg-action peer-checked:text-white peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-action"
        >
          Insufficient information
        </span>
      </label>
    </div>
  </fieldset>
</template>
