import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import App from '@/App.vue'
import type { AnswerPayload, Citation, ExpertAssignment, QuestionView } from '@/api/client'
import router from '@/router'
import { useAuthStore } from '@/stores/auth'

import { expert, jsonResponse, urlOf } from './helpers'

const TEXT = 'I have barely slept since the move. My hand starts shaking slightly.'
const FIFTEEN = 'one two three four five six seven eight nine ten eleven twelve thirteen a15 b15'
const TEN = 'one two three four five six seven eight nine ten'

const GATE: QuestionView[] = [
  { id: 'Q1', kind: 'open', text: 'Which fragments matter?', min_words: 15 },
  { id: 'Q2', kind: 'open', text: 'Which could be something else?', min_words: 10 },
  { id: 'Q3', kind: 'open', text: 'What is missing?', min_words: 10 },
]
const LATER: QuestionView[] = [
  {
    id: 'Q4',
    kind: 'shift',
    text: 'Given your hypothesis: how would it change if the writer had an exam?',
    min_words: 5,
    wording: {
      hypothesis: 'Your working hypothesis, in one sentence',
      hypothesis_min_words: 3,
      shift_lead: 'With this, my hypothesis…',
      shift_labels: {
        '-2': 'is strongly reinforced',
        '-1': 'is somewhat reinforced',
        '0': 'is unchanged',
        '1': 'partly changes',
        '2': 'changes completely',
      },
      toward: 'Towards…',
      toward_labels: {
        more_adhd: 'more ADHD-like',
        less_adhd: 'less ADHD-like',
        other: 'another explanation',
      },
      why: 'Why?',
    },
  },
  { id: 'Q5', kind: 'open', text: 'What would a junior clinician misread?', min_words: 10 },
  { id: 'Q6', kind: 'rating_1_5', text: 'Overall, how strongly?' },
]

function citation(chip: number, text: string, direction: Citation['direction'] = null): Citation {
  const start = TEXT.indexOf(text)
  return { chip, text, span: [start, start + text.length], direction }
}

function assignment(
  partial: Partial<AnswerPayload>,
  overrides: Partial<ExpertAssignment> = {},
): ExpertAssignment {
  const payload: AnswerPayload = {
    answers: {},
    highlights: [],
    insufficient_information: false,
    ...partial,
  }
  return {
    audience: 'expert',
    id: 'a1',
    state: 'in_progress',
    allowed_actions: ['pass_gate', 'save_draft'],
    updated_at: 'now',
    vignette: {
      code: 'V007',
      version: 1,
      text: TEXT,
      framing: 'personal_journal',
      word_count: 12,
      content_hash: 'x',
      questions: GATE,
    },
    draft: { version: 1, payload, updated_at: 'now' },
    gate_passed_at: null,
    locked_highlights: 0,
    started_at: 'now',
    submitted_at: null,
    ...overrides,
  }
}

const GATE_ANSWERS = { Q1: FIFTEEN, Q2: TEN, Q3: TEN }

function afterGate(payload: Partial<AnswerPayload>, locked: number): ExpertAssignment {
  const base = assignment(payload)
  return {
    ...base,
    allowed_actions: ['save_draft', 'submit'],
    gate_passed_at: 'now',
    locked_highlights: locked,
    vignette: { ...base.vignette, questions: [...GATE, ...LATER] },
  }
}

type Call = { method: string; url: string; body?: { version: number; payload: AnswerPayload } }
let calls: Call[]
let current: ExpertAssignment
let wrapper: VueWrapper | undefined

