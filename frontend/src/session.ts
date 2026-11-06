import type { Router } from 'vue-router'

import { setUnauthorizedHandler } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

/**
 * What happens when the API says the session has ended. Most pages send the user to the login
 * page. A page marked `keepOnExpiry` (the answering screen) stays where it is instead, so that
 * what was written is not thrown away: it asks for the password over the page, and carries on.
 */
export function installSessionHandler(router: Router): void {
  setUnauthorizedHandler(() => {
    const auth = useAuthStore()
    const { meta, fullPath } = router.currentRoute.value
    if (meta.keepOnExpiry && auth.user) {
      auth.endSession()
      return
    }
    auth.clear()
    if (meta.requiresAuth) router.push({ name: 'login', query: { next: fullPath } })
  })
}
