import { ref } from 'vue'
import { defineStore } from 'pinia'

import { api, type HomeData } from '@/api/client'

/** What the home page shows, and the counts the side panel reads from the same answer. */
export const useHomeStore = defineStore('home', () => {
  const data = ref<HomeData | null>(null)
  const failed = ref(false)

  async function load(): Promise<void> {
    try {
      data.value = (await api.GET('/api/v1/me/home')).data ?? null
      failed.value = false
    } catch {
      failed.value = true
    }
  }

  /** Tells the server what the page showed. The items keep the server's `unread` until the next load. */
  async function markSeen(): Promise<void> {
    const d = data.value
    if (!d?.unread_activity) return
    const until = d.activity.reduce((a, i) => (i.at > a ? i.at : a), '')
    try {
      await api.POST('/api/v1/me/activity/seen', { body: { until } })
      d.unread_activity = 0
    } catch {
      // Still unread: the next visit tries again.
    }
  }

  return { data, failed, load, markSeen }
})
