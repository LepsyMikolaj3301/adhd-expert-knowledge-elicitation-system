/**
 * One expert's draft of one vignette: loading it, and saving it without ever losing the race
 * against itself. Saves run one at a time and always use the version the last one returned, so the
 * only `draft_conflict` that can happen comes from another tab.
 */
import { computed, ref } from 'vue'

import { api, ApiError, type AnswerPayload, type ExpertAssignment } from '@/api/client'

import { forSaving } from './steps'

const SAVE_AFTER_MS = 2000
const RETRY_AFTER_MS = 5000

const EMPTY_PAYLOAD: AnswerPayload = {
  answers: {},
  highlights: [],
  insufficient_information: false,
}

/**
 * `failed`: the server can't be reached, so it tries again. `rejected`: the server refused this
 * draft, so trying again would only repeat the refusal (the reason is in `saveProblem`). `signin`:
 * the session ended, so saving waits for `resume()`. `conflict`: another tab saved since.
 */
export type SaveStatus =
  'saved' | 'unsaved' | 'saving' | 'failed' | 'rejected' | 'signin' | 'conflict'

/** A refusal that a retry can't fix. A timeout or "slow down" can be retried, the rest can't. */
function isRefusal(error: unknown): error is ApiError {
  return (
    error instanceof ApiError &&
    error.status >= 400 &&
    error.status < 500 &&
    error.status !== 408 &&
    error.status !== 429
  )
}

export function useAnswerDraft(id: string) {
  const view = ref<ExpertAssignment | null>(null)
  const payload = ref<AnswerPayload>(EMPTY_PAYLOAD)
  const status = ref<SaveStatus>('saved')
  const saveProblem = ref<ApiError | null>(null)
  const editable = computed(() => view.value?.allowed_actions.includes('save_draft') ?? false)

  const path = { params: { path: { assignment_id: id } } }
  let version = 0
  let dirty = false
  let stopped = false
  let timer: ReturnType<typeof setTimeout> | undefined
  let running: Promise<void> | null = null

  function apply(next: ExpertAssignment) {
    view.value = next
    if (next.draft) version = next.draft.version
  }

  async function fetchExpertView(): Promise<ExpertAssignment> {
    const { data } = await api.GET('/api/v1/assignments/{assignment_id}', path)
    if (data?.audience !== 'expert') {
      throw new ApiError(404, {
        code: 'not_found',
        message: 'This vignette is not assigned to you.',
      })
    }
    // openapi-fetch's types widen the `span` tuple to an array, though the API sends two numbers.
    return data as ExpertAssignment
  }

  async function load(): Promise<void> {
    clearTimeout(timer)
    dirty = false
    status.value = 'saved'
    saveProblem.value = null
    let current = await fetchExpertView()
    if (current.allowed_actions.includes('start')) {
      await api.POST('/api/v1/assignments/{assignment_id}/start', path)
      current = await fetchExpertView()
    }
    apply(current)
    if (current.submitted_at) {
      const { data } = await api.GET('/api/v1/assignments/{assignment_id}/submission', path)
      // A format 1 submission has no citations.
      payload.value = { ...EMPTY_PAYLOAD, ...(data?.payload as Partial<AnswerPayload>) }
    } else if (current.draft) {
      payload.value = structuredClone(current.draft.payload)
    }
  }

  async function saveOnce(): Promise<void> {
    dirty = false
    status.value = 'saving'
    try {
      const { data } = await api.PUT('/api/v1/assignments/{assignment_id}/draft', {
        ...path,
        body: { version, payload: forSaving(payload.value) },
      })
      if (data) version = data.version
      if (!dirty) status.value = 'saved'
    } catch (error) {
      dirty = true
      saveProblem.value = null
      if (error instanceof ApiError && error.code === 'draft_conflict') {
        status.value = 'conflict'
      } else if (error instanceof ApiError && error.status === 401) {
        status.value = 'signin'
      } else if (isRefusal(error)) {
        status.value = 'rejected'
        saveProblem.value = error
      } else {
        status.value = 'failed'
        if (!stopped) timer = setTimeout(() => void flush().catch(() => {}), RETRY_AFTER_MS)
      }
      throw error
    }
  }

  /** Resolves once everything is saved, and rejects if that isn't possible right now. */
  function flush(): Promise<void> {
    clearTimeout(timer)
    if (running) return running.then(() => (dirty ? flush() : undefined))
    if (!dirty) return Promise.resolve()
    if (status.value === 'conflict') {
      return Promise.reject(
        new ApiError(409, {
          code: 'draft_conflict',
          message: 'This draft was saved elsewhere. Reload it before continuing.',
        }),
      )
    }
    if (status.value === 'signin') {
      return Promise.reject(
        new ApiError(401, {
          code: 'not_authenticated',
          message: 'Please sign in again to save your changes.',
        }),
      )
    }
    running = saveOnce().finally(() => {
      running = null
    })
    return running.then(() => (dirty ? flush() : undefined))
  }

  /** Call after every edit of `payload`. */
  function changed(): void {
    dirty = true
    if (status.value === 'conflict' || status.value === 'signin') return
    saveProblem.value = null
    if (!running) status.value = 'unsaved'
    clearTimeout(timer)
    timer = setTimeout(() => void flush().catch(() => {}), SAVE_AFTER_MS)
  }

  /** After signing in again: save what was written while the session was over. */
  async function resume(): Promise<void> {
    if (status.value !== 'signin') return
    status.value = dirty ? 'unsaved' : 'saved'
    await flush().catch(() => {})
  }

  async function submit(): Promise<void> {
    await flush()
    const { data } = await api.POST('/api/v1/assignments/{assignment_id}/submit', path)
    if (data?.audience === 'expert') apply(data as ExpertAssignment)
  }

  function stop(): void {
    stopped = true
    clearTimeout(timer)
  }

  return {
    view,
    payload,
    status,
    saveProblem,
    editable,
    load,
    changed,
    flush,
    resume,
    submit,
    stop,
  }
}
