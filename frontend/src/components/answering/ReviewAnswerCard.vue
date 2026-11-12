<script setup lang="ts">
import { computed, ref } from 'vue'

import type { AnswerVote, LinkedHighlight, ReviewAnswer } from '@/api/client'
import AnswerThread from '@/components/answering/AnswerThread.vue'
import ChipText from '@/components/answering/ChipText.vue'
import QuoteTag from '@/components/answering/QuoteTag.vue'
import { questionLabel, quoteTagLabel, speakerLabel, tallyLabel } from '@/copy'

/**
 * One answer under review, set like a message from its author: the tally in the corner, the
 * reviewer's vote, the admin's decision (passed in as a slot) and the discussion folded below.
 */
const props = defineProps<{
  answer: ReviewAnswer
  highlights: LinkedHighlight[]
  assignmentId: string
  /** "You", "Author", or the author's pseudonym for the admin. */
  authorName: string
  canVote: boolean
  canComment: boolean
  /** The admin sees who voted which way. */
  showVoters: boolean
  startOpen: boolean
}>()
const emit = defineEmits<{ vote: [choice: AnswerVote]; posted: [] }>()

const DECISION: Record<string, { label: string; tone: string }> = {
  approve: { label: 'Approved', tone: 'border-success/40 bg-success/10 text-success' },
  reject: { label: 'Rejected', tone: 'border-danger/40 bg-danger/10 text-danger' },
  request_changes: { label: 'Changes requested', tone: 'border-warn/40 bg-warn/10 text-warn' },
}

const thread = ref<InstanceType<typeof AnswerThread>>()
const name = computed(() => questionLabel(props.answer.question_id))
const tally = computed(() => {
  const base = tallyLabel(props.answer.approvals, props.answer.disapprovals)
  if (!props.showVoters || !props.answer.votes.length) return base
  const who = (v: AnswerVote) =>
    props.answer.votes
      .filter((e) => e.vote === v)
      .map((e) => speakerLabel(e.speaker))
      .join(', ')
  return [
    base,
    who('approve') && `Approve: ${who('approve')}`,
    who('disapprove') && `Disapprove: ${who('disapprove')}`,
  ]
    .filter(Boolean)
    .join('\n')
})
const decision = computed(() =>
  props.answer.decision ? DECISION[props.answer.decision.decision] : null,
)

function addQuote(target: string) {
  void thread.value?.addQuote(target)
}
</script>

