import type { RouteLocationNormalized, RouteLocationRaw } from 'vue-router'

import type { User } from '@/api/client'

declare module 'vue-router' {
  interface RouteMeta {
    requiresAuth?: boolean
    roles?: User['role'][]
    guestOnly?: boolean
  }
}

/**
 * Where a navigation may go. This is for the user's convenience only: the API enforces every
 * permission again, whatever the browser does.
 */
export function guardRoute(
  to: Pick<RouteLocationNormalized, 'meta' | 'fullPath'>,
  user: User | null,
): true | RouteLocationRaw {
  if (to.meta.requiresAuth && !user) {
    return { name: 'login', query: { next: to.fullPath } }
  }
  if (to.meta.roles && (!user || !to.meta.roles.includes(user.role))) {
    return { name: 'assignments' }
  }
  if (to.meta.guestOnly && user) {
    return { name: 'assignments' }
  }
  return true
}

/** Only ever a path inside this app: `next` comes from the URL, so it can't be trusted. */
export function safeNextPath(next: unknown): string {
  return typeof next === 'string' && next.startsWith('/') && !next.startsWith('//')
    ? next
    : '/assignments'
}
