<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{ text: string }>()

const feedback = ref('')
const details = ref<HTMLDetailsElement>()

/** If the browser won't copy, the text is right there to select by hand. */
async function copy() {
  try {
    await navigator.clipboard.writeText(props.text)
    feedback.value = 'Copied.'
  } catch {
    feedback.value = "Couldn't copy automatically. Select the text below and copy it yourself."
    if (details.value) details.value.open = true
  }
}
</script>

<template>
  <div>
    <button type="button" class="btn-quiet" @click="copy">Copy my text</button>
    <span v-if="feedback" class="ml-3 text-sm" role="status">{{ feedback }}</span>
    <details ref="details" class="mt-2">
      <summary class="cursor-pointer text-sm">Show my unsaved text</summary>
      <textarea
        readonly
        :value="text"
        aria-label="Your unsaved text"
        class="field mt-2 min-h-32 font-sans"
      />
    </details>
  </div>
</template>
