import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import type { KnowledgeUnit } from '@/api/client'
import router from '@/router'
import { useAuthStore } from '@/stores/auth'
import KnowledgeView from '@/views/KnowledgeView.vue'

import { admin, jsonResponse, urlOf } from './helpers'

function unit(overrides: Partial<KnowledgeUnit> = {}): KnowledgeUnit {
  return {
    id: 'u1',
    assignment_id: 'a1',
    vignette_code: 'V001',
    vignette_version: 1,
    expert_id: 'x1',
    expert_pseudonym: 'E01',
    ordinal: 1,
    review_round: 1,
    text: 'Q1: «the box Mum sent…» The report gives childhood evidence.',
    kind: 'fragment',
    highlight_id: 'h1',
    direction: 'toward',
    patient_words: 'the box Mum sent and found my year four report.',
    status: 'ingested',
    created_at: '2026-11-10T10:00:00Z',
    embed_text: 'Clinician on an adult’s journal entry\nQ1: The report gives childhood evidence.',
    embed_text_combined: 'Clinician on an adult’s journal entry\nPatient: "the box"\nQ1: …',
    sentences: [{ id: 'Q1.1', question_id: 'Q1', assigned_by: 'chip' }],
    context: [],
    framing: 'personal_journal',
    classifier: 'qwen3.5:9b',
    prompt: 'Expert_sentence_targets.v1',
    findings_version: 1,
    ...overrides,
  }
}

type Call = { method: string; url: string; body?: Record<string, unknown> }
let calls: Call[]
let wrapper: VueWrapper | undefined

function serve(routes: Record<string, () => Response>) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: Request) => {
      const raw = input.method === 'GET' ? '' : await input.clone().text()
      const url = new URL(urlOf(input))
      calls.push({
        method: input.method,
        url: url.pathname + url.search,
        body: raw ? JSON.parse(raw) : undefined,
      })
      const reply = routes[`${input.method} ${url.pathname.replace('/api/v1', '')}`]
      return reply
        ? reply()
        : jsonResponse(404, { code: 'not_found', message: `No ${url.pathname}` })
    }),
  )
}

async function open(path = '/knowledge') {
  await router.push(path)
  wrapper = mount(KnowledgeView, { global: { plugins: [router] }, attachTo: document.body })
  await flushPromises()
  return wrapper
}

const view = () => wrapper as VueWrapper
const lastCall = () => calls[calls.length - 1]

function buttonNamed(name: string) {
  const button = view()
    .findAll('button')
    .find((b) => b.text() === name)
  if (!button) throw new Error(`no button "${name}" in: ${view().text()}`)
  return button
}

/** The confirm's own button: the unit cards have a "Remove" of their own. */
function confirmRemove() {
  const button = view()
    .get('dialog')
    .findAll('button')
    .find((b) => b.text() === 'Remove')
  if (!button) throw new Error('no confirm dialog')
  return button
}

async function search(text: string) {
  await view().find('#knowledge-query').setValue(text)
  await view().find('form').trigger('submit')
  await flushPromises()
}

const hit = (rank: number, overrides: Record<string, unknown> = {}) => ({
  rank,
  score: 0.0327,
  similarity: 0.834,
  matched_sentence: null,
  unit: unit({ id: `u${rank}` }),
  ...overrides,
})

beforeEach(() => {
  // jsdom has no modal dialogs; the confirm only needs to open.
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute('open', '')
  }
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute('open')
  }
  setActivePinia(createPinia())
  const auth = useAuthStore()
  auth.user = admin
  auth.loaded = true
  calls = []
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  document.body.innerHTML = ''
})

