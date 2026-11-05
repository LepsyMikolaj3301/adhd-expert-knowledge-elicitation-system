<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'

import { navFor } from '@/navigation'
import { SITE_NAME } from '@/site'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const items = computed(() => (auth.user ? navFor(auth.user.role) : []))

/** A section stays current on the pages under it, such as one vignette under Vignettes. */
function isCurrent(to: string, isActive: boolean, isExactActive: boolean): boolean {
  if (to === '/') return isExactActive
  return isActive || route.path.startsWith(`${to}/`)
}

/**
 * On a wide screen the current item takes the page colour and runs into the content, like a
 * folder tab. On a narrow screen the panel is a top bar and the current item is underlined.
 */
function tabClass(active: boolean): string {
  const base =
    'flex items-center gap-2 border-b-2 px-4 py-2.5 text-[0.95rem] whitespace-nowrap no-underline hover:no-underline focus-visible:-outline-offset-2 md:ml-3 md:rounded-l-lg md:border-b-0'
  return active
    ? `${base} border-white text-white md:bg-page md:text-ink focus-visible:outline-action`
    : `${base} border-transparent text-on-ink hover:bg-ink-raised hover:text-white focus-visible:outline-white`
}
</script>

<template>
  <div class="min-h-screen md:grid md:grid-cols-[15rem_1fr]">
    <aside
      class="flex flex-wrap items-center bg-ink text-on-ink md:sticky md:top-0 md:h-screen md:flex-col md:flex-nowrap md:items-stretch"
    >
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
          :class="[
            tabClass(isActive),
            'mr-2 md:order-last md:mr-0 md:mb-4 md:flex-col md:items-start md:gap-0',
          ]"
          @click="navigate"
        >
          <span class="font-medium">{{ auth.user.display_name }}</span>
          <span class="text-xs capitalize opacity-80">{{ auth.user.role }}</span>
        </a>
      </RouterLink>

      <nav
        aria-label="Main"
        class="order-last flex w-full overflow-x-auto md:order-none md:block md:flex-1 md:overflow-visible"
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
          </a>
        </RouterLink>
      </nav>
    </aside>

    <main
      :class="route.meta.wide ? 'min-w-0 px-4 py-6 md:px-8' : 'min-w-0 px-4 py-8 md:px-12 md:py-12'"
    >
      <div :class="route.meta.wide ? '' : 'max-w-4xl'">
        <RouterView />
      </div>
    </main>
  </div>
</template>
