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
    allowed_actions: ['pass_gate', 'save_draft'],
    job_running: false,
    vignette_code: 'V001',
    vignette_version: 1,
    vignette_version_id: 'v1',
    expert_pseudonym: 'E07',
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

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.useRealTimers())

describe('AssignmentsView', () => {
  it.each([
    ['assigned', ['start'], 'Not started', 'Start'],
    ['in_progress', ['pass_gate', 'save_draft'], 'In progress', 'Continue'],
    ['processing', [], 'Submitted', 'View'],
    ['expert_check', ['complete_expert_check', 'skip_expert_check'], 'Submitted', 'View'],
    ['ingested', [], 'Submitted', 'View'],
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
      vi.fn(async () => jsonResponse(200, [summary({ state: 'processing' })])),
    )
    await router.push({ path: '/assignments', query: { submitted: 'V001' } })
    const wrapper = mountView(AssignmentsView)
    await flushPromises()
    expect(wrapper.get('[role="status"]').text()).toBe('Case V001 submitted. Thank you.')
    wrapper.unmount()
    await router.push('/assignments')
  })

  it('shows admins the expert and the workflow state', async () => {
    logIn(admin)
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(200, [summary()])),
    )
    const wrapper = mountView(AssignmentsView)
    await flushPromises()
    expect(wrapper.text()).toContain('E07')
    expect(wrapper.get('[data-testid="state"]').text()).toBe('in_progress')
    expect(wrapper.get('[data-testid="actions"]').text()).toBe('pass_gate, save_draft')
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
    const pages = [summary({ job_running: true }), summary({ job_running: true })]
    const fetchMock = stubFetch(() =>
      jsonResponse(200, [pages.shift() ?? summary({ state: 'expert_check' })]),
    )

    const wrapper = mountView(AssignmentsView)
    await vi.advanceTimersByTimeAsync(0)
    expect(fetchMock).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(10_000)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(10_000)
    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(wrapper.get('[data-testid="state"]').text()).toBe('Submitted')

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
