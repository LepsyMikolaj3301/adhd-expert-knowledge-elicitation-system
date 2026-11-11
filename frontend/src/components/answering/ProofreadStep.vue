<script setup lang="ts">
/**
 * The proofread check: each answer as the expert wrote it, the changes proofreading made, and the
 * edited text to change freely. Under each answer, its sentences with the quotes each is about.
 * How the answers are cut for the knowledge base is not shown: that happens after review.
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'

import { chipFocus, useQuoteFocus } from '@/answering/quoteFocus'
import { changed } from '@/answering/wordDiff'
import {
  api,
  ApiError,
  type AnswerLine,
  type LinkedHighlight,
  type ProofreadItem,
  type ProofreadView,
} from '@/api/client'
import { describeError, proofreadPassNote, questionLabel } from '@/copy'

import ChipEditor from './ChipEditor.vue'
import ChipText from './ChipText.vue'
import ConfirmDialog from './ConfirmDialog.vue'
import DiffText from './DiffText.vue'
import QuoteTag from './QuoteTag.vue'

const SAVE_AFTER_MS = 1500
const RETRY_AFTER_MS = 5000

const props = defineProps<{ id: string }>()
const emit = defineEmits<{
  /** Sent for review: the page reloads the assignment. */
  submitted: []
  /** Nothing was proofread (an assignment from before proofreading existed). */
  missing: []
  highlights: [highlights: LinkedHighlight[]]
}>()

type Status = 'saved' | 'unsaved' | 'saving' | 'failed' | 'conflict' | 'rejected'

const view = ref<ProofreadView | null>(null)
const texts = ref<Record<string, string>>({})
const lines = ref<Record<string, AnswerLine[]>>({})
const status = ref<Status>('saved')
const error = ref('')
const loading = ref(true)
const confirming = ref(false)
const busy = ref(false)
/** The expert pressed "Submit for review" with something missing: mark where. */
const attempted = ref(false)

const focus = chipFocus(useQuoteFocus())
const path = { params: { path: { assignment_id: props.id } } }
let overrides: Record<string, Record<string, string[]>> = {}
let edited = new Set<string>()
let timer: ReturnType<typeof setTimeout> | undefined
let running: Promise<void> | null = null

const editable = computed(() => view.value?.editable ?? false)
const highlights = computed(() => view.value?.highlights ?? [])
const items = computed(() => view.value?.items ?? [])
const passNote = computed(() => (view.value ? proofreadPassNote(view.value.passes) : null))
const feedbackFor = (qid: string) =>
  (view.value?.feedback ?? []).filter((f) => f.question_id === qid)

/** The server's text of an answer: its lines belong to that text, not to what is being typed. */
const serverFinal = (qid: string) => items.value.find((i) => i.question_id === qid)?.final ?? ''
const linesStale = (qid: string) => (texts.value[qid] ?? '') !== serverFinal(qid)

/** The tags a line can have: the expert's quotes, the whole case, and any words this answer quotes. */
function optionsFor(item: ProofreadItem): string[] {
  const used = new Set((lines.value[item.question_id] ?? []).flatMap((l) => l.targets))
  return [
    ...highlights.value.filter((h) => h.origin === 'expert' || used.has(h.id)).map((h) => h.id),
    'case',
  ]
}

const emptyAnswers = computed(() =>
  items.value.filter((i) => !(texts.value[i.question_id] ?? '').trim()).map((i) => i.question_id),
)
const unlinked = computed(() =>
  items.value
    .filter((i) => i.linked && !linesStale(i.question_id))
    .flatMap((i) => (lines.value[i.question_id] ?? []).filter((l) => !l.targets.length)),
)
const blocker = computed(() => {
  if (emptyAnswers.value.length)
    return `${emptyAnswers.value.map(questionLabel).join(', ')} needs an answer.`
  if (unlinked.value.length)
    return unlinked.value.length === 1
      ? 'One sentence needs a quote, or “Whole case”.'
      : `${unlinked.value.length} sentences need a quote, or “Whole case”.`
  return null
})

