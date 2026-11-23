<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

import {
  countTextWords,
  designForSaving,
  emptyDesign,
  fieldForError,
  MAX_WORDS,
  MIN_WORDS,
  codeFrom,
  nextCode,
  type FormField,
} from '@/admin/vignetteForm'
import {
  api,
  ApiError,
  type VersionAdminView,
  type QuestionTemplate,
  type VignetteAdminView,
  type VignetteDesign,
} from '@/api/client'
import ConfirmDialog from '@/components/answering/ConfirmDialog.vue'
import { FRAMING_LABELS } from '@/copy'

const props = defineProps<{ id?: string }>()

type Framing = VersionAdminView['framing']
const FRAMINGS = Object.keys(FRAMING_LABELS) as Framing[]
const STATUS = { draft: 'Draft', published: 'Published', retired: 'Retired' }
const INPUT = 'field disabled:bg-page disabled:text-muted'

const router = useRouter()

const loading = ref(true)
const busy = ref(false)
const notice = ref('')
const formError = ref('')
const fieldErrors = ref<Partial<Record<FormField, string>>>({})
const confirmRetire = ref(false)

const vignette = ref<VignetteAdminView | null>(null)
const versionId = ref<string | null>(null)

const code = ref('')
const text = ref('')
const framing = ref<Framing>('personal_journal')
const whatIf = ref('')
const summary = ref('')
const questions = ref<QuestionTemplate[]>([])
const design = ref<VignetteDesign>(emptyDesign())
const baseline = ref('')

const current = computed(
  () => vignette.value?.versions.find((v) => v.id === versionId.value) ?? null,
)
const isNew = computed(() => !props.id)
const readOnly = computed(() => Boolean(current.value && current.value.status !== 'draft'))
const words = computed(() => countTextWords(text.value))
const wordsOk = computed(() => words.value >= MIN_WORDS && words.value <= MAX_WORDS)

const typedCode = computed(() => codeFrom(code.value))
const canSave = computed(
  () => Boolean(typedCode.value && text.value.trim() && whatIf.value.trim()),
)
const codeError = computed(
  () =>
    fieldErrors.value.code ??
    (isNew.value && !typedCode.value ? 'Use V and a number, like V012.' : ''),
)

function content() {
  return {
    text: text.value,
    framing: framing.value,
    q4_whatif: whatIf.value,
    patient_summary: summary.value,
    design: designForSaving(design.value),
  }
}

const dirty = computed(() => JSON.stringify(content()) !== baseline.value)

function show(version: VersionAdminView) {
  versionId.value = version.id
  text.value = version.text
  framing.value = version.framing
  whatIf.value = version.q4_whatif ?? ''
  summary.value = version.patient_summary
  // A copy, not `structuredClone`: this is a reactive object, which can't be cloned that way.
  design.value = { ...emptyDesign(), ...JSON.parse(JSON.stringify(version.design)) }
  baseline.value = JSON.stringify(content())
  fieldErrors.value = {}
  formError.value = ''
}

async function fetchAll(): Promise<VignetteAdminView[]> {
  const { data } = await api.GET('/api/v1/vignettes')
  return data ?? []
}

async function load(selectVersionId?: string) {
  const all = await fetchAll()
  if (!props.id) {
    code.value = nextCode(all.map((v) => v.code))
    baseline.value = JSON.stringify(content())
    return
  }
  vignette.value = all.find((v) => v.id === props.id) ?? null
  if (!vignette.value) {
    formError.value = 'This vignette does not exist.'
    return
  }
  code.value = vignette.value.code
  const versions = vignette.value.versions
  const selected = versions.find((v) => v.id === selectVersionId) ?? versions[versions.length - 1]
  if (selected) show(selected)
}

function report(error: unknown) {
  if (!(error instanceof ApiError)) {
    formError.value = 'Something went wrong. Please try again.'
    return
  }
  const field = fieldForError(error)
  if (field) fieldErrors.value = { ...fieldErrors.value, [field]: error.message }
  else formError.value = error.message
}

/** Runs one action, clearing the old messages first. False if the server refused it. */
async function attempt(action: () => Promise<void>): Promise<boolean> {
  busy.value = true
  notice.value = ''
  formError.value = ''
  fieldErrors.value = {}
  try {
    await action()
    return true
  } catch (error) {
    report(error)
    return false
  } finally {
    busy.value = false
  }
}

async function saveChanges() {
  if (isNew.value) {
    const { data } = await api.POST('/api/v1/vignettes', {
      body: { code: typedCode.value ?? code.value, ...content() },
    })
    await router.replace(`/vignettes/${data?.id}`)
    return
  }
  if (!current.value || !dirty.value) return
  await api.PATCH('/api/v1/vignette-versions/{version_id}', {
    params: { path: { version_id: current.value.id } },
    body: content(),
  })
  baseline.value = JSON.stringify(content())
}

