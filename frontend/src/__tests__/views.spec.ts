import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import type { AssignmentSummary, User } from '@/api/client'
import { TRUST_SENTENCE } from '@/copy'
import router from '@/router'
import { useAuthStore } from '@/stores/auth'
import AssignmentsView from '@/views/AssignmentsView.vue'
import LoginView from '@/views/LoginView.vue'

import { admin, expert, jsonResponse, stubFetch } from './helpers'

function summary(overrides: Partial<AssignmentSummary> = {}): AssignmentSummary {
  return {
    id: 'a1',
    state: 'in_progress',
    allowed_actions: ['save_draft', 'submit'],
    job_running: false,
    vignette_code: 'V001',
    vignette_version: 1,
    vignette_version_id: 'v1',
    expert_id: 'e7',
    expert_pseudonym: 'E07',
    patient_summary: 'A student.',
    framing: 'email',
    word_count: 130,
    opening: 'one two three…',
    updated_at: '2026-11-04T10:00:00Z',
    ...overrides,
  }
}

function mountView(component: Parameters<typeof mount>[0]) {
  return mount(component, { global: { plugins: [router] } })
}

/** Skips the router's call to /me, so that the stubbed fetch only sees the view's calls. */
function logIn(user: User) {
  const auth = useAuthStore()
  auth.user = user
  auth.loaded = true
}

function mockDialog() {
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute('open', '')
  }
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute('open')
  }
}

/** The paths of the writes a stubbed fetch has seen. */
function posts(mock: ReturnType<typeof stubFetch>) {
  return mock.mock.calls
    .map(([input]) => input as Request)
    .filter((r) => r.method !== 'GET')
    .map((r) => new URL(r.url).pathname)
}

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.useRealTimers())

