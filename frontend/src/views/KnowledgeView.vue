<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import SegmentedToggle from '@/components/SegmentedToggle.vue'
import KnowledgeSearch from '@/components/knowledge/KnowledgeSearch.vue'
import KnowledgeUnits from '@/components/knowledge/KnowledgeUnits.vue'

const TABS = [
  { value: 'units', label: 'Units' },
  { value: 'search', label: 'Test search' },
] as const

const route = useRoute()
const router = useRouter()
// In the address, so that a tab can be linked to and survives a reload.
const tab = computed(() => (route.query.tab === 'search' ? 'search' : 'units'))

const show = (value: 'units' | 'search') =>
  router.replace({ query: value === 'units' ? {} : { tab: value } })
</script>

<template>
  <div>
    <h1>Knowledge base</h1>
    <SegmentedToggle
      class="mt-4"
      label="Show"
      :options="TABS"
      :model-value="tab"
      @update:model-value="show"
    />
    <KnowledgeSearch v-if="tab === 'search'" />
    <KnowledgeUnits v-else />
  </div>
</template>
