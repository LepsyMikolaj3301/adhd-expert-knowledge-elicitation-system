<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'

import { TRUST_SENTENCE } from '@/copy'
import { navFor } from '@/navigation'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const sections = computed(() =>
  auth.user ? navFor(auth.user.role).filter((item) => item.to !== '/') : [],
)
</script>

<template>
  <div>
    <h1>Welcome, {{ auth.user?.display_name }}</h1>
    <ul class="mt-8 divide-y divide-line border-y border-line" data-testid="sections">
      <li v-for="item in sections" :key="item.to + item.label" class="py-4">
        <RouterLink :to="item.to" class="font-serif text-xl">{{ item.label }}</RouterLink>
        <p class="mt-1 text-muted">{{ item.blurb }}</p>
      </li>
    </ul>
    <p
      v-if="auth.user?.role === 'expert'"
      class="mt-8 max-w-xl text-sm text-muted"
      data-testid="trust"
    >
      {{ TRUST_SENTENCE }}
    </p>
  </div>
</template>
