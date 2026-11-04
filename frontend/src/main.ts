import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import { setUnauthorizedHandler } from './api/client'
import router from './router'
import { useAuthStore } from './stores/auth'

const app = createApp(App)

app.use(createPinia())
app.use(router)

setUnauthorizedHandler(() => {
  useAuthStore().clear()
  const { meta, fullPath } = router.currentRoute.value
  if (meta.requiresAuth) router.push({ name: 'login', query: { next: fullPath } })
})

app.mount('#app')
