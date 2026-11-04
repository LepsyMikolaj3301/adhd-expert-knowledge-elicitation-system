import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import type { AssignmentSummary, User } from '@/api/client'
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
  it('shows the state and what the server says is possible', async () => {
    logIn(expert)
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(200, [summary()])),
    )
    const wrapper = mountView(AssignmentsView)
    await flushPromises()

    expect(wrapper.get('[data-testid="state"]').text()).toBe('in_progress')
    expect(wrapper.get('[data-testid="actions"]').text()).toBe('pass_gate, save_draft')
    expect(wrapper.text()).not.toContain('E07')
    wrapper.unmount()
  })

  it('shows the expert column to admins only', async () => {
    logIn(admin)
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(200, [summary()])),
    )
    const wrapper = mountView(AssignmentsView)
    await flushPromises()
    expect(wrapper.text()).toContain('E07')
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
    expect(wrapper.find('[data-testid="empty"]').exists()).toBe(true)
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
    expect(wrapper.get('[data-testid="state"]').text()).toBe('expert_check')

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
