import createClient, { type Middleware } from 'openapi-fetch'

import type { components, paths } from './schema'

export type User = components['schemas']['UserView']
export type AssignmentSummary = components['schemas']['AssignmentSummary']
type ErrorBody = components['schemas']['ErrorResponse']

/** Every failed API call throws this. `code` is stable; `message` is safe to show the user. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: ErrorBody['details']

  constructor(status: number, body: ErrorBody) {
    super(body.message)
    this.name = 'ApiError'
    this.status = status
    this.code = body.code
    this.details = body.details
  }
}

let onUnauthorized: () => void = () => {}

/** Called whenever the API answers 401, e.g. because the session has expired. */
export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler
}

async function readError(response: Response): Promise<ErrorBody> {
  try {
    return (await response.clone().json()) as ErrorBody
  } catch {
    // Not from FastAPI: e.g. the proxy answering 502 while the backend is down.
    return { code: 'unavailable', message: 'The server is not responding. Please try again.' }
  }
}

const throwOnError: Middleware = {
  async onResponse({ response }) {
    if (response.ok) return undefined
    if (response.status === 401) onUnauthorized()
    throw new ApiError(response.status, await readError(response))
  },
}

export const api = createClient<paths>({
  baseUrl: window.location.origin,
  credentials: 'same-origin',
  // Looked up per call, so that tests can replace it.
  fetch: (request) => globalThis.fetch(request),
})
api.use(throwOnError)
