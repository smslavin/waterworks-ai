import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import '@/assets/base.css'
import '@/assets/animations.css'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
;(window as any).__pinia = pinia
app.mount('#app')
