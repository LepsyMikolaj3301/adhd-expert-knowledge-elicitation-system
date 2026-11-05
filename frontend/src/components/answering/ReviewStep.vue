<script setup lang="ts">
import { GATE_IDS, q4Wording } from '@/answering/steps'
import type { AnswerPayload, QuestionView } from '@/api/client'

import ChipText from './ChipText.vue'

const props = defineProps<{
  questions: QuestionView[]
  payload: AnswerPayload
  /** Which questions still have an Edit button. */
  editableIds: string[]
}>()

defineEmits<{ edit: [id: string]; active: [chip: number | null] }>()

function answerOf(id: string): string {
  return props.payload.answers[id] ?? ''
}

function scaleLine(question: QuestionView): string {
  const q4 = props.payload.q4
  if (q4?.shift === null || q4?.shift === undefined) return ''
  const wording = q4Wording(question)
  const sign = q4.shift > 0 ? '+' : q4.shift < 0 ? '−' : ''
  let line = `${sign}${Math.abs(q4.shift)} ${wording.shift_labels[String(q4.shift)]}`
  if (q4.toward) {
    const towards = q4.toward === 'other' ? q4.other_explanation : wording.toward_labels[q4.toward]
    line += `, towards ${towards}`
  }
  return line
}
</script>

<template>
  <ol class="divide-y divide-line border-y border-line">
    <li v-for="question in questions" :key="question.id" class="py-4" data-testid="review-answer">
      <div class="flex items-baseline justify-between gap-4">
        <h2 class="text-base">
          <span class="text-muted">{{ question.id }}</span> {{ question.text }}
        </h2>
        <button
          v-if="editableIds.includes(question.id)"
          type="button"
          class="btn-quiet shrink-0 !px-3 !py-1"
          @click="$emit('edit', question.id)"
        >
          Edit
        </button>
        <span v-else-if="GATE_IDS.includes(question.id)" class="shrink-0 text-sm text-muted">
          Locked
        </span>
      </div>

      <div class="mt-2 text-[0.95rem] leading-relaxed">
        <template v-if="question.kind === 'open'">
          <ChipText :text="answerOf(question.id)" @active="$emit('active', $event)" />
        </template>
        <template v-else-if="question.kind === 'shift'">
          <p>Hypothesis: {{ payload.q4?.hypothesis }}</p>
          <p class="mt-1">{{ scaleLine(question) }}</p>
          <p v-if="payload.q4?.shift && answerOf('Q4')" class="mt-1">
            Why: <ChipText :text="answerOf('Q4')" @active="$emit('active', $event)" />
          </p>
        </template>
        <template v-else>
          <p>
            {{
              payload.insufficient_information
                ? 'Insufficient information'
                : `${payload.rating} of 5`
            }}
          </p>
        </template>
      </div>
    </li>
  </ol>
</template>
