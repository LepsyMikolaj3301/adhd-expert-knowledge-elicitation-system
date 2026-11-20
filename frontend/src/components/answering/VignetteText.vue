<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { segmentsFor } from '@/answering/highlights'
import { inkOf } from '@/answering/quoteFocus'
import { CITE } from '@/copy'

const props = withDefaults(
  defineProps<{
    text: string
    /** The passage to light up: a citation, or words an answer quoted. Nothing else is marked. */
    active: { span: readonly number[]; chip: number | null } | null
    canCite: boolean
    /** What the button that turns the selection into a quote says. */
    citeLabel?: string
  }>(),
  { citeLabel: CITE.add },
)

const emit = defineEmits<{ cite: [start: number, end: number] }>()

const root = ref<HTMLElement>()
const mark = ref<HTMLElement>()
/** A pointer is down on the text: a selection may be about to start. */
const pressing = ref(false)
/** The selected words, waiting for the button. */
const pending = ref<[number, number] | null>(null)
/** The phone may drop the selection as the button is touched: the words are kept until the click. */
const armed = ref<[number, number] | null>(null)

// Marking a passage rewrites the text nodes, which would destroy a selection being made.
const shown = computed(() => (pressing.value || pending.value || armed.value ? null : props.active))
const parts = computed(() => segmentsFor(props.text, shown.value))

/** The browser's offset of a point inside the text. */
function offsetOf(container: Node, offset: number): number {
  const before = document.createRange()
  before.selectNodeContents(root.value as HTMLElement)
  before.setEnd(container, offset)
  return before.toString().length
}

function readSelection(): [number, number] | null {
  const selection = window.getSelection()
  if (!root.value || !selection || selection.isCollapsed || !selection.rangeCount) return null
  const range = selection.getRangeAt(0)
  if (!range.intersectsNode(root.value)) return null
  // A drag can run past the sheet: keep the part inside it.
  const start = root.value.contains(range.startContainer)
    ? offsetOf(range.startContainer, range.startOffset)
    : 0
  const end = root.value.contains(range.endContainer)
    ? offsetOf(range.endContainer, range.endOffset)
    : props.text.length
  return start < end ? [start, end] : null
}

/**
 * A selection only becomes a quote when the button is pressed. Adding it as the pointer lifts
 * fails on touch screens: a long press ends the pointer before the handles are dragged.
 */
function onSelectionChange() {
  pending.value = props.canCite ? readSelection() : null
}

function onPointerDown() {
  if (!props.canCite) return
  pressing.value = true
  const release = () => {
    window.removeEventListener('pointerup', release)
    window.removeEventListener('pointercancel', release)
    pressing.value = false
  }
  window.addEventListener('pointerup', release)
  window.addEventListener('pointercancel', release)
}

/** Preventing pointerdown on the button also keeps focus in a comment box. */
function arm() {
  armed.value = pending.value
}

function addQuote() {
  const offsets = armed.value ?? pending.value
  armed.value = null
  pending.value = null
  if (!offsets) return
  window.getSelection()?.removeAllRanges()
  emit('cite', offsets[0], offsets[1])
}

onMounted(() => document.addEventListener('selectionchange', onSelectionChange))
onBeforeUnmount(() => document.removeEventListener('selectionchange', onSelectionChange))

watch(
  () => props.canCite,
  (can) => {
    if (can) return
    pending.value = null
    armed.value = null
  },
)

watch(shown, async (citation) => {
  if (!citation) return
  await nextTick()
  mark.value?.scrollIntoView?.({ block: 'nearest' })
})
</script>

<template>
  <div class="px-5 py-5 md:px-7">
    <p ref="root" class="patient-text" data-testid="vignette-text" @pointerdown="onPointerDown">
      <span>{{ parts.before }}</span
      ><mark
        v-if="parts.marked"
        ref="mark"
        class="ink-mark"
        :style="{ '--ink': inkOf(active?.chip ?? null) }"
        >{{ parts.marked }}</mark
      ><span v-if="parts.after">{{ parts.after }}</span>
    </p>
    <!-- At the bottom of the screen: clear of the phone's own copy menu and selection handles. -->
    <Teleport to="body">
      <div v-if="pending || armed" class="add-quote-bar">
        <button
          type="button"
          class="btn shadow-lg"
          data-testid="add-quote"
          @pointerdown.prevent="arm"
          @pointercancel="armed = null"
          @mousedown.prevent
          @click="addQuote"
        >
          <span aria-hidden="true">+</span> {{ citeLabel }}
        </button>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.add-quote-bar {
  position: fixed;
  left: 0;
  right: 0;
  bottom: max(1rem, env(safe-area-inset-bottom));
  z-index: 40;
  display: flex;
  justify-content: center;
  pointer-events: none;
}

.add-quote-bar > button {
  pointer-events: auto;
}
</style>
