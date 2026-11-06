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
        Select more words to mark another passage. Point at a row, or tap its number, to find it in
        the text.
      </p>
      <div ref="rows" class="mt-2 min-h-0 overflow-y-auto">
        <table class="w-full border-collapse text-left text-sm">
          <thead class="sr-only">
            <tr>
              <th scope="col">Number</th>
              <th scope="col">Passage</th>
              <th scope="col">Direction and actions</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="citation in citations"
              :key="citation.chip"
              :data-row="citation.chip"
              class="border-t border-line align-top"
              :class="{ 'row-pulse': pulseChip === citation.chip }"
              :style="{ '--ink': inkFor(citation.chip) }"
              data-testid="citation"
              @mouseenter="emit('active', citation.chip)"
              @mouseleave="emit('active', null)"
              @focusin="emit('active', citation.chip)"
              @focusout="emit('active', null)"
            >
              <td class="w-10 py-1.5 pr-2 text-base">
                <!-- Focusing this shows the passage on a keyboard or a touch screen. -->
                <button
                  type="button"
                  class="chip"
                  :aria-label="`Show passage ${citation.chip} in the text`"
                >
                  {{ citation.chip }}
                </button>
              </td>
              <td class="py-1.5 pr-3">
                <span class="line-clamp-2 font-serif text-[0.95rem]">“{{ citation.text }}”</span>
                <span
                  v-if="editable && uncited.includes(citation.chip)"
                  class="mt-0.5 block text-xs text-muted"
                >
                  Not mentioned in an answer yet
                </span>
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
                <span v-if="editable" class="mt-0.5 flex gap-3 text-sm">
                  <button
                    type="button"
                    class="cursor-pointer text-action hover:underline disabled:cursor-not-allowed disabled:text-muted disabled:no-underline"
                    :disabled="!canInsert"
                    :aria-label="`Cite passage ${citation.chip} in your answer`"
                    @mousedown.prevent
                    @click="emit('insert', citation.chip)"
                  >
                    Cite
                  </button>
                  <button
                    v-if="!isLocked(citation.chip)"
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