function serve(initial: ExpertAssignment) {
  current = initial
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: Request) => {
      const raw = await input.clone().text()
      const url = urlOf(input)
      const call: Call = { method: input.method, url, body: raw ? JSON.parse(raw) : undefined }
      calls.push(call)
      if (call.method === 'PUT') {
        current = assignment(call.body?.payload as AnswerPayload, {
          ...current,
          draft: {
            version: (call.body?.version ?? 0) + 1,
            payload: call.body?.payload as AnswerPayload,
            updated_at: 'now',
          },
        })
        return jsonResponse(200, { version: current.draft?.version, updated_at: 'now' })
      }
      if (url.endsWith('/pass-gate')) {
        const payload = current.draft?.payload as AnswerPayload
        current = {
          ...afterGate(payload, payload.highlights.length),
          draft: current.draft,
        }
      } else if (url.endsWith('/submit')) {
        current = { ...current, state: 'processing', allowed_actions: [], submitted_at: 'now' }
      } else if (url.endsWith('/assignments')) {
        return jsonResponse(200, [])
      }
      return jsonResponse(200, current)
    }),
  )
}

async function open(initial: ExpertAssignment) {
  serve(initial)
  await router.push('/assignments/a1')
  wrapper = mount(App, { global: { plugins: [router] }, attachTo: document.body })
  await flushPromises()
  await flushPromises()
  return wrapper
}

const app = () => wrapper as VueWrapper
const marked = () => app().find('[data-testid="vignette-text"] mark')
const heading = () => app().get('[data-testid="question"]').text()
const rows = () => app().findAll('[data-testid="citation"]')

function buttonNamed(name: string) {
  const button = app()
    .findAll('button')
    .find((b) => b.text() === name)
  if (!button) throw new Error(`no button "${name}" in: ${app().text()}`)
  return button
}

async function selectInText(text: string) {
  const root = app().get('[data-testid="vignette-text"]')
  const node = root.element.firstElementChild?.firstChild as Text
  const start = (node.textContent ?? '').indexOf(text)
  const range = document.createRange()
  range.setStart(node, start)
  range.setEnd(node, start + text.length)
  const selection = window.getSelection() as Selection
  selection.removeAllRanges()
  await root.trigger('pointerdown')
  selection.addRange(range)
  window.dispatchEvent(new Event('pointerup'))
  await flushPromises()
}

beforeEach(async () => {
  setActivePinia(createPinia())
  const auth = useAuthStore()
  auth.user = expert
  auth.loaded = true
  calls = []
  window.getSelection()?.removeAllRanges()
  // jsdom doesn't implement dialogs.
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute('open', '')
  }
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute('open')
  }
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  document.body.innerHTML = ''
})

describe('the vignette text', () => {
  it('shows the patient text exactly as written, with nothing lit', async () => {
    await open(assignment({ answers: {}, highlights: [citation(1, 'barely slept')] }))
    expect(app().get('[data-testid="vignette-text"]').element.textContent).toBe(TEXT)
    expect(marked().exists()).toBe(false)
  })

  it('lights a passage only while its citation row is hovered', async () => {
    await open(
      assignment({
        answers: {},
        highlights: [citation(1, 'barely slept'), citation(2, 'hand starts')],
      }),
    )
    await rows()[1]?.trigger('mouseenter')
    expect(marked().text()).toBe('hand starts')
    expect(app().get('[data-testid="vignette-text"]').element.textContent).toBe(TEXT)
    await rows()[1]?.trigger('mouseleave')
    expect(marked().exists()).toBe(false)
  })

  it('lights a passage while its row has keyboard focus', async () => {
    await open(assignment({ answers: {}, highlights: [citation(1, 'barely slept')] }))
    await rows()[0]?.trigger('focusin')
    expect(marked().text()).toBe('barely slept')
    await rows()[0]?.trigger('focusout')
    expect(marked().exists()).toBe(false)
  })

  it('adds a citation when text is selected with the mouse, without lighting it', async () => {
    await open(assignment({ answers: {}, highlights: [] }))
    await selectInText('barely slept')
    expect(rows()).toHaveLength(1)
    expect(rows()[0]?.text()).toContain('barely slept')
    expect(marked().exists()).toBe(false)
    expect(window.getSelection()?.isCollapsed).toBe(true)
  })

  it('saves a new citation with no direction yet', async () => {
    vi.useFakeTimers()
    try {
      await open(assignment({ answers: {}, highlights: [] }))
      await selectInText('barely slept')
      await vi.advanceTimersByTimeAsync(2100)
      const put = calls.find((c) => c.method === 'PUT')
      expect(put?.body?.payload.highlights).toEqual([citation(1, 'barely slept')])
    } finally {
      vi.useRealTimers()
    }
  })

  it('does not add the same passage twice', async () => {
    await open(assignment({ answers: {}, highlights: [citation(1, 'barely slept')] }))
    await selectInText('barely slept')
    expect(rows()).toHaveLength(1)
  })

  it('ignores selections on a submitted vignette', async () => {
    await open(
      assignment(
        { answers: GATE_ANSWERS, highlights: [] },
        { state: 'processing', allowed_actions: [], submitted_at: 'now' },
      ),
    )
    await selectInText('barely slept')
    expect(rows()).toHaveLength(0)
  })
})

