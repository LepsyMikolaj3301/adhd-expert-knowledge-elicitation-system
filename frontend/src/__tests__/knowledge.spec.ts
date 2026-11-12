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
    expert_pseudonym: 'E01',
    expert_is_synthetic: false,
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
  it('lists the ingested units case by case and expert by expert', async () => {
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
      '4 units from 3 accepted answers in 2 cases.',
    )
    const first = view().findAll('[data-testid="case"]')[0]!
    expect(first.text()).toContain('Case V001')
    // Within an expert, in the order the answers were cut: the quote before the whole case.
    const kinds = first.findAll('[data-testid="unit-kind"]').map((k) => k.text())
    expect(kinds.slice(0, 2)).toEqual(['Quote h1', 'Whole case'])
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

    const sentences = view()
      .findAll('[data-testid="sentence"]')
      .map((s) => s.text())
    expect(sentences).toEqual(['Q1.1 | cited by the expert', 'Q2.1 | filed by the model'])
    expect(view().get('[data-testid="context"]').text()).toContain('h2 “sleep loss”')
    expect(view().get('[data-testid="unit-direction"]').text()).toBe('Points toward ADHD traits')
    expect(view().get('[data-testid="embedded"]').text()).toContain('qwen3.5:9b')
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
