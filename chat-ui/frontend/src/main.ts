import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import '@/assets/base.css'
import '@/assets/animations.css'

const app = createApp(App)
app.use(createPinia())
app.mount('#app')
