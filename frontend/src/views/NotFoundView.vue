<script setup lang="ts">
import { RouterLink } from 'vue-router'
</script>

<template>
  <div>
    <h1>We can't find that page.</h1>
    <p class="mt-3 text-muted">The link may be out of date.</p>
    <RouterLink to="/" class="btn mt-6 hover:no-underline" data-testid="not-found-home">
      Go to Home
    </RouterLink>
  </div>
</template>
