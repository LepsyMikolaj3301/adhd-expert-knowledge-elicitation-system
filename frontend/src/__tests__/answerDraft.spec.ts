import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { AnswerPayload, ExpertAssignment, QuestionView } from '@/api/client'
import { firstOpenStep, forSaving, stepProblem } from '@/answering/steps'
import { useAnswerDraft } from '@/answering/useAnswerDraft'

import { jsonResponse, urlOf } from './helpers'

const FIFTEEN = 'one two three four five six seven eight nine ten eleven twelve thirteen four15 x15'
const TEN = 'one two three four five six seven eight nine ten'

const GATE: QuestionView[] = [
  { id: 'Q1', kind: 'open', text: 'First?', min_words: 15 },
  { id: 'Q2', kind: 'open', text: 'Second?', min_words: 10 },
  { id: 'Q3', kind: 'open', text: 'Third?', min_words: 10 },
]
const Q4: QuestionView = {
  id: 'Q4',
  kind: 'shift',
  text: 'How would it change if the writer had an exam?',
  min_words: 5,
  wording: { hypothesis_min_words: 3 },
}
const LATER: QuestionView[] = [
  Q4,
  { id: 'Q5', kind: 'open', text: 'Fifth?', min_words: 10 },
  { id: 'Q6', kind: 'rating_1_5', text: 'Sixth?' },
]

function assignment(overrides: Partial<ExpertAssignment> = {}): ExpertAssignment {
  return {
    audience: 'expert',
    id: 'a1',
    state: 'in_progress',
    allowed_actions: ['pass_gate', 'save_draft'],
    updated_at: '2026-11-05T10:00:00Z',
    vignette: {
      code: 'V001',
      version: 1,
      text: 'The patient text.',
      framing: 'personal_journal',
      word_count: 3,
      content_hash: 'x',
      questions: GATE,
    },
    draft: {
      version: 4,
      payload: { answers: { Q1: 'saved' }, highlights: [], insufficient_information: false },
      updated_at: '2026-11-05T10:00:00Z',
    },
    gate_passed_at: null,
    locked_highlights: 0,
    started_at: '2026-11-05T10:00:00Z',
    submitted_at: null,
    ...overrides,
  }
}

function view(answers: Record<string, string>, extra: Partial<AnswerPayload> = {}): AnswerPayload {
  return { answers, highlights: [], insufficient_information: false, ...extra }
}

describe('stepProblem', () => {
  it('asks for more words on an open question, not counting chips', () => {
    const q2 = GATE[1] as QuestionView
    expect(stepProblem(q2, view({ Q2: '⟦h1⟧ ⟦h2⟧ two words' }))).toBe(
      'Q2 has 2 of 10 different words.',
    )
    expect(stepProblem(q2, view({ Q2: TEN }))).toBeNull()
  })

  it('names the first missing part of Q4', () => {
    expect(stepProblem(Q4, view({}))).toBe('Write your working hypothesis.')
    expect(stepProblem(Q4, view({}, { q4: { hypothesis: 'tired not trait' } }))).toBe(
      'Pick a point on the scale.',
    )
    const shifted = { hypothesis: 'tired not trait', shift: 1 }
    expect(stepProblem(Q4, view({}, { q4: shifted }))).toBe('Choose a direction.')
    expect(stepProblem(Q4, view({}, { q4: { ...shifted, toward: 'other' } }))).toBe(
      'Name the other explanation.',
    )
    expect(stepProblem(Q4, view({}, { q4: { ...shifted, toward: 'less_adhd' } }))).toBe(
      'Why? has 0 of 5 different words.',
    )
    expect(
      stepProblem(
        Q4,
        view({ Q4: 'because of the exam today' }, { q4: { ...shifted, toward: 'less_adhd' } }),
      ),
    ).toBeNull()
  })

  it('needs only the hypothesis and the scale at zero', () => {
    expect(
      stepProblem(Q4, view({}, { q4: { hypothesis: 'tired not trait', shift: 0 } })),
    ).toBeNull()
  })

  it('needs a rating or "insufficient information"', () => {
    const q6 = LATER[2] as QuestionView
    expect(stepProblem(q6, view({}))).toBe('Choose a rating.')
    expect(stepProblem(q6, view({}, { rating: 3 }))).toBeNull()
    expect(stepProblem(q6, view({}, { insufficient_information: true }))).toBeNull()
  })
})

