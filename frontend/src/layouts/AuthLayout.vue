<script setup lang="ts">
import { SITE_NAME } from '@/site'
</script>

<template>
  <div class="min-h-screen md:grid md:grid-cols-[15rem_1fr]">
    <div class="bg-ink px-6 py-5 md:py-7">
      <span class="font-serif text-xl text-white">{{ SITE_NAME }}</span>
    </div>
    <main class="flex items-start px-4 py-10 md:items-center md:px-12">
      <div class="w-full max-w-sm">
        <slot />
      </div>
    </main>
  </div>
</template>
