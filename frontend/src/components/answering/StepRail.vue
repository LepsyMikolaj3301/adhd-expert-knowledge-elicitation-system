<script setup lang="ts">
export interface RailStep {
  id: string
  label: string
  reachable: boolean
}

defineProps<{
  steps: RailStep[]
  current: string
  /** The gate sits after this step, shown as a padlock. */
  gateAfter: string
  gatePassed: boolean
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
        <li v-if="step.id === gateAfter" class="px-1 text-muted">
          <svg
            viewBox="0 0 16 16"
            width="14"
            height="14"
            fill="none"
            stroke="currentColor"
            stroke-width="1.5"
            role="img"
            :aria-label="
              gatePassed ? 'Questions before this are locked' : 'Locks when you continue'
            "
          >
            <rect
              x="3"
              y="7"
              width="10"
              height="7"
              rx="1"
              :fill="gatePassed ? 'currentColor' : 'none'"
            />
            <path :d="gatePassed ? 'M5 7V5a3 3 0 0 1 6 0v2' : 'M5 7V5a3 3 0 0 1 5.6-1.5'" />
          </svg>
        </li>
      </template>
    </ol>
  </nav>
</template>
