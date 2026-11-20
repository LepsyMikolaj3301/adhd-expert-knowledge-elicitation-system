<script setup lang="ts">
import { computed, onMounted, onUnmounted, watch } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'

import SignInAgainDialog from '@/components/SignInAgainDialog.vue'
import { SYSTEM } from '@/copy'
import { navFor } from '@/navigation'
import { SITE_NAME } from '@/site'
import { useAuthStore } from '@/stores/auth'
import { useHomeStore } from '@/stores/home'

const auth = useAuthStore()
const route = useRoute()
const home = useHomeStore()
const REFRESH_MS = 60_000
let timer: ReturnType<typeof setInterval> | undefined

/** The dot on Home and the count on Reviews, from the same answer as the home page. */
function badge(to: string): string {
  const d = home.data
  if (to === '/') return d?.unread_activity ? '●' : ''
  const waiting = d?.reviews_waiting_total ?? 0
  return to === '/reviews' && waiting ? String(waiting) : ''
}
const badgeLabel = (to: string) =>
  to === '/' ? 'new updates' : `${badge(to)} reviews waiting for you`

const refresh = () => document.visibilityState === 'visible' && auth.user && void home.load()
onMounted(() => {
  refresh()
  timer = setInterval(refresh, REFRESH_MS)
})
onUnmounted(() => clearInterval(timer))
// A different person signing in must not see the last one's counts.
watch(
  () => auth.user?.id,
  () => {
    home.data = null
    refresh()
  },
)
/** Only the admin's home answer carries `system`. */
const problems = computed(() => (auth.role === 'admin' ? SYSTEM.problems(home.data?.system) : []))
const items = computed(() => (auth.user ? navFor(auth.user.role) : []))

/** A section stays current on the pages under it, such as one vignette under Vignettes. */
function isCurrent(to: string, isActive: boolean, isExactActive: boolean): boolean {
  if (to === '/') return isExactActive
  return isActive || route.path.startsWith(`${to}/`)
}

/**
 * Every item is light text on the dark panel. The translucent pill behind the current one is a
 * single element that the browser slides from item to item: the current item is the CSS anchor
 * the pill is positioned on (see the style below), so nothing is measured here. The text never
 * changes colour on the way, and a browser without anchor positioning gets the plain background.
 */
function tabClass(active: boolean): string {
  const base =
    'relative z-10 mx-1 flex items-center gap-2 rounded-full px-4 py-2.5 text-[0.95rem] whitespace-nowrap no-underline hover:no-underline focus-visible:outline-white md:mx-3'
  return active
    ? `${base} text-white [anchor-name:--nav-current] not-supports-[anchor-name:--a]:bg-white/15`
    : `${base} text-on-ink hover:bg-white/10 hover:text-white`
}
</script>

<template>
  <div class="min-h-screen md:grid md:grid-cols-[15rem_1fr]">
    <aside
      class="relative flex flex-wrap items-center bg-ink text-on-ink md:sticky md:top-0 md:h-screen md:flex-col md:flex-nowrap md:items-stretch"
    >
      <span class="nav-pill" aria-hidden="true" data-testid="nav-highlight" />
      <RouterLink
        to="/"
        data-testid="site-name"
        class="flex-1 px-6 py-5 font-serif text-xl text-white no-underline hover:text-white hover:no-underline md:flex-none md:py-7"
      >
        {{ SITE_NAME }}
      </RouterLink>

      <RouterLink v-if="auth.user" v-slot="{ href, navigate, isActive }" to="/account" custom>
        <a
          :href="href"
          data-testid="account-link"
          :aria-current="isActive ? 'page' : undefined"
          :class="[tabClass(isActive), 'md:order-last md:mb-4']"
          @click="navigate"
        >
          <svg
            viewBox="0 0 24 24"
            width="20"
            height="20"
            fill="none"
            stroke="currentColor"
            stroke-width="1.75"
            stroke-linecap="round"
            class="shrink-0"
            aria-hidden="true"
          >
            <circle cx="12" cy="8" r="4" />
            <path d="M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7" />
          </svg>
          <span class="flex items-center gap-2 md:flex-col md:items-start md:gap-0">
            <span class="font-medium">{{ auth.user.display_name }}</span>
            <span class="text-xs capitalize opacity-80">{{ auth.user.role }}</span>
          </span>
        </a>
      </RouterLink>

      <nav
        aria-label="Main"
        class="order-last flex w-full overflow-x-auto pb-2 md:order-none md:block md:flex-1 md:overflow-visible md:pb-0"
      >
        <RouterLink
          v-for="item in items"
          :key="item.to + item.label"
          v-slot="{ href, navigate, isActive, isExactActive }"
          :to="item.to"
          custom
        >
          <a
            :href="href"
            :aria-current="isCurrent(item.to, isActive, isExactActive) ? 'page' : undefined"
            :class="tabClass(isCurrent(item.to, isActive, isExactActive))"
            @click="navigate"
          >
            {{ item.label }}
            <span v-if="badge(item.to)" class="text-xs" :aria-label="badgeLabel(item.to)">{{
              badge(item.to)
            }}</span>
          </a>
        </RouterLink>
      </nav>
    </aside>

    <main
      :class="route.meta.wide ? 'min-w-0 px-4 py-6 md:px-8' : 'min-w-0 px-4 py-8 md:px-12 md:py-12'"
    >
      <div :class="route.meta.wide ? '' : 'max-w-4xl'">
        <div v-if="problems.length" class="alert mb-6" role="status" data-testid="system-banner">
          {{ problems[0] }}
          <template v-if="problems.length > 1"> And {{ problems.length - 1 }} more.</template>
          <RouterLink to="/#system" class="ml-1 font-medium text-danger underline">{{
            SYSTEM.seeStatus
          }}</RouterLink>
        </div>
        <RouterView />
      </div>
    </main>

    <SignInAgainDialog v-if="auth.sessionEnded" />
  </div>
</template>

<style scoped>
/* Sits on whichever item holds the anchor name, and follows it when the name moves. */
.nav-pill {
  position: absolute;
  z-index: 0;
  pointer-events: none;
  border-radius: 9999px;
  background: rgb(255 255 255 / 0.15);
  position-anchor: --nav-current;
  top: anchor(top);
  left: anchor(left);
  width: anchor-size(width);
  height: anchor-size(height);
  transition:
    top 0.3s cubic-bezier(0.32, 0.72, 0, 1),
    left 0.3s cubic-bezier(0.32, 0.72, 0, 1),
    width 0.3s cubic-bezier(0.32, 0.72, 0, 1),
    height 0.3s cubic-bezier(0.32, 0.72, 0, 1);
}

@media (prefers-reduced-motion: reduce) {
  .nav-pill {
    transition: none;
  }
}

@supports not (anchor-name: --a) {
  .nav-pill {
    display: none;
  }
}
</style>