describe('AssignmentsView', () => {
  it.each([
    ['assigned', ['start'], 'Not started', 'Start'],
    ['in_progress', ['save_draft', 'submit'], 'In progress', 'Continue'],
    ['proofreading', [], 'Proofreading…', 'View'],
    ['proofread_check', ['submit_for_review'], 'Ready to check', 'Check'],
    ['peer_review', [], 'In review', 'View'],
    ['ingested', [], 'In review', 'View'],
  ] as const)(
    'shows an expert %s in plain words, with a link',
    async (state, actions, label, link) => {
      logIn(expert)
      vi.stubGlobal(
        'fetch',
        vi.fn(async () => jsonResponse(200, [summary({ state, allowed_actions: [...actions] })])),
      )
      const wrapper = mountView(AssignmentsView)
      await flushPromises()

      expect(wrapper.get('[data-testid="state"]').text()).toBe(label)
      const anchor = wrapper.get('[data-testid="open"]')
      expect(anchor.text()).toBe(link)
      expect(anchor.attributes('href')).toBe('/assignments/a1')
      expect(wrapper.text()).not.toContain('E07')
      wrapper.unmount()
    },
  )

  it("calls an expert's list My cases, and each row a case", async () => {
    logIn(expert)
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(200, [summary()])),
    )
    const wrapper = mountView(AssignmentsView)
    await flushPromises()
    expect(wrapper.get('h1').text()).toBe('My cases')
    expect(wrapper.get('[data-testid="assignment"]').text()).toContain('Case V001')
    wrapper.unmount()
  })

  it('offers nothing to open on a cancelled assignment', async () => {
    logIn(expert)
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(200, [summary({ state: 'cancelled', allowed_actions: [] })])),
    )
    const wrapper = mountView(AssignmentsView)
    await flushPromises()
    expect(wrapper.get('[data-testid="state"]').text()).toBe('Cancelled')
    expect(wrapper.find('[data-testid="open"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('confirms a submission that just happened', async () => {
    logIn(expert)
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(200, [summary({ state: 'proofreading' })])),
    )
    await router.push({ path: '/assignments', query: { submitted: 'V001' } })
    const wrapper = mountView(AssignmentsView)
    await flushPromises()
    const status = wrapper.get('[role="status"]').text()
    expect(status).toContain('Case V001 submitted for proofreading.')
    expect(status).toContain('submit it for review')
    wrapper.unmount()
    await router.push('/assignments')
  })

  it('confirms answers just sent for review', async () => {
    logIn(expert)
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(200, [summary({ state: 'peer_review' })])),
    )
    await router.push({ path: '/assignments', query: { sent: 'V001' } })
    const wrapper = mountView(AssignmentsView)
    await flushPromises()
    expect(wrapper.get('[role="status"]').text()).toBe('Case V001 sent for review. Thank you.')
    wrapper.unmount()
    await router.push('/assignments')
  })

  it('shows a loading circle while a case is proofread', async () => {
    logIn(expert)
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(200, [summary({ state: 'proofreading', job_running: true })])),
    )
    const wrapper = mountView(AssignmentsView)
    await flushPromises()
    const state = wrapper.get('[data-testid="state"]')
    expect(state.find('[data-testid="spinner"]').exists()).toBe(true)
    expect(state.text()).toBe('Proofreading…')
    wrapper.unmount()
  })

  it('shows admins the expert, a plain status and only the buttons they can use', async () => {
    logIn(admin)
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(200, [
          summary({
            state: 'peer_review',
            allowed_actions: ['cancel', 'comment', 'decide_answers'],
          }),
        ]),
      ),
    )
    const wrapper = mountView(AssignmentsView)
    await flushPromises()
    expect(wrapper.get('[data-testid="pseudonym"]').text()).toBe('E07')
    expect(wrapper.get('[data-testid="state"]').text()).toBe('In review, waiting for your decision')
    const actions = wrapper.get('[data-testid="actions"]')
    expect(actions.get('[data-testid="decide"]').attributes('href')).toBe('/reviews/a1')
    expect(actions.find('[data-testid="cancel"]').exists()).toBe(true)
    expect(actions.text()).not.toContain('comment')
    wrapper.unmount()
  })

  it('shows a dash when the admin has nothing to do on a row', async () => {
    logIn(admin)
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(200, [summary({ state: 'ingested', allowed_actions: [] })])),
    )
    const wrapper = mountView(AssignmentsView)
    await flushPromises()
    expect(wrapper.get('[data-testid="actions"]').text()).toBe('—')
    wrapper.unmount()
  })

  it('asks before the admin cancels, then cancels', async () => {
    logIn(admin)
    mockDialog()
    const fetchMock = stubFetch((url) =>
      jsonResponse(200, url.endsWith('/cancel') ? {} : [summary({ allowed_actions: ['cancel'] })]),
    )
    const wrapper = mountView(AssignmentsView)
    await flushPromises()
    await wrapper.get('[data-testid="cancel"]').trigger('click')
    expect(posts(fetchMock)).toHaveLength(0)
    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Cancel assignment')!
      .trigger('click')
    await flushPromises()
    expect(posts(fetchMock)).toEqual(['/api/v1/assignments/a1/cancel'])
    wrapper.unmount()
  })

  it('creates an assignment from an expert and a case', async () => {
    logIn(admin)
    mockDialog()
    const version = {
      id: 'v1',
      version: 1,
      status: 'published',
      text: 'one two three',
      patient_summary: 'A student.',
      framing: 'email',
      word_count: 3,
    }
    const fetchMock = stubFetch((url) => {
      if (url.endsWith('/users')) {
        return jsonResponse(200, [{ ...expert, id: 'e2', display_name: 'Finn', pseudonym: 'E02' }])
      }
      if (url.endsWith('/vignettes')) {
        return jsonResponse(200, [
          { id: 'vig1', code: 'V001', created_at: 'now', versions: [version] },
        ])
      }
      return jsonResponse(
        url.endsWith('/assignments') && url.includes('vignette-versions') ? 201 : 200,
        [],
      )
    })
    const wrapper = mountView(AssignmentsView)
    await flushPromises()
    await wrapper.get('[data-testid="create-assignment"]').trigger('click')
    await flushPromises()
    const assign = () => wrapper.findAll('button').find((b) => b.text() === 'Assign')!

    await assign().trigger('click')
    expect(wrapper.text()).toContain('Pick an expert and a case.')
    expect(posts(fetchMock)).toHaveLength(0)

    await wrapper.get('[data-testid="expert"]').setValue('e2')
    await wrapper.get('[data-testid="case-option"] input').setValue()
    await assign().trigger('click')
    await flushPromises()
    expect(posts(fetchMock)).toEqual(['/api/v1/vignette-versions/v1/assignments'])
    const request = fetchMock.mock.calls.find(
      ([r]) => (r as Request).method === 'POST',
    )![0] as Request
    expect(await request.clone().json()).toEqual({ expert_ids: ['e2'] })
    wrapper.unmount()
  })

  it('will not offer a case the chosen expert already has', async () => {
    logIn(admin)
    mockDialog()
    stubFetch((url) => {
      if (url.endsWith('/users'))
        return jsonResponse(200, [{ ...expert, id: 'e7', pseudonym: 'E07' }])
      if (url.endsWith('/vignettes')) {
        const version = {
          id: 'v1',
          version: 1,
          status: 'published',
          text: 'x',
          patient_summary: '',
          framing: 'email',
          word_count: 1,
        }
        return jsonResponse(200, [
          { id: 'vig1', code: 'V001', created_at: 'now', versions: [version] },
        ])
      }
      return jsonResponse(200, [summary()])
    })
    const wrapper = mountView(AssignmentsView)
    await flushPromises()
    await wrapper.get('[data-testid="create-assignment"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-testid="expert"]').setValue('e7')
    const option = wrapper.get('[data-testid="case-option"]')
    expect(option.get('input').attributes('disabled')).toBeDefined()
    expect(option.text()).toContain('already assigned')
    wrapper.unmount()
  })

  it('says so when there is nothing to do', async () => {
    logIn(expert)
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(200, [])),
    )
    const wrapper = mountView(AssignmentsView)
    await flushPromises()
    expect(wrapper.get('[data-testid="empty"]').text()).toBe(
      "No cases yet. You'll see them here once the study team assigns them.",
    )
    wrapper.unmount()
  })

  it('polls only while a job is running, and stops when it leaves', async () => {
    vi.useFakeTimers()
    logIn(expert)
    const pages = [
      summary({ state: 'proofreading', job_running: true }),
      summary({ state: 'proofreading', job_running: true }),
    ]
    const fetchMock = stubFetch(() =>
      jsonResponse(200, [pages.shift() ?? summary({ state: 'proofread_check' })]),
    )

    const wrapper = mountView(AssignmentsView)
    await vi.advanceTimersByTimeAsync(0)
    expect(fetchMock).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(10_000)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(10_000)
    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(wrapper.get('[data-testid="state"]').text()).toBe('Ready to check')

    await vi.advanceTimersByTimeAsync(60_000)
    expect(fetchMock).toHaveBeenCalledTimes(3)
    wrapper.unmount()
  })

  it('stops polling when the view closes', async () => {
    vi.useFakeTimers()
    logIn(expert)
    const fetchMock = stubFetch(() => jsonResponse(200, [summary({ job_running: true })]))
    const wrapper = mountView(AssignmentsView)
    await vi.advanceTimersByTimeAsync(0)
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})

describe('LoginView', () => {
  it('says what happens with the answers before anyone signs in', async () => {
    useAuthStore().loaded = true
    const wrapper = mountView(LoginView)
    expect(wrapper.get('h1').text()).toBe('Sign in')
    expect(wrapper.get('button[type="submit"]').text()).toBe('Sign in')
    expect(wrapper.get('[data-testid="trust"]').text()).toBe(TRUST_SENTENCE)
  })

  it('shows the message from the API when logging in fails', async () => {
    useAuthStore().loaded = true
    stubFetch(() =>
      jsonResponse(401, { code: 'invalid_credentials', message: 'Wrong email or password.' }),
    )
    const wrapper = mountView(LoginView)
    await wrapper.get('input[type="email"]').setValue('e@example.com')
    await wrapper.get('input[type="password"]').setValue('nope')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toBe('Wrong email or password.')
    expect(useAuthStore().user).toBeNull()
  })
})