describe('Knowledge base: units', () => {
  it('gives an overview of cases and their answers, with units shown per answer', async () => {
    serve({
      'GET /knowledge-units': () =>
        jsonResponse(200, [
          unit({ id: 'u1', ordinal: 2, kind: 'case', highlight_id: null, direction: null }),
          unit({ id: 'u2', ordinal: 1 }),
          unit({ id: 'u3', assignment_id: 'a2', expert_pseudonym: 'E02' }),
          unit({ id: 'u4', assignment_id: 'a3', vignette_code: 'V002' }),
        ]),
    })
    await open()

    expect(calls[0]?.url).toContain('status=ingested')
    expect(view().findAll('[data-testid="case"]')).toHaveLength(2)
    expect(view().findAll('[data-testid="expert"]')).toHaveLength(3)
    expect(view().get('[data-testid="summary"]').text()).toBe(
      '4 units from 3 accepted answers in 2 cases. Open an answer to see its units.',
    )
    // An overview: no unit is shown until its answer is opened.
    expect(view().findAll('[data-testid="unit"]')).toHaveLength(0)
    const first = view().findAll('[data-testid="case"]')[0]!
    expect(first.text()).toContain('Case V001')
    expect(first.get('[data-testid="expert-counts"]').text()).toBe(
      '2 units (1 quote, 1 whole-case)',
    )

    const toggle = first.get('[data-testid="expert-toggle"]')
    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(view().findAll('[data-testid="unit"]')).toHaveLength(2)

    // Within an expert, in the order the answers were cut: the quote before the whole case.
    const kinds = first.findAll('[data-testid="unit-kind"]').map((k) => k.text())
    expect(kinds).toEqual(['Quote h1', 'Whole case'])

    await toggle.trigger('click')
    expect(view().findAll('[data-testid="unit"]')).toHaveLength(0)
  })

  it('shows how a unit was cut and what is embedded', async () => {
    serve({
      'GET /knowledge-units': () =>
        jsonResponse(200, [
          unit({
            sentences: [
              { id: 'Q1.1', question_id: 'Q1', assigned_by: 'chip' },
              { id: 'Q2.1', question_id: 'Q2', assigned_by: 'llm' },
            ],
            context: [{ id: 'h2', text: 'sleep loss' }],
          }),
        ]),
    })
    await open()
    await view().get('[data-testid="expert-toggle"]').trigger('click')

    const sentences = view()
      .findAll('[data-testid="sentence"]')
      .map((s) => s.text())
    expect(sentences).toEqual(['Q1.1 | cited by the expert', 'Q2.1 | filed by the model'])
    expect(view().get('[data-testid="context"]').text()).toContain('h2 “sleep loss”')
    expect(view().get('[data-testid="unit-direction"]').text()).toBe('Points toward ADHD traits')
    expect(view().get('[data-testid="embedded"]').text()).toContain('qwen3.5:9b')
    // The embedded texts are on show, whole, with nothing to unfold.
    expect(view().find('[data-testid="embedded"] details').exists()).toBe(false)
    expect(view().get('[data-testid="embed-text"]').text()).toBe(unit().embed_text)
    expect(view().get('[data-testid="embed-text-combined"]').text()).toBe(
      unit().embed_text_combined,
    )
  })

  it('removes one unit after asking, and the index is refit in the background', async () => {
    let refitting = true
    serve({
      'GET /knowledge-units': () =>
        jsonResponse(200, [unit({ id: 'u1' }), unit({ id: 'u2', highlight_id: 'h2' })]),
      'DELETE /knowledge-units/u1': () => new Response(null, { status: 204 }),
      'GET /knowledge-units/index': () =>
        jsonResponse(200, { state: refitting ? 'running' : 'up_to_date', last_error: null }),
    })
    refitting = false
    await open()
    expect(view().get('[data-testid="index-status"]').text()).toContain('Search index up to date')
    await view().get('[data-testid="expert-toggle"]').trigger('click')

    await view().findAll('[data-testid="remove-unit"]')[0]!.trigger('click')
    expect(document.body.textContent).toContain('Remove this unit?')
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false)

    refitting = true
    await confirmRemove().trigger('click')
    await flushPromises()
    expect(calls.find((c) => c.method === 'DELETE')?.url).toBe('/api/v1/knowledge-units/u1')
    expect(view().findAll('[data-testid="unit"]')).toHaveLength(1)
    expect(view().get('[data-testid="index-status"]').text()).toContain('Refitting')
  })

  it("withdraws all of an expert's knowledge, in every case", async () => {
    serve({
      'GET /knowledge-units': () =>
        jsonResponse(200, [
          unit({ id: 'u1' }),
          unit({ id: 'u2', assignment_id: 'a2', vignette_code: 'V002' }),
          unit({ id: 'u3', assignment_id: 'a3', expert_id: 'x2', expert_pseudonym: 'E02' }),
        ]),
      'DELETE /knowledge-units/by-expert/x1': () => jsonResponse(200, { removed: 2 }),
      'GET /knowledge-units/index': () => jsonResponse(200, { state: 'up_to_date' }),
    })
    await open()
    await view().get('[data-testid="expert-menu"]').trigger('click')
    await view().get('[data-testid="remove-expert"]').trigger('click')
    expect(document.body.textContent).toContain("Remove all of E01's knowledge?")
    expect(document.querySelector('[data-testid="remove-expert-summary"]')?.textContent).toContain(
      '2 units from 2 cases',
    )

    await confirmRemove().trigger('click')
    await flushPromises()
    expect(calls.find((c) => c.method === 'DELETE')?.url).toBe(
      '/api/v1/knowledge-units/by-expert/x1',
    )
    expect(view().findAll('[data-testid="expert"]')).toHaveLength(1)
    expect(view().get('[data-testid="expert"]').text()).toContain('E02')
  })

  it('offers to refit again when a refit failed', async () => {
    serve({
      'GET /knowledge-units': () => jsonResponse(200, [unit()]),
      'GET /knowledge-units/index': () =>
        jsonResponse(200, { state: 'failed', last_error: 'RuntimeError' }),
      'POST /knowledge-units/index/refit': () => jsonResponse(202, { state: 'queued' }),
    })
    await open()
    expect(view().get('[data-testid="index-status"]').text()).toContain('RuntimeError')
    await buttonNamed('Try again').trigger('click')
    await flushPromises()
    expect(calls.some((c) => c.method === 'POST' && c.url.endsWith('/index/refit'))).toBe(true)
  })

  it('says when nothing has been ingested', async () => {
    serve({ 'GET /knowledge-units': () => jsonResponse(200, []) })
    await open()
    expect(view().get('[data-testid="empty"]').text()).toBe('Nothing has been ingested yet.')
  })
})

