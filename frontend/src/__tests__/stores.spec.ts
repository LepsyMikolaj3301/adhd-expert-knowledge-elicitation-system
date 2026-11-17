import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { ApiError, type HomeData } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useHomeStore } from '@/stores/home'

import { admin, expert, jsonResponse, serve, writes } from './helpers'

const ERROR = (code: string) => ({ code, message: `${code}.` })
const calls = (mock: ReturnType<typeof serve>) => mock.mock.calls.length

beforeEach(() => setActivePinia(createPinia()))

describe('the auth store', () => {
  it('asks the server once who is logged in, and remembers the answer', async () => {
    const mock = serve({ 'GET /api/v1/me': jsonResponse(200, expert) })
    const auth = useAuthStore()
    await auth.load()
    await auth.load()
    expect(calls(mock)).toBe(1)
    expect(auth.user).toEqual(expert)
    expect([auth.isLoggedIn, auth.loaded, auth.role]).toEqual([true, true, 'expert'])
  })

  it('reads a 401 as "nobody is logged in", which is an answer too', async () => {
    const mock = serve({ 'GET /api/v1/me': jsonResponse(401, ERROR('not_authenticated')) })
    const auth = useAuthStore()
    await auth.load()
    await auth.load()
    expect(calls(mock)).toBe(1)
    expect([auth.user, auth.isLoggedIn, auth.loaded]).toEqual([null, false, true])
  })

  it('does not decide anything when the server is down, so the next navigation asks again', async () => {
    let up = false
    const mock = serve({
      'GET /api/v1/me': () =>
        up ? jsonResponse(200, admin) : jsonResponse(500, ERROR('internal_error')),
    })
    const auth = useAuthStore()
    await expect(auth.load()).rejects.toBeInstanceOf(ApiError)
    expect(auth.loaded).toBe(false)
    up = true
    await auth.load()
    expect(calls(mock)).toBe(2)
    expect(auth.role).toBe('admin')
  })

  it('logs in, and a login ends the "sign in again" state', async () => {
    serve({ 'POST /api/v1/auth/login': jsonResponse(200, expert) })
    const auth = useAuthStore()
    auth.endSession()
    expect(auth.sessionEnded).toBe(true)
    await auth.login('e@example.com', 'secret')
    expect([auth.user, auth.loaded, auth.sessionEnded]).toEqual([expert, true, false])
  })

  it('stays logged out after a refused login', async () => {
    serve({ 'POST /api/v1/auth/login': jsonResponse(401, ERROR('invalid_credentials')) })
    const auth = useAuthStore()
    await expect(auth.login('e@example.com', 'wrong')).rejects.toMatchObject({
      code: 'invalid_credentials',
    })
    expect(auth.user).toBeNull()
  })

  it('logs out, and a failed logout keeps the person where they are', async () => {
    let fail = true
    const mock = serve({
      'POST /api/v1/auth/logout': () =>
        fail ? jsonResponse(500, ERROR('internal_error')) : new Response(null, { status: 204 }),
    })
    const auth = useAuthStore()
    auth.user = expert
    await expect(auth.logout()).rejects.toBeInstanceOf(ApiError)
    expect(auth.user).toEqual(expert)
    fail = false
    await auth.logout()
    expect(auth.user).toBeNull()
    expect(writes(mock)).toEqual(['POST /api/v1/auth/logout', 'POST /api/v1/auth/logout'])
  })

  it('tells "the session ended, stay on the page" from "the session is gone"', () => {
    const auth = useAuthStore()
    auth.user = expert
    auth.endSession()
    expect([auth.user, auth.sessionEnded]).toEqual([expert, true]) // the page stays
    auth.clear()
    expect([auth.user, auth.sessionEnded, auth.loaded]).toEqual([null, false, true])
  })
})

describe('the home store', () => {
  const data = (overrides: Partial<HomeData> = {}): HomeData => ({
    next_up: [],
    next_up_total: 0,
    reviews_waiting: [],
    reviews_waiting_total: 0,
    recent_reviews: [],
    activity: [
      { at: '2026-11-04T10:00:00Z' },
      { at: '2026-11-06T10:00:00Z' },
      { at: '2026-11-05T10:00:00Z' },
    ] as HomeData['activity'],
    unread_activity: 2,
    ...overrides,
  })

  it('keeps what it loaded, and "failed" only for as long as the last load failed', async () => {
    let up = false
    serve({
      'GET /api/v1/me/home': () => (up ? jsonResponse(200, data()) : jsonResponse(500, ERROR('x'))),
    })
    const home = useHomeStore()
    await home.load()
    expect([home.failed, home.data]).toEqual([true, null])
    up = true
    await home.load()
    expect([home.failed, home.data?.unread_activity]).toEqual([false, 2])
  })

  it('keeps the old page when a later load fails', async () => {
    let up = true
    serve({
      'GET /api/v1/me/home': () => (up ? jsonResponse(200, data()) : jsonResponse(500, ERROR('x'))),
    })
    const home = useHomeStore()
    await home.load()
    up = false
    await home.load()
    expect(home.failed).toBe(true)
    expect(home.data?.unread_activity).toBe(2)
  })

  it('tells the server up to the newest item it showed, then counts nothing as unread', async () => {
    const mock = serve({
      'GET /api/v1/me/home': jsonResponse(200, data()),
      'POST /api/v1/me/activity/seen': new Response(null, { status: 204 }),
    })
    const home = useHomeStore()
    await home.load()
    await home.markSeen()
    const request = mock.mock.calls.find(([i]) => (i as Request).method === 'POST')![0] as Request
    expect(await request.clone().json()).toEqual({ until: '2026-11-06T10:00:00Z' })
    expect(home.data?.unread_activity).toBe(0)
  })

  it('says nothing when nothing is unread', async () => {
    const mock = serve({ 'GET /api/v1/me/home': jsonResponse(200, data({ unread_activity: 0 })) })
    const home = useHomeStore()
    await home.load()
    await home.markSeen()
    expect(writes(mock)).toEqual([])
  })

  it('stays unread when the server could not be told, to try again on the next visit', async () => {
    serve({
      'GET /api/v1/me/home': jsonResponse(200, data()),
      'POST /api/v1/me/activity/seen': jsonResponse(500, ERROR('x')),
    })
    const home = useHomeStore()
    await home.load()
    await home.markSeen()
    expect(home.data?.unread_activity).toBe(2)
  })
})
