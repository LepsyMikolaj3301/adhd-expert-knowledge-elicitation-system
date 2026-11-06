<script setup lang="ts">
import { computed, ref } from 'vue'

import { countWords } from '@/answering/highlights'
import { q4Wording, wordCountLabel } from '@/answering/steps'
import type { Q4Answer, QuestionView } from '@/api/client'

import ChipEditor from './ChipEditor.vue'

const props = defineProps<{ question: QuestionView; q4: Q4Answer | null; why: string }>()
const emit = defineEmits<{
  'update:q4': [q4: Q4Answer]
  'update:why': [why: string]
  active: [chip: number | null]
}>()

const STOPS = [-2, -1, 0, 1, 2]
const TOWARD = ['more_adhd', 'less_adhd', 'other'] as const

const wording = computed(() => q4Wording(props.question))
const shift = computed(() => props.q4?.shift ?? null)
const askDirection = computed(() => shift.value !== null && shift.value > 0)
const askWhy = computed(() => shift.value !== null && shift.value !== 0)
const whyWords = computed(() => countWords(props.why))

function update(change: Partial<Q4Answer>) {
  emit('update:q4', { ...props.q4, ...change })
}

function signed(value: number): string {
  return value > 0 ? `+${value}` : value < 0 ? `−${-value}` : '0'
}

const editor = ref<InstanceType<typeof ChipEditor>>()
defineExpose({
  insertChip: (n: number) => editor.value?.insertChip(n),
  canInsert: askWhy,
})
</script>

<template>
  <div class="space-y-7">
    <label class="block">
      <span class="text-sm font-medium text-ink">{{ wording.hypothesis }}</span>
      <input
        class="field"
        type="text"
        maxlength="2000"
        data-testid="hypothesis"
        :value="q4?.hypothesis ?? ''"
        @input="update({ hypothesis: ($event.target as HTMLInputElement).value })"
      />
    </label>

    <fieldset>
      <legend class="text-sm font-medium text-ink">{{ wording.shift_lead }}</legend>
      <div class="mt-3 grid gap-2 sm:grid-cols-5 sm:gap-0">
        <label
          v-for="stop in STOPS"
          :key="stop"
          class="group relative flex cursor-pointer items-center gap-3 sm:flex-col sm:gap-1.5 sm:text-center"
        >
          <input
            class="peer sr-only"
            type="radio"
            name="q4-shift"
            :value="stop"
            :checked="shift === stop"
            @change="update({ shift: stop })"
          />
          <!-- The line between the stops. No stop looks chosen until the expert chooses one. -->
          <span
            aria-hidden="true"
            class="absolute top-[calc(0.625rem-0.5px)] right-1/2 hidden h-px w-full bg-line group-first:hidden sm:block"
          />
          <!-- z-10: the next stop's line runs into this dot's centre and must stay behind it. -->
          <span
            aria-hidden="true"
            class="relative z-10 h-5 w-5 shrink-0 rounded-full border-2 border-line bg-surface group-hover:border-action peer-checked:border-action peer-checked:bg-action peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-action"
          />
          <span class="text-sm leading-tight peer-checked:font-semibold peer-checked:text-ink">
            <span class="sm:block">{{ signed(stop) }}</span>
            {{ wording.shift_labels[String(stop)] }}
          </span>
        </label>
      </div>
    </fieldset>

    <fieldset v-if="askDirection">
      <legend class="text-sm font-medium text-ink">{{ wording.toward }}</legend>
      <div class="mt-2 space-y-1.5">
        <label v-for="option in TOWARD" :key="option" class="flex items-center gap-2 text-sm">
          <input
            type="radio"
            name="q4-toward"
            :value="option"
            :checked="q4?.toward === option"
            @change="update({ toward: option })"
          />
          {{ wording.toward_labels[option] }}
        </label>
      </div>
      <label v-if="q4?.toward === 'other'" class="mt-3 block">
        <span class="text-sm font-medium text-ink">Which explanation?</span>
        <input
          class="field"
          type="text"
          maxlength="2000"
          :value="q4?.other_explanation ?? ''"
          @input="update({ other_explanation: ($event.target as HTMLInputElement).value })"
        />
      </label>
    </fieldset>

    <div v-if="askWhy">
      <p id="q4-why" class="mb-1 text-sm font-medium text-ink">{{ wording.why }}</p>
      <ChipEditor
        ref="editor"
        :model-value="why"
        :label="wording.why"
        @update:model-value="emit('update:why', $event)"
        @active="emit('active', $event)"
      />
      <p class="mt-1 text-sm text-muted" aria-live="polite">
        {{ wordCountLabel(whyWords) }}
      </p>
    </div>
  </div>
</template>
