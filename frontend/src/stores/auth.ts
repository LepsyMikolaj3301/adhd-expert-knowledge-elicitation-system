import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { api, ApiError, type User } from '@/api/client'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const loaded = ref(false)
  /** The server ended the session while the user was on a page that must not be left. */
  const sessionEnded = ref(false)
  const isLoggedIn = computed(() => user.value !== null)
  /** Which side of the app the person is on. Experts and logged-out visitors read as `expert`. */
  const role = computed<'admin' | 'expert'>(() =>
    user.value?.role === 'admin' ? 'admin' : 'expert',
  )

  /** Ask the server who is logged in. The cookie is HttpOnly, so this is the only way to know. */
  async function load(): Promise<void> {
    if (loaded.value) return
    try {
      const { data } = await api.GET('/api/v1/me')
      user.value = data ?? null
      loaded.value = true
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 401) throw error
      user.value = null
      loaded.value = true
    }
  }

  async function login(email: string, password: string): Promise<void> {
    const { data } = await api.POST('/api/v1/auth/login', { body: { email, password } })
    user.value = data ?? null
    loaded.value = true
    sessionEnded.value = false
  }

  async function acceptInvite(token: string, password: string): Promise<void> {
    const { data } = await api.POST('/api/v1/auth/accept-invite', { body: { token, password } })
    user.value = data ?? null
    loaded.value = true
  }

  /** Throws `invalid_invite` when the link was used, replaced or has expired. */
  async function checkInvite(token: string): Promise<void> {
    await api.POST('/api/v1/auth/check-invite', { body: { token } })
  }

  async function logout(): Promise<void> {
    await api.POST('/api/v1/auth/logout')
    user.value = null
    sessionEnded.value = false
  }

  /** The session has ended on the server. */
  function clear(): void {
    user.value = null
    loaded.value = true
    sessionEnded.value = false
  }

  /** Like `clear`, but the page stays: the user is asked to sign in again over it. */
  function endSession(): void {
    sessionEnded.value = true
  }

  return {
    user,
    loaded,
    sessionEnded,
    isLoggedIn,
    role,
    load,
    login,
    acceptInvite,
    checkInvite,
    logout,
    clear,
    endSession,
  }
})
