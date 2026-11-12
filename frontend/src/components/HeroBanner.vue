<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

/**
 * The top panel of the home page: the name large and centred, with a line under it. Scrolling
 * folds it into a slim bar that keeps only the name. The panel keeps its full height all the
 * time and sticks with a negative `top`, so only its last `COMPACT` shows once folded: nothing
 * below it moves while it folds.
 */
defineProps<{ title: string; tagline: string }>()

const FULL = 176 // px, 11rem
const COMPACT = 56 // px, 3.5rem
const FOLD = FULL - COMPACT
// The name starts 44px from the top, 48px tall, and ends at 55% size in the middle of the bar.
const NAME_TOP = 44
const NAME_H = 48
const NAME_SCALE = 0.55
const NAME_SLIDE = FULL - COMPACT / 2 - (NAME_H * NAME_SCALE) / 2 - NAME_TOP

/** 0 at the top of the page, 1 once the panel is a bar. */
const progress = ref(0)
const update = () => (progress.value = Math.min(1, Math.max(0, window.scrollY / FOLD)))

onMounted(() => {
  update()
  window.addEventListener('scroll', update, { passive: true })
  // The bar covers the top of the window: keyboard focus and #anchors must stop below it.
  document.documentElement.style.scrollPaddingTop = `${COMPACT + 16}px`
})
onUnmounted(() => {
  window.removeEventListener('scroll', update)
  document.documentElement.style.scrollPaddingTop = ''
})

const style = computed(() => ({ '--p': progress.value, top: `-${FOLD}px`, height: `${FULL}px` }))
</script>

<template>
  <header
    class="sticky z-20 overflow-hidden bg-ink text-white"
    :style="style"
    data-testid="banner"
    :data-folded="progress >= 1"
  >
    <div
      class="absolute inset-x-0 text-center"
      :style="{
        top: `${NAME_TOP}px`,
        // Slides down to the middle of the last 3.5rem as it shrinks.
        transform: `translateY(calc(var(--p) * ${NAME_SLIDE}px)) scale(calc(1 - var(--p) * ${1 - NAME_SCALE}))`,
        transformOrigin: '50% 0',
      }"
    >
      <h1
        class="font-serif text-5xl leading-none font-medium tracking-tight text-white max-sm:text-4xl"
      >
        {{ title }}
      </h1>
    </div>

    <p
      class="absolute inset-x-0 top-[7rem] px-4 text-center text-base text-on-ink"
      :style="{ opacity: Math.max(0, 1 - progress * 2.5) }"
    >
      {{ tagline }}
    </p>

    <div
      class="absolute inset-x-0 bottom-0 h-px bg-white/20"
      :style="{ opacity: progress }"
      aria-hidden="true"
    />
  </header>
</template>
