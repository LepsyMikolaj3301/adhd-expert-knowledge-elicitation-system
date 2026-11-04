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
