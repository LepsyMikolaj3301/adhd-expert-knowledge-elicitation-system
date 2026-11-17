import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import type { UserAdmin } from '@/api/client'
import router from '@/router'
import { useAuthStore } from '@/stores/auth'
import ExpertsView from '@/views/ExpertsView.vue'

import { admin, expert, jsonResponse, serve, writes } from './helpers'

const person = (over: Partial<UserAdmin> = {}): UserAdmin => ({
  ...expert,
  id: 'u1',
  display_name: 'Eve',
  email: 'eve@example.com',
  invite_pending: false,
  ...over,
})

const REFUSED = { code: 'user_not_found', message: 'That account does not exist.' }
let wrapper: VueWrapper | undefined

/** The list is answered from `users`, which the writes below may change. */
async function open(users: UserAdmin[], routes: Parameters<typeof serve>[0] = {}) {
  const mock = serve({ 'GET /api/v1/users': () => jsonResponse(200, users), ...routes })
  wrapper = mount(ExpertsView, { global: { plugins: [router] }, attachTo: document.body })
  await flushPromises()
  return mock
}

const button = (name: string) => {
  const found = wrapper!.findAll('button').find((b) => b.text() === name)
  if (!found) throw new Error(`no button "${name}" in: ${wrapper!.text()}`)
  return found
}
const dialogButton = (name: string) =>
  wrapper!
    .get('dialog')
    .findAll('button')
    .find((b) => b.text() === name)!
const usersLoaded = (mock: ReturnType<typeof serve>) =>
  mock.mock.calls.filter(([i]) => (i as Request).method === 'GET').length
const body = async (mock: ReturnType<typeof serve>, method: string) =>
  (mock.mock.calls.find(([i]) => (i as Request).method === method)![0] as Request)
    .clone()
    .json() as Promise<Record<string, unknown>>

beforeEach(() => {
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
})
afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
})

describe('the experts list', () => {
  it('says it is loading, and then shows the accounts', async () => {
    let answer: (r: Response) => void = () => {}
    serve({
      'GET /api/v1/users': () => new Promise<Response>((resolve) => (answer = resolve)),
    })
    wrapper = mount(ExpertsView, { global: { plugins: [router] }, attachTo: document.body })
    expect(wrapper.text()).toContain('Loading…')
    answer(jsonResponse(200, [person()]))
    await flushPromises()
    expect(wrapper.text()).not.toContain('Loading…')
    expect(wrapper.findAll('[data-testid="user"]')).toHaveLength(1)
  })

  it('shows why the accounts could not be loaded', async () => {
    serve({ 'GET /api/v1/users': jsonResponse(500, { code: 'internal_error', message: 'x' }) })
    wrapper = mount(ExpertsView, { global: { plugins: [router] }, attachTo: document.body })
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).not.toBe('')
    expect(wrapper.find('[data-testid="user"]').exists()).toBe(false)
  })

  it('offers a new invite link only to accounts that are active', async () => {
    await open([person({ id: 'u1' }), person({ id: 'u2', is_active: false })])
    const rows = wrapper!.findAll('[data-testid="user"]')
    expect(rows[0]!.text()).toContain('New invite link')
    expect(rows[0]!.text()).toContain('Deactivate')
    expect(rows[1]!.text()).not.toContain('New invite link')
    expect(rows[1]!.text()).toContain('Reactivate')
  })
})

