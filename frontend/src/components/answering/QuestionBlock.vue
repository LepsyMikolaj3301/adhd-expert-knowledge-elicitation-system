<script setup lang="ts">
import { computed, ref } from 'vue'

import { countWords } from '@/answering/highlights'
import { wordCountLabel } from '@/answering/steps'
import type { AnswerPayload, Q4Answer, QuestionView } from '@/api/client'
import { questionLabel } from '@/copy'

import ChipEditor from './ChipEditor.vue'
import Q4Step from './Q4Step.vue'
import RatingStep from './RatingStep.vue'

/** How long an answer to Q1 can run with no chips before asking which quotes it is about. */
const Q1_NUDGE_WORDS = 60

const props = defineProps<{
  question: QuestionView
  payload: AnswerPayload
  /** What is missing, once the expert has tried to go on without it. Null shows nothing. */
  problem?: string | null
  /** Counts up on every such attempt, so the flash plays again. */
  flashKey?: number
}>()

const emit = defineEmits<{
  answer: [text: string]
  q4: [q4: Q4Answer]
  rate: [rating: number]
  insufficient: []
  active: [chip: number | null]
}>()

const answer = computed(() => props.payload.answers[props.question.id] ?? '')

/** Q4's question, with the what-if picked out as the thing to weigh. */
const heading = computed(() => {
  const text = props.question.text
  const match = props.question.kind === 'shift' ? /^(.* change if )(.+)(\?)$/.exec(text) : null
  return match
    ? { before: match[1], whatIf: match[2], after: match[3] }
    : { before: text, whatIf: '', after: '' }
})

const q1Nudge = computed(
  () =>
    props.question.id === 'Q1' &&
    countWords(answer.value) > Q1_NUDGE_WORDS &&
    !answer.value.includes('⟦h'),
)

const editor = ref<InstanceType<typeof ChipEditor>>()
const q4Box = ref<InstanceType<typeof Q4Step>>()

defineExpose({
  insertChip: (n: number) => (editor.value ?? q4Box.value)?.insertChip(n),
  /** Puts the cursor in the answer box; a question with only a rating has none. */
  focusEnd: () => (editor.value ?? q4Box.value)?.focusEnd(),
})
</script>

<template>
  <section class="py-6 first:pt-0">
    <h1 class="text-[1.375rem] leading-snug tracking-normal" data-testid="question">
      <span class="mb-1 block text-sm font-semibold tracking-wide text-action uppercase">
        {{ questionLabel(question.id) }}
      </span>
      {{ heading.before
      }}<strong v-if="heading.whatIf" class="font-semibold">{{ heading.whatIf }}</strong
      >{{ heading.after }}
    </h1>

    <div
      class="relative mt-5 rounded-sm"
      :class="problem ? 'ring-2 ring-inset ring-danger/70' : ''"
      :data-problem="problem ? 'true' : undefined"
    >
      <!-- Its own element, so the flash can play again without rebuilding the editor. -->
      <div
        v-if="problem"
        :key="flashKey ?? 0"
        class="flag-flash pointer-events-none absolute inset-0 rounded-sm"
        aria-hidden="true"
      />
      <template v-if="question.kind === 'open'">
        <ChipEditor
          ref="editor"
          :model-value="answer"
          :label="`Your answer to ${question.id}`"
          @update:model-value="emit('answer', $event)"
          @active="emit('active', $event)"
        />
        <p class="mt-1 text-sm text-muted" aria-live="polite" data-testid="word-count">
          {{ wordCountLabel(countWords(answer)) }}
        </p>
        <p v-if="q1Nudge" class="mt-2 text-sm text-ink">
          Which quotes is this about? Click one to add it here.
        </p>
      </template>

      <Q4Step
        v-else-if="question.kind === 'shift'"
        ref="q4Box"
        :question="question"
        :q4="payload.q4 ?? null"
        :why="answer"
        @update:q4="emit('q4', $event)"
        @update:why="emit('answer', $event)"
        @active="emit('active', $event)"
      />

      <RatingStep
        v-else
        :rating="payload.rating"
        :insufficient="payload.insufficient_information"
        @rate="emit('rate', $event)"
        @insufficient="emit('insufficient')"
      />
    </div>
    <p v-if="problem" class="mt-3 text-sm text-danger" data-testid="problem">{{ problem }}</p>
  </section>
</template>
