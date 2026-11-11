import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import { emptyDesign, fieldForError, nextCode } from '@/admin/vignetteForm'
import App from '@/App.vue'
import { ApiError, type VersionAdminView } from '@/api/client'
import router from '@/router'
import { useAuthStore } from '@/stores/auth'

import { admin, expert, jsonResponse, urlOf } from './helpers'

const TEXT = Array.from({ length: 130 }, (_, i) => `word${i}`).join(' ')

function version(overrides: Partial<VersionAdminView> = {}): VersionAdminView {
  return {
    id: 'ver1',
    vignette_id: 'vig1',
    version: 1,
    status: 'draft',
    text: TEXT,
    content_hash: 'x',
    framing: 'email',
    question_ids: ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q6'],
    q4_whatif: 'the writer had an exam',
    patient_summary: 'A student writing before an exam.',
    variant: null,
    design: { ...emptyDesign(), notes: 'Test notes' },
    created_at: 'now',
    published_at: null,
    word_count: 130,
    ...overrides,
  }
}

function vignette(versions: VersionAdminView[] = [version()], code = 'V007') {
  return { id: 'vig1', code, created_at: 'now', versions }
}

const QUESTIONS = [
  { id: 'Q1', kind: 'open', text: 'Which fragments matter?' },
  { id: 'Q2', kind: 'open', text: 'What else could explain them?' },
  { id: 'Q3', kind: 'open', text: 'What is missing?' },
  { id: 'Q4', kind: 'shift', text: 'Given your hypothesis: how would it change if {whatif}?' },
  { id: 'Q5', kind: 'open', text: 'What would a junior over-read?' },
  { id: 'Q6', kind: 'rating_1_5', text: 'Overall, how strongly?' },
]

type Call = { method: string; url: string; body?: Record<string, unknown> }
let calls: Call[]
let wrapper: VueWrapper | undefined
let routes: Record<string, () => Response>

function serve(table: Record<string, () => Response>) {
  routes = { 'GET /vignettes/questions': () => jsonResponse(200, QUESTIONS), ...table }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: Request) => {
      const raw = await input.clone().text()
      const url = new URL(urlOf(input))
      const path = url.pathname.replace('/api/v1', '')
      calls.push({
        method: input.method,
        url: url.pathname + url.search,
        body: raw ? JSON.parse(raw) : undefined,
      })
      const reply = routes[`${input.method} ${path}`]
      return reply ? reply() : jsonResponse(404, { code: 'not_found', message: `No ${path}` })
    }),
  )
}

async function open(path: string) {
  await router.push(path)
  wrapper = mount(App, { global: { plugins: [router] }, attachTo: document.body })
  await flushPromises()
  await flushPromises()
  return wrapper
}

const app = () => wrapper as VueWrapper
const writes = () => calls.filter((c) => c.method !== 'GET')

function buttonNamed(name: string) {
  const button = app()
    .findAll('button')
    .find((b) => b.text() === name)
  if (!button) throw new Error(`no button "${name}" in: ${app().text()}`)
  return button
}

beforeEach(() => {
  setActivePinia(createPinia())
  const auth = useAuthStore()
  auth.user = admin
  auth.loaded = true
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
  document.body.innerHTML = ''
})

describe('nextCode', () => {
  it('continues after the highest code', () => {
    expect(nextCode([])).toBe('V001')
    expect(nextCode(['V001', 'V014', 'V003'])).toBe('V015')
    expect(nextCode(['V999'])).toBe('V1000')
  })
})

describe('fieldForError', () => {
  const error = (code: string, details?: Record<string, unknown>) =>
    new ApiError(422, { code, message: 'x', details })

  it.each([
    ['word_count_out_of_range', undefined, 'text'],
    ['q4_without_whatif', undefined, 'q4_whatif'],
    ['summary_missing', undefined, 'patient_summary'],
    ['construct_word_in_text', { field: 'patient_summary' }, 'patient_summary'],
    ['span_not_in_text', undefined, 'quotes'],
    ['control_with_cues', undefined, 'quotes'],
    ['track_without_target', undefined, 'knowledge_target'],
    ['vignette_code_taken', undefined, 'code'],
    ['construct_word_in_text', { field: 'text' }, 'text'],
    ['construct_word_in_text', { field: 'q4_whatif' }, 'q4_whatif'],
    ['validation_error', { errors: [{ loc: ['body', 'code'] }] }, 'code'],
    ['something_else', undefined, null],
  ])('puts %s %j next to %s', (code, details, field) => {
    expect(fieldForError(error(code, details))).toBe(field)
  })
})

