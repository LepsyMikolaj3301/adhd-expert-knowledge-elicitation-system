<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'

import { inkFor } from '@/answering/highlights'
import type { Citation, Direction } from '@/api/client'
import { DIRECTIONS, directionLabel } from '@/copy'

const props = defineProps<{
  citations: Citation[]
  /** The first this many can't change any more. */
  lockedCount: number
  /** False on a submitted vignette: the table can then only be hovered. */
  editable: boolean
  /** Whether there is an answer box on screen to insert a chip into. */
  canInsert: boolean
  uncited: number[]
  pulseChip: number | null
}>()

const emit = defineEmits<{
  active: [chip: number | null]
  direction: [chip: number, direction: Direction]
  insert: [chip: number]
  remove: [chip: number]
}>()

const rows = ref<HTMLElement>()

/** The first words of a passage, enough to tell it from the others when it is read out. */
function shortQuote(text: string): string {
  const words = text.split(/\s+/)
  return `“${words.slice(0, 8).join(' ')}${words.length > 8 ? '…' : ''}”`
}

/**
 * Clicking a passage puts its reference at the cursor in the answer. Where there is no answer box
 * (a locked question, the rating, the review) it only shows the passage in the text.
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
  <section aria-labelledby="citations-heading" class="flex min-h-0 flex-col">
    <h2 id="citations-heading" class="font-sans text-sm font-semibold text-ink">Marked passages</h2>
    <p v-if="!citations.length" class="mt-2 text-sm text-muted" data-testid="no-citations">
      <template v-if="editable">Select the words your answer is about.</template>
      <template v-else>No marked passages.</template>
    </p>
    <template v-else>
      <p v-if="editable" class="mt-1 text-sm text-muted">
        Select more words to mark another passage.
        <template v-if="canInsert">
          Click a passage to add it to your answer at the cursor. Point at it to find it in the
          text.
        </template>
        <template v-else>Click a passage to find it in the text.</template>
      </p>
      <div ref="rows" class="mt-2 min-h-0 overflow-y-auto">
        <table class="w-full border-collapse text-left text-sm">
          <thead class="sr-only">
            <tr>
              <th scope="col">Passage</th>
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
                      : `Show passage ${citation.chip} in the text: ${shortQuote(citation.text)}`
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
                      v-if="editable && uncited.includes(citation.chip)"
                      class="mt-0.5 block text-xs text-muted"
                    >
                      Not mentioned in an answer yet
                    </span>
                  </span>
                  <span
                    v-if="canInsert"
                    class="shrink-0 pt-0.5 text-xs whitespace-nowrap text-action opacity-0 group-focus-within:opacity-100 group-hover:opacity-100"
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
                  :aria-label="`Direction of passage ${citation.chip}`"
                  @change="onDirection(citation.chip, $event)"
                >
                  <option value="" disabled>Direction needed</option>
                  <option v-for="d in DIRECTIONS" :key="d.value" :value="d.value">
                    {{ d.label }}
                  </option>
                </select>
                <span v-else class="block py-0.5">{{ directionLabel(citation.direction) }}</span>
                <span v-if="editable && !isLocked(citation.chip)" class="mt-0.5 flex text-sm">
                  <button
                    type="button"
                    class="cursor-pointer text-muted hover:text-danger hover:underline"
                    :aria-label="`Remove passage ${citation.chip}`"
                    @click="emit('remove', citation.chip)"
                  >
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
