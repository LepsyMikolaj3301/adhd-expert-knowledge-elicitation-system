import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

import CaseCard from '@/components/CaseCard.vue'
import PseudonymChip from '@/components/PseudonymChip.vue'

import { jsonResponse, stubFetch } from './helpers'

afterEach(() => vi.unstubAllGlobals())

describe('CaseCard', () => {
  const props = {
    code: 'V001',
    version: 2,
    patientSummary: 'A student before an exam.',
    framing: 'email',
    wordCount: 130,
    opening: 'I could not sleep…',
  }

  it('shows the summary and the opening of the text only after a click', async () => {
    const wrapper = mount(CaseCard, { props })
    expect(wrapper.text()).toBe('Case V001 v2')
    expect(wrapper.find('[data-testid="case-summary"]').exists()).toBe(false)

    await wrapper.trigger('mouseenter')
    expect(wrapper.find('[data-testid="case-summary"]').exists()).toBe(false)

    await wrapper.get('[data-testid="case-trigger"]').trigger('click')
    expect(wrapper.get('[data-testid="case-summary"]').text()).toBe('A student before an exam.')
    expect(wrapper.get('[data-testid="case-opening"]').text()).toBe('I could not sleep…')
    expect(wrapper.text()).toContain('Email | 130 words')

    await wrapper.get('[data-testid="case-trigger"]').trigger('click')
    expect(wrapper.find('[data-testid="case-summary"]').exists()).toBe(false)
  })

  it('closes on Escape and on a click outside', async () => {
    const wrapper = mount(CaseCard, { props, attachTo: document.body })
    const trigger = wrapper.get('[data-testid="case-trigger"]')
    await trigger.trigger('click')
    expect(wrapper.find('[data-testid="case-summary"]').exists()).toBe(true)

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()
    expect(wrapper.find('[data-testid="case-summary"]').exists()).toBe(false)

    await trigger.trigger('click')
    document.body.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
    await flushPromises()
    expect(wrapper.find('[data-testid="case-summary"]').exists()).toBe(false)
    wrapper.unmount()
  })
})

describe('PseudonymChip', () => {
  const adminCard = {
    audience: 'admin',
    pseudonym: 'E31',
    role: 'expert',
    display_name: 'Eve Example',
    email: 'eve@example.com',
    is_active: true,
    is_synthetic: false,
    cases: { open: 2, in_review: 1, done: 3, stopped: 0 },
  }

  it('looks the expert up once, on the first click, and shows the admin card', async () => {
    const fetchMock = stubFetch(() => jsonResponse(200, adminCard))
    const wrapper = mount(PseudonymChip, { props: { pseudonym: 'E31' } })
    expect(wrapper.text()).toBe('E31')
    expect(fetchMock).not.toHaveBeenCalled()

    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Eve Example')
    expect(wrapper.text()).toContain('eve@example.com')
    expect(wrapper.text()).toContain('2 open, 1 in review, 3 done, 0 stopped')

    await wrapper.get('button').trigger('click')
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('shows a colleague only the pseudonym, never a name', async () => {
    stubFetch(() => jsonResponse(200, { audience: 'peer', pseudonym: 'E32', role: 'expert' }))
    const wrapper = mount(PseudonymChip, { props: { pseudonym: 'E32' } })
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Expert E32')
    expect(wrapper.text()).not.toContain('@')
  })

  it('says so when the lookup fails', async () => {
    stubFetch(() => jsonResponse(404, { code: 'not_found', message: 'Person not found.' }))
    const wrapper = mount(PseudonymChip, { props: { pseudonym: 'E99' } })
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Could not load this expert.')
  })
})
