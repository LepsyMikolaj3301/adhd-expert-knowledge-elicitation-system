<script setup lang="ts">
export interface RailStep {
  id: string
  label: string
  reachable: boolean
}

defineProps<{
  steps: RailStep[]
  current: string
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
            type="button"
            class="rounded-sm border-b-2 px-2 py-1 disabled:cursor-not-allowed disabled:opacity-45"
            :class="
              step.id === current
                ? 'border-action font-semibold text-ink'
                : 'cursor-pointer border-transparent text-muted hover:text-ink'
            "
            :aria-current="step.id === current ? 'step' : undefined"
            :disabled="!step.reachable"
            data-testid="step"
            @click="$emit('go', step.id)"
          >
            {{ step.label }}
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