async function save() {
  if (await attempt(saveChanges)) notice.value = 'Draft saved.'
}

async function publish() {
  const id = versionId.value
  if (!id) return
  const done = await attempt(async () => {
    await saveChanges()
    await api.POST('/api/v1/vignette-versions/{version_id}/publish', {
      params: { path: { version_id: id } },
    })
    await load(id)
  })
  if (done) notice.value = 'Published. Assign it to experts from the Assignments page.'
}

async function retire() {
  confirmRetire.value = false
  const id = versionId.value
  if (!id) return
  const done = await attempt(async () => {
    await api.POST('/api/v1/vignette-versions/{version_id}/retire', {
      params: { path: { version_id: id } },
    })
    await load(id)
  })
  if (done) notice.value = 'Retired. Assignments already made can still be finished.'
}

async function newVersion() {
  const from = current.value
  if (!from || !props.id) return
  const vignetteId = props.id
  const done = await attempt(async () => {
    const { data } = await api.POST('/api/v1/vignettes/{vignette_id}/versions', {
      params: { path: { vignette_id: vignetteId } },
      body: {
        text: from.text,
        framing: from.framing,
        q4_whatif: from.q4_whatif,
        patient_summary: from.patient_summary,
        variant: from.variant,
        design: from.design,
      },
    })
    await load(data?.id)
  })
  if (done) notice.value = 'New draft version made from this one.'
}

async function open() {
  loading.value = true
  try {
    const [, asked] = await Promise.all([load(), api.GET('/api/v1/vignettes/questions')])
    questions.value = asked.data ?? []
  } catch (error) {
    report(error)
  } finally {
    loading.value = false
  }
}

onMounted(open)
// A message about the text stops being true once the text changes.
watch(code, () => {
  fieldErrors.value = { ...fieldErrors.value, code: undefined }
})
watch(text, () => {
  fieldErrors.value = { ...fieldErrors.value, text: undefined }
})
watch(summary, () => {
  fieldErrors.value = { ...fieldErrors.value, patient_summary: undefined }
})
watch(whatIf, () => {
  fieldErrors.value = { ...fieldErrors.value, q4_whatif: undefined }
})
/** Q4 is worded around the what-if, so its text is cut where the what-if goes. */
function around(question: QuestionTemplate): [string, string] {
  const [before, after = ''] = question.text.split('{whatif}')
  return [before ?? '', after]
}

// The router reuses this screen from one vignette to the next, and from "new" to the saved draft.
watch(() => props.id, open)
</script>

