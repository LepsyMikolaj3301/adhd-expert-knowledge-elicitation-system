<script setup lang="ts">
import { inkFor } from '@/answering/highlights'
import InfoPopover from '@/components/InfoPopover.vue'
import { CITE } from '@/copy'

/**
 * "How to add a quote", under the case text. Pointing at it (or tapping it) opens a short loop on
 * a small screen: a cursor selects some words, "Add quote" rises under the words, a tap presses it,
 * and the selection turns into a numbered quote. The panel only exists while open, so the loop
 * starts from the beginning every time.
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
          >{{ CITE.help }}</span
        >
      </template>
      <span class="screen" aria-hidden="true" data-testid="cite-demo">
        <span class="demo font-serif text-[0.95rem] text-ink">
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
        </span>
        <span class="bar">
          <span class="fake-button" data-testid="cite-demo-button"
            >+ {{ CITE.add }}<span class="tap"></span
          ></span>
        </span>
      </span>
      <p class="text-ink">{{ CITE.helpSteps }}</p>
      <p class="text-muted">{{ CITE.helpThen }}</p>
    </InfoPopover>
  </div>
</template>

<style scoped>
/* A small screen: the text above, the bar with the button at its bottom edge. */
.screen {
  --loop: 6s;
  display: block;
  overflow: hidden;
  border: 1px solid var(--color-line, currentColor);
  border-radius: 6px;
  background: var(--color-page, transparent);
}

.demo {
  display: block;
  line-height: 2;
  padding: 0.5rem 0.75rem 0.25rem;
}

.bar {
  display: flex;
  justify-content: center;
  height: 2.25rem;
  padding-top: 0.25rem;
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

/* After the button is pressed it turns into the quote's colour, like the real thing. */
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

.fake-button {
  position: relative;
  align-self: flex-start;
  border-radius: 6px;
  padding: 0.2rem 0.65rem;
  background: var(--color-action, #2459c9);
  color: #fff;
  font-size: 0.75rem;
  font-weight: 500;
  white-space: nowrap;
  opacity: 0;
  animation: demo-button var(--loop) ease-out infinite;
}

/* The finger (or click) that presses it. */
.tap {
  position: absolute;
  left: 50%;
  top: 50%;
  width: 1.75rem;
  height: 1.75rem;
  margin: -0.875rem 0 0 -0.875rem;
  border-radius: 50%;
  border: 1.5px solid var(--color-ink, currentColor);
  background: color-mix(in srgb, var(--color-ink, #14294d) 20%, transparent);
  opacity: 0;
  animation: demo-tap var(--loop) ease-out infinite;
}

@keyframes demo-select {
  0%,
  8% {
    transform: scaleX(0);
    opacity: 1;
  }
  35%,
  56% {
    transform: scaleX(1);
    opacity: 1;
  }
  62%,
  100% {
    transform: scaleX(1);
    opacity: 0;
  }
}

@keyframes demo-cursor {
  0% {
    left: 0;
    opacity: 0;
  }
  4%,
  8% {
    left: 0;
    opacity: 1;
  }
  35%,
  38% {
    left: 100%;
    opacity: 1;
  }
  42%,
  100% {
    left: 100%;
    opacity: 0;
  }
}

@keyframes demo-button {
  0%,
  38% {
    opacity: 0;
    transform: translateY(0.5rem);
  }
  44%,
  50% {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
  53% {
    opacity: 1;
    transform: scale(0.92);
  }
  57% {
    opacity: 1;
    transform: scale(1);
  }
  62%,
  100% {
    opacity: 0;
    transform: scale(1);
  }
}

@keyframes demo-tap {
  0%,
  48% {
    opacity: 0;
    transform: scale(0.4);
  }
  52% {
    opacity: 1;
    transform: scale(1);
  }
  60%,
  100% {
    opacity: 0;
    transform: scale(1.4);
  }
}

@keyframes demo-ink {
  0%,
  56% {
    opacity: 0;
  }
  62%,
  90% {
    opacity: 1;
  }
  97%,
  100% {
    opacity: 0;
  }
}

@keyframes demo-chip {
  0%,
  58% {
    opacity: 0;
    transform: scale(0.6);
  }
  65%,
  90% {
    opacity: 1;
    transform: scale(1);
  }
  97%,
  100% {
    opacity: 0;
    transform: scale(1);
  }
}

/* No motion: the words selected and the button to press. */
@media (prefers-reduced-motion: reduce) {
  .words::after,
  .cursor,
  .tap,
  .chip {
    animation: none;
    opacity: 0;
  }

  .words::before,
  .fake-button {
    animation: none;
    opacity: 1;
    transform: none;
  }
}
</style>
