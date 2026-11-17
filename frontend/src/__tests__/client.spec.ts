import { afterEach, describe, expect, it, vi } from 'vitest'

import { api, ApiError, setUnauthorizedHandler } from '@/api/client'

import { jsonResponse, stubFetch } from './helpers'

describe('api client', () => {
  afterEach(() => setUnauthorizedHandler(() => {}))

  it('turns API errors into ApiError with the stable code', async () => {
    stubFetch(() =>
      jsonResponse(409, { code: 'draft_conflict', message: 'Saved elsewhere.', details: { v: 2 } }),
    )
    const error = await api.GET('/api/v1/me').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({
      status: 409,
      code: 'draft_conflict',
      message: 'Saved elsewhere.',
      details: { v: 2 },
    })
  })

  it('survives a non-JSON error from a proxy', async () => {
    stubFetch(() => new Response('Bad Gateway', { status: 502 }))
    await expect(api.GET('/api/v1/me')).rejects.toMatchObject({ status: 502, code: 'unavailable' })
  })

  it('survives JSON errors that are not in our format, such as a stale backend', async () => {
    // FastAPI's own 404 for a path it doesn't serve.
    stubFetch(() => jsonResponse(404, { detail: 'Not Found' }))
    const error = await api
      .POST('/api/v1/auth/login', { body: { email: 'a@b.co', password: 'x' } })
      .catch((e: unknown) => e)
    expect(error).toMatchObject({ status: 404, code: 'unavailable' })
    expect((error as ApiError).message).not.toBe('')
  })

  it('reports a 401 to the handler, and only a 401', async () => {
    const handler = vi.fn<() => void>()
    setUnauthorizedHandler(handler)
    stubFetch(() => jsonResponse(403, { code: 'forbidden', message: 'No.' }))
    await expect(api.GET('/api/v1/me')).rejects.toBeInstanceOf(ApiError)
    expect(handler).not.toHaveBeenCalled()

    stubFetch(() => jsonResponse(401, { code: 'not_authenticated', message: 'Log in.' }))
    await expect(api.GET('/api/v1/me')).rejects.toBeInstanceOf(ApiError)
    expect(handler).toHaveBeenCalledOnce()
  })

  it('lets a network failure through as it is: it is not an answer from the server', async () => {
    const handler = vi.fn<() => void>()
    setUnauthorizedHandler(handler)
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch')
      }),
    )
    const error = await api.GET('/api/v1/me').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(TypeError)
    expect(error).not.toBeInstanceOf(ApiError)
    expect(handler).not.toHaveBeenCalled()
  })

  it('accepts an answer with no body', async () => {
    stubFetch(() => new Response(null, { status: 204 }))
    const { data, error } = await api.POST('/api/v1/auth/logout')
    expect(data).toBeUndefined()
    expect(error).toBeUndefined()
  })

  it('reports a 403 as an error without treating it as the end of the session', async () => {
    const handler = vi.fn<() => void>()
    setUnauthorizedHandler(handler)
    stubFetch(() => jsonResponse(403, { code: 'forbidden', message: 'You may not do this.' }))
    await expect(api.GET('/api/v1/users')).rejects.toMatchObject({ status: 403, code: 'forbidden' })
    expect(handler).not.toHaveBeenCalled()
  })

  it('calls the versioned path on the same origin', async () => {
    const fetchMock = stubFetch(() => jsonResponse(200, []))
    await api.GET('/api/v1/assignments')
    const request = fetchMock.mock.calls[0]![0] as Request
    expect(new URL(request.url).pathname).toBe('/api/v1/assignments')
    expect(new URL(request.url).origin).toBe(window.location.origin)
    expect(request.credentials).toBe('same-origin')
  })
})
