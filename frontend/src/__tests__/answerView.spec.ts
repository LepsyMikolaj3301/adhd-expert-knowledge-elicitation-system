import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import App from '@/App.vue'
import type { AnswerPayload, Citation, ExpertAssignment, QuestionView } from '@/api/client'
import ChipEditor from '@/components/answering/ChipEditor.vue'
import router from '@/router'
import { installSessionHandler } from '@/session'
import { acknowledgeIntro } from '@/intro'
import { useAuthStore } from '@/stores/auth'

import { expert, jsonResponse, urlOf } from './helpers'

const ROUND = { review_round: 1 }

const TEXT = 'I have barely slept since the move. My hand starts shaking slightly.'
const FIFTEEN = 'one two three four five six seven eight nine ten eleven twelve thirteen a15 b15'
const TEN = 'one two three four five six seven eight nine ten'

const GATE: QuestionView[] = [
  { id: 'Q1', kind: 'open', text: 'Which fragments matter?' },
  { id: 'Q2', kind: 'open', text: 'Which could be something else?' },
  { id: 'Q3', kind: 'open', text: 'What is missing?' },
]
const LATER: QuestionView[] = [
  {
    id: 'Q4',
    kind: 'shift',
    text: 'Given your hypothesis: how would it change if the writer had an exam?',
    wording: {
      hypothesis: 'Your working hypothesis, in one sentence',
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
  { id: 'Q5', kind: 'open', text: 'What would a junior clinician misread?' },
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
    // Spread, not written out: the field only exists in newer API types, and this builds with both.
    ...ROUND,
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
const block = (id: string) => app().get(`[data-question="${id}"]`)
const rows = () => app().findAll('[data-testid="citation"]')
const step = (label: string) =>
  app()
    .findAll('[data-testid="step"]')
    .find((s) => s.text().replace('●', '').trim() === label)!
const currentStep = () =>
  app().get('[data-testid="step"][aria-current="step"]').text().replace('●', '').trim()

async function confirmRemoval() {
  await app()
    .get('dialog[open]')
    .findAll('button')
    .find((b) => b.text() === 'Remove quote')
    ?.trigger('click')
  await flushPromises()
}

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

// jsdom has no layout, and focusing an editor scrolls the cursor into view.
beforeAll(() => {
  const noRects = () => [] as unknown as DOMRectList
  Range.prototype.getClientRects = noRects
  Element.prototype.getClientRects = noRects
  Range.prototype.getBoundingClientRect = () => new DOMRect()
})

beforeEach(async () => {
  setActivePinia(createPinia())
  installSessionHandler(router)
  const auth = useAuthStore()
  auth.user = expert
  auth.loaded = true
  // These tests are about the case, not the instructions that come before it.
  acknowledgeIntro(expert.id, true)
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

  it('lights a quote only while its citation row is hovered', async () => {
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

  it('lights a quote while its row has keyboard focus', async () => {
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

  it('does not add the same quote twice', async () => {
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
  it('keeps My cases marked as the current section inside a case', async () => {
    await open(assignment({}))
    const current = app().get('nav[aria-label="Main"] a[aria-current="page"]')
    expect(current.text()).toBe('My cases')
  })
})

describe('moving through the questions', () => {
  it('shows Q1 to Q3 together with one lock-in button, and never Q4 before the lock-in', async () => {
    await open(assignment({ answers: {}, highlights: [] }))
    const headings = app().findAll('[data-testid="question"]')
    expect(headings.map((h) => h.text())).toEqual([
      expect.stringContaining('Which fragments matter?'),
      expect.stringContaining('Which could be something else?'),
      expect.stringContaining('What is missing?'),
    ])
    expect(app().findAll('.chip-editor')).toHaveLength(3)
    expect(app().text()).not.toContain('writer had an exam')
    expect(buttonNamed('Lock in results')).toBeTruthy()
    expect(
      app()
        .findAll('button')
        .some((b) => b.text() === 'Next question'),
    ).toBe(false)
  })

  it('says that locking in is final, and no longer shows a padlock in the rail', async () => {
    await open(assignment({ answers: {}, highlights: [] }))
    expect(app().get('[data-testid="gate-note"]').text()).toContain("you can't change them")
    const rail = app().get('nav[aria-label="Questions"]')
    expect(rail.find('svg').exists()).toBe(false)
    expect(rail.find('[data-testid="gate-divider"]').exists()).toBe(true)
  })

  it('lets Q1 to Q3 be reached in any order, however little is written', async () => {
    await open(assignment({ answers: { Q1: 'too short' }, highlights: [] }))
    expect(block('Q1').text()).toContain('2 words')
    const steps = app().findAll('[data-testid="step"]')
    expect(steps.slice(0, 3).map((s) => s.attributes('disabled'))).toEqual([
      undefined,
      undefined,
      undefined,
    ])
    expect(step('Q4').attributes('disabled')).toBeDefined()
  })

  it('scrolls to the question clicked in the rail', async () => {
    const scrolled: (string | undefined)[] = []
    Element.prototype.scrollIntoView = function (this: Element) {
      scrolled.push(this.getAttribute('data-question') ?? undefined)
    }
    try {
      await open(assignment({ answers: {}, highlights: [] }))
      await step('Q3').trigger('click')
      await flushPromises()
      expect(currentStep()).toBe('Q3')
      expect(scrolled).toContain('Q3')
    } finally {
      Reflect.deleteProperty(Element.prototype, 'scrollIntoView')
    }
  })

  it('follows the cursor in the rail', async () => {
    await open(assignment({ answers: {}, highlights: [] }))
    await block('Q2').trigger('focusin')
    expect(currentStep()).toBe('Q2')
  })

  it('only asks for all three answers when locking in', async () => {
    await open(assignment({ answers: { Q1: 'short', Q3: 'also short' }, highlights: [] }))
    expect(buttonNamed('Lock in results').attributes('aria-disabled')).toBe('true')
    expect(app().text()).toContain('Q2 needs an answer.')
  })

  it('shows nothing red until the button has been pressed', async () => {
    await open(assignment({ answers: { Q1: 'short', Q3: 'also short' }, highlights: [] }))
    expect(app().find('[data-problem="true"]').exists()).toBe(false)
    expect(app().get('[data-testid="blocker"]').classes()).not.toContain('text-danger')
  })

  it('marks what is missing when the button is pressed, and goes nowhere', async () => {
    await open(assignment({ answers: { Q1: FIFTEEN, Q3: FIFTEEN }, highlights: [] }))
    await buttonNamed('Lock in results').trigger('click')
    expect(app().find('dialog[open]').exists()).toBe(false)
    expect(app().get('[data-testid="blocker"]').classes()).toContain('text-danger')
    expect(step('Q2').attributes('data-problem')).toBe('true')
    expect(step('Q1').attributes('data-problem')).toBeUndefined()
    expect(block('Q2').get('[data-testid="problem"]').text()).toBe('Q2 needs an answer.')
    expect(block('Q1').find('[data-testid="problem"]').exists()).toBe(false)
  })

  it('clears the mark on a question as soon as it is answered', async () => {
    await open(assignment({ answers: { Q1: FIFTEEN, Q3: FIFTEEN }, highlights: [] }))
    await buttonNamed('Lock in results').trigger('click')
    expect(step('Q2').attributes('data-problem')).toBe('true')
    // The second box is Q2's.
    app().findAllComponents(ChipEditor)[1]?.vm.$emit('update:modelValue', FIFTEEN)
    await flushPromises()
    expect(step('Q2').attributes('data-problem')).toBeUndefined()
    expect(block('Q2').find('[data-testid="problem"]').exists()).toBe(false)
  })

  it('heads each question with "Question N", not the short id', async () => {
    await open(assignment({ answers: {}, highlights: [] }))
    expect(heading()).toMatch(/^Question 1\s*Which fragments matter\?/)
  })

  it('counts every word, even a repeated one', async () => {
    await open(
      afterGate(
        {
          answers: { ...GATE_ANSWERS, Q5: `${TEN} ten` },
          q4: { hypothesis: 'tired not a trait', shift: 0 },
        },
        0,
      ),
    )
    expect(block('Q5').get('[data-testid="word-count"]').text()).toBe('11 words')
  })

  it('opens on the first unanswered question', async () => {
    await open(assignment({ answers: { Q1: FIFTEEN, Q2: TEN }, highlights: [] }))
    expect(currentStep()).toBe('Q3')
  })
})

describe('locking in', () => {
  it('needs a direction on every citation', async () => {
    await open(assignment({ answers: GATE_ANSWERS, highlights: [citation(1, 'barely slept')] }))
    expect(buttonNamed('Lock in results').attributes('aria-disabled')).toBe('true')
    expect(app().text()).toContain('Choose a direction for quote 1.')
    await rows()[0]?.get('select').setValue('away')
    expect(buttonNamed('Lock in results').attributes('aria-disabled')).toBeUndefined()
  })

  it('marks a quote without a direction once the button is pressed, then clears it', async () => {
    await open(assignment({ answers: GATE_ANSWERS, highlights: [citation(1, 'barely slept')] }))
    expect(rows()[0]?.get('select').attributes('data-missing')).toBeUndefined()
    await buttonNamed('Lock in results').trigger('click')
    expect(app().find('dialog[open]').exists()).toBe(false)
    expect(rows()[0]?.get('select').attributes('data-missing')).toBe('true')
    expect(app().find('[data-testid="direction-missing"]').exists()).toBe(true)
    await rows()[0]?.get('select').setValue('away')
    expect(rows()[0]?.get('select').attributes('data-missing')).toBeUndefined()
    expect(app().find('[data-testid="direction-missing"]').exists()).toBe(false)
  })

  it('asks first, then saves, then passes the gate and shows Q4', async () => {
    await open(assignment({ answers: GATE_ANSWERS, highlights: [citation(1, 'barely slept')] }))
    await rows()[0]?.get('select').setValue('away')
    await buttonNamed('Lock in results').trigger('click')
    expect(calls.filter((c) => c.url.endsWith('/pass-gate'))).toHaveLength(0)
    expect(app().get('dialog[open]').text()).toContain('not mentioned')

    await app()
      .get('dialog[open]')
      .findAll('button')
      .find((b) => b.text() === 'Lock in results')
      ?.trigger('click')
    await flushPromises()

    const writes = calls.filter((c) => c.method !== 'GET').map((c) => c.method)
    expect(writes).toEqual(['PUT', 'POST'])
    expect(block('Q4').text()).toContain('the writer had an exam')
    expect(currentStep()).toBe('Q4')
    expect(buttonNamed('Review answers')).toBeTruthy()
  })

  it('warns about no citations at all, without blocking', async () => {
    await open(assignment({ answers: GATE_ANSWERS, highlights: [] }))
    await buttonNamed('Lock in results').trigger('click')
    expect(app().get('dialog[open]').text()).toContain("haven't added any quotes")
  })

  it('keeps locked questions on screen read-only, with their chips, above the open ones', async () => {
    const payload = {
      answers: { ...GATE_ANSWERS, Q1: `⟦h1⟧ ${FIFTEEN}` },
      highlights: [citation(1, 'barely slept', 'away')],
    }
    await open(afterGate(payload, 1))
    expect(app().findAll('[data-testid="question"]')).toHaveLength(6)
    for (const id of ['Q1', 'Q2', 'Q3']) {
      expect(block(id).find('.chip-editor').exists()).toBe(false)
    }
    expect(block('Q5').find('.chip-editor').exists()).toBe(true)
    expect(app().get('[data-testid="gate-note"]').text()).toContain('locked')

    await block('Q1').get('[data-chip="1"]').trigger('mouseover')
    expect(marked().text()).toBe('barely slept')
  })

  it('indents a list in a locked answer, and keeps its text as written', async () => {
    const answers = { ...GATE_ANSWERS, Q2: 'intro\n1. first ⟦h1⟧\n- second\nend' }
    await open(afterGate({ answers, highlights: [citation(1, 'barely slept', 'away')] }, 1))
    const lines = block('Q2').findAll('.list-line')
    expect(lines.map((l) => l.text())).toEqual(['1. first 1', '- second'])
    expect(block('Q2').text()).toContain('intro')
    expect(block('Q2').text()).toContain('end')
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
    await confirmRemoval()
    expect(rows()).toHaveLength(1)
  })

  it('shows what went wrong when the server refuses, and stays on Q3', async () => {
    await open(assignment({ answers: GATE_ANSWERS, highlights: [] }))
    const fetchMock = globalThis.fetch as ReturnType<typeof vi.fn>
    const original = fetchMock.getMockImplementation()
    fetchMock.mockImplementation(async (input: Request) =>
      urlOf(input).endsWith('/pass-gate')
        ? jsonResponse(422, {
            code: 'gate_not_passed',
            message: 'Q3 needs an answer.',
            details: { missing: ['Q3'] },
          })
        : (original as (i: Request) => Promise<Response>)(input),
    )
    await buttonNamed('Lock in results').trigger('click')
    await app()
      .get('dialog[open]')
      .findAll('button')
      .find((b) => b.text() === 'Lock in results')
      ?.trigger('click')
    await flushPromises()
    expect(app().get('[role="alert"]').text()).toBe('Please answer questions 1–3 first.')
    expect(app().text()).toContain('What is missing?')
    expect(app().text()).not.toContain('writer had an exam')
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
    expect(app().get('dialog[open]').text()).toContain('cited once')
    await confirmRemoval()
    expect(rows()).toHaveLength(1)
    expect(rows()[0]?.text()).toContain('hand starts')
    expect(block('Q1').find('[data-chip="1"]').exists()).toBe(true)
    expect(block('Q1').find('[data-chip="2"]').exists()).toBe(false)
  })

  it('asks even when it is not cited, and warns about the numbers in red', async () => {
    await open(
      assignment({
        answers: {},
        highlights: [
          citation(1, 'barely slept'),
          citation(2, 'hand starts'),
          citation(3, 'shaking'),
        ],
      }),
    )
    await rows()[0]
      ?.findAll('button')
      .find((b) => b.text() === 'Remove')
      ?.trigger('click')
    const dialog = app().get('dialog[open]')
    expect(rows()).toHaveLength(3)
    expect(dialog.text()).toContain("isn't cited in any answer")
    const note = dialog.get('[data-testid="renumber-note"]')
    expect(note.text()).toBe('Quotes 2–3 will be renumbered 1–2.')
    expect(note.classes()).toContain('alert')
    expect(note.find('svg').exists()).toBe(true)
    expect(dialog.find('.btn-danger').exists()).toBe(true)

    await dialog
      .findAll('button')
      .find((b) => b.text() === 'Keep it')
      ?.trigger('click')
    expect(rows()).toHaveLength(3)
  })

  it('has nothing to say about numbers when the last one goes', async () => {
    await open(
      assignment({
        answers: {},
        highlights: [citation(1, 'barely slept'), citation(2, 'hand starts')],
      }),
    )
    await rows()[1]
      ?.findAll('button')
      .find((b) => b.text() === 'Remove')
      ?.trigger('click')
    expect(app().get('dialog[open]').find('[data-testid="renumber-note"]').exists()).toBe(false)
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

  it('does not show a Q4 direction that will not be submitted', async () => {
    // Start at +1 towards more ADHD-like, then move the scale to -1 in the same session: the screen
    // remembers the hidden "towards", but saving drops it, so Review must not show it.
    await open(
      afterGate(
        {
          ...finished,
          q4: { hypothesis: 'tired not a trait', shift: 1, toward: 'more_adhd' },
          answers: { ...finished.answers, Q4: 'because of the exam it moves' },
        },
        1,
      ),
    )
    expect(app().text()).toContain('towards more ADHD-like')

    await app()
      .findAll('button')
      .find((b) => b.text() === 'Edit')
      ?.trigger('click')
    const minusOne = app().get('input[name="q4-shift"][value="-1"]')
    ;(minusOne.element as HTMLInputElement).checked = true
    await minusOne.trigger('change')
    await app()
      .findAll('[data-testid="step"]')
      .find((s) => s.text() === 'Review')
      ?.trigger('click')

    expect(app().text()).toContain('somewhat reinforced')
    expect(app().text()).not.toContain('towards')
  })

  it('does not count a reference in a hidden Q4 answer as used', async () => {
    // At shift 0 the "why" is dropped when saving, so a reference only there is not in the answers.
    await open(
      afterGate(
        {
          ...finished,
          answers: { ...GATE_ANSWERS, Q4: '⟦h1⟧ left over', Q5: TEN },
          q4: { hypothesis: 'tired not a trait', shift: 0 },
        },
        1,
      ),
    )
    expect(app().text()).toContain('is not mentioned in any answer')
  })

  it('needs a direction on citations added after the lock-in', async () => {
    await open(
      afterGate(
        { ...finished, highlights: [...finished.highlights, citation(2, 'hand starts')] },
        1,
      ),
    )
    expect(buttonNamed('Submit answers').attributes('aria-disabled')).toBe('true')
    expect(app().text()).toContain('Choose a direction for quote 2.')
  })

  it('shows a submitted vignette read-only, and hovering still lights the text', async () => {
    const submitted = {
      ...afterGate(finished, 1),
      state: 'processing' as const,
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

  it('does not look locked once submitted', async () => {
    const submitted = {
      ...afterGate(finished, 1),
      state: 'processing' as const,
      allowed_actions: [],
      submitted_at: 'now',
    }
    await open(submitted)
    expect(app().text()).not.toContain('Locked')
    expect(app().text()).not.toContain('locked')
  })
})

describe('when saving does not work', () => {
  /** Answers every save with `reply`, and every other call as before. Counts the saves. */
  function answerSavesWith(reply: () => Response, login?: () => Response) {
    const fetchMock = globalThis.fetch as ReturnType<typeof vi.fn>
    const original = fetchMock.getMockImplementation() as (i: Request) => Promise<Response>
    const saves = { count: 0 }
    fetchMock.mockImplementation(async (input: Request) => {
      if (input.method === 'PUT') {
        saves.count++
        return reply()
      }
      if (login && urlOf(input).endsWith('/auth/login')) return login()
      return original(input)
    })
    return saves
  }

  afterEach(() => {
    vi.useRealTimers()
    Reflect.deleteProperty(navigator, 'clipboard')
  })

  async function editAndWaitForSave() {
    await selectInText('barely slept')
    await vi.advanceTimersByTimeAsync(2100)
  }

  it('says why a refused save cannot work, stops retrying, and offers to copy the text', async () => {
    vi.useFakeTimers()
    await open(assignment({ answers: { Q1: FIFTEEN }, highlights: [] }))
    const saves = answerSavesWith(() =>
      jsonResponse(422, { code: 'not_editable', message: 'x', details: { state: 'cancelled' } }),
    )
    await editAndWaitForSave()

    const problem = app().get('[data-testid="save-problem"]')
    expect(problem.text()).toContain("couldn't be saved")
    expect(problem.text()).toContain('cancelled this case')
    expect(buttonNamed('Copy my text')).toBeTruthy()
    expect(app().get('[data-testid="save-status"]').text()).toBe('Not saved')

    await vi.advanceTimersByTimeAsync(30_000)
    expect(saves.count).toBe(1)
  })

  it('copies what was written, word for word, with references as [n]', async () => {
    vi.useFakeTimers()
    const writeText = vi.fn<(text: string) => Promise<void>>().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    await open(
      assignment({ answers: { Q1: `⟦h1⟧ ${FIFTEEN}` }, highlights: [citation(1, 'hand starts')] }),
    )
    answerSavesWith(() => jsonResponse(422, { code: 'not_editable', message: 'x' }))
    await editAndWaitForSave()

    await buttonNamed('Copy my text').trigger('click')
    await vi.advanceTimersByTimeAsync(0)
    expect(writeText).toHaveBeenCalledWith(`Q1\n[1] ${FIFTEEN}`)
    expect(app().get('[data-testid="save-problem"]').text()).toContain('Copied.')
  })

  it('shows the unsaved text before it offers the saved version, after a change in another tab', async () => {
    vi.useFakeTimers()
    await open(assignment({ answers: { Q1: FIFTEEN }, highlights: [] }))
    answerSavesWith(() =>
      jsonResponse(409, { code: 'draft_conflict', message: 'Saved elsewhere.' }),
    )
    await editAndWaitForSave()

    const conflict = app().get('[data-testid="conflict"]')
    expect(conflict.text()).toContain('changed in another tab or device')
    expect(conflict.get('textarea').element.value).toContain(FIFTEEN)
    expect(conflict.get('textarea').attributes('readonly')).toBeDefined()
    expect(buttonNamed('Copy my text')).toBeTruthy()
    expect(buttonNamed('Load saved version')).toBeTruthy()
  })

  it('keeps the page and the text when the session ends, and saves after signing in again', async () => {
    vi.useFakeTimers()
    await open(assignment({ answers: { Q1: FIFTEEN }, highlights: [] }))
    let signedIn = false
    const saves = answerSavesWith(
      () =>
        signedIn
          ? jsonResponse(200, { version: 2, updated_at: 'now' })
          : jsonResponse(401, { code: 'not_authenticated', message: 'Please log in.' }),
      () => {
        signedIn = true
        return jsonResponse(200, expert)
      },
    )
    await editAndWaitForSave()

    const dialog = app().get('dialog[open]')
    expect(dialog.text()).toContain('Please sign in again')
    expect(dialog.text()).toContain(expert.email)
    expect(router.currentRoute.value.path).toBe('/assignments/a1')
    await vi.advanceTimersByTimeAsync(30_000)
    expect(saves.count).toBe(1)

    await dialog.get('input[type="password"]').setValue('secret-password')
    await dialog.get('form').trigger('submit')
    await vi.advanceTimersByTimeAsync(50)

    expect(app().find('dialog[open]').exists()).toBe(false)
    expect(saves.count).toBe(2)
    expect(app().get('[data-testid="save-status"]').text()).toBe('Saved')
  })

  it('shows the reason when signing in again fails, and keeps the dialog', async () => {
    vi.useFakeTimers()
    await open(assignment({ answers: { Q1: FIFTEEN }, highlights: [] }))
    answerSavesWith(
      () => jsonResponse(401, { code: 'not_authenticated', message: 'Please log in.' }),
      () => jsonResponse(401, { code: 'invalid_credentials', message: 'Wrong email or password.' }),
    )
    await editAndWaitForSave()

    const dialog = app().get('dialog[open]')
    await dialog.get('input[type="password"]').setValue('wrong')
    await dialog.get('form').trigger('submit')
    await vi.advanceTimersByTimeAsync(50)
    expect(dialog.get('[role="alert"]').text()).toBe('Wrong email or password.')
    expect(app().find('dialog[open]').exists()).toBe(true)
  })
})

describe('the quotes', () => {
  it('names them in clinical words, and spells the direction out', async () => {
    await open(
      assignment({
        answers: {},
        highlights: [citation(1, 'barely slept'), citation(2, 'hand starts', 'away')],
      }),
    )
    expect(app().get('#citations-heading').text()).toBe('Quotes')
    expect(
      rows()[0]
        ?.findAll('option')
        .map((o) => o.text()),
    ).toEqual([
      '-',
      'Points toward ADHD traits',
      'Points away from ADHD traits',
      'No bearing',
      'Unclear',
    ])
    expect(rows()[0]?.get('select').attributes('aria-label')).toBe('Direction of quote 1')
    expect((rows()[1]!.get('select').element as HTMLSelectElement).value).toBe('away')
  })

  it('asks for the words the answer is about when nothing is marked yet', async () => {
    await open(assignment({ answers: {}, highlights: [] }))
    expect(app().get('[data-testid="no-citations"]').text()).toBe(
      'Select the words your answer is about.',
    )
  })

  it('explains the directions when the help is opened, and closes it again', async () => {
    await open(assignment({ answers: {}, highlights: [citation(1, 'barely slept')] }))
    const help = () => app().find('[data-testid="direction-help"]')
    const button = app().get('[data-testid="direction-help-button"]')
    expect(help().exists()).toBe(false)
    expect(button.attributes('aria-expanded')).toBe('false')

    await button.trigger('click')
    expect(help().text()).toContain('No bearing')
    expect(help().text()).toContain('says nothing either way')
    expect(button.attributes('aria-expanded')).toBe('true')

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()
    expect(help().exists()).toBe(false)

    await button.trigger('click')
    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    await flushPromises()
    expect(help().exists()).toBe(false)
  })

  it('says how many times each one is cited, across all answers', async () => {
    await open(
      assignment({
        answers: { Q1: '⟦h1⟧ and ⟦h1⟧', Q2: 'also ⟦h1⟧' },
        highlights: [citation(1, 'barely slept'), citation(2, 'hand starts')],
      }),
    )
    const cited = rows().map((r) => r.get('[data-testid="cited-times"]').text())
    expect(cited).toEqual(['Cited 3 times', 'Cited 0 times'])
  })

  it('spells out the direction of a locked quote', async () => {
    const payload = { answers: GATE_ANSWERS, highlights: [citation(1, 'barely slept', 'neutral')] }
    await open(afterGate(payload, 1))
    expect(rows()[0]?.text()).toContain('No bearing')
  })

  it('calls the list of cases My cases, and the case a case', async () => {
    await open(assignment({}))
    const header = app().get('header')
    expect(header.text()).toContain('My cases')
    expect(header.text()).toContain('Case V007')
  })
})

describe('adding a reference by clicking the quote', () => {
  const addButton = (index = 0) => rows()[index]!.get('[data-testid="add-reference"]')
  const q1Editor = () => app().get('.chip-editor')

  it('has no separate Cite button any more', async () => {
    await open(assignment({ answers: {}, highlights: [citation(1, 'barely slept')] }))
    expect(
      app()
        .findAll('button')
        .some((b) => b.text() === 'Cite'),
    ).toBe(false)
  })

  it('adds the reference to the answer when the quote is clicked, and saves it as such', async () => {
    vi.useFakeTimers()
    try {
      await open(
        assignment({ answers: { Q1: 'because' }, highlights: [citation(1, 'barely slept')] }),
      )
      await step('Q1').trigger('click')
      await addButton().trigger('click')
      await vi.advanceTimersByTimeAsync(2100)

      expect(q1Editor().find('[data-chip="1"]').exists()).toBe(true)
      const put = calls.find((c) => c.method === 'PUT')
      expect(put?.body?.payload.answers.Q1).toBe('because⟦h1⟧ ')
    } finally {
      vi.useRealTimers()
    }
  })

  it('keeps the cursor in the answer while clicking', async () => {
    await open(assignment({ answers: {}, highlights: [citation(1, 'barely slept')] }))
    const press = new MouseEvent('mousedown', { bubbles: true, cancelable: true })
    addButton().element.dispatchEvent(press)
    expect(press.defaultPrevented).toBe(true)
  })

  it('does not add a reference when the direction is chosen or the quote is removed', async () => {
    await open(
      assignment({
        answers: {},
        highlights: [citation(1, 'barely slept'), citation(2, 'hand starts')],
      }),
    )
    await rows()[0]?.get('select').setValue('away')
    await rows()[1]
      ?.findAll('button')
      .find((b) => b.text() === 'Remove')
      ?.trigger('click')
    await confirmRemoval()
    expect(rows()).toHaveLength(1)
    expect(q1Editor().find('[data-chip]').exists()).toBe(false)
  })

  it('tells a screen reader what the click does', async () => {
    await open(assignment({ answers: {}, highlights: [citation(1, 'barely slept')] }))
    expect(addButton().attributes('aria-label')).toBe(
      'Add reference 1 to your answer: “barely slept”',
    )
    expect(rows()[0]?.text()).toContain('+ Add to answer')
    expect(rows()[0]?.html()).not.toContain('opacity-0')
    expect(app().text()).toContain('Click a quote to add it to your answer at the cursor.')
  })

  it('adds the reference to the question being worked on', async () => {
    await open(assignment({ answers: {}, highlights: [citation(1, 'barely slept')] }))
    await block('Q2').trigger('focusin')
    await addButton().trigger('click')
    await flushPromises()
    expect(block('Q2').find('[data-chip="1"]').exists()).toBe(true)
    expect(block('Q1').find('[data-chip="1"]').exists()).toBe(false)
  })

  it('only lights the quote where there is no answer box', async () => {
    const finished: AnswerPayload = {
      answers: { ...GATE_ANSWERS, Q5: TEN },
      highlights: [citation(1, 'barely slept', 'away')],
      q4: { hypothesis: 'tired not a trait', shift: 0 },
      rating: 3,
      insufficient_information: false,
    }
    await open(afterGate(finished, 1))
    expect(app().find('.chip-editor').exists()).toBe(false)
    expect(addButton().attributes('aria-label')).toBe('Show quote 1 in the text: “barely slept”')
    expect(rows()[0]?.text()).not.toContain('+ Add to answer')
    expect(app().text()).toContain('Click a quote to find it in the text.')

    await addButton().trigger('click')
    expect(marked().text()).toBe('barely slept')
    expect(calls.filter((c) => c.method === 'PUT')).toHaveLength(0)
  })

  it('adds to the first open answer when the question being looked at is locked', async () => {
    const payload = {
      answers: GATE_ANSWERS,
      highlights: [citation(1, 'barely slept', 'away')],
    }
    await open(afterGate(payload, 1))
    await step('Q1').trigger('click')
    await addButton().trigger('click')
    await flushPromises()
    expect(block('Q1').find('[data-chip]').exists()).toBe(false)
    expect(block('Q5').find('[data-chip="1"]').exists()).toBe(true)
  })
})
