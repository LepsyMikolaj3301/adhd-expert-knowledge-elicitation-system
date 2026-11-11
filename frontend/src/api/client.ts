import createClient, { type Middleware } from 'openapi-fetch'

import type { components, paths } from './schema'

export type User = components['schemas']['UserView']
export type AssignmentSummary = components['schemas']['AssignmentSummary']
export type ExpertAssignment = components['schemas']['ExpertAssignment']
export type QuestionView = components['schemas']['QuestionView']
export type AnswerPayload = components['schemas']['AnswerPayload']
export type Q4Answer = components['schemas']['Q4Answer']
export type Citation = components['schemas']['Highlight']
export type Direction = NonNullable<Citation['direction']>
export type VignetteAdminView = components['schemas']['VignetteAdminView']
export type VersionAdminView = components['schemas']['VersionAdminView']
export type VignetteDesign = components['schemas']['VignetteDesign']
export type ReviewItem = components['schemas']['ReviewItem']
export type HomeData = components['schemas']['HomeView']
export type ActivityItem = components['schemas']['ActivityItem']
export type FindingsView = components['schemas']['FindingsView']
export type ProofreadView = components['schemas']['ProofreadView']
export type ProofreadItem = components['schemas']['ProofreadItem']
export type AnswerLine = components['schemas']['AnswerLine']
export type LinkedHighlight = components['schemas']['LinkedHighlight']
export type ReviewAnswersView = components['schemas']['ReviewAnswersView']
export type ReviewAnswer = components['schemas']['ReviewAnswer']
export type CommentView = components['schemas']['CommentView']
export type Speaker = components['schemas']['Speaker']
export type UserAdmin = components['schemas']['UserAdminView']
export type AnswerVote = components['schemas']['AnswerVoteValue']
export type QuestionId =
  paths['/api/v1/assignments/{assignment_id}/answers/{question_id}/vote']['put']['parameters']['path']['question_id']
export type NextUpItem = components['schemas']['NextUpItem']
export type PersonView =
  components['schemas']['PersonAdminCard'] | components['schemas']['PersonCard']
export type QuestionTemplate = components['schemas']['QuestionTemplate']
export type State = AssignmentSummary['state']
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

const UNAVAILABLE: ErrorBody = {
  code: 'unavailable',
  message: 'The server is not responding. Please try again.',
}

async function readError(response: Response): Promise<ErrorBody> {
  try {
    const body: unknown = await response.clone().json()
    // Our own errors always have both. FastAPI's default 404 is `{"detail": ...}`, and an
    // outdated backend answers that for every path it doesn't know.
    if (
      typeof body === 'object' &&
      body !== null &&
      typeof (body as ErrorBody).code === 'string' &&
      typeof (body as ErrorBody).message === 'string'
    ) {
      return body as ErrorBody
    }
  } catch {
    // Not JSON at all: e.g. the proxy answering 502 while the backend is down.
  }
  return UNAVAILABLE
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