<template>
  <li :id="`answer-${answer.question_id}`" class="card p-5" data-testid="answer">
    <header class="flex items-start justify-between gap-4">
      <h2 class="min-w-0 text-base">
        <span class="mb-0.5 block text-xs font-semibold tracking-wide text-action uppercase">
          {{ name }}
        </span>
        {{ answer.question }}
      </h2>
      <p
        class="flex shrink-0 items-center gap-1.5 text-sm font-semibold"
        :title="tally"
        :aria-label="tallyLabel(answer.approvals, answer.disapprovals)"
        data-testid="tally"
      >
        <span
          class="inline-flex items-center gap-1 rounded-full border border-success/40 bg-success/10 px-2.5 py-0.5 text-success"
          :class="{ 'ring-2 ring-success/40': answer.my_vote === 'approve' }"
        >
          <svg
            viewBox="0 0 16 16"
            width="13"
            height="13"
            fill="none"
            stroke="currentColor"
            stroke-width="2.2"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path d="M3.5 8.5 6.5 11.5 12.5 4.5" />
          </svg>
          {{ answer.approvals }}
        </span>
        <span
          class="inline-flex items-center gap-1 rounded-full border border-danger/40 bg-danger/10 px-2.5 py-0.5 text-danger"
          :class="{ 'ring-2 ring-danger/40': answer.my_vote === 'disapprove' }"
        >
          <svg
            viewBox="0 0 16 16"
            width="13"
            height="13"
            fill="none"
            stroke="currentColor"
            stroke-width="2.2"
            stroke-linecap="round"
            aria-hidden="true"
          >
            <path d="M4.5 4.5l7 7M11.5 4.5l-7 7" />
          </svg>
          {{ answer.disapprovals }}
        </span>
      </p>
    </header>

    <!-- The author's answer: one plain box, a sentence per row, and what each row is about. -->
    <section
      class="mt-4 rounded-md border border-line bg-page px-4 py-3"
      :aria-label="`Answer by ${authorName}`"
      data-testid="author-answer"
    >
      <p class="eyebrow">Answer · {{ authorName }}</p>
      <ol v-if="answer.lines.length" class="mt-2 divide-y divide-line/60" data-testid="lines">
        <li
          v-for="(line, index) in answer.lines"
          :key="index"
          class="grid gap-x-4 gap-y-1.5 py-2 first:pt-0 last:pb-0 sm:grid-cols-[minmax(0,1fr)_auto]"
        >
          <span class="min-w-0 text-[0.95rem] leading-relaxed break-words">
            <ChipText :text="line.text" />
          </span>
          <span
            class="flex flex-wrap content-start items-center gap-1.5 sm:max-w-48 sm:justify-end sm:pt-0.5"
          >
            <span v-for="target in line.targets" :key="target" class="inline-flex items-center">
              <QuoteTag :target="target" :highlights="highlights" />
              <button
                v-if="canComment && target !== 'case'"
                type="button"
                class="ml-1 inline-flex h-5 w-5 cursor-pointer items-center justify-center rounded-sm border border-line bg-surface text-xs leading-none font-semibold text-action hover:border-action"
                :aria-label="`Add ${quoteTagLabel(target, highlights.find((h) => h.id === target) ?? null)} to your comment`"
                title="Add to your comment"
                data-testid="quote-to-comment"
                @click="addQuote(target)"
              >
                +
              </button>
            </span>
          </span>
        </li>
      </ol>
      <p v-else class="mt-2 text-[0.95rem] leading-relaxed break-words">
        <ChipText :text="answer.text" />
      </p>
    </section>

    <div v-if="canVote" class="mt-5" data-testid="votes">
      <div class="flex flex-wrap items-center gap-2">
        <span class="mr-1 text-sm font-medium text-ink">Your vote</span>
        <button
          type="button"
          class="inline-flex cursor-pointer items-center gap-1.5 rounded-md border-2 px-4 py-1.5 text-sm font-semibold transition-colors"
          :class="
            answer.my_vote === 'approve'
              ? 'border-success bg-success text-white'
              : 'border-success/50 bg-success/5 text-success hover:bg-success/15'
          "
          :aria-pressed="answer.my_vote === 'approve'"
          @click="emit('vote', 'approve')"
        >
          Approve
        </button>
        <button
          type="button"
          class="inline-flex cursor-pointer items-center gap-1.5 rounded-md border-2 px-4 py-1.5 text-sm font-semibold transition-colors"
          :class="
            answer.my_vote === 'disapprove'
              ? 'border-danger bg-danger text-white'
              : 'border-danger/50 bg-danger/5 text-danger hover:bg-danger/15'
          "
          :aria-pressed="answer.my_vote === 'disapprove'"
          @click="emit('vote', 'disapprove')"
        >
          Disapprove
        </button>
      </div>
    </div>

    <p
      v-if="decision && answer.decision"
      class="mt-5 rounded-md border px-3 py-2 text-sm"
      :class="decision.tone"
      data-testid="decision"
    >
      <strong>{{ decision.label }}</strong
      ><template v-if="answer.decision.comment"
        >: <span class="text-text">{{ answer.decision.comment }}</span></template
      >
    </p>

    <slot name="decide" />

    <AnswerThread
      ref="thread"
      :assignment-id="assignmentId"
      :question-id="answer.question_id"
      :question-name="name"
      :comments="answer.comments"
      :highlights="highlights"
      :can-comment="canComment"
      :can-stance="canVote"
      :start-open="startOpen"
      @posted="emit('posted')"
    />
  </li>
</template>
