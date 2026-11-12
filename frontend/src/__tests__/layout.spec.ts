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
  stubFetch((url) =>
    jsonResponse(
      200,
      url.endsWith('/me/home')
        ? {
            next_up: [],
            next_up_total: 0,
            reviews_waiting: [],
            reviews_waiting_total: 0,
            recent_reviews: [],
            activity: [],
            unread_activity: 0,
          }
        : url.endsWith('/assignments') ||
            url.includes('/reviews') ||
            url.includes('/knowledge-units')
          ? []
          : {},
    ),
  )
})
afterEach(() => wrapper?.unmount())

describe('side panel', () => {
  it('gives an admin all six sections, including the ones not built yet', async () => {
    const w = await open(admin, '/')
    expect(navLinks(w).map((a) => a.text())).toEqual([
      'Home',
      'All cases',
      'Reviews',
      'Assignments',
      'Experts',
      'Knowledge base',
    ])
  })

  it("gives an expert three, and opens the expert's own assignments as My cases", async () => {
    const w = await open(expert, '/')
    const links = navLinks(w)
    expect(links.map((a) => a.text())).toEqual(['Home', 'My cases', 'Reviews'])
    expect(links[1]!.attributes('href')).toBe('/assignments')
    expect(links[2]!.attributes('href')).toBe('/reviews')
  })

  it('marks Reviews as the section you are in on the reviews page', async () => {
    const w = await open(expert, '/reviews')
    const current = navLinks(w)
      .filter((a) => a.attributes('aria-current') === 'page')
      .map((a) => a.text())
    expect(current).toEqual(['Reviews'])
  })

  it('marks the section you are in', async () => {
    const w = await open(expert, '/assignments')
    const current = navLinks(w)
      .filter((a) => a.attributes('aria-current') === 'page')
      .map((a) => a.text())
    expect(current).toEqual(['My cases'])
  })

  it('shows who is logged in, linked to the account page', async () => {
    const w = await open(expert, '/')
    const account = w.get('[data-testid="account-link"]')
    expect(account.text()).toContain(expert.display_name)
    expect(account.text()).toContain('expert')
    expect(account.attributes('href')).toBe('/account')
    expect(account.find('svg[aria-hidden="true"]').exists()).toBe(true)
  })
})

describe('side panel highlight', () => {
  it('anchors the pill on the current section only, and moves the anchor when it changes', async () => {
    const w = await open(expert, '/')
    const anchored = () =>
      navLinks(w)
        .filter((a) => a.classes().some((c) => c.includes('anchor-name')))
        .map((a) => a.text())
    expect(w.find('[data-testid="nav-highlight"]').exists()).toBe(true)
    expect(anchored()).toEqual(['Home'])

    await router.push('/reviews')
    await flushPromises()
    expect(anchored()).toEqual(['Reviews'])
  })
})

