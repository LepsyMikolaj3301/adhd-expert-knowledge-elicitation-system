<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'

import { inkFor } from '@/answering/highlights'
import type { Citation, Direction } from '@/api/client'
import { citedTimes, DIRECTIONS, directionLabel } from '@/copy'

const props = defineProps<{
  citations: Citation[]
  /** The first this many can't change any more. */
  lockedCount: number
  /** False on a submitted vignette: the table can then only be hovered. */
  editable: boolean
  /** Whether there is an answer box on screen to insert a chip into. */
  canInsert: boolean
  /** How many times each one is referred to in the answers, by chip. */
  counts: Record<number, number>
  pulseChip: number | null
}>()

const emit = defineEmits<{
  active: [chip: number | null]
  direction: [chip: number, direction: Direction]
  insert: [chip: number]
  remove: [chip: number]
}>()

const rows = ref<HTMLElement>()
const helpOpen = ref(false)
const helpRoot = ref<HTMLElement>()
const helpButton = ref<HTMLButtonElement>()

/** The first words of a quote, enough to tell it from the others when it is read out. */
function shortQuote(text: string): string {
  const words = text.split(/\s+/)
  return `“${words.slice(0, 8).join(' ')}${words.length > 8 ? '…' : ''}”`
}

/**
 * Clicking a quote puts its reference at the cursor in the answer. Where there is no answer box
 * (the review, or nothing left to write in) it only shows the quote in the text.
 */
function pick(chip: number) {
  if (props.canInsert) emit('insert', chip)
  else emit('active', chip)
}

function isLocked(chip: number): boolean {
  return chip <= props.lockedCount
}

function onDirection(chip: number, event: Event) {
  emit('direction', chip, (event.target as HTMLSelectElement).value as Direction)
}

function closeHelpOutside(event: Event) {
  if (helpOpen.value && !helpRoot.value?.contains(event.target as Node)) helpOpen.value = false
}

function closeHelpOnEscape(event: KeyboardEvent) {
  if (event.key !== 'Escape' || !helpOpen.value) return
  helpOpen.value = false
  helpButton.value?.focus()
}

onMounted(() => {
  document.addEventListener('pointerdown', closeHelpOutside)
  document.addEventListener('keydown', closeHelpOnEscape)
})

onUnmounted(() => {
  document.removeEventListener('pointerdown', closeHelpOutside)
  document.removeEventListener('keydown', closeHelpOnEscape)
})

watch(
  () => props.pulseChip,
  async (chip) => {
    if (!chip) return
    await nextTick()
    rows.value?.querySelector(`[data-row="${chip}"]`)?.scrollIntoView?.({ block: 'nearest' })
  },
)
</script>

