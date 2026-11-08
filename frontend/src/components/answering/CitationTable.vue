<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'

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
  /** The expert tried to go on with something missing: say which quotes still need a direction. */
  marked?: boolean
  /** Counts up on every such attempt, so the flash plays again. */
  flashKey?: number
}>()

const emit = defineEmits<{
  active: [chip: number | null]
  direction: [chip: number, direction: Direction]
  insert: [chip: number]
  remove: [chip: number]
}>()

const rows = ref<HTMLElement>()
/** Quotes the expert can still give a direction that have none. */
const needsDirection = (chip: number): boolean => {
  const c = props.citations.find((x) => x.chip === chip)
  return Boolean(props.editable && c && !c.direction && !isLocked(chip))
}
const anyMissing = computed(() => props.citations.some((c) => needsDirection(c.chip)))
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
    <h2 id="citations-heading" class="font-sans text-sm font-semibold text-ink">Quotes</h2>
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
          <thead>
            <tr class="text-xs font-medium tracking-wide text-muted uppercase">
              <th scope="col" class="pb-1 pr-4 font-medium">Quote</th>
              <th scope="col" class="w-52 border-l border-line pb-1 pl-3 font-medium xl:w-60">
                <div ref="helpRoot" class="relative flex items-center gap-1.5">
                  <span :class="marked && anyMissing ? 'text-danger' : ''">Direction</span>
                  <span
                    v-if="marked && anyMissing"
                    class="text-danger"
                    data-testid="direction-missing"
                    aria-hidden="true"
                  >
                    ●
                  </span>
                  <button
                    ref="helpButton"
                    type="button"
                    class="flex h-5 w-5 cursor-pointer items-center justify-center rounded-full border border-line bg-surface text-xs font-semibold text-action normal-case hover:border-action"
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
                    class="absolute right-0 bottom-full z-20 mb-1 w-80 max-w-[85vw] rounded-sm border border-line bg-surface p-3 text-sm font-normal tracking-normal text-text normal-case shadow-md"
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
              </th>
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
              <td class="py-1.5 pr-4">
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
                    class="hidden shrink-0 pt-0.5 text-xs whitespace-nowrap text-action xl:block"
                    aria-hidden="true"
                  >
                    + Add to answer
                  </span>
                </button>
                <span v-if="editable && !isLocked(citation.chip)" class="mt-0.5 flex pl-8 text-sm">
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
              <td class="w-52 border-l border-line py-1.5 pl-3 xl:w-60">
                <select
                  v-if="editable && !isLocked(citation.chip)"
                  :key="`direction-${citation.chip}-${flashKey ?? 0}`"
                  class="w-full rounded-sm border bg-surface px-1 py-0.5 text-sm"
                  :class="[
                    citation.direction
                      ? 'border-line'
                      : marked
                        ? 'border-danger flag-flash'
                        : 'border-action',
                  ]"
                  :data-missing="!citation.direction && marked ? 'true' : undefined"
                  :value="citation.direction ?? ''"
                  :aria-label="`Direction of quote ${citation.chip}`"
                  :title="directionLabel(citation.direction) || undefined"
                  @change="onDirection(citation.chip, $event)"
                >
                  <option value="" disabled>-</option>
                  <option v-for="d in DIRECTIONS" :key="d.value" :value="d.value">
                    {{ d.label }}
                  </option>
                </select>
                <span v-else class="block py-0.5">{{ directionLabel(citation.direction) }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </section>
</template>
