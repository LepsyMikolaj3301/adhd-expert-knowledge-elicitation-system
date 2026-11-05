<script setup lang="ts">
import { useRoute } from 'vue-router'

const route = useRoute()
</script>

<template>
  <div>
    <h1>{{ route.meta.title }}</h1>
    <p class="mt-3 text-muted">This section isn't built yet.</p>
  </div>
</template>
