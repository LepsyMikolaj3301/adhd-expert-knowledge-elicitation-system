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
  nextCode,
  type FormField,
} from '@/admin/vignetteForm'
import {
  api,
  ApiError,
  type VersionAdminView,
  type VignetteAdminView,
  type VignetteDesign,
} from '@/api/client'
import AssignPanel from '@/components/admin/AssignPanel.vue'
import ConfirmDialog from '@/components/answering/ConfirmDialog.vue'

const props = defineProps<{ id?: string }>()

type Framing = VersionAdminView['framing']
const FRAMINGS: { value: Framing; label: string }[] = [
  { value: 'forum_post', label: 'Forum post' },
  { value: 'personal_journal', label: 'Personal journal' },
  { value: 'email', label: 'Email' },
]
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
const design = ref<VignetteDesign>(emptyDesign())
const baseline = ref('')

const textArea = ref<HTMLTextAreaElement>()
const quoteHint = ref('')

const current = computed(
  () => vignette.value?.versions.find((v) => v.id === versionId.value) ?? null,
)
const isNew = computed(() => !props.id)
const readOnly = computed(() => Boolean(current.value && current.value.status !== 'draft'))
const words = computed(() => countTextWords(text.value))
const wordsOk = computed(() => words.value >= MIN_WORDS && words.value <= MAX_WORDS)

const canSave = computed(
  () =>
    /^V\d{3,}$/.test(code.value) &&
    Boolean(text.value.trim() && whatIf.value.trim() && design.value.purpose.trim()),
)

function content() {
  return {
    text: text.value,
    framing: framing.value,
    q4_whatif: whatIf.value,
    design: designForSaving(design.value),
  }
}

const dirty = computed(() => JSON.stringify(content()) !== baseline.value)

function show(version: VersionAdminView) {
  versionId.value = version.id
  text.value = version.text
  framing.value = version.framing
  whatIf.value = version.q4_whatif ?? ''
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
      body: { code: code.value, ...content() },
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
  if (done) notice.value = 'Published. You can now assign it to experts.'
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
        variant: from.variant,
        design: from.design,
      },
    })
    await load(data?.id)
  })
  if (done) notice.value = 'New draft version made from this one.'
}

function selectedQuote(): string | null {
  const area = textArea.value
  if (!area) return null
  const quote = area.value.slice(area.selectionStart, area.selectionEnd).trim()
  if (!quote) quoteHint.value = 'Select words in the patient text first.'
  else quoteHint.value = ''
  return quote || null
}

function addCue() {
  const quote = selectedQuote()
  if (quote) design.value.planted_cues.push({ quote, trait: '', strength: 'moderate' })
}

function addConfounder() {
  const quote = selectedQuote()
  if (quote) design.value.confounders.push({ quote, alternative_explanation: '' })
}

function inText(quote: string): boolean {
  return text.value.includes(quote)
}

async function open() {
  loading.value = true
  try {
    await load()
  } catch (error) {
    report(error)
  } finally {
    loading.value = false
  }
}

onMounted(open)
// A message about the text stops being true once the text changes.
watch(text, () => {
  fieldErrors.value = { ...fieldErrors.value, text: undefined }
})
watch(whatIf, () => {
  fieldErrors.value = { ...fieldErrors.value, q4_whatif: undefined }
})
// The router reuses this screen from one vignette to the next, and from "new" to the saved draft.
watch(() => props.id, open)
</script>