<template>
  <section aria-labelledby="citations-heading" class="relative flex min-h-0 flex-col">
    <div class="flex items-center justify-between gap-3">
      <h2 id="citations-heading" class="font-sans text-sm font-semibold text-ink">Quotes</h2>
      <div
        v-if="citations.length"
        ref="helpRoot"
        class="flex w-32 items-center gap-1.5 text-sm text-muted"
      >
        <span>Direction</span>
        <button
          ref="helpButton"
          type="button"
          class="flex h-5 w-5 cursor-pointer items-center justify-center rounded-full border border-line bg-surface text-xs font-semibold text-action hover:border-action"
          aria-label="What the directions mean"
          aria-controls="direction-help"
          :aria-expanded="helpOpen"
          data-testid="direction-help-button"
          @click="helpOpen = !helpOpen"
        >
          ?
        </button>
        <div
          v-if="helpOpen"
          id="direction-help"
          class="absolute right-0 bottom-full z-20 mb-1 w-[min(20rem,100%)] rounded-sm border border-line bg-surface p-3 text-sm text-text shadow-md"
          data-testid="direction-help"
        >
          <p class="font-medium text-ink">What does this quote do to your reading?</p>
          <dl class="mt-2 space-y-2">
            <div v-for="d in DIRECTIONS" :key="d.value">
              <dt class="font-medium">{{ d.label }}</dt>
              <dd class="text-muted">{{ d.help }}</dd>
            </div>
          </dl>
        </div>
      </div>
    </div>
    <p v-if="!citations.length" class="mt-2 text-sm text-muted" data-testid="no-citations">
      <template v-if="editable">Select the words your answer is about.</template>
      <template v-else>No quotes.</template>
    </p>
    <template v-else>
      <p v-if="editable" class="mt-1 text-sm text-muted">
        Select more words to add another quote.
        <template v-if="canInsert">
          Click a quote to add it to your answer at the cursor. Point at it to find it in the text.
        </template>
        <template v-else>Click a quote to find it in the text.</template>
      </p>
      <div ref="rows" class="mt-2 min-h-0 overflow-y-auto">
        <table class="w-full border-collapse text-left text-sm">
          <thead class="sr-only">
            <tr>
              <th scope="col">Quote</th>
              <th scope="col">Direction and actions</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="citation in citations"
              :key="citation.chip"
              :data-row="citation.chip"
              class="group border-t border-line align-top"
              :class="{ 'row-pulse': pulseChip === citation.chip }"
              :style="{ '--ink': inkFor(citation.chip) }"
              data-testid="citation"
              @mouseenter="emit('active', citation.chip)"
              @mouseleave="emit('active', null)"
              @focusin="emit('active', citation.chip)"
              @focusout="emit('active', null)"
            >
              <td class="py-1.5 pr-3">
                <!-- One target: the number and the words. The mouse-down is stopped so that the
                     cursor stays in the answer and the reference lands where it was. -->
                <button
                  type="button"
                  class="flex w-full cursor-pointer items-start gap-2 rounded-sm text-left"
                  data-testid="add-reference"
                  :aria-label="
                    canInsert
                      ? `Add reference ${citation.chip} to your answer: ${shortQuote(citation.text)}`
                      : `Show quote ${citation.chip} in the text: ${shortQuote(citation.text)}`
                  "
                  @mousedown.prevent
                  @click="pick(citation.chip)"
                >
                  <span class="chip mt-0.5 text-base" aria-hidden="true">{{ citation.chip }}</span>
                  <span class="min-w-0 flex-1">
                    <span class="line-clamp-2 font-serif text-[0.95rem]">
                      “{{ citation.text }}”
                    </span>
                    <span
                      v-if="editable"
                      class="mt-0.5 block text-xs text-muted"
                      data-testid="cited-times"
                    >
                      {{ citedTimes(counts[citation.chip] ?? 0) }}
                    </span>
                  </span>
                  <span
                    v-if="canInsert"
                    class="shrink-0 pt-0.5 text-xs whitespace-nowrap text-action"
                    aria-hidden="true"
                  >
                    + Add to answer
                  </span>
                </button>
              </td>
              <td class="w-32 py-1.5">
                <select
                  v-if="editable && !isLocked(citation.chip)"
                  class="w-full rounded-sm border bg-surface px-1 py-0.5 text-sm"
                  :class="citation.direction ? 'border-line' : 'border-action'"
                  :value="citation.direction ?? ''"
                  :aria-label="`Direction of quote ${citation.chip}`"
                  @change="onDirection(citation.chip, $event)"
                >
                  <option value="" disabled>-</option>
                  <option v-for="d in DIRECTIONS" :key="d.value" :value="d.value">
                    {{ d.label }}
                  </option>
                </select>
                <span v-else class="block py-0.5">{{ directionLabel(citation.direction) }}</span>
                <span v-if="editable && !isLocked(citation.chip)" class="mt-0.5 flex text-sm">
                  <button
                    type="button"
                    class="flex cursor-pointer items-center gap-1 text-muted hover:text-danger hover:underline"
                    :aria-label="`Remove quote ${citation.chip}`"
                    @click="emit('remove', citation.chip)"
                  >
                    <svg
                      viewBox="0 0 16 16"
                      width="13"
                      height="13"
                      fill="none"
                      stroke="currentColor"
                      stroke-width="1.5"
                      stroke-linecap="round"
                      stroke-linejoin="round"
                      aria-hidden="true"
                    >
                      <path
                        d="M2.5 4h11M6.5 4V2.5h3V4M4 4l.7 9.5h6.6L12 4M6.75 6.75v4M9.25 6.75v4"
                      />
                    </svg>
                    Remove
                  </button>
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </section>
</template>