<template>
  <div>
    <p class="text-sm">
      <RouterLink to="/vignettes">All cases</RouterLink>
      <span class="px-1.5 text-muted">/</span>
      <span class="font-medium text-ink">{{ isNew ? 'New' : code }}</span>
    </p>

    <p v-if="loading" class="mt-6 text-muted">Loading…</p>

    <template v-else>
      <div class="mt-3 flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
        <h1>{{ isNew ? 'New vignette' : code }}</h1>
        <p v-if="current" class="text-muted" data-testid="status">
          Version {{ current.version }}, {{ STATUS[current.status].toLowerCase() }}
        </p>
      </div>

      <div v-if="(vignette?.versions.length ?? 0) > 1" class="mt-3 flex flex-wrap gap-2 text-sm">
        <button
          v-for="version in vignette?.versions"
          :key="version.id"
          type="button"
          class="cursor-pointer rounded-sm border-b-2 px-2 py-1"
          :class="
            version.id === versionId
              ? 'border-action font-semibold text-ink'
              : 'border-transparent text-muted hover:text-ink'
          "
          :aria-current="version.id === versionId ? 'true' : undefined"
          @click="show(version)"
        >
          Version {{ version.version }}
        </button>
      </div>

      <p v-if="formError" class="alert mt-5" role="alert">{{ formError }}</p>
      <p v-if="notice" class="mt-5 text-ink" role="status">{{ notice }}</p>

      <form class="mt-6 space-y-8" @submit.prevent>
        <div class="grid gap-6 sm:grid-cols-[10rem_1fr_1fr]">
          <label class="block">
            <span class="text-sm font-medium text-ink">Code</span>
            <input
              v-model="code"
              :class="INPUT"
              data-testid="code"
              :disabled="!isNew"
              maxlength="32"
            />
            <span v-if="codeError" class="mt-1 block text-sm text-danger" data-error="code">
              {{ codeError }}
            </span>
          </label>
          <label class="block">
            <span class="text-sm font-medium text-ink">Where it was written</span>
            <select v-model="framing" :class="INPUT" :disabled="readOnly">
              <option v-for="f in FRAMINGS" :key="f" :value="f">{{ FRAMING_LABELS[f] }}</option>
            </select>
          </label>
          <label class="block">
            <span class="text-sm font-medium text-ink">Population</span>
            <input v-model="design.population" :class="INPUT" :disabled="readOnly" maxlength="64" />
          </label>
        </div>

        <label class="block">
          <span class="text-sm font-medium text-ink">Patient summary</span>
          <span class="mt-1 block text-sm text-muted">
            A short description of the patient, in your own words. Experts read it above the text.
          </span>
          <textarea
            v-model="summary"
            :class="INPUT"
            class="mt-1"
            data-testid="summary"
            maxlength="600"
            rows="3"
            :disabled="readOnly"
          />
          <span
            v-if="fieldErrors.patient_summary"
            class="mt-1 block text-sm text-danger"
            data-error="patient_summary"
          >
            {{ fieldErrors.patient_summary }}
          </span>
        </label>

        <label class="block">
          <span class="text-sm font-medium text-ink">Patient text</span>
          <textarea
            v-model="text"
            class="patient-text mt-1 block min-h-80 w-full max-w-none rounded-sm border border-line bg-surface px-5 py-4 disabled:bg-page"
            data-testid="text"
            maxlength="20000"
            :disabled="readOnly"
          />
          <span
            class="mt-1 block text-sm"
            :class="wordsOk ? 'text-muted' : 'text-ink'"
            aria-live="polite"
            data-testid="word-count"
          >
            {{ words }} words. Publishing needs {{ MIN_WORDS }} to {{ MAX_WORDS }}.
          </span>
          <span v-if="fieldErrors.text" class="mt-1 block text-sm text-danger" data-error="text">
            {{ fieldErrors.text }}
          </span>
        </label>

        <section>
          <h2 class="text-xl">Questions</h2>
          <p class="mt-1 text-sm text-muted">
            Every vignette asks the same six questions. Q4 is built around a what-if: one concrete
            fact the text doesn't state, that should move a reading or deliberately not move it. Not
            a diagnosis, and not a rewording of the text.
          </p>
          <ol class="mt-3 space-y-3" data-testid="questions">
            <li v-for="q in questions" :key="q.id" class="flex gap-3" data-testid="question">
              <span class="w-8 shrink-0 font-semibold text-ink">{{ q.id }}</span>
              <p v-if="q.id !== 'Q4'" class="font-serif">{{ q.text }}</p>
              <div v-else class="min-w-0 flex-1">
                <p class="flex flex-wrap items-center gap-x-2 font-serif">
                  <span>{{ around(q)[0] }}</span>
                  <input
                    v-model="whatIf"
                    class="min-w-64 flex-1 rounded-sm border border-line bg-surface px-3 py-2 font-sans disabled:bg-page disabled:text-muted"
                    aria-label="What-if for Q4"
                    data-testid="whatif"
                    maxlength="1000"
                    :disabled="readOnly"
                  />
                  <span>{{ around(q)[1] }}</span>
                </p>
                <span
                  v-if="fieldErrors.q4_whatif"
                  class="mt-1 block text-sm text-danger"
                  data-error="q4_whatif"
                >
                  {{ fieldErrors.q4_whatif }}
                </span>
              </div>
            </li>
          </ol>
        </section>

        <label class="block border-t border-line pt-6">
          <span class="text-xl font-serif text-ink">Notes</span>
          <span class="mt-1 block text-sm text-muted">Only admins see these.</span>
          <textarea
            v-model="design.notes"
            :class="INPUT"
            class="mt-1"
            data-testid="notes"
            rows="4"
            :disabled="readOnly"
          />
        </label>

        <div class="flex flex-wrap gap-3 border-t border-line pt-6">
          <template v-if="!readOnly">
            <button type="button" class="btn-quiet" :disabled="!canSave || busy" @click="save">
              Save draft
            </button>
            <button
              v-if="!isNew"
              type="button"
              class="btn"
              :disabled="!canSave || busy"
              @click="publish"
            >
              Publish
            </button>
          </template>
          <template v-else>
            <button type="button" class="btn-quiet" :disabled="busy" @click="newVersion">
              New version
            </button>
            <button
              v-if="current?.status === 'published'"
              type="button"
              class="btn-quiet"
              :disabled="busy"
              @click="confirmRetire = true"
            >
              Retire
            </button>
          </template>
        </div>
      </form>

      <ConfirmDialog
        v-if="confirmRetire"
        title="Retire this version?"
        confirm-label="Retire version"
        cancel-label="Keep it"
        @confirm="retire"
        @cancel="confirmRetire = false"
      >
        <p>It can't be assigned to anyone new. Assignments already made can still be finished.</p>
      </ConfirmDialog>
    </template>
  </div>
</template>