describe('the side panel', () => {
  it('keeps Vignettes marked as the current section inside a vignette', async () => {
    await open(assignment({}))
    const current = app().get('nav[aria-label="Main"] a[aria-current="page"]')
    expect(current.text()).toBe('Vignettes')
  })
})

describe('moving through the questions', () => {
  it('shows one question at a time, and never Q4 before the lock-in', async () => {
    await open(assignment({ answers: {}, highlights: [] }))
    expect(heading()).toContain('Which fragments matter?')
    expect(app().text()).not.toContain('What is missing?')
    expect(app().text()).not.toContain('writer had an exam')
    expect(
      app()
        .findAll('button')
        .some((b) => b.text() === 'Lock in results'),
    ).toBe(false)
  })

  it('keeps Next disabled until the answer is long enough, and says why', async () => {
    await open(assignment({ answers: { Q1: 'too short' }, highlights: [] }))
    const next = buttonNamed('Next question')
    expect(next.attributes('disabled')).toBeDefined()
    expect(app().text()).toContain('2 of 15 different words')
  })

  it('counts plainly once the answer is long enough', async () => {
    await open(
      afterGate(
        {
          answers: { ...GATE_ANSWERS, Q5: `${TEN} more` },
          q4: { hypothesis: 'tired not a trait', shift: 0 },
        },
        0,
      ),
    )
    await app()
      .findAll('[data-testid="step"]')
      .find((s) => s.text() === 'Q5')
      ?.trigger('click')
    expect(app().get('[data-testid="word-count"]').text()).toBe('11 different words')
  })

  it('moves to Q2 with the button, and back again', async () => {
    await open(assignment({ answers: { Q1: FIFTEEN }, highlights: [] }))
    expect(heading()).toContain('Which could be something else?')
    await buttonNamed('Back').trigger('click')
    expect(heading()).toContain('Which fragments matter?')
    await buttonNamed('Next question').trigger('click')
    expect(heading()).toContain('Which could be something else?')
  })

  it('opens on the first unanswered question', async () => {
    await open(assignment({ answers: { Q1: FIFTEEN, Q2: TEN }, highlights: [] }))
    expect(heading()).toContain('What is missing?')
  })
})