const saveLabel = computed(
  () =>
    ({
      saved: 'Saved',
      unsaved: 'Not saved yet',
      saving: 'Saving…',
      failed: "Can't reach the server. Your text is still here, and we keep trying.",
      conflict: 'Not saved',
      rejected: 'Not saved',
    })[status.value],
)

function apply(next: ProofreadView, sent: Record<string, string> = {}) {
  view.value = next
  emit('highlights', next.highlights)
  for (const item of next.items) {
    const qid = item.question_id
    // Keep what was typed while the save was on its way.
    if (!(qid in texts.value) || texts.value[qid] === (sent[qid] ?? item.final)) {
      texts.value[qid] = item.final
    }
    if (texts.value[qid] === item.final) lines.value[qid] = item.lines.map((l) => ({ ...l }))
  }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await api.GET('/api/v1/assignments/{assignment_id}/proofread', path)
    if (data) {
      texts.value = {}
      overrides = {}
      edited = new Set()
      status.value = 'saved'
      // openapi-fetch's types widen the `span` tuple to an array, though the API sends two numbers.
      apply(data as ProofreadView)
    }
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) emit('missing')
    else error.value = describeError(e)
  } finally {
    loading.value = false
  }
}

async function saveOnce() {
  if (!view.value) return
  const sent: Record<string, string> = {}
  for (const qid of edited) sent[qid] = texts.value[qid] ?? ''
  const sentOverrides = overrides
  edited = new Set()
  overrides = {}
  status.value = 'saving'
  try {
    const { data } = await api.PUT('/api/v1/assignments/{assignment_id}/proofread', {
      ...path,
      body: { version: view.value.version, answers: sent, overrides: sentOverrides },
    })
    if (data) apply(data as ProofreadView, sent)
    status.value = edited.size || Object.keys(overrides).length ? 'unsaved' : 'saved'
  } catch (e) {
    for (const qid of Object.keys(sent)) edited.add(qid)
    for (const [qid, byLine] of Object.entries(sentOverrides))
      overrides[qid] = { ...byLine, ...overrides[qid] }
    if (e instanceof ApiError && e.code === 'proofread_conflict') status.value = 'conflict'
    else if (e instanceof ApiError && e.status >= 400 && e.status < 500) {
      status.value = 'rejected'
      error.value = describeError(e)
    } else {
      status.value = 'failed'
      timer = setTimeout(() => void flush().catch(() => {}), RETRY_AFTER_MS)
    }
    throw e
  }
}

function dirty() {
  return edited.size > 0 || Object.keys(overrides).length > 0
}

/** Resolves once everything is saved. */
function flush(): Promise<void> {
  clearTimeout(timer)
  if (running) return running.then(() => (dirty() ? flush() : undefined))
  if (!dirty()) return Promise.resolve()
  if (status.value === 'conflict')
    return Promise.reject(new ApiError(409, { code: 'proofread_conflict', message: '' }))
  running = saveOnce().finally(() => (running = null))
  return running.then(() => (dirty() ? flush() : undefined))
}

function schedule() {
  if (status.value === 'conflict') return
  error.value = ''
  if (!running) status.value = 'unsaved'
  clearTimeout(timer)
  timer = setTimeout(() => void flush().catch(() => {}), SAVE_AFTER_MS)
}

function setText(qid: string, text: string) {
  texts.value[qid] = text
  edited.add(qid)
  schedule()
}

function toggle(qid: string, index: number, target: string) {
  const line = lines.value[qid]?.[index]
  if (!line || !editable.value || linesStale(qid)) return
  const has = line.targets.includes(target)
  // A sentence is always about something: the last tag goes only by choosing another first.
  if (has && line.targets.length === 1) return
  const targets = has ? line.targets.filter((t) => t !== target) : [...line.targets, target]
  lines.value[qid]![index] = { ...line, targets, assigned_by: 'expert' }
  overrides[qid] = { ...overrides[qid], [line.text]: targets }
  schedule()
}

