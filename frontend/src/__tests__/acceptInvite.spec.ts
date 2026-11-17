import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import router from '@/router'
import { useAuthStore } from '@/stores/auth'
import AcceptInviteView from '@/views/AcceptInviteView.vue'

import { admin, jsonResponse, serve, writes } from './helpers'

let wrapper: VueWrapper | undefined
const ACCEPT = 'POST /api/v1/auth/accept-invite'

async function open(routes: Parameters<typeof serve>[0]) {
  const mock = serve({
    'GET /api/v1/me': jsonResponse(401, { code: 'not_authenticated', message: 'Sign in.' }),
    ...routes,
  })
  await router.push('/invite/invite-token')
  wrapper = mount(AcceptInviteView, { global: { plugins: [router] } })
  await flushPromises()
  return mock
}

async function setPassword(password: string) {
  await wrapper!.get('input[type="password"]').setValue(password)
  await wrapper!.get('form').trigger('submit')
  await flushPromises()
}

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
})

describe('accepting an invite', () => {
  it('asks for a password of at least twelve characters', async () => {
    await open({})
    const input = wrapper!.get('input[type="password"]')
    expect(input.attributes('minlength')).toBe('12')
    expect(input.attributes('required')).toBeDefined()
    expect(input.attributes('autocomplete')).toBe('new-password')
    expect(wrapper!.text()).toContain('at least 12 characters')
  })

  it('sends the token from the link with the password, signs in and goes home', async () => {
    const mock = await open({ [ACCEPT]: jsonResponse(200, admin) })
    await setPassword('a long enough password')

    expect(writes(mock)).toEqual([ACCEPT])
    const request = mock.mock.calls.find(([i]) => (i as Request).method === 'POST')![0] as Request
    expect(await request.clone().json()).toEqual({
      token: 'invite-token',
      password: 'a long enough password',
    })
    expect(useAuthStore().user?.email).toBe(admin.email)
    expect(router.currentRoute.value.name).toBe('home')
  })

  it.each([
    [410, 'invite_expired', 'This invitation has expired.'],
    [404, 'invite_invalid', 'This invitation is not valid.'],
    [422, 'validation_error', 'Password: String should have at least 12 characters.'],
  ])('shows what the server said when it answers %s', async (status, code, message) => {
    await open({ [ACCEPT]: jsonResponse(status, { code, message }) })
    await setPassword('a long enough password')
    expect(wrapper!.get('[role="alert"]').text()).toBe(message)
    expect(useAuthStore().user).toBeNull()
    expect(router.currentRoute.value.name).toBe('invite')
  })

  it('uses its own words when nothing came back from the server', async () => {
    await open({
      [ACCEPT]: () => {
        throw new TypeError('network down')
      },
    })
    await setPassword('a long enough password')
    expect(wrapper!.get('[role="alert"]').text()).toBe('Something went wrong. Please try again.')
    expect(useAuthStore().user).toBeNull()
  })

  it('cannot be sent twice while it waits, and the error goes when it is tried again', async () => {
    let answer: (r: Response) => void = () => {}
    const slow = new Promise<Response>((resolve) => (answer = resolve))
    let calls = 0
    const mock = await open({
      [ACCEPT]: () => (calls++ ? slow : jsonResponse(410, { code: 'x', message: 'Expired.' })),
    })
    await setPassword('a long enough password')
    expect(wrapper!.find('[role="alert"]').exists()).toBe(true)

    await wrapper!.get('form').trigger('submit')
    expect(wrapper!.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper!.get('button[type="submit"]').attributes('disabled')).toBeDefined()
    answer(jsonResponse(200, admin))
    await flushPromises()
    expect(writes(mock)).toHaveLength(2)
    expect(wrapper!.get('button[type="submit"]').attributes('disabled')).toBeUndefined()
  })
})
