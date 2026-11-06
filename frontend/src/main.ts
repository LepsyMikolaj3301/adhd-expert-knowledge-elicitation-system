import { createApp } from 'vue'
import { createPinia } from 'pinia'
import '@fontsource-variable/instrument-sans'
import '@fontsource-variable/newsreader'

import './assets/main.css'
import App from './App.vue'
import router from './router'
import { installSessionHandler } from './session'
import { SITE_NAME } from './site'

document.title = SITE_NAME

const app = createApp(App)

app.use(createPinia())
app.use(router)

installSessionHandler(router)

app.mount('#app')