describe('locking in', () => {
  it('needs a direction on every citation', async () => {
    await open(assignment({ answers: GATE_ANSWERS, highlights: [citation(1, 'barely slept')] }))
    expect(buttonNamed('Lock in results').attributes('disabled')).toBeDefined()
    expect(app().text()).toContain('Choose a direction for citation 1.')
    await rows()[0]?.get('select').setValue('away')
    expect(buttonNamed('Lock in results').attributes('disabled')).toBeUndefined()
  })

  it('asks first, then saves, then passes the gate and shows Q4', async () => {
    await open(assignment({ answers: GATE_ANSWERS, highlights: [citation(1, 'barely slept')] }))
    await rows()[0]?.get('select').setValue('away')
    await buttonNamed('Lock in results').trigger('click')
    expect(calls.filter((c) => c.url.endsWith('/pass-gate'))).toHaveLength(0)
    expect(app().get('dialog[open]').text()).toContain('not cited')

    await app()
      .get('dialog[open]')
      .findAll('button')
      .find((b) => b.text() === 'Lock in results')
      ?.trigger('click')
    await flushPromises()

    const writes = calls.filter((c) => c.method !== 'GET').map((c) => c.method)
    expect(writes).toEqual(['PUT', 'POST'])
    expect(heading()).toContain('the writer had an exam')
  })

  it('warns about no citations at all, without blocking', async () => {
    await open(assignment({ answers: GATE_ANSWERS, highlights: [] }))
    await buttonNamed('Lock in results').trigger('click')
    expect(app().get('dialog[open]').text()).toContain('no citations')
  })

  it('shows locked questions read-only, with their chips', async () => {
    const payload = {
      answers: { ...GATE_ANSWERS, Q1: `⟦h1⟧ ${FIFTEEN}` },
      highlights: [citation(1, 'barely slept', 'away')],
    }
    await open(afterGate(payload, 1))
    await app().findAll('[data-testid="step"]')[0]?.trigger('click')
    expect(heading()).toContain('Which fragments matter?')
    expect(app().find('.chip-editor').exists()).toBe(false)
    expect(app().text()).toContain('Locked')

    await app().get('[data-chip="1"]').trigger('mouseover')
    expect(marked().text()).toBe('barely slept')
  })

  it('keeps locked citations fixed, while new ones can be added and removed', async () => {
    const payload = {
      answers: GATE_ANSWERS,
      highlights: [citation(1, 'barely slept', 'away')],
    }
    await open(afterGate(payload, 1))
    expect(rows()[0]?.find('select').exists()).toBe(false)
    expect(rows()[0]?.text()).not.toContain('Remove')

    await selectInText('hand starts')
    expect(rows()).toHaveLength(2)
    expect(rows()[1]?.find('select').exists()).toBe(true)
    await rows()[1]
      ?.findAll('button')
      .find((b) => b.text() === 'Remove')
      ?.trigger('click')
    expect(rows()).toHaveLength(1)
  })

  it('shows what went wrong when the server refuses, and stays on Q3', async () => {
    await open(assignment({ answers: GATE_ANSWERS, highlights: [] }))
    const fetchMock = globalThis.fetch as ReturnType<typeof vi.fn>
    const original = fetchMock.getMockImplementation()
    fetchMock.mockImplementation(async (input: Request) =>
      urlOf(input).endsWith('/pass-gate')
        ? jsonResponse(422, { code: 'answer_too_short', message: 'Q3: please write a bit more.' })
        : (original as (i: Request) => Promise<Response>)(input),
    )
    await buttonNamed('Lock in results').trigger('click')
    await app()
      .get('dialog[open]')
      .findAll('button')
      .find((b) => b.text() === 'Lock in results')
      ?.trigger('click')
    await flushPromises()
    expect(app().get('[role="alert"]').text()).toBe('Q3: please write a bit more.')
    expect(heading()).toContain('What is missing?')
  })
})

describe('removing a citation', () => {
  it('asks when it is cited, then renumbers the rest and their chips', async () => {
    await open(
      assignment({
        answers: { Q1: `⟦h1⟧ and ⟦h2⟧ ${FIFTEEN}` },
        highlights: [citation(1, 'barely slept'), citation(2, 'hand starts')],
      }),
    )
    await rows()[0]
      ?.findAll('button')
      .find((b) => b.text() === 'Remove')
      ?.trigger('click')
    expect(rows()).toHaveLength(2)
    await app()
      .get('dialog[open]')
      .findAll('button')
      .find((b) => b.text() === 'Remove citation')
      ?.trigger('click')
    await flushPromises()
    expect(rows()).toHaveLength(1)
    expect(rows()[0]?.text()).toContain('hand starts')
  })
})

