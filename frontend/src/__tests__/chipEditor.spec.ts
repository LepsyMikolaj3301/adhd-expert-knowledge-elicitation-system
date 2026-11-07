import { beforeAll, describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

import ChipEditor from '@/components/answering/ChipEditor.vue'

// jsdom has no layout, and focusing an editor scrolls the cursor into view.
beforeAll(() => {
  const noRects = () => [] as unknown as DOMRectList
  Range.prototype.getClientRects = noRects
  Element.prototype.getClientRects = noRects
  Range.prototype.getBoundingClientRect = () => new DOMRect()
})

function mountEditor(modelValue: string) {
  return mount(ChipEditor, {
    props: { modelValue, label: 'Answer' },
    attachTo: document.body,
  })
}

describe('ChipEditor', () => {
  it('opens an answer without changing it', async () => {
    const wrapper = mountEditor('see ⟦h2⟧\nnext line')
    await flushPromises()
    expect(wrapper.get('[data-chip="2"]').text()).toBe('2')
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    wrapper.unmount()
  })

  it('inserts a chip at the cursor as one unit, followed by a space', async () => {
    const wrapper = mountEditor('see')
    await flushPromises()
    ;(wrapper.vm as unknown as { insertChip(n: number): void }).insertChip(3)
    await flushPromises()
    expect(wrapper.emitted('update:modelValue')?.slice(-1)[0]).toEqual(['see⟦h3⟧ '])
    wrapper.unmount()
  })

  it('follows a new value from outside, such as a renumbering', async () => {
    const wrapper = mountEditor('⟦h2⟧ old')
    await flushPromises()
    await wrapper.setProps({ modelValue: '⟦h1⟧ old' })
    await flushPromises()
    expect(wrapper.find('[data-chip="2"]').exists()).toBe(false)
    expect(wrapper.get('[data-chip="1"]').text()).toBe('1')
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    wrapper.unmount()
  })

  it('does not bring back old numbers when undo is pressed after a renumbering', async () => {
    const wrapper = mountEditor('⟦h3⟧ old')
    await flushPromises()
    await wrapper.setProps({ modelValue: '⟦h2⟧ old' })
    await flushPromises()

    await wrapper.get('.ProseMirror').trigger('keydown', { key: 'z', ctrlKey: true })
    await flushPromises()

    const emitted = (wrapper.emitted('update:modelValue') ?? []).map((e) => e[0])
    expect(emitted).not.toContain('⟦h3⟧ old')
    expect(wrapper.find('[data-chip="3"]').exists()).toBe(false)
    expect(wrapper.get('[data-chip="2"]').text()).toBe('2')
    wrapper.unmount()
  })

  it('still undoes what the expert typed', async () => {
    const wrapper = mountEditor('see')
    await flushPromises()
    ;(wrapper.vm as unknown as { insertChip(n: number): void }).insertChip(3)
    await flushPromises()
    await wrapper.get('.ProseMirror').trigger('keydown', { key: 'z', ctrlKey: true })
    await flushPromises()
    expect(wrapper.emitted('update:modelValue')?.slice(-1)[0]).toEqual(['see'])
    wrapper.unmount()
  })

  describe('lists', () => {
    const lastValue = (wrapper: ReturnType<typeof mountEditor>) =>
      wrapper.emitted('update:modelValue')?.slice(-1)[0]?.[0]

    async function pressEnterAtEnd(wrapper: ReturnType<typeof mountEditor>) {
      ;(wrapper.vm as unknown as { focusEnd(): void }).focusEnd()
      await flushPromises()
      await wrapper.get('.ProseMirror').trigger('keydown', { key: 'Enter' })
      await flushPromises()
    }

    it('indents lines that start a list, and no others', async () => {
      const wrapper = mountEditor('1. first\nplain\n- dash\n1.5 hours')
      await flushPromises()
      const lines = wrapper.findAll('.ProseMirror p')
      expect(lines.map((l) => l.classes().includes('list-line'))).toEqual([
        true,
        false,
        true,
        false,
      ])
      expect(wrapper.emitted('update:modelValue')).toBeUndefined()
      wrapper.unmount()
    })

    it('continues the numbering on Enter, in the stored text too', async () => {
      const wrapper = mountEditor('1. first')
      await flushPromises()
      await pressEnterAtEnd(wrapper)
      expect(lastValue(wrapper)).toBe('1. first\n2. ')
      wrapper.unmount()
    })

    it('continues a dash on Enter', async () => {
      const wrapper = mountEditor('- first')
      await flushPromises()
      await pressEnterAtEnd(wrapper)
      expect(lastValue(wrapper)).toBe('- first\n- ')
      wrapper.unmount()
    })

    it('ends the list on Enter at an empty item', async () => {
      const wrapper = mountEditor('1. first\n2. ')
      await flushPromises()
      await pressEnterAtEnd(wrapper)
      expect(lastValue(wrapper)).toBe('1. first\n')
      wrapper.unmount()
    })

    it('leaves Enter alone outside a list', async () => {
      const wrapper = mountEditor('plain')
      await flushPromises()
      await pressEnterAtEnd(wrapper)
      expect(lastValue(wrapper)).toBe('plain\n')
      wrapper.unmount()
    })
  })

  it('tells which chip the pointer is on', async () => {
    const wrapper = mountEditor('see ⟦h2⟧ here')
    await flushPromises()
    await wrapper.get('[data-chip="2"]').trigger('mouseover')
    expect(wrapper.emitted('active')?.slice(-1)[0]).toEqual([2])
    await wrapper.get('[data-chip="2"]').trigger('mouseout')
    expect(wrapper.emitted('active')?.slice(-1)[0]).toEqual([null])
    wrapper.unmount()
  })
})
