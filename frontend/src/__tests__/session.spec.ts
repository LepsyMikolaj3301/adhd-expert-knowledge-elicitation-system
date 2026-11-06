import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { api, ApiError } from '@/api/client'
import router from '@/router'
import { installSessionHandler } from '@/session'
import { useAuthStore } from '@/stores/auth'

import { expert, jsonResponse, stubFetch } from './helpers'

beforeEach(() => {
  setActivePinia(createPinia())
  installSessionHandler(router)
  const auth = useAuthStore()
  auth.user = expert
  auth.loaded = true
  stubFetch(() => jsonResponse(401, { code: 'not_authenticated', message: 'Please log in.' }))
})

describe('when the session ends', () => {
  it('sends the user to the login page from an ordinary page, remembering where they were', async () => {
    await router.push('/account')
    await expect(api.GET('/api/v1/me')).rejects.toBeInstanceOf(ApiError)
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe('login'))
    expect(router.currentRoute.value.query.next).toBe('/account')
    expect(useAuthStore().user).toBeNull()
  })

  it('stays on the answering page, so that what was written is not lost', async () => {
    await router.push('/assignments/a1')
    await expect(api.GET('/api/v1/me')).rejects.toBeInstanceOf(ApiError)
    expect(router.currentRoute.value.path).toBe('/assignments/a1')
    expect(useAuthStore().sessionEnded).toBe(true)
    expect(useAuthStore().user).not.toBeNull()
  })
})
