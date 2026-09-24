import { createApp } from "vue"
import { createPinia } from "pinia"

import App from "./App.vue"
import { i18n, initializeLocale } from "./i18n"
import { router } from "./router"
import { initializeTheme } from "./theme"
import "./styles.css"

initializeTheme()
initializeLocale()

const app = createApp(App)
app.use(createPinia())
app.use(i18n)
app.use(router)
app.mount("#app")
