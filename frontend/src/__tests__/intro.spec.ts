import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { INTRO } from '@/copy'
import { acknowledgeIntro, introNeeded } from '@/intro'
import router from '@/router'
import { useAuthStore } from '@/stores/auth'
import IntroView from '@/views/IntroView.vue'

import { expert } from './helpers'

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  setActivePinia(createPinia())
  const auth = useAuthStore()
  auth.user = expert
  auth.loaded = true
})

afterEach(() => vi.restoreAllMocks())

async function show(next?: string) {
  await router.push({ name: 'instructions', query: next ? { next } : {} })
  await router.isReady()
  return mount(IntroView, { global: { plugins: [router] } })
}

describe('the instruction page', () => {
  it('explains the two stages and the lock-in', async () => {
    const page = await show()
    const structure = page.get('[data-testid="intro-structure"]').text()
    expect(structure).toContain('Stage 1')
    expect(structure).toContain('Stage 2')
    expect(structure).toContain("can't change your answers to Q1 to Q3")
    expect(page.get('[data-testid="intro-flow"]').text()).toContain('Lock in')
  })

  it('lists what is wanted and the four directions', async () => {
    const text = (await show()).text()
    for (const item of INTRO.aim.items) expect(text).toContain(item.term)
    for (const d of ['Points toward ADHD traits', 'No bearing', 'Unclear']) {
      expect(text).toContain(d)
    }
  })

  it('goes on to the case it was on the way to', async () => {
    const page = await show('/assignments/a1')
    await page.get('[data-testid="intro-continue"]').trigger('click')
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/assignments/a1'))
  })

  it('goes to My cases when opened from the link, and never to another site', async () => {
    const page = await show()
    await page.get('[data-testid="intro-continue"]').trigger('click')
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/assignments'))

    const other = await show('//evil.example')
    await other.get('[data-testid="intro-continue"]').trigger('click')
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/'))
  })

  it('is shown again next session unless "don\'t show again" is ticked', async () => {
    const page = await show()
    await page.get('[data-testid="intro-continue"]').trigger('click')
    await flushPromises()
    expect(introNeeded(expert.id)).toBe(false)
    sessionStorage.clear()
    expect(introNeeded(expert.id)).toBe(true)
  })

  it('is never shown again once "don\'t show again" is ticked', async () => {
    const page = await show()
    await page.get('[data-testid="intro-hide"]').setValue(true)
    await page.get('[data-testid="intro-continue"]').trigger('click')
    await flushPromises()
    sessionStorage.clear()
    expect(introNeeded(expert.id)).toBe(false)
  })
})

describe('when the browser refuses storage', () => {
  it('shows the page every time and does not crash', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(() => acknowledgeIntro(expert.id, true)).not.toThrow()
    expect(introNeeded(expert.id)).toBe(true)
  })
})