describe('invite links', () => {
  it('shows a new link for the account, as a full address, and then lets it go', async () => {
    const mock = await open([person()], {
      'POST /api/v1/users/u1/invite': jsonResponse(200, { invite_path: '/invite/fresh' }),
    })
    await button('New invite link').trigger('click')
    await flushPromises()
    expect(writes(mock)).toEqual(['POST /api/v1/users/u1/invite'])
    const box = wrapper!.get('[data-testid="invite"]')
    expect(box.text()).toContain('Eve')
    expect((box.get('input').element as HTMLInputElement).value).toBe(
      `${location.origin}/invite/fresh`,
    )
    await button('I have sent it').trigger('click')
    expect(wrapper!.find('[data-testid="invite"]').exists()).toBe(false)
  })

  it('says whether the link was copied', async () => {
    await open([person()], {
      'POST /api/v1/users/u1/invite': jsonResponse(200, { invite_path: '/invite/fresh' }),
    })
    await button('New invite link').trigger('click')
    await flushPromises()

    vi.stubGlobal('navigator', {
      clipboard: { writeText: vi.fn<() => Promise<void>>().mockResolvedValue(undefined) },
    })
    await button('Copy link').trigger('click')
    await flushPromises()
    expect(wrapper!.get('[data-testid="invite"]').text()).toContain('Copied.')

    vi.stubGlobal('navigator', {
      clipboard: { writeText: vi.fn<() => Promise<void>>().mockRejectedValue(new Error('denied')) },
    })
    await button('Copy link').trigger('click')
    await flushPromises()
    expect(wrapper!.get('[data-testid="invite"]').text()).toContain('Could not copy.')
  })

  it('shows the server’s reason when no link could be made, and still shows the list', async () => {
    const mock = await open([person()], {
      'POST /api/v1/users/u1/invite': jsonResponse(404, REFUSED),
    })
    await button('New invite link').trigger('click')
    await flushPromises()
    expect(wrapper!.get('[role="alert"]').text()).toBe('That account does not exist.')
    expect(wrapper!.find('[data-testid="invite"]').exists()).toBe(false)
    expect(usersLoaded(mock)).toBe(2)
  })
})

describe('adding, renaming and deactivating accounts', () => {
  it('keeps what was typed when the account could not be added', async () => {
    const mock = await open([], {
      'POST /api/v1/users': jsonResponse(409, {
        code: 'email_taken',
        message: 'engineering words',
      }),
    })
    await wrapper!.get('input[type="email"]').setValue('eve@example.com')
    await wrapper!.get('input:not([type])').setValue('Eve')
    await wrapper!.get('form').trigger('submit')
    await flushPromises()
    expect(await body(mock, 'POST')).toMatchObject({
      email: 'eve@example.com',
      display_name: 'Eve',
      role: 'expert',
    })
    expect(wrapper!.get('[role="alert"]').text()).toContain('already has an account')
    expect((wrapper!.get('input[type="email"]').element as HTMLInputElement).value).toBe(
      'eve@example.com',
    )
  })

  it('renames an account and shows the list again', async () => {
    const mock = await open([person()], { 'PATCH /api/v1/users/u1': jsonResponse(200, person()) })
    await button('Edit name').trigger('click')
    await wrapper!.get('input[aria-label="Name of Eve"]').setValue('Evelyn')
    await button('Save').trigger('click')
    await flushPromises()
    expect(await body(mock, 'PATCH')).toEqual({ display_name: 'Evelyn' })
    expect(usersLoaded(mock)).toBe(2)
    expect(wrapper!.find('input[aria-label="Name of Eve"]').exists()).toBe(false)
  })

  it('asks before deactivating, and does nothing when the admin cancels', async () => {
    const mock = await open([person()])
    await button('Deactivate').trigger('click')
    expect(document.body.textContent).toContain('Deactivate this account?')
    expect(wrapper!.get('dialog').text()).toContain('Eve will no longer be able to sign in.')
    await dialogButton('Cancel').trigger('click')
    expect(writes(mock)).toEqual([])
    expect(wrapper!.find('dialog').exists()).toBe(false)
  })

  it.each([
    [true, 'Deactivate', false, 'will no longer be able to sign in'],
    [false, 'Reactivate', true, 'will be able to sign in again'],
  ])(
    'sets is_active when the admin confirms (active now: %s)',
    async (active, label, sent, message) => {
      const mock = await open([person({ is_active: active })], {
        'PATCH /api/v1/users/u1': jsonResponse(200, person()),
      })
      await button(label).trigger('click')
      expect(wrapper!.get('dialog').text()).toContain(message)
      await dialogButton(label).trigger('click')
      await flushPromises()
      expect(await body(mock, 'PATCH')).toEqual({ is_active: sent })
      expect(usersLoaded(mock)).toBe(2)
    },
  )

  it('shows why an account could not be changed', async () => {
    await open([person()], { 'PATCH /api/v1/users/u1': jsonResponse(404, REFUSED) })
    await button('Deactivate').trigger('click')
    await dialogButton('Deactivate').trigger('click')
    await flushPromises()
    expect(wrapper!.get('[role="alert"]').text()).toBe('That account does not exist.')
  })
})
