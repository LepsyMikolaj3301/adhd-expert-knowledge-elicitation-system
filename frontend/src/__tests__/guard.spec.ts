import { beforeEach, describe, expect, it } from 'vitest'
import type { RouteMeta } from 'vue-router'

import { acknowledgeIntro } from '@/intro'
import { guardRoute, safeNextPath } from '@/router/guard'

import { admin, expert } from './helpers'

const to = (meta: RouteMeta, fullPath = '/target') => ({ meta, fullPath })

describe('guardRoute', () => {
  it('sends anonymous users to login and remembers where they were going', () => {
    expect(guardRoute(to({ requiresAuth: true }), null)).toEqual({
      name: 'login',
      query: { next: '/target' },
    })
  })

  it('lets logged-in users through', () => {
    expect(guardRoute(to({ requiresAuth: true }), expert)).toBe(true)
  })

  it('leaves public routes open', () => {
    expect(guardRoute(to({}), null)).toBe(true)
  })

  it('keeps users away from routes of another role', () => {
    const meta: RouteMeta = { requiresAuth: true, roles: ['admin'] }
    expect(guardRoute(to(meta), expert)).toEqual({ name: 'home' })
    expect(guardRoute(to(meta), admin)).toBe(true)
  })

  it('skips the login page when already logged in', () => {
    expect(guardRoute(to({ guestOnly: true }), expert)).toEqual({ name: 'home' })
    expect(guardRoute(to({ guestOnly: true }), null)).toBe(true)
  })
})

describe('the instructions', () => {
  const meta: RouteMeta = { requiresAuth: true, roles: ['expert'], needsIntro: true }

  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
  })

  it('come first, and remember where the expert was going', () => {
    expect(guardRoute(to(meta, '/assignments/a1'), expert)).toEqual({
      name: 'instructions',
      query: { next: '/assignments/a1' },
    })
  })

  it('stop coming once read for good', () => {
    acknowledgeIntro(expert.id, true)
    expect(guardRoute(to(meta), expert)).toBe(true)
    sessionStorage.clear()
    expect(guardRoute(to(meta), expert)).toBe(true)
  })

  it('come back next session when read without "don\'t show again"', () => {
    acknowledgeIntro(expert.id, false)
    expect(guardRoute(to(meta), expert)).toBe(true)
    sessionStorage.clear()
    expect(guardRoute(to(meta), expert)).toEqual({
      name: 'instructions',
      query: { next: '/target' },
    })
  })

  it('are remembered per user', () => {
    acknowledgeIntro('someone-else', true)
    expect(guardRoute(to(meta), expert)).toEqual({
      name: 'instructions',
      query: { next: '/target' },
    })
  })

  it('are not in the way of the routes that do not ask for them', () => {
    expect(guardRoute(to({ requiresAuth: true }), expert)).toBe(true)
  })
})

describe('safeNextPath', () => {
  it.each([
    ['/assignments/1', '/assignments/1'],
    ['//evil.example', '/'],
    ['https://evil.example', '/'],
    [undefined, '/'],
    [['/a', '/b'], '/'],
  ])('%s -> %s', (input, expected) => {
    expect(safeNextPath(input)).toBe(expected)
  })
})

describe('the privacy notice', () => {
  const meta: RouteMeta = { requiresAuth: true, roles: ['expert'], needsIntro: true }

  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
  })

  const fresh = { ...expert, privacy_version: null, privacy_accepted_at: null }

  it('comes before the instructions, and remembers where the expert was going', () => {
    expect(guardRoute(to(meta, '/assignments/a1'), fresh)).toEqual({
      name: 'privacy',
      query: { next: '/assignments/a1' },
    })
    acknowledgeIntro(expert.id, true)
    expect(guardRoute(to(meta), expert)).toBe(true)
  })

  it('is asked again when the notice changes', () => {
    acknowledgeIntro(expert.id, true)
    const older = { ...expert, privacy_version: 'an-older-version' }
    expect(guardRoute(to(meta), older)).toEqual({ name: 'privacy', query: { next: '/target' } })
  })

  it('is not in the way of the routes that do not ask for it', () => {
    expect(guardRoute(to({ requiresAuth: true }), expert)).toBe(true)
  })
})
