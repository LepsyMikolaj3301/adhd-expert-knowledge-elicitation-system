import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import type { User } from '@/api/client'
import App from '@/App.vue'
import router from '@/router'
import { useAuthStore } from '@/stores/auth'

import { TRUST_SENTENCE } from '@/copy'

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

beforeEach(() => {
  setActivePinia(createPinia())
  stubFetch((url) => jsonResponse(200, url.endsWith('/assignments') ? [] : {}))
})
afterEach(() => wrapper?.unmount())

describe('side panel', () => {
  it('gives an admin the three sections that collect answers', async () => {
    const w = await open(admin, '/vignettes')
    expect(navLinks(w).map((a) => a.text())).toEqual(['Vignettes', 'Assignments', 'Experts'])
  })

  it("gives an expert one, and opens the expert's own assignments as My cases", async () => {
    const w = await open(expert, '/assignments')
    const links = navLinks(w)
    expect(links.map((a) => a.text())).toEqual(['My cases'])
    expect(links[0]!.attributes('href')).toBe('/assignments')
  })

  it('marks the section you are in', async () => {
    const w = await open(expert, '/assignments')
    const current = navLinks(w)
      .filter((a) => a.attributes('aria-current') === 'page')
      .map((a) => a.text())
    expect(current).toEqual(['My cases'])
  })

  it('shows who is logged in, linked to the account page', async () => {
    const w = await open(expert, '/assignments')
    const account = w.get('[data-testid="account-link"]')
    expect(account.text()).toContain(expert.display_name)
    expect(account.text()).toContain('expert')
    expect(account.attributes('href')).toBe('/account')
    expect(account.find('svg[aria-hidden="true"]').exists()).toBe(true)
  })

  it('does not ask for the home counts: this build has no reviews to count', async () => {
    const fetchMock = stubFetch((url) => jsonResponse(200, url.endsWith('/assignments') ? [] : {}))
    await open(expert, '/assignments')
    const urls = fetchMock.mock.calls.map(([input]) => String((input as Request).url))
    expect(urls.some((u) => u.endsWith('/me/home'))).toBe(false)
  })
})

describe('sections', () => {
  it('leaves the site name and the root address leading to the expert cases', async () => {
    const w = await open(expert, '/')
    expect(router.currentRoute.value.name).toBe('assignments')
    expect(w.get('h1').text()).toBe('My cases')
  })

  it('sends an expert home from an admin-only section', async () => {
    await open(expert, '/vignettes')
    // Home is the list of cases in this build.
    expect(router.currentRoute.value.name).toBe('assignments')
  })

  it.each(['/reviews', '/reviews/some-id', '/knowledge'])(
    'has no page at %s: the review and knowledge sections are not in this build',
    async (path) => {
      const w = await open(admin, path)
      expect(router.currentRoute.value.name).toBe('not-found')
      expect(w.get('h1').text()).toBe("We can't find that page.")
    },
  )
})

describe('a page that does not exist', () => {
  it('says so, and leads home', async () => {
    const w = await open(expert, '/no/such/page')
    expect(w.get('h1').text()).toBe("We can't find that page.")
    const home = w.get('[data-testid="not-found-home"]')
    expect(home.text()).toBe('Go to Home')
    expect(home.attributes('href')).toBe('/')
  })
})

describe('account page', () => {
  it('says what happens with the answers, and under which pseudonym they are kept', async () => {
    const w = await open(expert, '/account')
    expect(w.get('[data-testid="trust"]').text()).toBe(TRUST_SENTENCE)
    expect(w.text()).toContain('Your answers are stored under this pseudonym.')
  })

  it('signs out and goes to the login page', async () => {
    const fetchMock = stubFetch((url) =>
      url.endsWith('/auth/logout') ? new Response(null, { status: 204 }) : jsonResponse(200, {}),
    )
    const w = await open(expert, '/account')
    expect(w.text()).toContain(expert.email)

    await w.get('button').trigger('click')
    await flushPromises()

    const urls = fetchMock.mock.calls.map(([input]) => String((input as Request).url))
    expect(urls).toEqual([expect.stringMatching(/\/api\/v1\/auth\/logout$/)])
    expect(useAuthStore().user).toBeNull()
    // The login page is a lazy chunk, so the navigation can take longer than flushPromises.
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe('login'))
  })

  it('says so when signing out fails, and stays signed in', async () => {
    stubFetch(() => jsonResponse(500, { code: 'internal', message: 'Could not log out.' }))
    const w = await open(expert, '/account')

    await w.get('button').trigger('click')
    await flushPromises()

    expect(w.get('[role="alert"]').text()).toBe('Could not log out.')
    expect(useAuthStore().user).not.toBeNull()
    expect(router.currentRoute.value.name).toBe('account')
  })
})
