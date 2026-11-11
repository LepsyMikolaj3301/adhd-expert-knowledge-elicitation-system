<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'

let counter = 0

const props = defineProps<{ mode: 'hover' | 'click' }>()
const emit = defineEmits<{ open: [] }>()

const open = ref(false)
const root = ref<HTMLElement>()
const id = `popover-${++counter}`

function outside(event: MouseEvent) {
  if (!root.value?.contains(event.target as Node)) open.value = false
}
function escape(event: KeyboardEvent) {
  if (event.key === 'Escape') open.value = false
}
function stop() {
  document.removeEventListener('mousedown', outside)
  document.removeEventListener('keydown', escape)
}
watch(open, (now) => {
  stop()
  if (!now) return
  emit('open')
  document.addEventListener('mousedown', outside)
  document.addEventListener('keydown', escape)
})
onBeforeUnmount(stop)

/** shortcut: always opens below; a card at the very bottom of a short page scrolls into view. */
const hover = (state: boolean) => {
  if (props.mode === 'hover') open.value = state
}
</script>

<template>
  <span
    ref="root"
    class="relative inline-block"
    @mouseenter="hover(true)"
    @mouseleave="hover(false)"
    @focusin="hover(true)"
    @focusout="hover(false)"
  >
    <slot name="trigger" :open="open" :toggle="() => (open = !open)" :panel-id="id" />
    <!-- No gap between trigger and panel: the pointer would leave the hover area crossing it. -->
    <span v-if="open" :id="id" class="absolute left-0 top-full z-20 block pt-1" role="dialog">
      <span
        class="block w-80 max-w-[85vw] space-y-2 rounded-sm border border-line bg-surface p-3 text-left text-sm font-sans font-normal text-text shadow-lg"
      >
        <slot />
      </span>
    </span>
  </span>
</template>
