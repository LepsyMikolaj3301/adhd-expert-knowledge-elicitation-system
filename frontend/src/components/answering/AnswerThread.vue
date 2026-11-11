<script setup lang="ts">
import { computed, ref } from 'vue'

import { api, type CommentView, type QuestionId } from '@/api/client'
import UnsavedText from '@/components/answering/UnsavedText.vue'
import PseudonymChip from '@/components/PseudonymChip.vue'
import { describeError, speakerLabel, STANCES } from '@/copy'

/** The discussion under one answer: comments, and replies one level deep. */
const props = defineProps<{
  assignmentId: string
  questionId: string
  comments: CommentView[]
  canComment: boolean
  /** Only reviewers take a side; the author and the admin don't. */
  canStance: boolean
}>()
const emit = defineEmits<{ posted: [] }>()

const body = ref('')
const stance = ref<CommentView['stance']>(null)
const replyTo = ref<string | null>(null)
const error = ref('')
const busy = ref(false)

const top = computed(() => props.comments.filter((c) => !c.parent_id))
const repliesTo = (id: string) => props.comments.filter((c) => c.parent_id === id)

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
    emit('posted')
  } catch (e) {
    // The text stays in the box, and is offered for copying too.
    error.value = describeError(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="mt-4 border-t border-line pt-3">
    <ul class="space-y-3 text-sm" data-testid="comments">
      <li v-for="c in top" :key="c.id" data-testid="comment">
        <p>
          <PseudonymChip
            v-if="c.speaker?.pseudonym"
            :pseudonym="c.speaker.pseudonym"
            class="font-bold"
          />
          <strong v-else>{{ speakerLabel(c.speaker) }}</strong>
          <span v-if="c.stance" class="ml-2 rounded-sm border border-line px-1.5 text-xs">{{
            STANCES[c.stance]
          }}</span>
        </p>
        <p class="whitespace-pre-wrap">{{ c.body }}</p>
        <button v-if="canComment" type="button" class="text-xs" @click="replyTo = c.id">
          Reply
        </button>
        <ul v-if="repliesTo(c.id).length" class="mt-2 space-y-2 border-l-2 border-line pl-3">
          <li v-for="r in repliesTo(c.id)" :key="r.id">
            <p>
              <PseudonymChip
                v-if="r.speaker?.pseudonym"
                :pseudonym="r.speaker.pseudonym"
                class="font-bold"
              />
              <strong v-else>{{ speakerLabel(r.speaker) }}</strong>
              <span v-if="r.stance" class="ml-2 rounded-sm border border-line px-1.5 text-xs">{{
                STANCES[r.stance]
              }}</span>
            </p>
            <p class="whitespace-pre-wrap">{{ r.body }}</p>
            <!-- A reply to a reply goes under the same comment: threads are one level deep. -->
            <button v-if="canComment" type="button" class="text-xs" @click="replyTo = c.id">
              Reply
            </button>
          </li>
        </ul>
      </li>
    </ul>
    <p v-if="!top.length" class="text-sm text-muted">No comments yet.</p>

    <form v-if="canComment" class="mt-3" @submit.prevent="post">
      <label class="text-sm">
        {{ replyTo ? 'Your reply' : 'Add a comment' }}
        <textarea v-model="body" required maxlength="5000" rows="3" class="field" />
      </label>
      <div class="mt-2 flex flex-wrap items-center gap-3">
        <select
          v-if="canStance"
          v-model="stance"
          class="field !mt-0 !w-auto"
          aria-label="Your stance"
        >
          <option :value="null">No stance</option>
          <option v-for="(label, value) in STANCES" :key="value" :value="value">{{ label }}</option>
        </select>
        <button class="btn" :disabled="busy || !body.trim()">Post</button>
        <button v-if="replyTo" type="button" class="btn-quiet" @click="replyTo = null">
          Cancel reply
        </button>
      </div>
      <div v-if="error" class="alert mt-2" role="alert">
        <p>{{ error }}</p>
        <UnsavedText :text="body" class="mt-2" />
      </div>
    </form>
  </div>
</template>
