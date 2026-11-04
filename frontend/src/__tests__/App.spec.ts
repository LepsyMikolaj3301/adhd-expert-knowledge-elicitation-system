import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import App from '../App.vue'
import router from '../router'
import { jsonResponse, stubFetch } from './helpers'

describe('App', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('renders the home view and reports backend health', async () => {
    const fetchMock = stubFetch((url) =>
      url.endsWith('/me')
        ? jsonResponse(401, { code: 'not_authenticated', message: 'Please log in.' })
        : jsonResponse(200, { status: 'ok' }),
    )

    await router.push('/')
    await router.isReady()
    const wrapper = mount(App, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('ADHD Expert Knowledge Elicitation')
    expect(wrapper.get('[data-testid="backend-status"]').text()).toBe('ok')
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/health')
  })
})
