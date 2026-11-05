import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import { emptyDesign, fieldForError, nextCode } from '@/admin/vignetteForm'
import App from '@/App.vue'
import { ApiError, type AssignmentSummary, type User, type VersionAdminView } from '@/api/client'
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
    variant: null,
    design: { ...emptyDesign(), purpose: 'Test purpose' },
    created_at: 'now',
    published_at: null,
    word_count: 130,
    ...overrides,
  }
}

function vignette(versions: VersionAdminView[] = [version()], code = 'V007') {
  return { id: 'vig1', code, created_at: 'now', versions }
}

function summary(overrides: Partial<AssignmentSummary> = {}): AssignmentSummary {
  return {
    id: 'as1',
    state: 'assigned',
    allowed_actions: ['cancel'],
    job_running: false,
    vignette_code: 'V007',
    vignette_version: 1,
    vignette_version_id: 'ver1',
    expert_pseudonym: 'E01',
    updated_at: 'now',
    ...overrides,
  }
}

type Call = { method: string; url: string; body?: Record<string, unknown> }
let calls: Call[]
let wrapper: VueWrapper | undefined
let routes: Record<string, () => Response>

function serve(table: Record<string, () => Response>) {
  routes = table
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
    await app().get('[data-testid="purpose"]').setValue('Sleep as a confounder')
  }

  it('suggests the next code, and creates a draft with no questions in it', async () => {
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
    expect(body.design).toMatchObject({ purpose: 'Sleep as a confounder', origin: 'hand_written' })

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

  it('adds a planted cue from text selected in the patient text', async () => {
    serve({ 'GET /vignettes': () => jsonResponse(200, []) })
    await open('/vignettes/new')
    await fillRequired()
    const area = app().get('[data-testid="text"]').element as HTMLTextAreaElement
    area.setSelectionRange(0, 'word0 word1'.length)
    await buttonNamed('Add selected text as a cue').trigger('click')
    expect(app().get('[data-testid="cue"]').text()).toContain('word0 word1')
    expect((app().get('[data-testid="cue"] input').element as HTMLInputElement).value).toBe('')
  })

  it('says when nothing is selected for a cue', async () => {
    serve({ 'GET /vignettes': () => jsonResponse(200, []) })
    await open('/vignettes/new')
    await buttonNamed('Add selected text as a cue').trigger('click')
    expect(app().findAll('[data-testid="cue"]')).toHaveLength(0)
    expect(app().text()).toContain('Select words in the patient text first.')
  })

  it('warns when a quote is no longer in the text', async () => {
    serve({
      'GET /vignettes': () =>
        jsonResponse(200, [
          vignette([
            version({
              design: {
                ...emptyDesign(),
                purpose: 'p',
                planted_cues: [{ quote: 'word0', trait: 't', strength: 'weak' }],
                confounders: [],
              },
            }),
          ]),
        ]),
    })
    await open('/vignettes/vig1')
    await app().get('[data-testid="text"]').setValue('all new words')
    expect(app().get('[data-testid="cue"]').text()).toContain('no longer in the text')
  })
})

