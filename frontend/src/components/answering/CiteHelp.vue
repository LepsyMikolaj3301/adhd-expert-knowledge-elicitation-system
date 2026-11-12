<script setup lang="ts">
import { inkFor } from '@/answering/highlights'
import InfoPopover from '@/components/InfoPopover.vue'

/**
 * "How to add a quote", under the case text. Pointing at it opens a short loop: a cursor selects
 * some words, the selection turns into a numbered quote. The panel only exists while open, so the
 * loop starts from the beginning on every hover.
 */
</script>

<template>
  <div class="text-sm text-muted">
    <InfoPopover mode="hover">
      <template #trigger="{ panelId }">
        <span
          class="cursor-help underline decoration-dotted underline-offset-4"
          tabindex="0"
          :aria-describedby="panelId"
          data-testid="cite-help"
          >How to add a quote</span
        >
      </template>
      <p class="demo font-serif text-[0.95rem] text-ink" aria-hidden="true" data-testid="cite-demo">
        Some days I
        <span class="words" :style="{ '--ink': inkFor(1) }"
          >lose my keys<svg
            class="cursor"
            viewBox="0 0 8 20"
            width="8"
            height="20"
            fill="none"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linecap="round"
          >
            <path d="M1 1h6M1 19h6M4 1v18" /></svg
          ><span class="chip">1</span></span
        >
        three times before lunch.
      </p>
      <p class="text-ink">
        Select words in the text above. They become a quote as soon as you let go.
      </p>
      <p class="text-muted">Then choose its direction in the list of quotes.</p>
    </InfoPopover>
  </div>
</template>

<style scoped>
.demo {
  --loop: 4.5s;
  line-height: 2;
  padding: 0.25rem 0.5rem;
  border-radius: 2px;
  background: var(--color-page, transparent);
}

.words {
  position: relative;
  isolation: isolate;
  white-space: nowrap;
}

/* The browser-blue selection grows behind the words as the cursor passes over them. */
.words::before,
.words::after {
  content: '';
  position: absolute;
  inset: 0.15em -1px;
  z-index: -1;
}

.words::before {
  background: color-mix(in srgb, #3b82f6 35%, transparent);
  transform-origin: left;
  animation: demo-select var(--loop) ease-in-out infinite;
}

/* Then it turns into the quote's colour, like the real thing. */
.words::after {
  background: var(--ink);
  opacity: 0;
  animation: demo-ink var(--loop) ease-in-out infinite;
}

.cursor {
  position: absolute;
  top: 50%;
  left: 0;
  margin: -10px 0 0 -4px;
  color: var(--color-ink, currentColor);
  opacity: 0;
  animation: demo-cursor var(--loop) ease-in-out infinite;
}

.chip {
  margin-left: 0.25rem;
  opacity: 0;
  animation: demo-chip var(--loop) ease-out infinite;
}

@keyframes demo-select {
  0%,
  12% {
    transform: scaleX(0);
    opacity: 1;
  }
  45%,
  52% {
    transform: scaleX(1);
    opacity: 1;
  }
  58%,
  100% {
    transform: scaleX(1);
    opacity: 0;
  }
}

@keyframes demo-ink {
  0%,
  50% {
    opacity: 0;
  }
  58%,
  88% {
    opacity: 1;
  }
  96%,
  100% {
    opacity: 0;
  }
}

@keyframes demo-cursor {
  0% {
    left: 0;
    opacity: 0;
  }
  5%,
  12% {
    left: 0;
    opacity: 1;
  }
  45% {
    left: 100%;
    opacity: 1;
  }
  52% {
    left: 100%;
    opacity: 1;
  }
  58%,
  100% {
    left: 100%;
    opacity: 0;
  }
}

@keyframes demo-chip {
  0%,
  55% {
    opacity: 0;
    transform: scale(0.6);
  }
  62%,
  88% {
    opacity: 1;
    transform: scale(1);
  }
  96%,
  100% {
    opacity: 0;
    transform: scale(1);
  }
}

/* No motion: show where it ends up, the quote and its number. */
@media (prefers-reduced-motion: reduce) {
  .words::before,
  .cursor {
    animation: none;
    opacity: 0;
  }

  .words::after,
  .chip {
    animation: none;
    opacity: 1;
  }
}
</style>
