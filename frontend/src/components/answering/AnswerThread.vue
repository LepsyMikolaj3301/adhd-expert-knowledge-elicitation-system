<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'

import { quoted, useCommentSink, type CommentSink } from '@/answering/commentSink'
import { readable } from '@/answering/plainText'
import { api, type CommentView, type LinkedHighlight, type QuestionId } from '@/api/client'
import ChipEditor from '@/components/answering/ChipEditor.vue'
import ChipText from '@/components/answering/ChipText.vue'
import UnsavedText from '@/components/answering/UnsavedText.vue'
import PseudonymChip from '@/components/PseudonymChip.vue'
import { describeError, postedAt, speakerLabel, STANCES } from '@/copy'

/**
 * The discussion under one answer, folded away until opened: comments, and replies one level
 * deep. Its comment box takes quotes, from the quote table, the case text, or an answer's tags.
 */
const props = defineProps<{
  assignmentId: string
  questionId: string
  /** "Question 2", for saying where a quote went. */
  questionName: string
  comments: CommentView[]
  highlights: LinkedHighlight[]
  canComment: boolean
  /** Only reviewers take a side; the author and the admin don't. */
  canStance: boolean
  /** Opened from the start: a link pointed at this answer. */
  startOpen?: boolean
}>()
const emit = defineEmits<{ posted: [] }>()

const STANCE_TONE: Record<keyof typeof STANCES, string> = {
  support: 'border-success/40 bg-success/10 text-success',
  challenge: 'border-danger/40 bg-danger/10 text-danger',
  question: 'border-action/40 bg-action/10 text-action',
}

const open = ref(props.startOpen ?? false)
const body = ref('')
const stance = ref<CommentView['stance']>(null)
const replyTo = ref<string | null>(null)
const error = ref('')
const notice = ref('')
const busy = ref(false)
const editor = ref<InstanceType<typeof ChipEditor>>()
const composer = ref<HTMLElement>()
const sink = useCommentSink()

const top = computed(() => props.comments.filter((c) => !c.parent_id))
const repliesTo = (id: string) => props.comments.filter((c) => c.parent_id === id)
const replyingTo = computed(() => props.comments.find((c) => c.id === replyTo.value) ?? null)
const countLabel = computed(() => {
  const n = props.comments.length
  return n === 0 ? 'No comments yet' : n === 1 ? '1 comment' : `${n} comments`
})

/** Says where the quote went, and flashes the box so the eye finds it. */
function added(what: string) {
  notice.value = `${what} added to your comment on ${props.questionName.toLowerCase()}.`
  composer.value?.animate?.(
    [
      { boxShadow: '0 0 0 4px color-mix(in srgb, var(--color-action) 35%, transparent)' },
      { boxShadow: '0 0 0 0 transparent' },
    ],
    { duration: 900, easing: 'ease-out' },
  )
}

const me: CommentSink = {
  questionId: props.questionId,
  insertChip: (chip) => {
    editor.value?.insertChip(chip)
    added(`Quote ${chip}`)
  },
  insertText: (text) => {
    editor.value?.insertText(text)
    added('The passage')
  },
}

function claim() {
  if (props.canComment) sink.value = me
}

function release() {
  if (sink.value === me) sink.value = null
}

watch(open, (isOpen) => (isOpen ? claim() : release()), { immediate: true })
onUnmounted(release)

/** From a quote tag in the answer: open the discussion and put the quote in its comment box. */
async function addQuote(target: string) {
  open.value = true
  await nextTick()
  claim()
  const highlight = props.highlights.find((h) => h.id === target)
  if (highlight?.chip) me.insertChip(highlight.chip)
  else if (highlight) me.insertText(quoted(highlight.text))
}

async function startReply(id: string) {
  replyTo.value = id
  await nextTick()
  claim()
  editor.value?.focusEnd()
}

async function post() {
  busy.value = true
  error.value = ''
  try {
    await api.POST('/api/v1/assignments/{assignment_id}/answers/{question_id}/comments', {
      params: {
        path: {
          assignment_id: props.assignmentId,
          question_id: props.questionId as QuestionId,
        },
      },
      body: {
        body: body.value,
        parent_id: replyTo.value,
        stance: props.canStance ? stance.value : null,
      },
    })
    body.value = ''
    stance.value = null
    replyTo.value = null
    notice.value = ''
    emit('posted')
  } catch (e) {
    // The text stays in the box, and is offered for copying too.
    error.value = describeError(e)
  } finally {
    busy.value = false
  }
}

defineExpose({ addQuote })
</script>

