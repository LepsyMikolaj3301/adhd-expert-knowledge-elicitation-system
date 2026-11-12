<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { openingWords } from '@/admin/vignetteForm'
import {
  api,
  ApiError,
  type AssignmentSummary,
  type User,
  type VersionAdminView,
} from '@/api/client'
import ConfirmDialog from '@/components/answering/ConfirmDialog.vue'
import CaseCard from '@/components/CaseCard.vue'
import { describeAdminError } from '@/copy'

const props = defineProps<{ assignments: AssignmentSummary[] }>()
const emit = defineEmits<{ done: []; cancel: [] }>()

type Case = VersionAdminView & { code: string }

const users = ref<User[]>([])
const cases = ref<Case[]>([])
const expertId = ref('')
const versionId = ref('')
const error = ref('')
const loading = ref(true)

const experts = computed(() => users.value.filter((u) => u.role === 'expert' && u.is_active))
/** A cancelled assignment doesn't stop the expert being given the case again. */
const held = computed(
  () =>
    new Set(
      props.assignments
        .filter((a) => a.expert_id === expertId.value && a.state !== 'cancelled')
        .map((a) => a.vignette_version_id),
    ),
)

function explain(e: unknown): string {
  if (!(e instanceof ApiError)) return describeAdminError(e)
  const ids = (e.details?.expert_ids ?? []) as string[]
  const names = ids.map((id) => users.value.find((u) => u.id === id)?.display_name ?? id)
  const message = describeAdminError(e)
  return names.length ? `${message} ${names.join(', ')}.` : message
}

async function submit() {
  if (!expertId.value || !versionId.value) {
    error.value = 'Pick an expert and a case.'
    return
  }
  try {
    await api.POST('/api/v1/vignette-versions/{version_id}/assignments', {
      params: { path: { version_id: versionId.value } },
      body: { expert_ids: [expertId.value] },
    })
    emit('done')
  } catch (e) {
    error.value = explain(e)
  }
}

onMounted(async () => {
  try {
    const [people, vignettes] = await Promise.all([
      api.GET('/api/v1/users'),
      api.GET('/api/v1/vignettes'),
    ])
    users.value = people.data ?? []
    // The latest published version of each vignette is the one to hand out.
    cases.value = (vignettes.data ?? []).flatMap((v) => {
      const latest = [...v.versions].reverse().find((x) => x.status === 'published')
      return latest ? [{ ...latest, code: v.code }] : []
    })
  } catch (e) {
    error.value = explain(e)
  } finally {
    loading.value = false
  }
})
// A case the newly chosen expert already has can't stay picked.
watch(expertId, () => {
  if (held.value.has(versionId.value)) versionId.value = ''
})
</script>

<template>
  <ConfirmDialog
    title="Create new assignment"
    confirm-label="Assign"
    cancel-label="Cancel"
    @confirm="submit"
    @cancel="emit('cancel')"
  >
    <p v-if="error" class="alert" role="alert">{{ error }}</p>
    <p v-if="loading" class="text-muted">Loading…</p>
    <template v-else>
      <label class="block">
        <span class="font-medium text-ink">Expert</span>
        <select v-model="expertId" class="field" data-testid="expert">
          <option value="" disabled>Choose an expert</option>
          <option v-for="u in experts" :key="u.id" :value="u.id">
            {{ u.display_name }} ({{ u.pseudonym }})
          </option>
        </select>
      </label>
      <fieldset>
        <legend class="font-medium text-ink">Case</legend>
        <p v-if="!cases.length" class="text-muted">No case is published yet.</p>
        <ul class="mt-1 space-y-1.5">
          <li v-for="c in cases" :key="c.id" data-testid="case-option">
            <label class="flex items-center gap-2" :class="held.has(c.id) ? 'text-muted' : ''">
              <input v-model="versionId" type="radio" :value="c.id" :disabled="held.has(c.id)" />
              <CaseCard
                :code="c.code"
                :version="c.version"
                :patient-summary="c.patient_summary"
                :framing="c.framing"
                :word-count="c.word_count"
                :opening="openingWords(c.text)"
              />
              <span v-if="held.has(c.id)" class="text-xs">already assigned</span>
            </label>
          </li>
        </ul>
      </fieldset>
    </template>
  </ConfirmDialog>
</template>
