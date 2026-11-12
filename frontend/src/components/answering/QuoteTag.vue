<script setup lang="ts">
import { computed } from 'vue'

import { inkOf, togglePin, useQuoteFocus, useQuotePin } from '@/answering/quoteFocus'
import type { LinkedHighlight } from '@/api/client'
import { quoteTagLabel } from '@/copy'

/** One of the quotes a line of an answer is about, or the case as a whole. */
const props = defineProps<{
  target: string
  highlights: LinkedHighlight[]
  /** A toggle: pressed means the line is linked to it. */
  pressed?: boolean
  toggle?: boolean
  disabled?: boolean
}>()
defineEmits<{ toggle: [] }>()

const focus = useQuoteFocus()
const pin = useQuotePin()
const pinnable = pin !== null
const pinned = computed(() => props.target !== 'case' && pin?.value === props.target)
const togglePinned = () => togglePin(pin, props.target)
const highlight = computed(() => props.highlights.find((h) => h.id === props.target) ?? null)
const label = computed(() => quoteTagLabel(props.target, highlight.value))
const ink = computed(() =>
  props.target === 'case' ? 'var(--color-surface)' : inkOf(highlight.value?.chip ?? null),
)

function point(on: boolean) {
  if (props.target !== 'case') focus.value = on ? props.target : null
}
</script>

<template>
  <button
    v-if="toggle"
    type="button"
    class="quote-tag cursor-pointer disabled:cursor-not-allowed"
    :class="pressed ? 'border-text/60' : 'border-dashed bg-transparent! text-muted opacity-80'"
    :style="{ backgroundColor: pressed ? ink : undefined }"
    :aria-pressed="pressed"
    :disabled="disabled"
    :title="highlight ? `“${highlight.text}”` : undefined"
    data-testid="quote-tag"
    @mouseover="point(true)"
    @mouseout="point(false)"
    @focus="point(true)"
    @blur="point(false)"
    @click="$emit('toggle')"
  >
    {{ label }}
  </button>
  <!-- Where the page keeps a clicked quote lit, the tag is a button that pins it. -->
  <button
    v-else-if="pinnable && target !== 'case'"
    type="button"
    class="quote-tag cursor-pointer hover:border-text/60"
    :class="{ 'quote-pinned': pinned }"
    :style="{ backgroundColor: ink }"
    :title="highlight ? `“${highlight.text}”` : undefined"
    :aria-pressed="pinned"
    data-testid="quote-tag"
    @mouseover="point(true)"
    @mouseout="point(false)"
    @focus="point(true)"
    @blur="point(false)"
    @click="togglePinned"
  >
    {{ label }}
  </button>
  <span
    v-else
    class="quote-tag"
    :style="{ backgroundColor: ink }"
    :title="highlight ? `“${highlight.text}”` : undefined"
    data-testid="quote-tag"
    @mouseover="point(true)"
    @mouseout="point(false)"
  >
    {{ label }}
  </span>
</template>
