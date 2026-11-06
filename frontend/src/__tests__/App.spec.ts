import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import App from '../App.vue'
import router from '../router'
import { SITE_NAME } from '../site'
import { expert, jsonResponse, stubFetch } from './helpers'

describe('App', () => {
  beforeEach(() => setActivePinia(createPinia()))

  // Must stay the first test: the router is shared, and this needs its very first navigation.
  it('still shows the login page when the backend cannot be reached', async () => {
    // What the dev proxy answers while the backend is down: not JSON, not a 401.
    stubFetch(() => new Response('Bad Gateway', { status: 502 }))

    await router.push('/')
    const wrapper = mount(App, { global: { plugins: [router] } })
    await flushPromises()

    expect(router.currentRoute.value.name).toBe('login')
    expect(wrapper.text()).toContain('Sign in')
  })

  it('sends an anonymous visitor to the login page, without the side panel', async () => {
    stubFetch(() => jsonResponse(401, { code: 'not_authenticated', message: 'Please log in.' }))

    await router.push('/')
    const wrapper = mount(App, { global: { plugins: [router] } })
    await flushPromises()

    expect(router.currentRoute.value.name).toBe('login')
    expect(wrapper.text()).toContain('Sign in')
    expect(wrapper.text()).toContain(SITE_NAME)
    expect(wrapper.find('nav').exists()).toBe(false)
  })

  it('welcomes a logged-in user inside the side panel', async () => {
    stubFetch(() => jsonResponse(200, expert))

    await router.push('/')
    const wrapper = mount(App, { global: { plugins: [router] } })
    await flushPromises()

    expect(router.currentRoute.value.name).toBe('home')
    expect(wrapper.get('[data-testid="site-name"]').text()).toBe(SITE_NAME)
    expect(wrapper.get('h1').text()).toBe(`Welcome, ${expert.display_name}`)
    expect(wrapper.find('nav').exists()).toBe(true)
  })
})
