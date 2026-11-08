import { createRouter, createWebHistory } from 'vue-router'

import AppLayout from '@/layouts/AppLayout.vue'
import { useAuthStore } from '@/stores/auth'

import { guardRoute } from './guard'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { guestOnly: true },
    },
    {
      path: '/invite/:token',
      name: 'invite',
      component: () => import('@/views/AcceptInviteView.vue'),
    },
    {
      // Everything behind the login shares the side panel. The children inherit `requiresAuth`.
      path: '/',
      component: AppLayout,
      meta: { requiresAuth: true },
      children: [
        // No home page in this build: the guard and the site name still send people to 'home'.
        { path: '', name: 'home', redirect: '/assignments' },
        {
          path: 'assignments',
          name: 'assignments',
          component: () => import('@/views/AssignmentsView.vue'),
        },
        {
          path: 'assignments/:id',
          name: 'assignment',
          component: () => import('@/views/AnswerView.vue'),
          props: true,
          meta: { wide: true, roles: ['expert'], keepOnExpiry: true, needsIntro: true },
        },
        {
          path: 'instructions',
          name: 'instructions',
          component: () => import('@/views/IntroView.vue'),
          meta: { roles: ['expert'], title: 'Instructions' },
        },
        {
          path: 'vignettes',
          name: 'vignettes',
          component: () => import('@/views/AdminVignettesView.vue'),
          meta: { roles: ['admin'] },
        },
        {
          path: 'vignettes/new',
          name: 'vignette-new',
          component: () => import('@/views/VignetteEditView.vue'),
          meta: { roles: ['admin'] },
        },
        {
          path: 'vignettes/:id',
          name: 'vignette',
          component: () => import('@/views/VignetteEditView.vue'),
          props: true,
          meta: { roles: ['admin'] },
        },
        {
          path: 'experts',
          name: 'experts',
          component: () => import('@/views/ExpertsView.vue'),
          meta: { roles: ['admin'] },
        },
        {
          path: 'account',
          name: 'account',
          component: () => import('@/views/AccountView.vue'),
        },
        {
          // Last: an address that matches nothing above.
          path: ':pathMatch(.*)*',
          name: 'not-found',
          component: () => import('@/views/NotFoundView.vue'),
        },
      ],
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  try {
    await auth.load()
  } catch {
    // The backend can't be reached. Carry on as logged out so that the login page still renders;
    // load() only caches a successful answer, so the next navigation asks again.
  }
  return guardRoute(to, auth.user)
})

export default router