describe('sections', () => {
  it('opens the knowledge base on its list of units, with the test search a click away', async () => {
    const w = await open(admin, '/knowledge')
    expect(w.get('h1').text()).toBe('Knowledge base')
    expect(w.find('[data-testid="empty"]').exists()).toBe(true)
    expect(w.findAll('button').map((b) => b.text())).toEqual(['Units', 'Test search'])
  })

  it('sends an expert home from an admin-only section', async () => {
    await open(expert, '/vignettes')
    expect(router.currentRoute.value.name).toBe('home')
  })

  it('gives an expert a card for My cases and one for Reviews on the home page', async () => {
    const w = await open(expert, '/')
    const cards = w.get('[data-testid="sections"]').findAll('article')
    expect(cards.map((c) => c.get('h2').text())).toEqual(['My cases', 'Reviews'])
    expect(cards[0]!.text()).toContain('clinical vignette')
    expect(cards[1]!.text()).toContain('colleagues')
    expect(cards[0]!.get('a.btn').attributes('href')).toBe('/assignments')
    expect(cards[1]!.get('a.btn').attributes('href')).toBe('/reviews')
  })

  it('gives an admin a card for every section, each with its blurb in sight', async () => {
    const w = await open(admin, '/')
    const cards = w.get('[data-testid="sections"]').findAll('article')
    expect(cards.map((c) => c.get('h2').text())).toEqual([
      'Assignments',
      'Reviews',
      'All cases',
      'Experts',
      'Knowledge base',
    ])
    expect(cards[4]!.text()).toContain('Browse the ingested knowledge units')
    expect(cards[4]!.get('a.btn').attributes('href')).toBe('/knowledge')
  })

  it('explains the app on the home page, with Learn more leading to its own page', async () => {
    const w = await open(expert, '/')
    const about = w.get('[data-testid="about"]')
    expect(about.get('h2').text()).toBe('What is PsyKnowHow?')
    expect(about.text()).toContain('written expert interview')
    expect(w.find('details').exists()).toBe(false)
    expect(about.get('a[data-testid="learn-more"]').attributes('href')).toBe('/about')
  })

  it('opens the About page from Learn more, with the cases and reviews explained to an expert', async () => {
    const w = await open(expert, '/')
    await w.get('a[data-testid="learn-more"]').trigger('click')
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/about'))
    await flushPromises()
    expect(w.get('h1').text()).toBe('What is PsyKnowHow?')
    expect(w.get('[data-testid="about-flow"]').text()).toContain('Proofread')
    const chips = w
      .get('[data-testid="about-contents"]')
      .findAll('a')
      .map((a) => a.text())
    expect(chips).toEqual([
      'Why written cases',
      'How a case goes',
      'My cases',
      'Reviews',
      'What happens to answers',
    ])
    expect(w.get('#my-cases').text()).toContain('Ready to check')
    expect(w.get('#reviews').text()).toContain('Votes are advice')
    expect(w.find('a[href="/instructions"]').exists()).toBe(true)
  })

  it('words the About page for the study team, without the expert sections', async () => {
    const w = await open(admin, '/about')
    expect(w.text()).toContain('you decide which answers enter the knowledge base')
    expect(w.find('#my-cases').exists()).toBe(false)
    expect(w.find('#reviews').exists()).toBe(false)
    expect(w.get('#review').text()).toContain('Votes are advice')
  })

  it('shows a top panel on the home page that folds to a bar when the page is scrolled', async () => {
    const w = await open(expert, '/')
    const banner = w.get('[data-testid="banner"]')
    expect(banner.get('h1').text()).toBe('PsyKnowHow')
    expect(banner.attributes('data-folded')).toBe('false')
    // The same flat colour as the side panel, not a tint of it.
    expect(banner.classes()).toContain('bg-ink')
    expect(banner.findAll('div[aria-hidden="true"]:not(.h-px)')).toHaveLength(0)
    for (const y of [60, 500]) {
      Object.defineProperty(window, 'scrollY', { value: y, configurable: true })
      window.dispatchEvent(new Event('scroll'))
      await flushPromises()
    }
    expect(banner.attributes('data-folded')).toBe('true')
    expect(banner.attributes('style')).toContain('--p: 1')
    Object.defineProperty(window, 'scrollY', { value: 0, configurable: true })
  })

  it('says on the home page what happens with the answers, to an expert', async () => {
    const w = await open(expert, '/')
    expect(w.get('[data-testid="trust"]').text()).toBe(TRUST_SENTENCE)
  })

  it('does not tell an admin that their answers are kept', async () => {
    const w = await open(admin, '/')
    expect(w.find('[data-testid="trust"]').exists()).toBe(false)
  })

  it('opens the Reviews page for an expert, with a reminder of what it is for', async () => {
    const w = await open(expert, '/reviews')
    expect(w.get('h1').text()).toBe('Reviews')
    const intro = w.get('[data-testid="page-intro"]')
    expect(intro.text()).toContain('Approve or disapprove each answer')
    expect(intro.get('a[data-testid="learn-more"]').attributes('href')).toBe('/about#reviews')
  })

  it('gives the study team a shorter Reviews reminder, with nothing to expand', async () => {
    const w = await open(admin, '/reviews')
    const intro = w.get('[data-testid="page-intro"]')
    expect(intro.text()).toContain('then decide')
    expect(intro.find('a[data-testid="learn-more"]').exists()).toBe(false)
  })

  it('reminds an expert on My cases what a case is, with Learn more as the only way on', async () => {
    const w = await open(expert, '/assignments')
    const intro = w.get('[data-testid="page-intro"]')
    expect(intro.text()).toContain('like a clinical vignette')
    expect(intro.get('a[data-testid="learn-more"]').attributes('href')).toBe('/about#my-cases')
    expect(w.find('[data-testid="instructions-link"]').exists()).toBe(false)
  })

  it('gives the study team no expert explanation on Assignments', async () => {
    const w = await open(admin, '/assignments')
    const intro = w.get('[data-testid="page-intro"]')
    expect(intro.text()).toContain('Give cases to experts')
    expect(intro.find('a[data-testid="learn-more"]').exists()).toBe(false)
    expect(w.find('[data-testid="instructions-link"]').exists()).toBe(false)
  })
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
    // The side panel also asks for the counts on its badges.
    expect(urls.filter((u) => !u.endsWith('/me/home'))).toEqual([
      expect.stringMatching(/\/api\/v1\/auth\/logout$/),
    ])
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
