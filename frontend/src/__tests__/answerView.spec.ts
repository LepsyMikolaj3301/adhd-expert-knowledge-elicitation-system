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

const FIRST: QuestionView[] = [
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
    allowed_actions: ['save_draft', 'submit'],
    updated_at: 'now',
    vignette: {
      code: 'V007',
      version: 1,
      text: TEXT,
      framing: 'personal_journal',
      patient_summary: 'A student.',
      word_count: 12,
      content_hash: 'x',
      questions: [...FIRST, ...LATER],
    },
    draft: { version: 1, payload, updated_at: 'now' },
    started_at: 'now',
    submitted_at: null,
    ...overrides,
  }
}

const FIRST_ANSWERS = { Q1: FIFTEEN, Q2: TEN, Q3: TEN }
/** Everything answered: the review can be reached. */
const DONE: Partial<AnswerPayload> = {
  answers: { ...FIRST_ANSWERS, Q5: TEN },
  q4: { hypothesis: 'tired not a trait', shift: 0 },
  rating: 3,
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
      if (url.endsWith('/submit')) {
        current = { ...current, state: 'proofreading', allowed_actions: [], submitted_at: 'now' }
      } else if (url.endsWith('/assignments')) {
        return jsonResponse(200, [])
      } else if (url.endsWith('/proofread')) {
        // Nothing proofread yet: the shape the page expects, not the assignment.
        return jsonResponse(200, {
          items: [],
          highlights: [],
          flags: [],
          passes: {},
          feedback: [],
          editable: false,
          submitted_at: null,
        })
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

/** An assignment in progress with these answers (the lock is gone: everything is open). */
function withAnswers(payload: Partial<AnswerPayload>): ExpertAssignment {
  return assignment(payload)
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

/** Drag over the words: the selection is made, the pointer lifts, nothing is added yet. */
async function dragOver(text: string) {
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
  document.dispatchEvent(new Event('selectionchange'))
  window.dispatchEvent(new Event('pointerup'))
  await flushPromises()
}

/** The "Add quote" button, which lives at the bottom of the screen, outside the app's tree. */
function addQuoteButton(): HTMLButtonElement | null {
  return document.querySelector('[data-testid="add-quote"]')
}

async function pressAddQuote() {
  const button = addQuoteButton()
  if (!button) throw new Error('no "Add quote" button')
  button.dispatchEvent(new Event('pointerdown', { cancelable: true }))
  // The phone drops the selection as the button is touched.
  window.getSelection()?.removeAllRanges()
  document.dispatchEvent(new Event('selectionchange'))
  await flushPromises()
  button.click()
  await flushPromises()
}

async function selectInText(text: string) {
  await dragOver(text)
  await pressAddQuote()
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
  it('labels the patient text, with the summary in a box of its own above it', async () => {
    await open(assignment({ answers: {}, highlights: [] }))
    const summary = app().get('[data-testid="patient-summary"]')
    expect(summary.text()).toContain('About the patient')
    expect(summary.text()).toContain('A student.')
    expect(summary.element.contains(app().get('[data-testid="vignette-text"]').element)).toBe(false)
    expect(app().text()).toContain('Patient text')
    expect(app().text()).toContain('This is the text you analyse')
  })

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

  it('adds nothing when the pointer lifts: the selection waits for "Add quote"', async () => {
    await open(assignment({ answers: {}, highlights: [] }))
    expect(addQuoteButton()).toBeNull()
    await dragOver('barely slept')
    expect(rows()).toHaveLength(0)
    expect(addQuoteButton()?.textContent).toContain('Add quote')
    expect(window.getSelection()?.isCollapsed).toBe(false)
  })

  it('hides "Add quote" when the selection goes away', async () => {
    await open(assignment({ answers: {}, highlights: [] }))
    await dragOver('barely slept')
    window.getSelection()?.removeAllRanges()
    document.dispatchEvent(new Event('selectionchange'))
    await flushPromises()
    expect(addQuoteButton()).toBeNull()
    expect(rows()).toHaveLength(0)
  })

  it('offers no "Add quote" for words selected outside the patient text', async () => {
    await open(assignment({ answers: {}, highlights: [] }))
    const range = document.createRange()
    range.selectNodeContents(app().get('h1').element)
    window.getSelection()?.removeAllRanges()
    window.getSelection()?.addRange(range)
    document.dispatchEvent(new Event('selectionchange'))
    await flushPromises()
    expect(addQuoteButton()).toBeNull()
  })

  it('adds one quote from the keyboard too', async () => {
    await open(assignment({ answers: {}, highlights: [] }))
    await dragOver('barely slept')
    addQuoteButton()!.click()
    await flushPromises()
    addQuoteButton()?.click()
    await flushPromises()
    expect(rows()).toHaveLength(1)
    expect(addQuoteButton()).toBeNull()
  })

  it('ignores selections on a submitted vignette', async () => {
    await open(
      assignment(
        { answers: FIRST_ANSWERS, highlights: [] },
        { state: 'processing', allowed_actions: [], submitted_at: 'now' },
      ),
    )
    await dragOver('barely slept')
    expect(rows()).toHaveLength(0)
    expect(addQuoteButton()).toBeNull()
  })

  it('puts "How to add a quote" under the text box, and only while quotes can be added', async () => {
    await open(assignment({ answers: {}, highlights: [] }))
    const help = app().get('[data-testid="cite-help"]')
    expect(help.text()).toBe('How to add a quote')
    expect(
      app().get('[aria-labelledby="h-patient-text"]').find('[data-testid="cite-help"]').exists(),
    ).toBe(false)
    wrapper?.unmount()
    await open(
      assignment(
        { answers: FIRST_ANSWERS, highlights: [] },
        { state: 'processing', allowed_actions: [], submitted_at: 'now' },
      ),
    )
    expect(app().find('[data-testid="cite-help"]').exists()).toBe(false)
  })

  it('shows words being selected and "Add quote" pressed in the help, once it is open', async () => {
    await open(assignment({ answers: {}, highlights: [] }))
    expect(app().find('[data-testid="cite-demo"]').exists()).toBe(false)
    await app().get('[data-testid="cite-help"]').trigger('focusin')
    const demo = app().get('[data-testid="cite-demo"]')
    expect(demo.find('svg.cursor').exists()).toBe(true)
    expect(demo.get('.words').text()).toContain('lose my keys')
    expect(demo.get('[data-testid="cite-demo-button"]').text()).toBe('+ Add quote')
    expect(demo.find('.tap').exists()).toBe(true)
    expect(app().text()).toContain('then press “Add quote” at the bottom of the screen')
  })

  it('says how the text was written in the text box, not in the breadcrumb', async () => {
    await open(assignment({}))
    const box = app().get('[aria-labelledby="h-patient-text"]')
    expect(box.get('[data-testid="text-type"]').text()).toBe('Written as: Journal entry')
    expect(app().get('header').text()).not.toContain('Journal entry')
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
  it('shows every question at once, with nothing locked', async () => {
    await open(assignment({ answers: {}, highlights: [] }))
    const headings = app().findAll('[data-testid="question"]')
    expect(headings).toHaveLength(6)
    expect(headings[3]?.text()).toContain('writer had an exam')
    expect(app().findAll('.chip-editor')).toHaveLength(4)
    expect(app().find('[data-testid="gate-note"]').exists()).toBe(false)
    expect(app().text()).not.toContain('Lock in')
    expect(app().text()).not.toMatch(/locked/i)
    const rail = app().get('nav[aria-label="Questions"]')
    expect(rail.find('[data-testid="gate-divider"]').exists()).toBe(false)
  })

  it('lets every question be reached in any order, however little is written', async () => {
    await open(assignment({ answers: { Q5: 'too short' }, highlights: [] }))
    expect(block('Q5').text()).toContain('2 words')
    const steps = app().findAll('[data-testid="step"]')
    expect(steps.slice(0, 6).map((s) => s.attributes('disabled'))).toEqual(Array(6).fill(undefined))
    expect(step('Review').attributes('disabled')).toBeDefined()
    await step('Q6').trigger('click')
    expect(currentStep()).toBe('Q6')
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

  it('follows what is typed, even when the cursor never left the box', async () => {
    await open(assignment({ answers: {}, highlights: [] }))
    await step('Q3').trigger('click')
    expect(currentStep()).toBe('Q3')
    app().findAllComponents(ChipEditor)[1]?.vm.$emit('update:modelValue', 'a few words')
    await flushPromises()
    expect(currentStep()).toBe('Q2')
  })

  it('follows the scrolling, but not the scroll that a click in the rail starts', async () => {
    const top: Record<string, number> = { Q1: -600, Q2: 100, Q3: 900 }
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (
      this: HTMLElement,
    ) {
      return { top: top[this.getAttribute('data-question') ?? ''] ?? 5000 } as DOMRect
    })
    // jsdom has no layout: a page that is taller than the window, so it is not "at the end".
    vi.spyOn(document.documentElement, 'scrollHeight', 'get').mockReturnValue(9000)
    try {
      await open(assignment({ answers: {}, highlights: [] }))
      window.dispatchEvent(new Event('scroll'))
      await flushPromises()
      expect(currentStep()).toBe('Q2')
      await step('Q3').trigger('click')
      top.Q2 = -900
      top.Q3 = 100
      window.dispatchEvent(new Event('scroll'))
      await flushPromises()
      expect(currentStep()).toBe('Q3')
      top.Q3 = 900
      top.Q2 = 100
      window.dispatchEvent(new Event('scroll'))
      await flushPromises()
      // Still inside the moment after the click: the jump's own scroll is not read.
      expect(currentStep()).toBe('Q3')
    } finally {
      vi.restoreAllMocks()
    }
  })

  it('puts the cursor in the question picked in the rail', async () => {
    const focused: (string | null | undefined)[] = []
    const focus = vi.spyOn(HTMLElement.prototype, 'focus').mockImplementation(function (
      this: HTMLElement,
    ) {
      focused.push(this.closest('[data-question]')?.getAttribute('data-question'))
    })
    try {
      await open(assignment({ answers: {}, highlights: [] }))
      await step('Q3').trigger('click')
      // The editor puts its cursor in on the next animation frame.
      await vi.waitFor(() => expect(focused).toContain('Q3'))
    } finally {
      focus.mockRestore()
    }
  })

  it('asks for every answer before the review', async () => {
    await open(assignment({ answers: { Q1: 'short', Q3: 'also short' }, highlights: [] }))
    expect(buttonNamed('Review answers').attributes('aria-disabled')).toBe('true')
    expect(app().text()).toContain('Q2 needs an answer.')
  })

  it('shows nothing red until the button has been pressed', async () => {
    await open(assignment({ answers: { Q1: 'short', Q3: 'also short' }, highlights: [] }))
    expect(app().find('[data-problem="true"]').exists()).toBe(false)
    expect(app().get('[data-testid="blocker"]').classes()).not.toContain('text-danger')
  })

  it('marks what is missing when the button is pressed, and goes nowhere', async () => {
    await open(assignment({ ...DONE, answers: { Q1: FIFTEEN, Q3: FIFTEEN, Q5: TEN } }))
    await buttonNamed('Review answers').trigger('click')
    expect(app().find('dialog[open]').exists()).toBe(false)
    expect(app().get('[data-testid="blocker"]').classes()).toContain('text-danger')
    expect(step('Q2').attributes('data-problem')).toBe('true')
    expect(step('Q1').attributes('data-problem')).toBeUndefined()
    expect(block('Q2').get('[data-testid="problem"]').text()).toBe('Q2 needs an answer.')
    expect(block('Q1').find('[data-testid="problem"]').exists()).toBe(false)
  })

  it('clears the mark on a question as soon as it is answered', async () => {
    await open(assignment({ ...DONE, answers: { Q1: FIFTEEN, Q3: FIFTEEN, Q5: TEN } }))
    await buttonNamed('Review answers').trigger('click')
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
      withAnswers({
        answers: { ...FIRST_ANSWERS, Q5: `${TEN} ten` },
        q4: { hypothesis: 'tired not a trait', shift: 0 },
      }),
    )
    expect(block('Q5').get('[data-testid="word-count"]').text()).toBe('11 words')
  })

  it('opens on the first unanswered question', async () => {
    await open(assignment({ answers: { Q1: FIFTEEN, Q2: TEN }, highlights: [] }))
    expect(currentStep()).toBe('Q3')
  })
})

describe('quotes and the review', () => {
  it('can add, change and remove any quote at any time', async () => {
    await open(assignment({ ...DONE, highlights: [citation(1, 'barely slept', 'away')] }))
    expect(rows()[0]?.find('select').exists()).toBe(true)
    expect(rows()[0]?.text()).toContain('Remove')
    await selectInText('hand starts')
    expect(rows()).toHaveLength(2)
    await rows()[0]
      ?.findAll('button')
      .find((b) => b.text() === 'Remove')
      ?.trigger('click')
    await confirmRemoval()
    expect(rows()).toHaveLength(1)
  })

  it('needs a direction on every citation before submitting', async () => {
    await open(assignment({ ...DONE, highlights: [citation(1, 'barely slept')] }))
    expect(currentStep()).toBe('Review')
    expect(buttonNamed('Submit for proofreading').attributes('aria-disabled')).toBe('true')
    expect(app().text()).toContain('Choose a direction for quote 1.')
    await rows()[0]?.get('select').setValue('away')
    expect(buttonNamed('Submit for proofreading').attributes('aria-disabled')).toBeUndefined()
  })

  it('marks a quote without a direction once the button is pressed, then clears it', async () => {
    await open(assignment({ ...DONE, highlights: [citation(1, 'barely slept')] }))
    expect(rows()[0]?.get('select').attributes('data-missing')).toBeUndefined()
    await buttonNamed('Submit for proofreading').trigger('click')
    expect(app().find('dialog[open]').exists()).toBe(false)
    expect(rows()[0]?.get('select').attributes('data-missing')).toBe('true')
    await rows()[0]?.get('select').setValue('away')
    expect(rows()[0]?.get('select').attributes('data-missing')).toBeUndefined()
  })

  it('indents a list in an answer on the review, and keeps its text as written', async () => {
    const answers = { ...DONE.answers, Q2: 'intro\n1. first ⟦h1⟧\n- second\nend' }
    await open(assignment({ ...DONE, answers, highlights: [citation(1, 'barely slept', 'away')] }))
    const q2 = app().findAll('[data-testid="review-answer"]')[1]!
    expect(q2.findAll('.list-line').map((l) => l.text())).toEqual(['1. first 1', '- second'])
    expect(q2.text()).toContain('intro')
    expect(q2.text()).toContain('end')
    await q2.get('[data-chip="1"]').trigger('mouseover')
    expect(marked().text()).toBe('barely slept')
  })

  it('shows what went wrong when the server refuses, and stays on the review', async () => {
    await open(assignment({ ...DONE, highlights: [] }))
    const fetchMock = globalThis.fetch as ReturnType<typeof vi.fn>
    const original = fetchMock.getMockImplementation()
    fetchMock.mockImplementation(async (input: Request) =>
      urlOf(input).endsWith('/submit')
        ? jsonResponse(422, {
            code: 'empty_answer',
            message: 'Q3 needs an answer.',
            details: {},
          })
        : (original as (i: Request) => Promise<Response>)(input),
    )
    await buttonNamed('Submit for proofreading').trigger('click')
    await app()
      .get('dialog[open]')
      .findAll('button')
      .find((b) => b.text() === 'Submit for proofreading')
      ?.trigger('click')
    await flushPromises()
    expect(app().get('[role="alert"]').text()).toBe('An answer needs a little more.')
    expect(router.currentRoute.value.path).toBe('/assignments/a1')
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
    await open(withAnswers({ answers: FIRST_ANSWERS, highlights: [], q4 }))
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
    answers: { ...FIRST_ANSWERS, Q5: TEN },
    highlights: [citation(1, 'barely slept', 'away')],
    q4: { hypothesis: 'tired not a trait', shift: 0 },
    rating: 3,
    insufficient_information: false,
  }

  it('reviews everything, with Edit on every answer', async () => {
    await open(withAnswers(finished))
    expect(app().findAll('[data-testid="review-answer"]')).toHaveLength(6)
    expect(
      app()
        .findAll('button')
        .filter((b) => b.text() === 'Edit'),
    ).toHaveLength(6)
    expect(app().text()).toContain('0 is unchanged')
  })

  it('asks first, saves, submits for proofreading and goes back to the list', async () => {
    await open(withAnswers(finished))
    await buttonNamed('Submit for proofreading').trigger('click')
    expect(calls.filter((c) => c.url.endsWith('/submit'))).toHaveLength(0)
    expect(app().get('dialog[open]').text()).toContain('edited ones')
    await app()
      .get('dialog[open]')
      .findAll('button')
      .find((b) => b.text() === 'Submit for proofreading')
      ?.trigger('click')
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/assignments'))
    expect(calls.filter((c) => c.url.endsWith('/submit'))).toHaveLength(1)
    expect(router.currentRoute.value.query.submitted).toBe('V007')
  })

  it('does not show a Q4 direction that will not be submitted', async () => {
    // Start at +1 towards more ADHD-like, then move the scale to -1 in the same session: the screen
    // remembers the hidden "towards", but saving drops it, so Review must not show it.
    await open(
      withAnswers({
        ...finished,
        q4: { hypothesis: 'tired not a trait', shift: 1, toward: 'more_adhd' },
        answers: { ...finished.answers, Q4: 'because of the exam it moves' },
      }),
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
      withAnswers({
        ...finished,
        answers: { ...FIRST_ANSWERS, Q4: '⟦h1⟧ left over', Q5: TEN },
        q4: { hypothesis: 'tired not a trait', shift: 0 },
      }),
    )
    expect(app().text()).toContain('is not mentioned in any answer')
  })

  it('shows answers with nothing proofread read-only, and hovering still lights the text', async () => {
    const submitted = {
      ...withAnswers(finished),
      state: 'ingested' as const,
      allowed_actions: [],
      submitted_at: 'now',
    }
    serve(submitted)
    const fetchMock = globalThis.fetch as ReturnType<typeof vi.fn>
    const original = fetchMock.getMockImplementation()
    fetchMock.mockImplementation(async (input: Request) =>
      urlOf(input).endsWith('/proofread')
        ? jsonResponse(404, { code: 'not_found', message: 'Proofread not found.', details: {} })
        : urlOf(input).endsWith('/submission')
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

    expect(app().text()).toContain('Your answers')
    expect(
      app()
        .findAll('button')
        .some((b) => b.text() === 'Submit for proofreading'),
    ).toBe(false)
    expect(
      app()
        .findAll('button')
        .some((b) => b.text() === 'Edit'),
    ).toBe(false)
    await rows()[0]?.trigger('mouseenter')
    expect(marked().text()).toBe('barely slept')
  })

  it('shows a loading circle while the answers are proofread, and what comes next', async () => {
    const submitted = {
      ...withAnswers(finished),
      state: 'proofreading' as const,
      allowed_actions: [],
      submitted_at: 'now',
    }
    await open(submitted)
    const panel = app().get('[data-testid="proofreading"]')
    expect(panel.find('[data-testid="spinner"]').exists()).toBe(true)
    expect(panel.text()).toContain('Proofreading your answers')
    expect(panel.text()).toContain('submit it for review')
    expect(app().text()).not.toMatch(/locked/i)
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
    // The help is placed on the body, outside the scrolling table, so it is not inside the app.
    const help = () => ({
      exists: () => document.querySelector('[data-testid="direction-help"]') !== null,
      text: () => document.querySelector('[data-testid="direction-help"]')?.textContent ?? '',
    })
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

  it('spells out the direction of a quote once submitted', async () => {
    const payload = { answers: FIRST_ANSWERS, highlights: [citation(1, 'barely slept', 'neutral')] }
    await open({ ...withAnswers(payload), state: 'proofreading', allowed_actions: [] })
    expect(rows()[0]?.find('select').exists()).toBe(false)
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
      answers: { ...FIRST_ANSWERS, Q5: TEN },
      highlights: [citation(1, 'barely slept', 'away')],
      q4: { hypothesis: 'tired not a trait', shift: 0 },
      rating: 3,
      insufficient_information: false,
    }
    await open(withAnswers(finished))
    expect(app().find('.chip-editor').exists()).toBe(false)
    expect(addButton().attributes('aria-label')).toBe('Show quote 1 in the text: “barely slept”')
    expect(rows()[0]?.text()).not.toContain('+ Add to answer')
    expect(app().text()).toContain('Click a quote to find it in the text.')

    await addButton().trigger('click')
    expect(marked().text()).toBe('barely slept')
    expect(calls.filter((c) => c.method === 'PUT')).toHaveLength(0)
  })

  it('adds to the question clicked in the rail, whichever it is', async () => {
    const payload = { answers: FIRST_ANSWERS, highlights: [citation(1, 'barely slept', 'away')] }
    await open(withAnswers(payload))
    await step('Q2').trigger('click')
    await addButton().trigger('click')
    await flushPromises()
    expect(block('Q2').find('[data-chip="1"]').exists()).toBe(true)
    expect(block('Q5').find('[data-chip]').exists()).toBe(false)
  })
})
