<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import { api, ApiError, type VignetteAdminView } from '@/api/client'

const STATUS = { draft: 'Draft', published: 'Published', retired: 'Retired' }

const vignettes = ref<VignetteAdminView[]>([])
const loading = ref(true)
const error = ref('')

function latest(vignette: VignetteAdminView) {
  return vignette.versions[vignette.versions.length - 1]
}

onMounted(async () => {
  try {
    const { data } = await api.GET('/api/v1/vignettes')
    vignettes.value = data ?? []
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Could not load the vignettes.'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div>
    <div class="flex flex-wrap items-center justify-between gap-4">
      <h1>Vignettes</h1>
      <RouterLink to="/vignettes/new" class="btn hover:no-underline">New vignette</RouterLink>
    </div>

    <p v-if="error" class="alert mt-6" role="alert">{{ error }}</p>
    <p v-if="loading" class="mt-6 text-muted">Loading…</p>
    <p v-else-if="!vignettes.length && !error" class="mt-6 text-muted">
      No vignettes yet. Write the first one to start assigning it to experts.
    </p>

    <table v-else-if="vignettes.length" class="mt-8 w-full border-collapse text-left text-sm">
      <thead>
        <tr class="border-b border-line text-muted">
          <th scope="col" class="py-2 pr-4 font-medium">Vignette</th>
          <th scope="col" class="py-2 pr-4 font-medium">Latest version</th>
          <th scope="col" class="py-2 pr-4 font-medium">Status</th>
          <th scope="col" class="py-2 text-right font-medium">Words</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="vignette in vignettes"
          :key="vignette.id"
          class="border-b border-line"
          data-testid="vignette"
        >
          <td class="py-3 pr-4">
            <RouterLink :to="`/vignettes/${vignette.id}`" class="font-serif text-lg">
              {{ vignette.code }}
            </RouterLink>
          </td>
          <td class="py-3 pr-4">Version {{ latest(vignette)?.version }}</td>
          <td class="py-3 pr-4">{{ STATUS[latest(vignette)?.status ?? 'draft'] }}</td>
          <td class="py-3 text-right tabular-nums">{{ latest(vignette)?.word_count }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
