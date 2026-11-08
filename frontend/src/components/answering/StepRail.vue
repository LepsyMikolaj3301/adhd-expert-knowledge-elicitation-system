<script setup lang="ts">
export interface RailStep {
  id: string
  label: string
  reachable: boolean
  /** What is missing here, shown once the expert has tried to go on. */
  problem?: string | null
}

defineProps<{
  steps: RailStep[]
  current: string
  /** Counts up on every attempt to go on, so the flash plays again. */
  flashKey?: number
  /** A thin line after this step separates the questions that get locked from the rest. */
  gateAfter: string
}>()

defineEmits<{ go: [id: string] }>()
</script>

<template>
  <nav aria-label="Questions">
    <ol class="flex flex-wrap items-center gap-x-1 gap-y-1 text-sm">
      <template v-for="step in steps" :key="step.id">
        <li>
          <button
            :key="`${step.id}-${step.problem ? (flashKey ?? 0) : 'ok'}`"
            type="button"
            class="rounded-sm border-b-2 px-2 py-1 disabled:cursor-not-allowed disabled:opacity-45"
            :class="[
              step.problem
                ? 'flag-shake border-danger font-semibold text-danger'
                : step.id === current
                  ? 'border-action font-semibold text-ink'
                  : 'cursor-pointer border-transparent text-muted hover:text-ink',
            ]"
            :aria-current="step.id === current ? 'step' : undefined"
            :aria-label="step.problem ? `${step.label}: ${step.problem}` : undefined"
            :disabled="!step.reachable"
            :data-problem="step.problem ? 'true' : undefined"
            data-testid="step"
            @click="$emit('go', step.id)"
          >
            {{ step.label }}
            <span v-if="step.problem" aria-hidden="true">●</span>
          </button>
        </li>
        <li
          v-if="step.id === gateAfter"
          class="mx-1 h-4 w-px bg-line"
          aria-hidden="true"
          data-testid="gate-divider"
        />
      </template>
    </ol>
  </nav>
</template>
