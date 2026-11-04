import { describe, it, expect, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'

import App from '../App.vue'
import router from '../router'

describe('App', () => {
  it('renders the home view and reports backend health', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }))

    await router.push('/')
    await router.isReady()
    const wrapper = mount(App, { global: { plugins: [createPinia(), router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('ADHD Expert Knowledge Elicitation')
    expect(wrapper.get('[data-testid="backend-status"]').text()).toBe('ok')
    expect(fetch).toHaveBeenCalledWith('/api/v1/health')
  })
})