describe('Knowledge base: test search', () => {
  it('opens on the tab named in the address', async () => {
    serve({})
    await open('/knowledge?tab=search')
    expect(view().find('#knowledge-query').exists()).toBe(true)
    expect(calls).toHaveLength(0)
  })

  it('searches the way a clinician asks and shows how close each unit is', async () => {
    serve({
      'GET /knowledge-units': () => jsonResponse(200, []),
      'POST /knowledge-units/search': () =>
        jsonResponse(200, { hits: [hit(1), hit(2, { similarity: 0.5 })] }),
    })
    await open()
    await buttonNamed('Test search').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query.tab).toBe('search')

    await search('school report')

    expect(lastCall()).toMatchObject({
      method: 'POST',
      body: { query: 'school report', mode: 'question', k: 8 },
    })
    const hits = view().findAll('[data-testid="hit"]')
    expect(hits).toHaveLength(2)
    expect(hits[0]!.get('[data-testid="similarity"]').text()).toBe('Similarity 0.83')
    expect(hits[1]!.get('[data-testid="similarity"]').text()).toBe('Similarity 0.50')
    expect(hits[0]!.text()).toContain('Case V001')
    expect(hits[0]!.find('[data-testid="matched"]').exists()).toBe(false)
  })

  it("searches with a patient's text and names the sentence that matched", async () => {
    serve({
      'POST /knowledge-units/search': () =>
        jsonResponse(200, { hits: [hit(1, { matched_sentence: 'I found my old report.' })] }),
    })
    await open('/knowledge?tab=search')
    await buttonNamed("A patient's text").trigger('click')
    expect(view().find('textarea#knowledge-query').exists()).toBe(true)

    await search('Hello. I found my old report.')

    expect(lastCall()?.body).toMatchObject({ mode: 'patient_text' })
    expect(view().get('[data-testid="matched"]').text()).toContain('I found my old report.')
  })

  it('forgets the results when the kind of search changes', async () => {
    serve({ 'POST /knowledge-units/search': () => jsonResponse(200, { hits: [hit(1)] }) })
    await open('/knowledge?tab=search')
    await search('school report')
    expect(view().find('[data-testid="hits"]').exists()).toBe(true)

    await buttonNamed("A patient's text").trigger('click')
    expect(view().find('[data-testid="hits"]').exists()).toBe(false)
  })

  it('says when nothing matches', async () => {
    serve({ 'POST /knowledge-units/search': () => jsonResponse(200, { hits: [] }) })
    await open('/knowledge?tab=search')
    await search('zzz')
    expect(view().get('[data-testid="no-hits"]').text()).toBe(
      'Nothing in the knowledge base matches.',
    )
  })

  it('shows the message when the embedding model is down', async () => {
    serve({
      'POST /knowledge-units/search': () =>
        jsonResponse(503, {
          code: 'embedding_unavailable',
          message: "The embedding model can't be reached, so search is off right now.",
        }),
    })
    await open('/knowledge?tab=search')
    await search('school report')
    expect(view().get('[data-testid="search-error"]').text()).toContain('embedding model')
    expect(view().find('[data-testid="hits"]').exists()).toBe(false)
  })
})

