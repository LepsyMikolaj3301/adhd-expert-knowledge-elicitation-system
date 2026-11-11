import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import type { ProofreadView } from '@/api/client'
import ChipEditor from '@/components/answering/ChipEditor.vue'
import ProofreadStep from '@/components/answering/ProofreadStep.vue'

import { jsonResponse, urlOf } from './helpers'

function proofread(overrides: Partial<ProofreadView> = {}): ProofreadView {
  return {
    review_round: 1,
    version: 1,
    editable: true,
    submitted_at: null,
    feedback: [],
    highlights: [
      {
        id: 'h1',
        chip: 1,
        text: 'barely slept',
        span: [2, 14],
        origin: 'expert',
        direction: 'away',
      },
    ],
    flags: [],
    passes: { Q1: { grammar: 1, enhanced: true, dropped: 1 } },
    items: [
      {
        question_id: 'Q1',
        question: 'Which fragments matter?',
        original: '⟦h1⟧ shows sleep loss teh move afdoafgja',
        proposed: '⟦h1⟧ shows sleep loss after the move.\nIt is not a trait.',
        final: '⟦h1⟧ shows sleep loss after the move.\nIt is not a trait.',
        linked: true,
        lines: [
          { text: '⟦h1⟧ shows sleep loss after the move.', targets: ['h1'], assigned_by: 'chip' },
          { text: 'It is not a trait.', targets: [], assigned_by: null },
        ],
        dropped: ['afdoafgja'],
      },
      {
        question_id: 'Q4',
        question: 'How would it change?',
        original: 'exam stress',
        proposed: 'Exam stress.',
        final: 'Exam stress.',
        linked: false,
        lines: [],
        dropped: [],
      },
    ],
    ...overrides,
  }
}

type Call = { method: string; url: string; body?: Record<string, unknown> }
let calls: Call[]
let wrapper: VueWrapper | undefined

/** The server: GET answers `view`, PUT applies the overrides it was sent, POST submits. */
function serve(view: ProofreadView | null) {
  let current = view
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: Request) => {
      const raw = await input.clone().text()
      const call: Call = {
        method: input.method,
        url: urlOf(input).replace(/^.*\/api\/v1/, ''),
        body: raw ? JSON.parse(raw) : undefined,
      }
      calls.push(call)
      if (!current) return jsonResponse(404, { code: 'not_found', message: 'Not found.' })
      if (call.method === 'PUT') {
        const body = call.body as {
          answers: Record<string, string>
          overrides: Record<string, Record<string, string[]>>
        }
        current = {
          ...current,
          version: current.version + 1,
          items: current.items.map((item) => ({
            ...item,
            final: body.answers[item.question_id] ?? item.final,
            lines: item.lines.map((line) => {
              const targets = body.overrides[item.question_id]?.[line.text]
              return targets ? { ...line, targets, assigned_by: 'expert' } : line
            }),
          })),
        }
      }
      if (call.method === 'POST') return jsonResponse(200, {})
      return jsonResponse(200, current)
    }),
  )
}

async function show(view: ProofreadView | null = proofread()) {
  serve(view)
  wrapper = mount(ProofreadStep, { props: { id: 'a1' }, attachTo: document.body })
  await flushPromises()
  return wrapper
}

const app = () => wrapper as VueWrapper
const lines = () => app().findAll('[data-testid="line"]')
const button = (name: string) =>
  app()
    .findAll('button')
    .find((b) => b.text() === name)!

beforeAll(() => {
  const noRects = () => [] as unknown as DOMRectList
  Range.prototype.getClientRects = noRects
  Element.prototype.getClientRects = noRects
  Range.prototype.getBoundingClientRect = () => new DOMRect()
})

beforeEach(() => {
  setActivePinia(createPinia())
  calls = []
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
  vi.useRealTimers()
  document.body.innerHTML = ''
})