describe('firstOpenStep', () => {
  const answered = { Q1: FIFTEEN, Q2: TEN, Q3: TEN }

  it('goes to the first unanswered question', () => {
    expect(firstOpenStep(GATE, view({}), false)).toBe('Q1')
    expect(firstOpenStep(GATE, view({ Q1: FIFTEEN }), false)).toBe('Q2')
  })

  it('stays on Q3 before the gate, where the lock-in button is', () => {
    expect(firstOpenStep(GATE, view(answered), false)).toBe('Q3')
  })

  it('moves on after the gate, and ends on the review', () => {
    const all = [...GATE, ...LATER]
    expect(firstOpenStep(all, view(answered), true)).toBe('Q4')
    expect(
      firstOpenStep(
        all,
        view(
          { ...answered, Q5: TEN },
          { q4: { hypothesis: 'tired not trait', shift: 0 }, rating: 2 },
        ),
        true,
      ),
    ).toBe('review')
  })
})

describe('forSaving', () => {
  it('leaves out the parts of Q4 that are hidden at zero', () => {
    const saved = forSaving(
      view(
        { Q1: 'keep', Q4: 'remembered why' },
        {
          q4: {
            hypothesis: 'tired',
            shift: 0,
            toward: 'other',
            other_explanation: 'remembered name',
          },
        },
      ),
    )
    expect(saved.answers).toEqual({ Q1: 'keep' })
    expect(saved.q4).toEqual({
      hypothesis: 'tired',
      shift: 0,
      toward: null,
      other_explanation: null,
    })
  })

  it('leaves out the direction below +1 and the name without "other"', () => {
    const below = forSaving(view({}, { q4: { shift: -1, toward: 'less_adhd' } }))
    expect(below.q4?.toward).toBeNull()
    const named = forSaving(
      view({}, { q4: { shift: 1, toward: 'less_adhd', other_explanation: 'old' } }),
    )
    expect(named.q4?.other_explanation).toBeNull()
  })

  it('does not change what the screen remembers', () => {
    const payload = view({ Q4: 'remembered' }, { q4: { shift: 0, toward: 'other' } })
    forSaving(payload)
    expect(payload.answers.Q4).toBe('remembered')
    expect(payload.q4?.toward).toBe('other')
  })
})

