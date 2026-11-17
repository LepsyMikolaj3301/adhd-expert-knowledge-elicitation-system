import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import type { AssignmentSummary, User } from '@/api/client'
import router from '@/router'
import { useAuthStore } from '@/stores/auth'
import AssignmentsView from '@/views/AssignmentsView.vue'
import HomeView from '@/views/HomeView.vue'

import { admin, expert, jsonResponse, serve, writes } from './helpers'

const REFUSED = { code: 'job_still_running', message: 'The job has not finished yet.' }

function summary(overrides: Partial<AssignmentSummary> = {}): AssignmentSummary {
  return {
    id: 'a1',
    state: 'proofreading',
    allowed_actions: [],
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

const gets = (mock: ReturnType<typeof serve>, path: string) =>
  mock.mock.calls.filter(
    ([i]) => (i as Request).method === 'GET' && (i as Request).url.endsWith(path),
  ).length

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.useRealTimers())

describe('a failed action on the assignments list', () => {
  async function open(
    actions: AssignmentSummary['allowed_actions'],
    write: string,
    answer: Response,
  ) {
    logIn(admin)
    mockDialog()
    const mock = serve({
      'GET /api/v1/assignments': jsonResponse(200, [summary({ allowed_actions: actions })]),
      [write]: answer,
    })
    const wrapper = mount(AssignmentsView, { global: { plugins: [router] } })
    await flushPromises()
    return { mock, wrapper }
  }

  it('tells the admin why a cancel was refused, and keeps the case in the list', async () => {
    const { mock, wrapper } = await open(
      ['cancel'],
      'POST /api/v1/assignments/a1/cancel',
      jsonResponse(409, REFUSED),
    )
    await wrapper.get('[data-testid="cancel"]').trigger('click')
    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Cancel assignment')!
      .trigger('click')
    await flushPromises()
    expect(writes(mock)).toEqual(['POST /api/v1/assignments/a1/cancel'])
    expect(wrapper.get('[role="alert"]').text()).toContain('The job has not finished yet.')
    expect(wrapper.findAll('[data-testid="assignment"]')).toHaveLength(1)
    wrapper.unmount()
  })

  it('tells the admin why a retry was refused', async () => {
    const { mock, wrapper } = await open(
      ['retry'],
      'POST /api/v1/assignments/a1/retry',
      jsonResponse(409, REFUSED),
    )
    await wrapper.get('[data-testid="retry"]').trigger('click')
    await flushPromises()
    expect(writes(mock)).toEqual(['POST /api/v1/assignments/a1/retry'])
    expect(wrapper.get('[role="alert"]').text()).toContain('The job has not finished yet.')
    wrapper.unmount()
  })

  it('reloads the list after a retry that worked, with nothing to complain about', async () => {
    const { mock, wrapper } = await open(
      ['retry'],
      'POST /api/v1/assignments/a1/retry',
      jsonResponse(200, {}),
    )
    await wrapper.get('[data-testid="retry"]').trigger('click')
    await flushPromises()
    expect(gets(mock, '/api/v1/assignments')).toBe(2)
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    wrapper.unmount()
  })
})

describe('a failed retry on the home page', () => {
  const home = {
    next_up: [
      {
        assignment_id: 'a9',
        action: 'retry',
        vignette_code: 'V009',
        vignette_version: 1,
        state: 'proofreading',
        updated_at: '',
        expert_pseudonym: null,
      },
    ],
    next_up_total: 1,
    reviews_waiting: [],
    reviews_waiting_total: 0,
    recent_reviews: [],
    activity: [],
    unread_activity: 0,
  }

  async function open(answer: Response) {
    logIn(expert)
    const mock = serve({
      'GET /api/v1/me/home': jsonResponse(200, home),
      'POST /api/v1/assignments/a9/retry': answer,
    })
    const wrapper = mount(HomeView, { global: { plugins: [router] } })
    await flushPromises()
    return { mock, wrapper }
  }

  it('says so instead of failing silently, and shows the list as it is now', async () => {
    const { mock, wrapper } = await open(jsonResponse(409, REFUSED))
    const failures: unknown[] = []
    const onRejection = (e: unknown) => failures.push(e)
    process.on('unhandledRejection', onRejection)
    await wrapper.get('[data-testid="next-up"] button').trigger('click')
    await flushPromises()
    process.off('unhandledRejection', onRejection)
    expect(failures).toEqual([])
    expect(writes(mock)).toEqual(['POST /api/v1/assignments/a9/retry'])
    // an expert gets the calm wording, never the server's
    expect(wrapper.get('[data-testid="next-up"] [role="alert"]').text()).toContain(
      'Something went wrong. Your text is safe.',
    )
    expect(gets(mock, '/api/v1/me/home')).toBe(2)
    wrapper.unmount()
  })

  it('reloads the list after a retry that worked', async () => {
    const { mock, wrapper } = await open(jsonResponse(200, {}))
    await wrapper.get('[data-testid="next-up"] button').trigger('click')
    await flushPromises()
    expect(gets(mock, '/api/v1/me/home')).toBe(2)
    expect(wrapper.find('[data-testid="next-up"] [role="alert"]').exists()).toBe(false)
    wrapper.unmount()
  })
})
