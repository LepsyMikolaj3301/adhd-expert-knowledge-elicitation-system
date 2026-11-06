<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'

import { inkFor, segmentsFor } from '@/answering/highlights'
import type { Citation } from '@/api/client'

const props = defineProps<{
  text: string
  /** The citation to light up. Nothing else is ever marked. */
  active: Citation | null
  canCite: boolean
}>()

const emit = defineEmits<{ cite: [start: number, end: number] }>()

const root = ref<HTMLElement>()
const mark = ref<HTMLElement>()
// Marking a passage rewrites the text nodes, which would destroy a selection being dragged.
const selecting = ref(false)
const hasSelection = ref(false)

const shown = computed(() => (selecting.value ? null : props.active))
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

function citeSelection() {
  const offsets = readSelection()
  if (!offsets) return
  window.getSelection()?.removeAllRanges()
  hasSelection.value = false
  emit('cite', offsets[0], offsets[1])
}

function onPointerDown(event: PointerEvent) {
  if (!props.canCite) return
  selecting.value = true
  // A touch selection is adjusted after the finger lifts: the button below confirms it.
  const automatic = event.pointerType !== 'touch'
  const finish = () => {
    window.removeEventListener('pointerup', finish)
    window.removeEventListener('pointercancel', finish)
    selecting.value = false
    if (automatic) citeSelection()
  }
  window.addEventListener('pointerup', finish)
  window.addEventListener('pointercancel', finish)
}

function onSelectionChange() {
  hasSelection.value = props.canCite && !selecting.value && readSelection() !== null
}

onMounted(() => document.addEventListener('selectionchange', onSelectionChange))
onUnmounted(() => document.removeEventListener('selectionchange', onSelectionChange))

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
        :style="{ '--ink': inkFor(active?.chip ?? 1) }"
        >{{ parts.marked }}</mark
      ><span v-if="parts.after">{{ parts.after }}</span>
    </p>
    <button
      v-if="hasSelection"
      type="button"
      class="btn-quiet mt-3"
      data-testid="cite-selection"
      @click="citeSelection"
    >
      Mark selection
    </button>
  </div>
</template>
