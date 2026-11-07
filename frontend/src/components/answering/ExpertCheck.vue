<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { api, ApiError, type FindingsView } from '@/api/client'
import { describeError } from '@/copy'

const props = defineProps<{ id: string; canSkip: boolean }>()
const emit = defineEmits<{ done: [] }>()

const DIRECTIONS = {
  toward: 'Points toward',
  away: 'Points away',
  neutral: 'No bearing',
  unclear: 'Unclear',
} as const

const findings = ref<FindingsView | null>(null)
const sentences = ref<Record<string, string[]>>({})
const directions = ref<Record<string, string>>({})
const error = ref('')
const busy = ref(false)
const path = { params: { path: { assignment_id: props.id } } }

async function load() {
  error.value = ''
  try {
    const { data } = await api.GET('/api/v1/assignments/{assignment_id}/findings', path)
    findings.value = data ?? null
    sentences.value = Object.fromEntries((data?.sentences ?? []).map((s) => [s.id, [...s.targets]]))
    directions.value = Object.fromEntries(
      (data?.highlights ?? []).map((h) => [h.id, h.direction ?? 'unclear']),
    )
  } catch (e) {
    error.value = describeError(e)
  }
}

/** Only what differs from the server's filing is sent. */
const changes = computed(() => {
  const f = findings.value
  if (!f) return { sentences: {}, directions: {} }
  const same = (a: string[], b: string[]) => a.length === b.length && a.every((t) => b.includes(t))
  return {
    sentences: Object.fromEntries(
      f.sentences
        .filter((s) => !same(s.targets, sentences.value[s.id] ?? []))
        .map((s) => [s.id, sentences.value[s.id]]),
    ),
    directions: Object.fromEntries(
      f.highlights
        .filter((h) => (h.direction ?? 'unclear') !== directions.value[h.id])
        .map((h) => [h.id, directions.value[h.id]]),
    ),
  }
})
const dirty = computed(
  () =>
    Object.keys(changes.value.sentences).length + Object.keys(changes.value.directions).length > 0,
)
const empty = computed(() => Object.values(sentences.value).some((t) => !t.length))

function toggle(sentenceId: string, target: string) {
  const now = sentences.value[sentenceId] ?? []
  sentences.value[sentenceId] = now.includes(target)
    ? now.filter((t) => t !== target)
    : [...now, target]
}

async function finish(action: 'complete' | 'skip') {
  busy.value = true
  error.value = ''
  try {
    if (action === 'complete' && dirty.value && findings.value) {
      await api.PUT('/api/v1/assignments/{assignment_id}/findings', {
        ...path,
        // The types widen the direction values to strings.
        body: { version: findings.value.version, ...changes.value } as never,
      })
    }
    if (action === 'complete')
      await api.POST('/api/v1/assignments/{assignment_id}/expert-check/complete', path)
    else await api.POST('/api/v1/assignments/{assignment_id}/expert-check/skip', path)
    emit('done')
  } catch (e) {
    error.value = describeError(e)
    // A conflict means another tab saved first: show what is there now.
    if (e instanceof ApiError && e.code === 'findings_conflict') await load()
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<template>
  <div data-testid="expert-check">
    <h1 class="text-2xl">Check how your answers were filed</h1>
    <p class="mt-2 text-muted">
      Each sentence of your answers was filed under the quotes it is about, or under the case as a
      whole. Correct anything that is wrong, then approve.
    </p>
    <p v-if="error" class="alert mt-4" role="alert">{{ error }}</p>

    <template v-if="findings">
      <section v-if="findings.feedback.length" class="mt-5 rounded-md border border-line p-3">
        <h2>Changes asked for</h2>
        <ul class="mt-2 space-y-2 text-sm">
          <li v-for="(f, i) in findings.feedback" :key="i">
            <span class="text-muted">About “{{ f.unit_text }}”:</span> {{ f.comment }}
          </li>
        </ul>
      </section>

      <ul
        v-if="findings.flags.length"
        class="mt-5 space-y-1 text-sm text-danger"
        data-testid="flags"
      >
        <li v-for="(flag, i) in findings.flags" :key="i">{{ flag.message }}</li>
      </ul>

      <section v-if="findings.highlights.length" class="mt-5">
        <h2>Quotes</h2>
        <ul class="mt-2 space-y-2 text-sm">
          <li
            v-for="h in findings.highlights"
            :key="h.id"
            class="flex flex-wrap items-center gap-2"
          >
            <span
              class="chip"
              :style="{ '--ink': `var(--ink-${(((h.chip ?? 1) - 1) % 8) + 1})` }"
              >{{ h.chip ?? '·' }}</span
            >
            <span class="min-w-0 flex-1">{{ h.text }}</span>
            <select
              v-model="directions[h.id]"
              class="field !mt-0 !w-auto"
              :disabled="!findings.editable"
              :aria-label="`Direction of quote ${h.chip}`"
            >
              <option v-for="(label, value) in DIRECTIONS" :key="value" :value="value">
                {{ label }}
              </option>
            </select>
          </li>
        </ul>
      </section>

      <section class="mt-5">
        <h2>Sentences</h2>
        <ul class="mt-2 divide-y divide-line border-y border-line">
          <li v-for="s in findings.sentences" :key="s.id" class="py-3" data-testid="sentence">
            <p>{{ s.text }}</p>
            <div class="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm">
              <label v-for="h in findings.highlights" :key="h.id" class="flex items-center gap-1.5">
                <input
                  type="checkbox"
                  :checked="sentences[s.id]?.includes(h.id)"
                  :disabled="!findings.editable"
                  @change="toggle(s.id, h.id)"
                />
                Quote {{ h.chip }}
              </label>
              <label class="flex items-center gap-1.5">
                <input
                  type="checkbox"
                  :checked="sentences[s.id]?.includes('case')"
                  :disabled="!findings.editable"
                  @change="toggle(s.id, 'case')"
                />
                The case as a whole
              </label>
            </div>
          </li>
        </ul>
      </section>

      <p v-if="empty" class="mt-3 text-sm text-muted">Every sentence needs at least one place.</p>
      <div class="mt-6 flex justify-end gap-3">
        <button
          v-if="canSkip"
          type="button"
          class="btn-quiet"
          :disabled="busy"
          @click="finish('skip')"
        >
          Skip the check
        </button>
        <button
          type="button"
          class="btn"
          :disabled="busy || empty || !findings.editable"
          @click="finish('complete')"
        >
          {{ dirty ? 'Save and approve' : 'Approve' }}
        </button>
      </div>
    </template>
  </div>
</template>
