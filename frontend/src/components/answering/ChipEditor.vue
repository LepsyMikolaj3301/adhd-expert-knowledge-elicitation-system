<script setup lang="ts">
import { mergeAttributes, Node } from '@tiptap/core'
import Document from '@tiptap/extension-document'
import Paragraph from '@tiptap/extension-paragraph'
import Text from '@tiptap/extension-text'
import { UndoRedo } from '@tiptap/extensions'
import { EditorContent, useEditor } from '@tiptap/vue-3'
import { watch } from 'vue'

import { docToText, textToDoc } from '@/answering/chipDoc'
import { inkFor } from '@/answering/highlights'

const props = defineProps<{ modelValue: string; label: string }>()
const emit = defineEmits<{
  'update:modelValue': [value: string]
  active: [chip: number | null]
}>()

/** A citation inside an answer: one unit that the cursor steps over and backspace removes whole. */
const Chip = Node.create({
  name: 'chip',
  group: 'inline',
  inline: true,
  atom: true,
  selectable: false,
  addAttributes() {
    return {
      n: {
        default: 1,
        parseHTML: (element) => Number(element.getAttribute('data-chip')),
        renderHTML: (attributes) => ({
          'data-chip': attributes.n,
          style: `--ink: ${inkFor(attributes.n)}`,
          'aria-label': `citation ${attributes.n}`,
        }),
      },
    }
  },
  parseHTML: () => [{ tag: 'span[data-chip]' }],
  renderHTML({ node, HTMLAttributes }) {
    return ['span', mergeAttributes(HTMLAttributes, { class: 'chip' }), String(node.attrs.n)]
  },
  renderText: ({ node }) => `⟦h${node.attrs.n}⟧`,
})

let hasBeenFocused = false

const editor = useEditor({
  content: textToDoc(props.modelValue),
  extensions: [Document, Paragraph, Text, Chip, UndoRedo],
  editorProps: {
    attributes: {
      class: 'chip-editor',
      role: 'textbox',
      'aria-multiline': 'true',
      'aria-label': props.label,
    },
  },
  onFocus: () => {
    hasBeenFocused = true
  },
  onUpdate: ({ editor: current }) => emit('update:modelValue', docToText(current.getJSON())),
})

// Only changes from outside get here with a different text, such as a renumbering after a removal.
watch(
  () => props.modelValue,
  (value) => {
    const current = editor.value
    if (current && value !== docToText(current.getJSON())) {
      // Not an edit by the expert, so Ctrl+Z must not go back to it: the old numbers would point at
      // different passages.
      current
        .chain()
        .setMeta('addToHistory', false)
        .setContent(textToDoc(value), { emitUpdate: false })
        .run()
    }
  },
)

function insertChip(n: number) {
  const current = editor.value
  if (!current) return
  // Citing before ever clicking into the answer continues it, instead of starting it.
  const position = hasBeenFocused ? undefined : 'end'
  if (!hasBeenFocused) current.commands.focus('end')
  const next = current.state.selection.$to.nodeAfter?.text ?? ''
  current
    .chain()
    .focus(position)
    .insertContent(
      /^\s/.test(next)
        ? [{ type: 'chip', attrs: { n } }]
        : [
            { type: 'chip', attrs: { n } },
            { type: 'text', text: ' ' },
          ],
    )
    .run()
}

function chipUnder(event: Event): number | null {
  const chip = (event.target as HTMLElement).closest?.('[data-chip]')
  return chip ? Number(chip.getAttribute('data-chip')) : null
}

function onOver(event: Event) {
  const chip = chipUnder(event)
  if (chip !== null) emit('active', chip)
}

function onOut(event: Event) {
  if (chipUnder(event) !== null) emit('active', null)
}

defineExpose({ insertChip })
</script>

<template>
  <div @mouseover="onOver" @mouseout="onOut">
    <EditorContent v-if="editor" :editor="editor" />
  </div>
</template>
