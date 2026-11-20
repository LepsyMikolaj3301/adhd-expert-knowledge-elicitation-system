import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import router from '@/router'
import { useAuthStore } from '@/stores/auth'
import AcceptInviteView from '@/views/AcceptInviteView.vue'

import { admin, jsonResponse, serve, writes } from './helpers'

let wrapper: VueWrapper | undefined
const ACCEPT = 'POST /api/v1/auth/accept-invite'
const CHECK = 'POST /api/v1/auth/check-invite'
const DEAD = jsonResponse(400, { code: 'invalid_invite', message: 'This invite is not valid.' })

async function open(routes: Parameters<typeof serve>[0]) {
  const mock = serve({
    'GET /api/v1/me': jsonResponse(401, { code: 'not_authenticated', message: 'Sign in.' }),
    [CHECK]: new Response(null, { status: 204 }),
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

    expect(writes(mock)).toEqual([CHECK, ACCEPT])
    const request = mock.mock.calls
      .map(([i]) => i as Request)
      .find((r) => r.url.endsWith('/accept-invite'))!
    expect(await request.clone().json()).toEqual({
      token: 'invite-token',
      password: 'a long enough password',
    })
    expect(useAuthStore().user?.email).toBe(admin.email)
    expect(router.currentRoute.value.name).toBe('home')
  })

  it.each([
    [429, 'rate_limited', 'Too many tries.'],
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
      [ACCEPT]: () => (calls++ ? slow : jsonResponse(500, { code: 'x', message: 'Broken.' })),
    })
    await setPassword('a long enough password')
    expect(wrapper!.find('[role="alert"]').exists()).toBe(true)

    await wrapper!.get('form').trigger('submit')
    expect(wrapper!.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper!.get('button[type="submit"]').attributes('disabled')).toBeDefined()
    answer(jsonResponse(200, admin))
    await flushPromises()
    expect(writes(mock)).toEqual([CHECK, ACCEPT, ACCEPT])
    expect(wrapper!.get('button[type="submit"]').attributes('disabled')).toBeUndefined()
  })

  it('says under the field, not in a bubble, that the password is too short, and sends nothing', async () => {
    const mock = await open({ [ACCEPT]: jsonResponse(200, admin) })
    expect(wrapper!.get('form').attributes('novalidate')).toBeDefined()
    await setPassword('short')
    const error = wrapper!.get('[data-testid="password-error"]')
    expect(error.text()).toBe('The password needs at least 12 characters. It has 5 now.')
    expect(wrapper!.get('input').attributes('aria-invalid')).toBe('true')
    // Between the field and the button.
    const order = wrapper!.get('form').element.innerHTML
    expect(order.indexOf('password-error')).toBeGreaterThan(order.indexOf('<input'))
    expect(order.indexOf('password-error')).toBeLessThan(order.indexOf('<button'))
    expect(writes(mock)).toEqual([CHECK])
  })

  it('updates the message as the password is typed, and drops it once it is long enough', async () => {
    await open({ [ACCEPT]: jsonResponse(200, admin) })
    await setPassword('short')
    await wrapper!.get('input').setValue('a bit longer')
    expect(wrapper!.find('[data-testid="password-error"]').exists()).toBe(false)
    await wrapper!.get('input').setValue('a bit')
    expect(wrapper!.get('[data-testid="password-error"]').text()).toContain('It has 5 now.')
  })

  it('shows no form for a link that was already used, and points to sign in', async () => {
    const mock = await open({ [CHECK]: DEAD })
    expect(wrapper!.find('form').exists()).toBe(false)
    expect(wrapper!.text()).toContain("This link can't be used")
    expect(wrapper!.get('[data-testid="invite-dead"]').text()).toContain(
      'Each link works only once',
    )
    expect(wrapper!.get('a').attributes('href')).toBe('/login')
    expect(writes(mock)).toEqual([CHECK])
  })

  it('shows the same when the link dies before the password is set', async () => {
    await open({ [ACCEPT]: DEAD })
    await setPassword('a long enough password')
    expect(wrapper!.find('form').exists()).toBe(false)
    expect(wrapper!.text()).toContain("This link can't be used")
  })

  it('still offers the form when the link could not be checked', async () => {
    await open({
      [CHECK]: () => {
        throw new TypeError('network down')
      },
    })
    expect(wrapper!.find('form').exists()).toBe(true)
  })
})