<template>
  <div>
    <p class="text-sm">
      <RouterLink to="/vignettes">Vignettes</RouterLink>
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
        <div class="grid gap-6 sm:grid-cols-[10rem_1fr]">
          <label class="block">
            <span class="text-sm font-medium text-ink">Code</span>
            <input
              v-model="code"
              :class="INPUT"
              data-testid="code"
              :disabled="!isNew"
              maxlength="32"
            />
            <span v-if="fieldErrors.code" class="mt-1 block text-sm text-danger" data-error="code">
              {{ fieldErrors.code }}
            </span>
          </label>
          <label class="block">
            <span class="text-sm font-medium text-ink">Where it was written</span>
            <select v-model="framing" :class="INPUT" :disabled="readOnly">
              <option v-for="f in FRAMINGS" :key="f.value" :value="f.value">{{ f.label }}</option>
            </select>
          </label>
        </div>

        <label class="block">
          <span class="text-sm font-medium text-ink">Patient text</span>
          <textarea
            ref="textArea"
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

        <label class="block">
          <span class="text-sm font-medium text-ink">What-if for Q4</span>
          <span class="mt-1 block text-sm text-muted">
            One concrete fact the text doesn't state, that should move a reading or deliberately not
            move it. Not a diagnosis, and not a rewording of the text.
          </span>
          <span class="mt-2 flex flex-wrap items-center gap-x-2 font-serif">
            <span>…how would it change if</span>
            <input
              v-model="whatIf"
              class="min-w-64 flex-1 rounded-sm border border-line bg-surface px-3 py-2 font-sans disabled:bg-page disabled:text-muted"
              data-testid="whatif"
              maxlength="1000"
              :disabled="readOnly"
            />
            <span>?</span>
          </span>
          <span
            v-if="fieldErrors.q4_whatif"
            class="mt-1 block text-sm text-danger"
            data-error="q4_whatif"
          >
            {{ fieldErrors.q4_whatif }}
          </span>
        </label>

        <p class="text-sm text-muted">Every vignette asks the same six questions.</p>

        <fieldset class="space-y-5 border-t border-line pt-6" :disabled="readOnly">
          <legend class="float-left mb-1 w-full font-serif text-xl text-ink">Design notes</legend>
          <p class="clear-both text-sm text-muted">
            Experts and reviewers never see these. They are what the answers get scored against.
          </p>

          <label class="block">
            <span class="text-sm font-medium text-ink">Purpose</span>
            <input v-model="design.purpose" :class="INPUT" data-testid="purpose" />
          </label>

          <div class="grid gap-5 sm:grid-cols-3">
            <label class="block">
              <span class="text-sm font-medium text-ink">Track</span>
              <select v-model="design.track" :class="INPUT">
                <option value="general">General</option>
                <option value="text_analysis">Text analysis</option>
              </select>
            </label>
            <label class="block">
              <span class="text-sm font-medium text-ink">Population</span>
              <input v-model="design.population" :class="INPUT" />
            </label>
            <label class="block">
              <span class="text-sm font-medium text-ink">Origin</span>
              <select v-model="design.origin" :class="INPUT">
                <option value="hand_written">Hand written</option>
                <option value="real_text">Real text</option>
                <option value="llm">Generated</option>
              </select>
            </label>
          </div>

          <label v-if="design.track === 'text_analysis'" class="block">
            <span class="text-sm font-medium text-ink">Knowledge it should elicit</span>
            <input v-model="design.knowledge_target" :class="INPUT" />
            <span
              v-if="fieldErrors.knowledge_target"
              class="mt-1 block text-sm text-danger"
              data-error="knowledge_target"
            >
              {{ fieldErrors.knowledge_target }}
            </span>
          </label>

          <label v-if="design.origin === 'real_text'" class="block">
            <span class="text-sm font-medium text-ink">Source</span>
            <input v-model="design.source_ref" :class="INPUT" />
          </label>

          <label class="flex items-center gap-2 text-sm">
            <input v-model="design.is_control" type="checkbox" />
            Control vignette (no planted cues)
          </label>

          <p v-if="fieldErrors.quotes" class="text-sm text-danger" data-error="quotes" role="alert">
            {{ fieldErrors.quotes }}
          </p>

          <div v-if="!design.is_control">
            <h3 class="text-sm font-semibold text-ink">Planted cues</h3>
            <ul class="mt-2 space-y-3">
              <li
                v-for="(cue, index) in design.planted_cues"
                :key="index"
                class="border-l-2 border-line pl-3"
                data-testid="cue"
              >
                <p class="font-serif">“{{ cue.quote }}”</p>
                <p v-if="!inText(cue.quote)" class="text-sm text-danger">
                  This quote is no longer in the text.
                </p>
                <div class="mt-1 flex flex-wrap items-center gap-3">
                  <input
                    v-model="cue.trait"
                    class="min-w-48 flex-1 rounded-sm border border-line bg-surface px-2 py-1 text-sm disabled:bg-page disabled:text-muted"
                    placeholder="Trait"
                    aria-label="Trait"
                  />
                  <select
                    v-model="cue.strength"
                    class="rounded-sm border border-line bg-surface px-2 py-1 text-sm disabled:bg-page disabled:text-muted"
                    aria-label="Strength"
                  >
                    <option value="weak">Weak</option>
                    <option value="moderate">Moderate</option>
                    <option value="strong">Strong</option>
                  </select>
                  <button
                    v-if="!readOnly"
                    type="button"
                    class="cursor-pointer text-sm text-muted hover:text-danger hover:underline"
                    @click="design.planted_cues.splice(index, 1)"
                  >
                    Remove
                  </button>
                </div>
              </li>
            </ul>
            <button v-if="!readOnly" type="button" class="btn-quiet mt-3" @click="addCue">
              Add selected text as a cue
            </button>
          </div>

          <div>
            <h3 class="text-sm font-semibold text-ink">Confounders</h3>
            <ul class="mt-2 space-y-3">
              <li
                v-for="(confounder, index) in design.confounders"
                :key="index"
                class="border-l-2 border-line pl-3"
                data-testid="confounder"
              >
                <p class="font-serif">“{{ confounder.quote }}”</p>
                <p v-if="!inText(confounder.quote)" class="text-sm text-danger">
                  This quote is no longer in the text.
                </p>
                <div class="mt-1 flex flex-wrap items-center gap-3">
                  <input
                    v-model="confounder.alternative_explanation"
                    class="min-w-48 flex-1 rounded-sm border border-line bg-surface px-2 py-1 text-sm disabled:bg-page disabled:text-muted"
                    placeholder="Alternative explanation"
                    aria-label="Alternative explanation"
                  />
                  <button
                    v-if="!readOnly"
                    type="button"
                    class="cursor-pointer text-sm text-muted hover:text-danger hover:underline"
                    @click="design.confounders.splice(index, 1)"
                  >
                    Remove
                  </button>
                </div>
              </li>
            </ul>
            <button v-if="!readOnly" type="button" class="btn-quiet mt-3" @click="addConfounder">
              Add selected text as a confounder
            </button>
          </div>
          <p v-if="quoteHint" class="text-sm text-ink" role="status">{{ quoteHint }}</p>
        </fieldset>

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

      <AssignPanel
        v-if="current && current.status !== 'draft'"
        :version-id="current.id"
        :can-assign="current.status === 'published'"
      />

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