describe('a draft version', () => {
  it('saves changes without touching the variant, then publishes', async () => {
    const published = version({ status: 'published' })
    serve({
      'GET /vignettes': () => jsonResponse(200, [vignette()]),
      'PATCH /vignette-versions/ver1': () => jsonResponse(200, version()),
      'POST /vignette-versions/ver1/publish': () => jsonResponse(200, published),
      'GET /users': () => jsonResponse(200, []),
      'GET /assignments': () => jsonResponse(200, []),
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

  it('offers no assigning before it is published', async () => {
    serve({ 'GET /vignettes': () => jsonResponse(200, [vignette()]) })
    await open('/vignettes/vig1')
    expect(app().find('[data-testid="assign-panel"]').exists()).toBe(false)
  })
})

describe('a published version', () => {
  const experts: User[] = [
    { ...expert, id: 'e1', display_name: 'Eve', pseudonym: 'E01' },
    { ...expert, id: 'e2', display_name: 'Finn', pseudonym: 'E02' },
    { ...expert, id: 'e3', display_name: 'Gone', pseudonym: 'E03', is_active: false },
    { ...admin, id: 'a1' },
  ]

  function publishedRoutes(extra: Record<string, () => Response> = {}) {
    return {
      'GET /vignettes': () => jsonResponse(200, [vignette([version({ status: 'published' })])]),
      'GET /users': () => jsonResponse(200, experts),
      'GET /assignments': () => jsonResponse(200, [summary()]),
      ...extra,
    }
  }

  it('is read-only', async () => {
    serve(publishedRoutes())
    await open('/vignettes/vig1')
    expect(app().get('[data-testid="text"]').attributes('disabled')).toBeDefined()
    expect(
      app()
        .findAll('button')
        .some((b) => b.text() === 'Save draft'),
    ).toBe(false)
  })

  it('asks only for the assignments of this version', async () => {
    serve(publishedRoutes())
    await open('/vignettes/vig1')
    const asked = calls.find((c) => c.url.startsWith('/api/v1/assignments'))
    expect(asked?.url).toContain('vignette_version_id=ver1')
  })

  it('lists who has it, and offers only active experts who do not', async () => {
    serve(publishedRoutes())
    await open('/vignettes/vig1')
    const panel = app().get('[data-testid="assign-panel"]')
    expect(panel.get('[data-testid="assigned"]').text()).toContain('Eve')
    expect(panel.get('[data-testid="assigned"]').text()).toContain('Not started')
    const offered = panel.findAll('[data-testid="offer"]').map((o) => o.text())
    expect(offered).toEqual([expect.stringContaining('Finn')])
  })

  it('assigns the chosen experts, then shows the new state', async () => {
    serve(
      publishedRoutes({
        'POST /vignette-versions/ver1/assignments': () => jsonResponse(201, []),
      }),
    )
    await open('/vignettes/vig1')
    expect(buttonNamed('Assign').attributes('disabled')).toBeDefined()
    await app().get('[data-testid="offer"] input').setValue(true)
    await buttonNamed('Assign').trigger('click')
    await flushPromises()
    expect(writes()[0]?.url).toBe('/api/v1/vignette-versions/ver1/assignments')
    expect(writes()[0]?.body).toEqual({ expert_ids: ['e2'] })
    expect(calls.filter((c) => c.url.startsWith('/api/v1/assignments')).length).toBe(2)
  })

  it('names the experts a refusal is about', async () => {
    serve(
      publishedRoutes({
        'POST /vignette-versions/ver1/assignments': () =>
          jsonResponse(409, {
            code: 'reviewer_contaminated',
            message: 'These experts have already reviewed answers to this vignette.',
            details: { expert_ids: ['e2'] },
          }),
      }),
    )
    await open('/vignettes/vig1')
    await app().get('[data-testid="offer"] input').setValue(true)
    await buttonNamed('Assign').trigger('click')
    await flushPromises()
    const alert = app().get('[data-testid="assign-panel"] [role="alert"]').text()
    expect(alert).toContain('already reviewed')
    expect(alert).toContain('Finn')
  })

  it('asks before cancelling an assignment', async () => {
    serve(publishedRoutes({ 'POST /assignments/as1/cancel': () => jsonResponse(200, {}) }))
    await open('/vignettes/vig1')
    await buttonNamed('Cancel').trigger('click')
    expect(writes()).toHaveLength(0)
    await app()
      .get('dialog[open]')
      .findAll('button')
      .find((b) => b.text() === 'Cancel assignment')
      ?.trigger('click')
    await flushPromises()
    expect(writes()[0]?.url).toBe('/api/v1/assignments/as1/cancel')
  })

  it('treats a cancelled assignment as open again', async () => {
    serve(
      publishedRoutes({
        'GET /assignments': () =>
          jsonResponse(200, [summary({ state: 'cancelled', allowed_actions: [] })]),
      }),
    )
    await open('/vignettes/vig1')
    expect(app().findAll('[data-testid="offer"]')).toHaveLength(2)
    expect(app().find('[data-testid="assigned"]').exists()).toBe(false)
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

  it('offers no new assignments on a retired version', async () => {
    serve(
      publishedRoutes({
        'GET /vignettes': () => jsonResponse(200, [vignette([version({ status: 'retired' })])]),
      }),
    )
    await open('/vignettes/vig1')
    expect(app().find('[data-testid="assign-panel"]').exists()).toBe(true)
    expect(app().find('[data-testid="offer"]').exists()).toBe(false)
  })

  it('can start a new version that keeps the variant', async () => {
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
    expect(writes()[0]?.body).toMatchObject({ text: TEXT, variant })
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