describe('the vignette list', () => {
  it('shows the latest version of each vignette', async () => {
    serve({
      'GET /vignettes': () =>
        jsonResponse(200, [
          vignette([
            version(),
            version({ id: 'ver2', version: 2, status: 'published', word_count: 200 }),
          ]),
        ]),
    })
    await open('/vignettes')
    const row = app().get('[data-testid="vignette"]')
    expect(row.text()).toContain('V007')
    expect(row.text()).toContain('Version 2')
    expect(row.text()).toContain('Published')
    expect(row.text()).toContain('200')
    expect(row.get('a').attributes('href')).toBe('/vignettes/vig1')
  })

  it('invites the admin to write the first one', async () => {
    serve({ 'GET /vignettes': () => jsonResponse(200, []) })
    await open('/vignettes')
    expect(app().text()).toContain('No vignettes yet')
    expect(app().find('a[href="/vignettes/new"]').exists()).toBe(true)
  })
})

describe('writing a vignette', () => {
  async function fillRequired() {
    await app().get('[data-testid="text"]').setValue(TEXT)
    await app().get('[data-testid="whatif"]').setValue('the writer had an exam')
    await app().get('[data-testid="summary"]').setValue('A student before an exam.')
    await app().get('[data-testid="notes"]').setValue('Sleep as a confounder')
  }

  it('suggests the next code, and creates a draft with a summary and notes', async () => {
    serve({
      'GET /vignettes': () => jsonResponse(200, [vignette()]),
      'POST /vignettes': () => jsonResponse(201, vignette([version()], 'V008')),
    })
    await open('/vignettes/new')
    expect((app().get('[data-testid="code"]').element as HTMLInputElement).value).toBe('V008')
    await fillRequired()
    await buttonNamed('Save draft').trigger('click')
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/vignettes/vig1'))

    const body = writes()[0]?.body as Record<string, unknown>
    expect(body.code).toBe('V008')
    expect(body.text).toBe(TEXT)
    expect(body.q4_whatif).toBe('the writer had an exam')
    expect(body).not.toHaveProperty('question_ids')
    expect(body.patient_summary).toBe('A student before an exam.')
    expect(body.design).toMatchObject({ notes: 'Sleep as a confounder', origin: 'hand_written' })

    // The same screen stays on the page, and has to show the saved draft.
    await vi.waitFor(() => expect(app().get('[data-testid="status"]').text()).toContain('draft'))
    expect(
      app()
        .findAll('button')
        .some((b) => b.text() === 'Publish'),
    ).toBe(true)
  })

  it('needs the required parts before saving', async () => {
    serve({ 'GET /vignettes': () => jsonResponse(200, []) })
    await open('/vignettes/new')
    expect(buttonNamed('Save draft').attributes('disabled')).toBeDefined()
    await fillRequired()
    expect(buttonNamed('Save draft').attributes('disabled')).toBeUndefined()
  })

  it('counts the words against the publishing rule', async () => {
    serve({ 'GET /vignettes': () => jsonResponse(200, []) })
    await open('/vignettes/new')
    await app().get('[data-testid="text"]').setValue('only three words')
    expect(app().get('[data-testid="word-count"]').text()).toContain('3 words')
    expect(app().get('[data-testid="word-count"]').text()).toContain('120 to 250')
  })

  it('shows a server refusal next to the field it is about', async () => {
    serve({
      'GET /vignettes': () => jsonResponse(200, [vignette()]),
      'POST /vignettes': () =>
        jsonResponse(409, { code: 'vignette_code_taken', message: 'V008 already exists.' }),
    })
    await open('/vignettes/new')
    await fillRequired()
    await buttonNamed('Save draft').trigger('click')
    await flushPromises()
    expect(app().get('[data-error="code"]').text()).toBe('V008 already exists.')
  })

  it('shows the six questions, with the what-if written inside Q4', async () => {
    serve({ 'GET /vignettes': () => jsonResponse(200, []) })
    await open('/vignettes/new')
    const questions = app().findAll('[data-testid="question"]')
    expect(questions.map((q) => q.text().slice(0, 2))).toEqual(['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q6'])
    expect(questions[0]?.text()).toContain('Which fragments matter?')
    const q4 = questions[3]!
    expect(q4.text()).toContain('Given your hypothesis: how would it change if')
    expect(q4.find('[data-testid="whatif"]').exists()).toBe(true)
    expect(app().findAll('[data-testid="whatif"]')).toHaveLength(1)
  })

  it('has no planted cues, confounders or design section', async () => {
    serve({ 'GET /vignettes': () => jsonResponse(200, []) })
    await open('/vignettes/new')
    expect(app().text()).not.toContain('Planted cues')
    expect(app().text()).not.toContain('Design notes')
    expect(app().find('[data-testid="purpose"]').exists()).toBe(false)
  })

  it('shows the missing summary next to its field', async () => {
    serve({
      'GET /vignettes': () => jsonResponse(200, [vignette()]),
      'POST /vignette-versions/ver1/publish': () =>
        jsonResponse(422, { code: 'summary_missing', message: 'Add a short description.' }),
    })
    await open('/vignettes/vig1')
    await buttonNamed('Publish').trigger('click')
    await flushPromises()
    expect(app().get('[data-error="patient_summary"]').text()).toContain('short description')
  })

  it('keeps the cues of an imported vignette when it is saved', async () => {
    const cue = { quote: 'word0', trait: 't', strength: 'weak' as const }
    serve({
      'GET /vignettes': () =>
        jsonResponse(200, [
          vignette([version({ design: { ...emptyDesign(), planted_cues: [cue] } })]),
        ]),
      'PATCH /vignette-versions/ver1': () => jsonResponse(200, version()),
    })
    await open('/vignettes/vig1')
    await app().get('[data-testid="notes"]').setValue('changed')
    await buttonNamed('Save draft').trigger('click')
    await flushPromises()
    expect(writes()[0]?.body?.design).toMatchObject({ planted_cues: [cue], notes: 'changed' })
  })
})

