import { vi } from 'vitest'

import type { User } from '@/api/client'

type FetchInput = RequestInfo | URL

export function urlOf(input: FetchInput): string {
  return input instanceof Request ? input.url : String(input)
}

/** A fetch stub that answers from a function of the URL. */
export function stubFetch(answer: (url: string) => Response) {
  const mock = vi.fn<(input: FetchInput) => Promise<Response>>(async (input) =>
    answer(urlOf(input)),
  )
  vi.stubGlobal('fetch', mock)
  return mock
}

/**
 * A fetch stub that answers by method and path, `'POST /api/v1/assignments/a1/cancel'`. A route is
 * a response or a function of the request (so it can change between calls); anything else is a 404.
 * Every call is kept in `.mock.calls`, and `writes(mock)` lists the non-GET ones.
 */
export type Route = Response | ((request: Request) => Response | Promise<Response>)

export function serve(routes: Record<string, Route>) {
  const mock = vi.fn<(input: FetchInput) => Promise<Response>>(async (input) => {
    const request = input as Request
    const route = routes[`${request.method} ${new URL(request.url).pathname}`]
    if (!route) return jsonResponse(404, { code: 'not_found', message: 'Not found.' })
    return typeof route === 'function' ? route(request) : route.clone()
  })
  vi.stubGlobal('fetch', mock)
  return mock
}

/** `'METHOD /path'` of every write a stub has seen. */
export function writes(mock: ReturnType<typeof serve>): string[] {
  return mock.mock.calls
    .map(([input]) => input as Request)
    .filter((r) => r.method !== 'GET')
    .map((r) => `${r.method} ${new URL(r.url).pathname}`)
}

export function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

export const expert: User = {
  id: '1',
  email: 'e@example.com',
  display_name: 'Eve',
  role: 'expert',
  pseudonym: 'E01',
  is_synthetic: false,
  is_active: true,
  created_at: '2026-11-04T10:00:00Z',
}

export const admin: User = {
  ...expert,
  id: '2',
  display_name: 'Ada',
  role: 'admin',
  pseudonym: 'A01',
}