describe('the proofread check', () => {
  it('shows each answer as written, with the changes marked, next to the edited text', async () => {
    await show()
    const [q1] = app().findAll('[data-testid="proofread-answer"]')
    const original = q1!.get('[data-testid="original"]')
    expect(original.findAll('[data-diff="removed"]').map((d) => d.text())).toEqual(
      expect.arrayContaining([expect.stringContaining('teh')]),
    )
    expect(original.findAll('[data-diff="added"]').map((d) => d.text())).toEqual(
      expect.arrayContaining([expect.stringContaining('the')]),
    )
    expect(q1!.get('[data-testid="dropped"]').text()).toContain('afdoafgja')
    expect(q1!.findComponent(ChipEditor).props('modelValue')).toBe(proofread().items[0]!.final)
  })

  it('lists the sentences of a linked answer with their quote tags, and none for Q4', async () => {
    await show()
    expect(lines()).toHaveLength(2)
    const first = lines()[0]!.findAll('[data-testid="quote-tag"]')
    expect(first.map((t) => [t.text(), t.attributes('aria-pressed')])).toEqual([
      ['Quote 1', 'true'],
      ['Whole case', 'false'],
    ])
    const q4 = app().findAll('[data-testid="proofread-answer"]')[1]!
    expect(q4.find('[data-testid="lines"]').exists()).toBe(false)
  })

  it('blocks submitting while a sentence has no quote, and marks it once pressed', async () => {
    await show()
    expect(lines()[1]!.text()).toContain('Choose quotes')
    expect(app().get('[data-testid="blocker"]').text()).toBe(
      'One sentence needs a quote, or “Whole case”.',
    )
    await button('Submit for review').trigger('click')
    expect(app().find('dialog[open]').exists()).toBe(false)
    expect(lines()[1]!.classes()).toContain('flag-flash')
  })

  it('saves a changed tag as the expert’s own, then lets them submit', async () => {
    vi.useFakeTimers()
    await show()
    const caseTag = lines()[1]!
      .findAll('[data-testid="quote-tag"]')
      .find((t) => t.text() === 'Whole case')!
    await caseTag.trigger('click')
    expect(caseTag.attributes('aria-pressed')).toBe('true')
    await vi.advanceTimersByTimeAsync(1600)
    const put = calls.find((c) => c.method === 'PUT')
    expect(put?.body).toEqual({
      version: 1,
      answers: {},
      overrides: { Q1: { 'It is not a trait.': ['case'] } },
    })
    expect(app().find('[data-testid="blocker"]').exists()).toBe(false)

    await button('Submit for review').trigger('click')
    await app()
      .get('dialog[open]')
      .findAll('button')
      .find((b) => b.text() === 'Submit for review')!
      .trigger('click')
    await vi.advanceTimersByTimeAsync(0)
    expect(calls.filter((c) => c.method === 'POST').map((c) => c.url)).toEqual([
      '/assignments/a1/submit-for-review',
    ])
    expect(app().emitted('submitted')).toHaveLength(1)
  })

  it('never lets the last tag of a sentence go', async () => {
    await show()
    const quote = lines()[0]!.findAll('[data-testid="quote-tag"]')[0]!
    await quote.trigger('click')
    expect(quote.attributes('aria-pressed')).toBe('true')
  })

  it('saves edited text, and shows the sentences as updating until the server has them', async () => {
    vi.useFakeTimers()
    await show()
    app().findComponent(ChipEditor).vm.$emit('update:modelValue', '⟦h1⟧ is sleep loss.')
    await vi.advanceTimersByTimeAsync(0)
    expect(app().get('[data-testid="lines"]').text()).toContain('Updating…')
    await vi.advanceTimersByTimeAsync(1600)
    const put = calls.find((c) => c.method === 'PUT')
    expect(put?.body?.answers).toEqual({ Q1: '⟦h1⟧ is sleep loss.' })
    expect(app().get('[data-testid="save-status"]').text()).toBe('Saved')
  })

  it('says what the study team asked for when the answers were sent back', async () => {
    await show(proofread({ review_round: 2, feedback: [{ question_id: 'Q1', comment: 'More.' }] }))
    expect(app().get('[data-testid="feedback"]').text()).toContain('More.')
  })

  it('says so when a pass could not run', async () => {
    await show(proofread({ passes: { Q1: { grammar: 'unavailable', enhanced: true } } }))
    expect(app().text()).toContain("The grammar check couldn't run this time.")
  })

  it('shows the edited answers read-only once they are under review', async () => {
    await show(proofread({ editable: false, submitted_at: 'now' }))
    expect(app().findComponent(ChipEditor).exists()).toBe(false)
    expect(app().find('[data-testid="blocker"]').exists()).toBe(false)
    expect(
      lines()[0]!
        .findAll('[data-testid="quote-tag"]')
        .map((t) => t.text()),
    ).toEqual(['Quote 1'])
    expect(app().text()).toContain('Your edited answers')
  })

  it('tells the page when nothing was proofread', async () => {
    await show(null)
    expect(app().emitted('missing')).toHaveLength(1)
  })
})