describe('Knowledge base: removals that do not go to plan', () => {
  const two = () => jsonResponse(200, [unit({ id: 'u1' }), unit({ id: 'u2', highlight_id: 'h2' })])
  const upToDate = () => jsonResponse(200, { state: 'up_to_date' })

  async function askToRemoveFirstUnit() {
    await open()
    await view().get('[data-testid="expert-toggle"]').trigger('click')
    await view().findAll('[data-testid="remove-unit"]')[0]!.trigger('click')
  }

  const deletes = () => calls.filter((c) => c.method === 'DELETE')

  it('keeps the unit and says so when the removal is refused', async () => {
    serve({
      'GET /knowledge-units': two,
      'GET /knowledge-units/index': upToDate,
      'DELETE /knowledge-units/u1': () =>
        jsonResponse(403, { code: 'forbidden', message: 'You may not do this.' }),
    })
    await askToRemoveFirstUnit()
    await confirmRemove().trigger('click')
    await flushPromises()

    expect(deletes()).toHaveLength(1)
    expect(view().get('[role="alert"]').text()).not.toBe('')
    expect(view().findAll('[data-testid="unit"]')).toHaveLength(2)
    expect(document.querySelector('dialog')).toBeNull() // the question is closed either way
  })

  it('says so when the unit is already gone', async () => {
    serve({
      'GET /knowledge-units': two,
      'GET /knowledge-units/index': upToDate,
      'DELETE /knowledge-units/u1': () =>
        jsonResponse(404, { code: 'not_found', message: 'Unit not found.' }),
    })
    await askToRemoveFirstUnit()
    await confirmRemove().trigger('click')
    await flushPromises()
    expect(view().find('[role="alert"]').exists()).toBe(true)
    expect(view().findAll('[data-testid="unit"]')).toHaveLength(2)
  })

  it('sends nothing when the admin keeps the unit', async () => {
    serve({ 'GET /knowledge-units': two, 'GET /knowledge-units/index': upToDate })
    await askToRemoveFirstUnit()
    expect(document.body.textContent).toContain('Remove this unit?')
    await view()
      .get('dialog')
      .findAll('button')
      .find((b) => b.text() === 'Keep')!
      .trigger('click')
    expect(deletes()).toHaveLength(0)
    expect(document.querySelector('dialog')).toBeNull()
    expect(view().findAll('[data-testid="unit"]')).toHaveLength(2)
  })

  it('removes once, however often the button is pressed, and says it is working', async () => {
    let finish: (r: Response) => void = () => {}
    const slow = new Promise<Response>((resolve) => (finish = resolve))
    serve({
      'GET /knowledge-units': two,
      'GET /knowledge-units/index': upToDate,
      'DELETE /knowledge-units/u1': () => slow as unknown as Response,
    })
    await askToRemoveFirstUnit()
    const button = confirmRemove()
    await button.trigger('click')
    await button.trigger('click')
    expect(button.text()).toBe('Removing…')
    finish(new Response(null, { status: 204 }))
    await flushPromises()
    expect(deletes()).toHaveLength(1)
    expect(view().findAll('[data-testid="unit"]')).toHaveLength(1)
  })

  it('shows the empty page once the last unit is gone', async () => {
    serve({
      'GET /knowledge-units': () => jsonResponse(200, [unit({ id: 'u1' })]),
      'GET /knowledge-units/index': upToDate,
      'DELETE /knowledge-units/u1': () => new Response(null, { status: 204 }),
    })
    await askToRemoveFirstUnit()
    await confirmRemove().trigger('click')
    await flushPromises()
    expect(view().find('[data-testid="case"]').exists()).toBe(false)
    expect(view().get('[data-testid="empty"]').text()).toBe('Nothing has been ingested yet.')
  })

  it('keeps the other units of an expert when one answer is removed from a case', async () => {
    serve({
      'GET /knowledge-units': () =>
        jsonResponse(200, [
          unit({ id: 'u1' }),
          unit({ id: 'u2', assignment_id: 'a2', expert_id: 'x2', expert_pseudonym: 'E02' }),
        ]),
      'GET /knowledge-units/index': upToDate,
      'DELETE /knowledge-units/u1': () => new Response(null, { status: 204 }),
    })
    await askToRemoveFirstUnit()
    await confirmRemove().trigger('click')
    await flushPromises()
    expect(view().findAll('[data-testid="expert"]')).toHaveLength(1)
    expect(view().get('[data-testid="expert"]').text()).toContain('E02')
  })

  it('does not claim zero units when the list cannot be loaded', async () => {
    serve({
      'GET /knowledge-units': () => jsonResponse(500, { code: 'internal_error', message: 'x' }),
      'GET /knowledge-units/index': upToDate,
    })
    await open()
    expect(view().get('[role="alert"]').text()).not.toBe('')
    expect(view().find('[data-testid="summary"]').exists()).toBe(false)
    expect(view().find('[data-testid="empty"]').exists()).toBe(false)
  })

  it('shows why a refit could not be started', async () => {
    serve({
      'GET /knowledge-units': () => jsonResponse(200, [unit()]),
      'GET /knowledge-units/index': () => jsonResponse(200, { state: 'failed' }),
      'POST /knowledge-units/index/refit': () =>
        jsonResponse(500, { code: 'internal_error', message: 'x' }),
    })
    await open()
    await buttonNamed('Try again').trigger('click')
    await flushPromises()
    expect(view().get('[role="alert"]').text()).not.toBe('')
  })

  describe('the index status', () => {
    beforeEach(() => vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] }))
    afterEach(() => vi.useRealTimers())

    const indexCalls = () => calls.filter((c) => c.url.endsWith('/knowledge-units/index')).length

    it('follows the refit from queued to running to up to date, then stops asking', async () => {
      const states = ['queued', 'running', 'up_to_date']
      serve({
        'GET /knowledge-units': () => jsonResponse(200, [unit()]),
        'GET /knowledge-units/index': () =>
          jsonResponse(200, { state: states[Math.min(indexCalls() - 1, 2)] }),
      })
      await open()
      expect(view().get('[data-testid="index-status"]').text()).toContain('Refitting')
      await vi.advanceTimersByTimeAsync(2000)
      await flushPromises()
      expect(view().get('[data-testid="index-status"]').text()).toContain('Refitting')
      await vi.advanceTimersByTimeAsync(2000)
      await flushPromises()
      expect(view().get('[data-testid="index-status"]').text()).toContain('up to date')
      const asked = indexCalls()
      await vi.advanceTimersByTimeAsync(20000)
      expect(indexCalls()).toBe(asked)
    })

    it('stops asking when the page is left', async () => {
      serve({
        'GET /knowledge-units': () => jsonResponse(200, [unit()]),
        'GET /knowledge-units/index': () => jsonResponse(200, { state: 'running' }),
      })
      await open()
      await vi.advanceTimersByTimeAsync(2000)
      const asked = indexCalls()
      expect(asked).toBeGreaterThan(1)
      wrapper?.unmount()
      wrapper = undefined
      await vi.advanceTimersByTimeAsync(20000)
      expect(indexCalls()).toBe(asked)
    })

    it('shows no status line at all when the status cannot be read', async () => {
      serve({
        'GET /knowledge-units': () => jsonResponse(200, [unit()]),
        'GET /knowledge-units/index': () => jsonResponse(500, { code: 'internal_error' }),
      })
      await open()
      expect(view().find('[data-testid="index-status"]').exists()).toBe(false)
      expect(view().find('[role="alert"]').exists()).toBe(false)
    })
  })

  it('never offers to remove a unit from a search result', async () => {
    serve({
      'GET /knowledge-units': () => jsonResponse(200, []),
      'POST /knowledge-units/search': () => jsonResponse(200, { hits: [hit(1), hit(2)] }),
    })
    await open('/knowledge?tab=search')
    await search('school report')
    expect(view().findAll('[data-testid="hit"]')).toHaveLength(2)
    expect(view().find('[data-testid="remove-unit"]').exists()).toBe(false)
  })
})