async function submit() {
  confirming.value = false
  busy.value = true
  error.value = ''
  try {
    await flush()
    await api.POST('/api/v1/assignments/{assignment_id}/submit-for-review', path)
    emit('submitted')
  } catch (e) {
    error.value = describeError(e)
    if (e instanceof ApiError && e.code === 'links_missing') attempted.value = true
  } finally {
    busy.value = false
  }
}

function trySubmit() {
  if (blocker.value) attempted.value = true
  else confirming.value = true
}

defineExpose({ flush })

onMounted(load)
onUnmounted(() => clearTimeout(timer))
</script>

<template>
  <div>
    <p v-if="loading" class="text-muted">Loading…</p>
    <template v-else-if="view">
      <div class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h1 class="text-2xl" data-testid="question">
          {{ editable ? 'Check your edited answers' : 'Your edited answers' }}
        </h1>
        <p v-if="editable" class="text-sm text-muted" aria-live="polite" data-testid="save-status">
          {{ saveLabel }}
        </p>
      </div>
      <p v-if="editable" class="mt-2 text-sm text-muted">
        Each answer was checked for spelling, grammar and punctuation, and short notes were written
        out in full. Changes are marked on the left. Change anything you like on the right: the
        edited text is what your colleagues will read.
      </p>
      <p
        v-if="passNote"
        class="mt-3 rounded-sm border-l-2 border-action bg-surface px-3 py-2 text-sm"
      >
        {{ passNote }}
      </p>
      <div v-if="status === 'conflict'" class="alert mt-3" role="alert" data-testid="conflict">
        <p>These answers were changed in another tab or device.</p>
        <button type="button" class="btn mt-2" @click="load">Load the saved version</button>
      </div>
      <ul
        v-if="editable && view.flags.length"
        class="mt-3 space-y-1 rounded-sm border border-line bg-surface px-3 py-2 text-sm"
        data-testid="flags"
      >
        <li v-for="flag in view.flags" :key="`${flag.kind}-${flag.highlight}`">
          <ChipText :text="flag.message" />
        </li>
      </ul>

      <section
        v-for="item in items"
        :key="item.question_id"
        class="border-b border-line py-6"
        :data-question="item.question_id"
        data-testid="proofread-answer"
      >
        <h2 class="text-base">
          <span class="mb-0.5 block text-sm font-semibold tracking-wide text-action uppercase">
            {{ questionLabel(item.question_id) }}
          </span>
          {{ item.question }}
        </h2>
        <p
          v-for="(f, index) in feedbackFor(item.question_id)"
          :key="index"
          class="alert mt-3 text-ink!"
          data-testid="feedback"
        >
          <strong>The study team asked:</strong> {{ f.comment }}
        </p>

        <div class="mt-4 grid gap-4 xl:grid-cols-2">
          <div class="min-w-0">
            <h3 class="font-sans text-xs font-semibold tracking-wide text-muted uppercase">
              What you wrote, and what changed
            </h3>
            <div
              class="mt-1 rounded-sm border border-line bg-page px-4 py-3 text-[0.95rem]"
              data-testid="original"
            >
              <DiffText :before="item.original" :after="texts[item.question_id] ?? ''" />
            </div>
            <p
              v-if="!changed(item.original, texts[item.question_id] ?? '')"
              class="mt-1 text-sm text-muted"
            >
              No changes to the words.
            </p>
            <p v-if="item.dropped.length" class="mt-1 text-sm text-muted" data-testid="dropped">
              Left out as unreadable:
              <span v-for="(d, index) in item.dropped" :key="index" class="italic"
                >“{{ d }}”{{ index < item.dropped.length - 1 ? ', ' : '' }}</span
              >
            </p>
          </div>
          <div class="min-w-0">
            <h3 class="font-sans text-xs font-semibold tracking-wide text-muted uppercase">
              Edited answer
            </h3>
            <div v-if="editable" class="mt-1">
              <ChipEditor
                :model-value="texts[item.question_id] ?? ''"
                :label="`Edited answer to ${item.question_id}`"
                @update:model-value="setText(item.question_id, $event)"
                @active="focus = $event"
              />
            </div>
            <p
              v-else
              class="mt-1 rounded-sm border border-line bg-surface px-4 py-3 text-[0.95rem] leading-relaxed"
            >
              <ChipText :text="texts[item.question_id] ?? ''" />
            </p>
            <p
              v-if="attempted && !(texts[item.question_id] ?? '').trim()"
              class="mt-1 text-sm text-danger"
            >
              This answer is empty.
            </p>
          </div>
        </div>

        <div v-if="item.linked" class="mt-5" data-testid="lines">
          <h3 class="font-sans text-xs font-semibold tracking-wide text-muted uppercase">
            What each sentence is about
            <span
              v-if="linesStale(item.question_id)"
              class="ml-2 font-normal normal-case"
              aria-live="polite"
              >Updating…</span
            >
          </h3>
          <p v-if="editable" class="mt-1 text-sm text-muted">
            Click a tag to add or remove it. Point at a quote to find it in the text.
          </p>
          <ol
            class="mt-2 divide-y divide-line rounded-sm border border-line bg-surface"
            :class="linesStale(item.question_id) ? 'opacity-60' : ''"
          >
            <li
              v-for="(line, index) in lines[item.question_id] ?? []"
              :key="`${index}-${line.text}`"
              class="flex flex-wrap items-start justify-between gap-x-4 gap-y-1 px-3 py-2"
              :class="!line.targets.length && attempted ? 'flag-flash' : ''"
              :data-missing="!line.targets.length ? 'true' : undefined"
              data-testid="line"
            >
              <span class="min-w-0 flex-1 text-[0.95rem] leading-relaxed">
                <ChipText :text="line.text" />
              </span>
              <span class="flex flex-wrap items-center gap-1">
                <template v-if="editable">
                  <QuoteTag
                    v-for="target in optionsFor(item)"
                    :key="target"
                    :target="target"
                    :highlights="highlights"
                    toggle
                    :pressed="line.targets.includes(target)"
                    :disabled="linesStale(item.question_id)"
                    @toggle="toggle(item.question_id, index, target)"
                  />
                </template>
                <template v-else>
                  <QuoteTag
                    v-for="target in line.targets"
                    :key="target"
                    :target="target"
                    :highlights="highlights"
                  />
                </template>
                <span
                  v-if="!line.targets.length"
                  class="text-sm font-medium"
                  :class="attempted ? 'text-danger' : 'text-muted'"
                  >Choose quotes</span
                >
              </span>
            </li>
          </ol>
        </div>
      </section>

      <p v-if="error" class="alert mt-4" role="alert">{{ error }}</p>

      <footer v-if="editable" class="mt-5">
        <p
          v-if="blocker"
          class="mb-2 text-right text-sm"
          :class="attempted ? 'font-medium text-danger' : 'text-muted'"
          data-testid="blocker"
        >
          {{ blocker }}
        </p>
        <div class="flex justify-end">
          <button
            type="button"
            class="btn"
            :class="blocker ? 'opacity-60' : ''"
            :aria-disabled="blocker ? 'true' : undefined"
            :disabled="busy"
            @click="trySubmit"
          >
            Submit for review
          </button>
        </div>
      </footer>

      <ConfirmDialog
        v-if="confirming"
        title="Submit for review?"
        confirm-label="Submit for review"
        cancel-label="Keep checking"
        @confirm="submit"
        @cancel="confirming = false"
      >
        <p>Your colleagues will read the edited answers, and the study team decides on each.</p>
        <p>You can't change them afterwards, unless the study team sends them back to you.</p>
      </ConfirmDialog>
    </template>
    <p v-else-if="error" class="alert" role="alert">{{ error }}</p>
  </div>
</template>
