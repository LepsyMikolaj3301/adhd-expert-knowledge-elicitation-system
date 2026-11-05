import { createApp } from 'vue'
import { createPinia } from 'pinia'
import '@fontsource-variable/instrument-sans'
import '@fontsource-variable/newsreader'

import './assets/main.css'
import App from './App.vue'
import { setUnauthorizedHandler } from './api/client'
import router from './router'
import { SITE_NAME } from './site'
import { useAuthStore } from './stores/auth'

document.title = SITE_NAME

const app = createApp(App)

app.use(createPinia())
app.use(router)

setUnauthorizedHandler(() => {
  useAuthStore().clear()
  const { meta, fullPath } = router.currentRoute.value
  if (meta.requiresAuth) router.push({ name: 'login', query: { next: fullPath } })
})

app.mount('#app')
