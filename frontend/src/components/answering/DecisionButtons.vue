<script setup lang="ts">
/** The admin's decision on one answer: three large buttons, and a note under the chosen one. */
export type Decision = 'approve' | 'reject' | 'request_changes'

const props = defineProps<{ questionId: string }>()
const decision = defineModel<Decision | ''>('decision', { required: true })
const comment = defineModel<string>('comment', { required: true })

const OPTIONS: { value: Decision; label: string; icon: string; idle: string; chosen: string }[] = [
  {
    value: 'approve',
    label: 'Approve',
    icon: 'M3.5 8.5 6.5 11.5 12.5 4.5',
    idle: 'border-success/50 bg-success/5 text-success hover:bg-success/15',
    chosen: 'border-success bg-success text-white shadow-sm',
  },
  {
    value: 'request_changes',
    label: 'Request changes',
    icon: 'M12.5 6A4.75 4.75 0 1 0 12.6 10M12.75 2.75V6H9.5',
    idle: 'border-warn/50 bg-warn/5 text-warn hover:bg-warn/15',
    chosen: 'border-warn bg-warn text-white shadow-sm',
  },
  {
    value: 'reject',
    label: 'Reject',
    icon: 'M4 4l8 8M12 4l-8 8',
    idle: 'border-danger/50 bg-danger/5 text-danger hover:bg-danger/15',
    chosen: 'border-danger bg-danger text-white shadow-sm',
  },
]

const needsReason = () => decision.value === 'request_changes'
</script>

<template>
  <div class="mt-6" data-testid="decide">
    <p :id="`decide-${props.questionId}`" class="text-sm font-semibold text-ink">Your decision</p>
    <div
      class="mt-2 flex flex-wrap gap-2"
      role="group"
      :aria-labelledby="`decide-${props.questionId}`"
    >
      <button
        v-for="o in OPTIONS"
        :key="o.value"
        type="button"
        class="inline-flex min-h-12 flex-auto cursor-pointer items-center justify-center gap-2 rounded-md border-2 px-4 py-2.5 text-base leading-none font-semibold whitespace-nowrap transition-colors"
        :class="decision === o.value ? o.chosen : o.idle"
        :aria-pressed="decision === o.value"
        :data-decision="o.value"
        @click="decision = decision === o.value ? '' : o.value"
      >
        <svg
          viewBox="0 0 16 16"
          width="18"
          height="18"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
          class="shrink-0"
          aria-hidden="true"
        >
          <path :d="o.icon" />
        </svg>
        {{ o.label }}
      </button>
    </div>
    <textarea
      v-if="decision"
      v-model="comment"
      rows="2"
      class="field mt-3"
      :class="needsReason() && !comment.trim() ? 'border-warn' : ''"
      :aria-label="needsReason() ? 'What should change' : 'A note for the author (optional)'"
      :placeholder="
        needsReason() ? 'What should change? (required)' : 'A note for the author (optional)'
      "
    />
  </div>
</template>