describe('Q4', () => {
  async function openQ4(q4: AnswerPayload['q4'] = null) {
    await open(afterGate({ answers: GATE_ANSWERS, highlights: [], q4 }, 0))
  }

  it('has no point chosen on the scale until the expert picks one', async () => {
    await openQ4()
    const stops = app().findAll('input[name="q4-shift"]')
    expect(stops).toHaveLength(5)
    expect(stops.every((s) => !(s.element as HTMLInputElement).checked)).toBe(true)
  })

  it('at zero, asks for nothing more', async () => {
    await openQ4({ hypothesis: 'tired not a trait', shift: 0 })
    expect(app().text()).not.toContain('Towards…')
    expect(app().text()).not.toContain('Why?')
    await flushPromises()
  })

  it('above zero, asks for the direction and the reason', async () => {
    await openQ4({ hypothesis: 'tired not a trait', shift: 1 })
    expect(app().text()).toContain('Towards…')
    expect(app().text()).toContain('Why?')
  })

  it('below zero, asks for the reason only', async () => {
    await openQ4({ hypothesis: 'tired not a trait', shift: -1 })
    expect(app().text()).not.toContain('Towards…')
    expect(app().text()).toContain('Why?')
  })
})

describe('submitting', () => {
  const finished: AnswerPayload = {
    answers: { ...GATE_ANSWERS, Q5: TEN },
    highlights: [citation(1, 'barely slept', 'away')],
    q4: { hypothesis: 'tired not a trait', shift: 0 },
    rating: 3,
    insufficient_information: false,
  }

  it('reviews everything, with Edit only on Q4 to Q6', async () => {
    await open(afterGate(finished, 1))
    expect(app().findAll('[data-testid="review-answer"]')).toHaveLength(6)
    expect(
      app()
        .findAll('button')
        .filter((b) => b.text() === 'Edit'),
    ).toHaveLength(3)
    expect(app().text()).toContain('0 is unchanged')
  })

  it('asks first, saves, submits and goes back to the list', async () => {
    await open(afterGate(finished, 1))
    await buttonNamed('Submit answers').trigger('click')
    expect(calls.filter((c) => c.url.endsWith('/submit'))).toHaveLength(0)
    await app()
      .get('dialog[open]')
      .findAll('button')
      .find((b) => b.text() === 'Submit answers')
      ?.trigger('click')
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/assignments'))
    expect(calls.filter((c) => c.url.endsWith('/submit'))).toHaveLength(1)
    expect(router.currentRoute.value.query.submitted).toBe('V007')
  })

  it('needs a direction on citations added after the lock-in', async () => {
    await open(
      afterGate(
        { ...finished, highlights: [...finished.highlights, citation(2, 'hand starts')] },
        1,
      ),
    )
    expect(buttonNamed('Submit answers').attributes('disabled')).toBeDefined()
    expect(app().text()).toContain('Choose a direction for citation 2.')
  })

  it('shows a submitted vignette read-only, and hovering still lights the text', async () => {
    const submitted = {
      ...afterGate(finished, 1),
      state: 'expert_check' as const,
      allowed_actions: [],
      submitted_at: 'now',
    }
    serve(submitted)
    const fetchMock = globalThis.fetch as ReturnType<typeof vi.fn>
    const original = fetchMock.getMockImplementation()
    fetchMock.mockImplementation(async (input: Request) =>
      urlOf(input).endsWith('/submission')
        ? jsonResponse(200, {
            assignment_id: 'a1',
            payload_format: 2,
            vignette_hash: 'x',
            submitted_at: 'now',
            payload: finished,
          })
        : (original as (i: Request) => Promise<Response>)(input),
    )
    await router.push('/assignments/a1')
    wrapper = mount(App, { global: { plugins: [router] }, attachTo: document.body })
    await flushPromises()
    await flushPromises()

    expect(
      app()
        .findAll('button')
        .some((b) => b.text() === 'Submit answers'),
    ).toBe(false)
    expect(
      app()
        .findAll('button')
        .some((b) => b.text() === 'Edit'),
    ).toBe(false)
    await rows()[0]?.trigger('mouseenter')
    expect(marked().text()).toBe('barely slept')
  })
})
