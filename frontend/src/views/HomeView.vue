<script setup lang="ts">
import { onMounted, ref } from 'vue'

const status = ref<'loading' | 'ok' | 'down'>('loading')

onMounted(async () => {
  try {
    const res = await fetch('/api/health')
    status.value = res.ok ? 'ok' : 'down'
  } catch {
    status.value = 'down'
  }
})
</script>

<template>
  <main>
    <h1>ADHD Expert Knowledge Elicitation</h1>
    <p>
      Backend:
      <strong data-testid="backend-status">{{ status }}</strong>
    </p>
  </main>
</template>
