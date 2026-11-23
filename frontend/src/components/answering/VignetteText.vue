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
const box = ref<HTMLElement>()
const button = ref<HTMLButtonElement>()
const mark = ref<HTMLElement>()
/** Where "Add quote" sits in the box: just under the last line of the selected words. */
const place = ref<{ top: number; left: number } | null>(null)
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
  if (pending.value) void placeButton()
}

/**
 * Under the end of the selection, inside the text's box. On a touch screen it drops a little
 * further, below the phone's selection handle. Without layout (or a selection) it keeps its
 * last place, which starts at the left under the first line.
 */
async function placeButton() {
  await nextTick()
  const selection = window.getSelection()
  if (!box.value || !selection?.rangeCount) return
  const rects = selection.getRangeAt(0).getClientRects()
  const last = rects[rects.length - 1]
  if (!last) return
  const outer = box.value.getBoundingClientRect()
  const width = button.value?.offsetWidth ?? 0
  const coarse = window.matchMedia?.('(pointer: coarse)').matches ?? false
  const top = last.bottom - outer.top + (coarse ? 28 : 6)
  // Its left edge at the start of the selection's last line, kept inside the box.
  const left = Math.max(8, Math.min(last.left - outer.left, outer.width - width - 8))
  place.value = { top, left }
}

/** Once the words are chosen, the button is scrolled into view if the text box cut it off. */
watch(
  () => Boolean((pending.value || armed.value) && !pressing.value),
  async (ready) => {
    if (!ready) return
    await placeButton()
    button.value?.scrollIntoView?.({ block: 'nearest' })
  },
)

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
  place.value = null
  if (!offsets) return
  window.getSelection()?.removeAllRanges()
  emit('cite', offsets[0], offsets[1])
}

/** The lines wrap differently after a resize: the button follows the words. */
function onResize() {
  if (pending.value || armed.value) void placeButton()
}

onMounted(() => {
  document.addEventListener('selectionchange', onSelectionChange)
  window.addEventListener('resize', onResize)
})
onBeforeUnmount(() => {
  document.removeEventListener('selectionchange', onSelectionChange)
  window.removeEventListener('resize', onResize)
})

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
  <!-- Room at the bottom, so that "Add quote" fits under a selection on the last line. Always
       there: in a review quoting comes and goes with the comment box, and the text must not jump. -->
  <div ref="box" class="relative px-5 pt-5 pb-16 md:px-7">
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
    <!-- Right under the selected words, so it is seen where the eye already is. -->
    <button
      v-if="pending || armed"
      ref="button"
      type="button"
      class="btn add-quote shadow-lg"
      :style="place ? { top: `${place.top}px`, left: `${place.left}px` } : undefined"
      data-testid="add-quote"
      @pointerdown.prevent="arm"
      @pointercancel="armed = null"
      @mousedown.prevent
      @click="addQuote"
    >
      <span aria-hidden="true">+</span> {{ citeLabel }}
    </button>
  </div>
</template>

<style scoped>
.add-quote {
  position: absolute;
  /* Before the first measurement: under the start of the text. */
  top: 2.5rem;
  left: 1.25rem;
  z-index: 20;
  white-space: nowrap;
}
</style>