<template>
  <section class="mt-6 border-t border-line pt-4">
    <button
      type="button"
      class="flex w-full cursor-pointer items-center justify-between gap-3 rounded-md px-2 py-1.5 text-left text-sm font-medium text-ink hover:bg-page"
      :aria-expanded="open"
      data-testid="discussion-toggle"
      @click="open = !open"
    >
      <span class="flex items-center gap-2">
        <svg
          viewBox="0 0 16 16"
          width="14"
          height="14"
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
          stroke-linecap="round"
          stroke-linejoin="round"
          class="transition-transform"
          :class="open ? 'rotate-90' : ''"
          aria-hidden="true"
        >
          <path d="M6 3.5 10.5 8 6 12.5" />
        </svg>
        Discussion
        <span class="font-normal text-muted">| {{ countLabel }}</span>
      </span>
      <span v-if="!open && canComment" class="text-xs font-normal text-action">Add a comment</span>
    </button>

    <div v-if="open" class="mt-3 px-1" data-testid="discussion">
      <ul class="space-y-4 text-sm" data-testid="comments">
        <li v-for="c in top" :key="c.id" data-testid="comment">
          <div
            class="rounded-lg rounded-tl-sm border border-line px-3 py-2"
            :class="c.is_mine ? 'bg-action/5' : 'bg-surface'"
          >
            <p class="flex flex-wrap items-center gap-x-2 gap-y-1">
              <PseudonymChip
                v-if="c.speaker?.pseudonym"
                :pseudonym="c.speaker.pseudonym"
                class="font-semibold"
              />
              <strong v-else class="font-semibold">{{ speakerLabel(c.speaker) }}</strong>
              <span
                v-if="c.stance"
                class="rounded-full border px-2 text-xs font-medium"
                :class="STANCE_TONE[c.stance]"
                >{{ STANCES[c.stance] }}</span
              >
              <span class="ml-auto text-xs text-muted">{{ postedAt(c.created_at) }}</span>
            </p>
            <p class="mt-1 leading-relaxed" data-testid="comment-body">
              <ChipText :text="c.body" />
            </p>
          </div>
          <button
            v-if="canComment"
            type="button"
            class="mt-1 ml-2 cursor-pointer text-xs text-action hover:underline"
            @click="startReply(c.id)"
          >
            Reply
          </button>
          <ul v-if="repliesTo(c.id).length" class="mt-2 ml-5 space-y-2 border-l-2 border-line pl-3">
            <li v-for="r in repliesTo(c.id)" :key="r.id">
              <div
                class="rounded-lg rounded-tl-sm border border-line px-3 py-2"
                :class="r.is_mine ? 'bg-action/5' : 'bg-surface'"
              >
                <p class="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <PseudonymChip
                    v-if="r.speaker?.pseudonym"
                    :pseudonym="r.speaker.pseudonym"
                    class="font-semibold"
                  />
                  <strong v-else class="font-semibold">{{ speakerLabel(r.speaker) }}</strong>
                  <span
                    v-if="r.stance"
                    class="rounded-full border px-2 text-xs font-medium"
                    :class="STANCE_TONE[r.stance]"
                    >{{ STANCES[r.stance] }}</span
                  >
                  <span class="ml-auto text-xs text-muted">{{ postedAt(r.created_at) }}</span>
                </p>
                <p class="mt-1 leading-relaxed" data-testid="comment-body">
                  <ChipText :text="r.body" />
                </p>
              </div>
              <!-- A reply to a reply goes under the same comment: threads are one level deep. -->
              <button
                v-if="canComment"
                type="button"
                class="mt-1 ml-2 cursor-pointer text-xs text-action hover:underline"
                @click="startReply(c.id)"
              >
                Reply
              </button>
            </li>
          </ul>
        </li>
      </ul>
      <p v-if="!top.length" class="text-sm text-muted">No comments yet.</p>

      <form v-if="canComment" class="mt-5" @submit.prevent="post">
        <p class="flex flex-wrap items-baseline justify-between gap-x-3 text-sm font-medium">
          <span v-if="replyingTo">
            Reply to {{ speakerLabel(replyingTo.speaker) }}
            <button
              type="button"
              class="ml-1 cursor-pointer text-xs font-normal text-action hover:underline"
              @click="replyTo = null"
            >
              Cancel reply
            </button>
          </span>
          <span v-else>Add a comment</span>
          <span class="text-xs font-normal text-muted">
            Click a quote, or select words in the case, to quote it.
          </span>
        </p>
        <div ref="composer" class="mt-1.5 rounded-sm" data-testid="composer">
          <ChipEditor
            ref="editor"
            v-model="body"
            compact
            :label="replyTo ? 'Your reply' : 'Add a comment'"
            @focus="claim"
          />
        </div>
        <p class="mt-1 min-h-4 text-xs text-action" aria-live="polite" data-testid="quote-notice">
          {{ notice }}
        </p>
        <div class="mt-2 flex flex-wrap items-center gap-3">
          <select
            v-if="canStance"
            v-model="stance"
            class="field !mt-0 !w-auto"
            aria-label="Your stance"
          >
            <option :value="null">No stance</option>
            <option v-for="(label, value) in STANCES" :key="value" :value="value">
              {{ label }}
            </option>
          </select>
          <button class="btn" :disabled="busy || !body.trim()">
            {{ replyTo ? 'Post reply' : 'Post' }}
          </button>
        </div>
        <div v-if="error" class="alert mt-2" role="alert">
          <p>{{ error }}</p>
          <UnsavedText :text="readable(body)" class="mt-2" />
        </div>
      </form>
    </div>
  </section>
</template>
