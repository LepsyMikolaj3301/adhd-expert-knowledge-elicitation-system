import { beforeAll, describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

import ChipEditor from '@/components/answering/ChipEditor.vue'

// jsdom has no layout, and focusing an editor scrolls the cursor into view.
beforeAll(() => {
  const noRects = () => [] as unknown as DOMRectList
  Range.prototype.getClientRects = noRects
  Element.prototype.getClientRects = noRects
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
