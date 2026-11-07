<script setup lang="ts">
import { Extension, mergeAttributes, Node } from '@tiptap/core'
import Document from '@tiptap/extension-document'
import Paragraph from '@tiptap/extension-paragraph'
import Text from '@tiptap/extension-text'
import { UndoRedo } from '@tiptap/extensions'
import type { Node as ProseMirrorNode } from '@tiptap/pm/model'
import { Plugin } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'
import { EditorContent, useEditor } from '@tiptap/vue-3'
import { watch } from 'vue'

import { docToText, textToDoc } from '@/answering/chipDoc'
import { inkFor } from '@/answering/highlights'
import { listMarker, nextMarker } from '@/answering/listLines'

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
          'aria-label': `reference ${attributes.n}`,
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

/** The list marker of a line. A chip stands in as a character, so "⟦h1⟧ 1. " is not a list item. */
function markerOf(paragraph: ProseMirrorNode): string | null {
  return listMarker(paragraph.textBetween(0, paragraph.content.size, undefined, '￼'))
}

/**
 * Indents list items and carries them on with Enter. This only adds a class and types the next
 * marker, so the text that is stored is what a person could have typed.
 */
const ListLines = Extension.create({
  name: 'listLines',
  // Ahead of the editor's own Enter, which would otherwise split the line first.
  priority: 1000,
  addProseMirrorPlugins() {
    return [
      new Plugin({
        props: {
          decorations(state) {
            const lines: Decoration[] = []
            state.doc.forEach((paragraph, offset) => {
              if (markerOf(paragraph)) {
                lines.push(
                  Decoration.node(offset, offset + paragraph.nodeSize, { class: 'list-line' }),
                )
              }
            })
            return DecorationSet.create(state.doc, lines)
          },
        },
      }),
    ]
  },
  addKeyboardShortcuts() {
    return {
      Enter: ({ editor: current }) => {
        const { $from, empty } = current.state.selection
        const marker = markerOf($from.parent)
        if (!empty || !marker || $from.parentOffset < marker.length) return false
        // Enter on an empty item ends the list: the marker goes, and the line stays.
        if ($from.parent.content.size === marker.length) {
          return current.commands.deleteRange({ from: $from.start(), to: $from.end() })
        }
        return current
          .chain()
          .splitBlock()
          .insertContent({ type: 'text', text: nextMarker(marker) })
          .run()
      },
    }
  },
})

let hasBeenFocused = false

const editor = useEditor({
  content: textToDoc(props.modelValue),
  extensions: [Document, Paragraph, Text, Chip, UndoRedo, ListLines],
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

function focusEnd() {
  editor.value?.commands.focus('end')
}

defineExpose({ insertChip, focusEnd })
</script>

<template>
  <div @mouseover="onOver" @mouseout="onOut">
    <EditorContent v-if="editor" :editor="editor" />
  </div>
</template>
