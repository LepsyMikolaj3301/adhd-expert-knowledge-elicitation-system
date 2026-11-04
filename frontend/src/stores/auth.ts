import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { api, ApiError, type User } from '@/api/client'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const loaded = ref(false)
  const isLoggedIn = computed(() => user.value !== null)

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
  }

  async function acceptInvite(token: string, password: string): Promise<void> {
    const { data } = await api.POST('/api/v1/auth/accept-invite', { body: { token, password } })
    user.value = data ?? null
    loaded.value = true
  }

  async function logout(): Promise<void> {
    await api.POST('/api/v1/auth/logout')
    user.value = null
  }

  /** The session has ended on the server. */
  function clear(): void {
    user.value = null
    loaded.value = true
  }

  return { user, loaded, isLoggedIn, load, login, acceptInvite, logout, clear }
})