describe('a draft version', () => {
  it('saves changes without touching the variant, then publishes', async () => {
    const published = version({ status: 'published' })
    serve({
      'GET /vignettes': () => jsonResponse(200, [vignette()]),
      'PATCH /vignette-versions/ver1': () => jsonResponse(200, version()),
      'POST /vignette-versions/ver1/publish': () => jsonResponse(200, published),
    })
    await open('/vignettes/vig1')
    await app().get('[data-testid="whatif"]').setValue('the writer slept well')
    await buttonNamed('Publish').trigger('click')
    await flushPromises()
    await flushPromises()

    expect(writes().map((c) => `${c.method} ${c.url}`)).toEqual([
      'PATCH /api/v1/vignette-versions/ver1',
      'POST /api/v1/vignette-versions/ver1/publish',
    ])
    expect(writes()[0]?.body).toMatchObject({ q4_whatif: 'the writer slept well' })
    expect(writes()[0]?.body).not.toHaveProperty('variant')
  })

  it('shows why publishing was refused, next to the text', async () => {
    serve({
      'GET /vignettes': () => jsonResponse(200, [vignette()]),
      'POST /vignette-versions/ver1/publish': () =>
        jsonResponse(422, {
          code: 'word_count_out_of_range',
          message: 'The text must be 120-250 words; it has 3.',
        }),
    })
    await open('/vignettes/vig1')
    await buttonNamed('Publish').trigger('click')
    await flushPromises()
    expect(app().get('[data-error="text"]').text()).toContain('it has 3')
    await app().get('[data-testid="text"]').setValue(`${TEXT} more`)
    expect(app().find('[data-error="text"]').exists()).toBe(false)
  })
})

describe('a published version', () => {
  function publishedRoutes(extra: Record<string, () => Response> = {}) {
    return {
      'GET /vignettes': () => jsonResponse(200, [vignette([version({ status: 'published' })])]),
      ...extra,
    }
  }

  it('is read-only, and leaves assigning to the Assignments page', async () => {
    serve(publishedRoutes())
    await open('/vignettes/vig1')
    expect(app().get('[data-testid="text"]').attributes('disabled')).toBeDefined()
    expect(app().get('[data-testid="summary"]').attributes('disabled')).toBeDefined()
    expect(
      app()
        .findAll('button')
        .some((b) => b.text() === 'Save draft'),
    ).toBe(false)
    expect(app().find('[data-testid="assign-panel"]').exists()).toBe(false)
  })

  it('retires only after asking', async () => {
    serve(
      publishedRoutes({
        'POST /vignette-versions/ver1/retire': () =>
          jsonResponse(200, version({ status: 'retired' })),
      }),
    )
    await open('/vignettes/vig1')
    await buttonNamed('Retire').trigger('click')
    expect(writes()).toHaveLength(0)
    await app()
      .get('dialog[open]')
      .findAll('button')
      .find((b) => b.text() === 'Retire version')
      ?.trigger('click')
    await flushPromises()
    expect(writes()[0]?.url).toBe('/api/v1/vignette-versions/ver1/retire')
  })

  it('can start a new version that keeps the variant and the summary', async () => {
    const variant = { pair_id: 'P1', arm: 'A' as const, change: null }
    serve(
      publishedRoutes({
        'GET /vignettes': () =>
          jsonResponse(200, [vignette([version({ status: 'published', variant })])]),
        'POST /vignettes/vig1/versions': () =>
          jsonResponse(201, version({ id: 'ver2', version: 2, variant })),
      }),
    )
    await open('/vignettes/vig1')
    await buttonNamed('New version').trigger('click')
    await flushPromises()
    expect(writes()[0]?.url).toBe('/api/v1/vignettes/vig1/versions')
    expect(writes()[0]?.body).toMatchObject({
      text: TEXT,
      variant,
      patient_summary: 'A student writing before an exam.',
    })
  })
})

describe('permissions in the browser', () => {
  it('keeps an expert out of the vignette screens', async () => {
    useAuthStore().user = expert
    serve({ 'GET /assignments': () => jsonResponse(200, []) })
    await open('/vignettes/new')
    expect(router.currentRoute.value.name).toBe('home')
  })
})
