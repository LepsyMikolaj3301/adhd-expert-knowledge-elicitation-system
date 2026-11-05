<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'

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
  </div>
</template>
