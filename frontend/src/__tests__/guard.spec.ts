import { describe, expect, it } from 'vitest'
import type { RouteMeta } from 'vue-router'

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
    expect(guardRoute(to(meta), expert)).toEqual({ name: 'assignments' })
    expect(guardRoute(to(meta), admin)).toBe(true)
  })

  it('skips the login page when already logged in', () => {
    expect(guardRoute(to({ guestOnly: true }), expert)).toEqual({ name: 'assignments' })
    expect(guardRoute(to({ guestOnly: true }), null)).toBe(true)
  })
})

describe('safeNextPath', () => {
  it.each([
    ['/assignments/1', '/assignments/1'],
    ['//evil.example', '/assignments'],
    ['https://evil.example', '/assignments'],
    [undefined, '/assignments'],
    [['/a', '/b'], '/assignments'],
  ])('%s -> %s', (input, expected) => {
    expect(safeNextPath(input)).toBe(expected)
  })
})
