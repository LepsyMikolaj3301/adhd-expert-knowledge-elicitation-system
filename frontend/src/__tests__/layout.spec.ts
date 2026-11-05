import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import type { User } from '@/api/client'
import App from '@/App.vue'
import router from '@/router'
import { useAuthStore } from '@/stores/auth'

import { admin, expert, jsonResponse, stubFetch } from './helpers'

let wrapper: VueWrapper | undefined

/** Logs in without the router's call to /me, then opens the page inside the whole app. */
async function open(user: User, path: string) {
  const auth = useAuthStore()
  auth.user = user
  auth.loaded = true
  await router.push(path)
  wrapper = mount(App, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

const navLinks = (w: VueWrapper) => w.findAll('nav[aria-label="Main"] a')

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => wrapper?.unmount())

describe('side panel', () => {
  it('gives an admin all six sections', async () => {
    const w = await open(admin, '/')
    expect(navLinks(w).map((a) => a.text())).toEqual([
      'Home',
      'Vignettes',
      'Reviews',
      'Assignments',
      'Experts',
      'Knowledge base',
    ])
  })

  it("gives an expert three, and opens the expert's own assignments as Vignettes", async () => {
    const w = await open(expert, '/')
    const links = navLinks(w)
    expect(links.map((a) => a.text())).toEqual(['Home', 'Vignettes', 'Reviews'])
    expect(links[1]!.attributes('href')).toBe('/assignments')
  })

  it('marks the section you are in', async () => {
    const w = await open(expert, '/reviews')
    const current = navLinks(w)
      .filter((a) => a.attributes('aria-current') === 'page')
      .map((a) => a.text())
    expect(current).toEqual(['Reviews'])
  })

  it('shows who is logged in, linked to the account page', async () => {
    const w = await open(expert, '/')
    const account = w.get('[data-testid="account-link"]')
    expect(account.text()).toContain(expert.display_name)
    expect(account.text()).toContain('expert')
    expect(account.attributes('href')).toBe('/account')
  })
})

describe('sections', () => {
  it('shows a placeholder for a section that is not built yet', async () => {
    const w = await open(admin, '/experts')
    expect(w.get('h1').text()).toBe('Experts')
    expect(w.text()).toContain("This section isn't built yet.")
  })

  it('sends an expert home from an admin-only section', async () => {
    await open(expert, '/vignettes')
    expect(router.currentRoute.value.name).toBe('home')
  })

  it('lists the other sections on the home page', async () => {
    const w = await open(expert, '/')
    expect(w.get('[data-testid="sections"]').text()).toContain(
      'Answer the vignettes assigned to you.',
    )
  })
})

describe('account page', () => {
  it('logs out and goes to the login page', async () => {
    const fetchMock = stubFetch((url) =>
      url.endsWith('/auth/logout') ? new Response(null, { status: 204 }) : jsonResponse(200, {}),
    )
    const w = await open(expert, '/account')
    expect(w.text()).toContain(expert.email)

    await w.get('button').trigger('click')
    await flushPromises()

    expect(fetchMock.mock.calls.map(([input]) => String((input as Request).url))).toEqual([
      expect.stringMatching(/\/api\/v1\/auth\/logout$/),
    ])
    expect(useAuthStore().user).toBeNull()
    // The login page is a lazy chunk, so the navigation can take longer than flushPromises.
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe('login'))
  })

  it('says so when logging out fails, and stays logged in', async () => {
    stubFetch(() => jsonResponse(500, { code: 'internal', message: 'Could not log out.' }))
    const w = await open(expert, '/account')

    await w.get('button').trigger('click')
    await flushPromises()

    expect(w.get('[role="alert"]').text()).toBe('Could not log out.')
    expect(useAuthStore().user).not.toBeNull()
    expect(router.currentRoute.value.name).toBe('account')
  })
})
