import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import router from '@/router'
import { acknowledgeIntro } from '@/intro'
import { useAuthStore } from '@/stores/auth'
import type { User } from '@/api/client'

import { admin, expert, jsonResponse, serve } from './helpers'

/** The real router and its guard, with the user already known (no call to /me). */
async function visit(user: User | null, path: string) {
  const auth = useAuthStore()
  auth.user = null
  auth.loaded = true
  await router.replace({ name: 'invite', params: { token: 'neutral' } }) // an unguarded start
  auth.user = user
  await router.push(path)
  return router.currentRoute.value
}

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  sessionStorage.clear()
})

describe('where the router lets each kind of visitor go', () => {
  it('sends a visitor who is not logged in to the login page, remembering where they wanted to go', async () => {
    const route = await visit(null, '/assignments?state=proofreading')
    expect(route.name).toBe('login')
    expect(route.query.next).toBe('/assignments?state=proofreading')
  })

  it('treats an address that matches nothing like any other page behind the login', async () => {
    expect((await visit(null, '/nowhere/at/all')).name).toBe('login')
    expect((await visit(expert, '/nowhere/at/all')).name).toBe('not-found')
  })

  it('keeps a visitor on the login and invite pages, and a logged-in one off the login', async () => {
    expect((await visit(null, '/login')).name).toBe('login')
    expect((await visit(null, '/invite/some-token')).name).toBe('invite')
    expect((await visit(expert, '/login')).name).toBe('home')
    expect((await visit(admin, '/login')).name).toBe('home')
  })

  it.each(['/experts', '/knowledge', '/vignettes', '/vignettes/new', '/vignettes/v1'])(
    'keeps an expert out of %s, which is for the admin',
    async (path) => {
      expect((await visit(expert, path)).name).toBe('home')
      expect((await visit(admin, path)).name).not.toBe('home')
    },
  )

  it.each(['/assignments/a1', '/instructions'])(
    'keeps the admin out of %s, which is for the experts',
    async (path) => {
      expect((await visit(admin, path)).name).toBe('home')
    },
  )

  it.each(['/', '/assignments', '/reviews', '/reviews/a1', '/about', '/account'])(
    'lets both roles into %s',
    async (path) => {
      for (const user of [expert, admin]) {
        expect((await visit(user, path)).fullPath).toBe(path)
      }
    },
  )

  it('sends an expert to the instructions first, once, with the way on', async () => {
    const route = await visit(expert, '/assignments/a1')
    expect(route.name).toBe('instructions')
    expect(route.query.next).toBe('/assignments/a1')

    acknowledgeIntro(expert.id, true)
    expect((await visit(expert, '/assignments/a1')).name).toBe('assignment')
  })
})

describe('when the backend cannot be reached', () => {
  it('carries on as logged out so the login page still renders, and asks again next time', async () => {
    let up = false
    const mock = serve({
      'GET /api/v1/me': () =>
        up
          ? jsonResponse(200, expert)
          : jsonResponse(500, { code: 'internal_error', message: 'x' }),
    })
    const auth = useAuthStore()
    await router.replace({ name: 'invite', params: { token: 'neutral' } })
    await router.push('/assignments')
    expect(router.currentRoute.value.name).toBe('login')
    expect(auth.loaded).toBe(false) // nothing was decided
    const asked = mock.mock.calls.length

    up = true
    await router.push('/assignments')
    expect(mock.mock.calls.length).toBeGreaterThan(asked) // it asked again
    expect(router.currentRoute.value.name).toBe('assignments')
    expect(auth.user).toEqual(expert)
    vi.unstubAllGlobals()
  })
})
