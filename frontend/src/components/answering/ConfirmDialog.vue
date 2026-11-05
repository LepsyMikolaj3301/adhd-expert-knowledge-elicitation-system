<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

defineProps<{ title: string; confirmLabel: string; cancelLabel: string }>()
const emit = defineEmits<{ confirm: []; cancel: [] }>()

const dialog = ref<HTMLDialogElement>()

onMounted(() => dialog.value?.showModal())
// Closing it properly is what returns the focus to the button that opened it.
onBeforeUnmount(() => dialog.value?.close())
</script>

<template>
  <dialog
    ref="dialog"
    class="m-auto w-[min(32rem,calc(100vw-2rem))] rounded-sm border border-line bg-surface p-6 text-text backdrop:bg-ink/40"
    aria-labelledby="confirm-title"
    @cancel.prevent="emit('cancel')"
  >
    <h2 id="confirm-title">{{ title }}</h2>
    <div class="mt-3 space-y-2 text-sm">
      <slot />
    </div>
    <div class="mt-6 flex justify-end gap-3">
      <button type="button" class="btn-quiet" @click="emit('cancel')">{{ cancelLabel }}</button>
      <button type="button" class="btn" @click="emit('confirm')">{{ confirmLabel }}</button>
    </div>
  </dialog>
</template>
