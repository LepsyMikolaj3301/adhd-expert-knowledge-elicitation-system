import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { PRIVACY } from '@/copy'
import { privacyNeeded } from '@/privacy'
import router from '@/router'
import { useAuthStore } from '@/stores/auth'
import PrivacyView from '@/views/PrivacyView.vue'

import { admin, expert, jsonResponse, serve, writes } from './helpers'

/** An expert who has not confirmed the notice yet. */
const fresh = { ...expert, privacy_version: null, privacy_accepted_at: null }

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  setActivePinia(createPinia())
  const auth = useAuthStore()
  auth.user = fresh
  auth.loaded = true
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

async function show(next?: string) {
  await router.push({ name: 'privacy', query: next ? { next } : {} })
  await router.isReady()
  return mount(PrivacyView, { global: { plugins: [router] } })
}

/** The server records the confirmation and answers with the user as it now is. */
function serveConfirmation() {
  return serve({
    'POST /api/v1/me/privacy': async (request) => {
      const { version } = await request.json()
      return jsonResponse(200, {
        ...fresh,
        privacy_version: version,
        privacy_accepted_at: '2026-11-23T10:00:00Z',
      })
    },
  })
}

describe('the privacy notice', () => {
  it('covers what GDPR Art. 13 asks to be told', async () => {
    const text = (await show()).text()
    for (const words of [
      'Data controller',
      'Data protection officer',
      'What we collect',
      'legal basis',
      'Who sees your data',
      'How long we keep it',
      'Your rights',
      'complain',
      'pseudonym',
    ]) {
      expect(text).toContain(words)
    }
  })

  it('records "I understand" on the server, then goes on to the case it was on the way to', async () => {
    const mock = serveConfirmation()
    const page = await show('/assignments/a1')
    await page.get('[data-testid="privacy-understand"]').trigger('click')
    await flushPromises()
    expect(writes(mock)).toEqual(['POST /api/v1/me/privacy'])
    const auth = useAuthStore()
    expect(auth.user?.privacy_version).toBe(PRIVACY.version)
    expect(privacyNeeded(auth.user!)).toBe(false)
    // The guard sends it on to the instructions, which have not been read yet.
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe('instructions'))
    expect(router.currentRoute.value.query.next).toBe('/assignments/a1')
  })

  it('stays on the page when opened from home, and says it was confirmed', async () => {
    serveConfirmation()
    const page = await show()
    await page.get('[data-testid="privacy-understand"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('privacy')
    expect(page.get('[data-testid="privacy-done"]').text()).toBe(PRIVACY.confirmed)
  })

  it('says so and stays when the server does not record it', async () => {
    serve({
      'POST /api/v1/me/privacy': jsonResponse(500, { code: 'internal_error', message: 'x' }),
    })
    const page = await show('/assignments/a1')
    await page.get('[data-testid="privacy-understand"]').trigger('click')
    await flushPromises()
    expect(page.find('[role="alert"]').exists()).toBe(true)
    expect(router.currentRoute.value.name).toBe('privacy')
    expect(privacyNeeded(useAuthStore().user!)).toBe(true)
  })

  it('shows it as already confirmed for an expert who has', async () => {
    useAuthStore().user = expert
    const page = await show()
    expect(page.find('[data-testid="privacy-understand"]').exists()).toBe(false)
    expect(page.find('[data-testid="privacy-done"]').exists()).toBe(true)
  })

  it('asks nothing of an admin', async () => {
    useAuthStore().user = admin
    const page = await show()
    expect(page.find('[data-testid="privacy-understand"]').exists()).toBe(false)
  })
})