describe('useAnswerDraft', () => {
  type Call = { method: string; url: string; body?: { version: number; payload: AnswerPayload } }
  let calls: Call[]
  let answer: (call: Call) => Response | Promise<Response>

  beforeEach(() => {
    vi.useFakeTimers()
    calls = []
    answer = (call) =>
      call.method === 'PUT'
        ? jsonResponse(200, { version: (call.body?.version ?? 0) + 1, updated_at: 'now' })
        : jsonResponse(200, assignment())
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: Request) => {
        const raw = await input.clone().text()
        const call: Call = {
          method: input.method,
          url: urlOf(input),
          body: raw ? JSON.parse(raw) : undefined,
        }
        calls.push(call)
        return answer(call)
      }),
    )
  })
  afterEach(() => vi.useRealTimers())

  const writes = () => calls.filter((c) => c.method !== 'GET')

  it('starts an assignment that has not been started', async () => {
    let started = false
    answer = (call) => {
      if (call.method === 'POST') started = true
      return jsonResponse(
        200,
        assignment(started ? {} : { state: 'assigned', allowed_actions: ['start'], draft: null }),
      )
    }
    const draft = useAnswerDraft('a1')
    await draft.load()
    expect(writes().map((c) => c.url)).toEqual([expect.stringContaining('/assignments/a1/start')])
    expect(draft.view.value?.state).toBe('in_progress')
  })

  it('saves once, two seconds after the last change', async () => {
    const draft = useAnswerDraft('a1')
    await draft.load()
    draft.payload.value.answers = { Q1: 'first' }
    draft.changed()
    await vi.advanceTimersByTimeAsync(1500)
    draft.payload.value.answers = { Q1: 'second' }
    draft.changed()
    await vi.advanceTimersByTimeAsync(1500)
    expect(writes()).toHaveLength(0)
    await vi.advanceTimersByTimeAsync(600)
    expect(writes()).toHaveLength(1)
    expect(writes()[0]?.body).toEqual({ version: 4, payload: expect.anything() })
    expect(writes()[0]?.body?.payload.answers).toEqual({ Q1: 'second' })
    expect(draft.status.value).toBe('saved')
  })

  it('leaves hidden Q4 parts out of what it saves, and keeps them on the screen', async () => {
    const draft = useAnswerDraft('a1')
    await draft.load()
    draft.payload.value.answers = { Q4: 'remembered why' }
    draft.payload.value.q4 = { hypothesis: 'tired', shift: 0, toward: 'other' }
    draft.changed()
    await draft.flush()
    expect(writes()[0]?.body?.payload.answers).toEqual({})
    expect(writes()[0]?.body?.payload.q4?.toward).toBeNull()
    expect(draft.payload.value.answers.Q4).toBe('remembered why')
  })

  it('never runs two saves at once, and uses the version the last one returned', async () => {
    const draft = useAnswerDraft('a1')
    await draft.load()
    let finish: (r: Response) => void = () => {}
    answer = (call) =>
      call.method === 'PUT' && call.body?.version === 4
        ? new Promise<Response>((resolve) => (finish = resolve))
        : jsonResponse(200, { version: 6, updated_at: 'now' })

    draft.payload.value.answers = { Q1: 'one' }
    draft.changed()
    const first = draft.flush()
    await vi.advanceTimersByTimeAsync(0)
    draft.payload.value.answers = { Q1: 'two' }
    draft.changed()
    await vi.advanceTimersByTimeAsync(5000)
    expect(writes()).toHaveLength(1)

    finish(jsonResponse(200, { version: 5, updated_at: 'now' }))
    await first
    await vi.advanceTimersByTimeAsync(0)
    expect(writes()).toHaveLength(2)
    expect(writes()[1]?.body?.version).toBe(5)
    expect(writes()[1]?.body?.payload.answers).toEqual({ Q1: 'two' })
  })

  it('saves before locking in, because the server checks the saved draft', async () => {
    const draft = useAnswerDraft('a1')
    await draft.load()
    answer = (call) =>
      call.method === 'PUT'
        ? jsonResponse(200, { version: 5, updated_at: 'now' })
        : jsonResponse(
            200,
            assignment({
              gate_passed_at: 'now',
              locked_highlights: 0,
              allowed_actions: ['save_draft', 'submit'],
              vignette: { ...assignment().vignette, questions: [...GATE, ...LATER] },
            }),
          )
    draft.payload.value.answers = { Q1: 'latest' }
    draft.changed()
    await draft.passGate()
    expect(writes().map((c) => c.method)).toEqual(['PUT', 'POST'])
    expect(writes()[1]?.url).toContain('/pass-gate')
    expect(draft.view.value?.vignette.questions).toHaveLength(6)
  })

  it('does not lock in when the save fails', async () => {
    const draft = useAnswerDraft('a1')
    await draft.load()
    answer = () => jsonResponse(503, { code: 'unavailable', message: 'Down.' })
    draft.payload.value.answers = { Q1: 'latest' }
    draft.changed()
    await expect(draft.passGate()).rejects.toThrow('Down.')
    expect(writes().map((c) => c.method)).toEqual(['PUT'])
    expect(draft.status.value).toBe('failed')
    draft.stop()
  })

  it('tries again after a failed save', async () => {
    const draft = useAnswerDraft('a1')
    await draft.load()
    const replies = [
      jsonResponse(503, { code: 'unavailable', message: 'Down.' }),
      jsonResponse(200, { version: 5, updated_at: 'now' }),
    ]
    answer = () => replies.shift() as Response
    draft.payload.value.answers = { Q1: 'latest' }
    draft.changed()
    await vi.advanceTimersByTimeAsync(2000)
    expect(draft.status.value).toBe('failed')
    await vi.advanceTimersByTimeAsync(5000)
    expect(writes()).toHaveLength(2)
    expect(draft.status.value).toBe('saved')
  })

  it('stops saving after a conflict, until the draft is reloaded', async () => {
    const draft = useAnswerDraft('a1')
    await draft.load()
    answer = () => jsonResponse(409, { code: 'draft_conflict', message: 'Saved elsewhere.' })
    draft.payload.value.answers = { Q1: 'mine' }
    draft.changed()
    await vi.advanceTimersByTimeAsync(2000)
    expect(draft.status.value).toBe('conflict')
    draft.changed()
    await vi.advanceTimersByTimeAsync(10_000)
    expect(writes()).toHaveLength(1)

    answer = () => jsonResponse(200, assignment())
    await draft.load()
    expect(draft.status.value).toBe('saved')
    expect(draft.payload.value.answers).toEqual({ Q1: 'saved' })
  })

  it('reads a submitted vignette from the submission', async () => {
    const submitted = assignment({
      state: 'expert_check',
      allowed_actions: [],
      submitted_at: 'now',
    })
    answer = (call) =>
      call.url.endsWith('/submission')
        ? jsonResponse(200, {
            assignment_id: 'a1',
            payload_format: 2,
            vignette_hash: 'x',
            submitted_at: 'now',
            payload: { answers: { Q1: 'frozen' }, highlights: [], rating: 2 },
          })
        : jsonResponse(200, submitted)
    const draft = useAnswerDraft('a1')
    await draft.load()
    expect(draft.payload.value.answers).toEqual({ Q1: 'frozen' })
    expect(draft.editable.value).toBe(false)
  })

  it('does not save after it is stopped', async () => {
    const draft = useAnswerDraft('a1')
    await draft.load()
    draft.payload.value.answers = { Q1: 'x' }
    draft.changed()
    draft.stop()
    await vi.advanceTimersByTimeAsync(10_000)
    expect(writes()).toHaveLength(0)
  })
})
