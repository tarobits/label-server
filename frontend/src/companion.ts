import { createApp } from 'vue'
import CompanionApp from './CompanionApp.vue'
import './style.css'
import './motion.css'
import './shared/focusVisibility'
import { i18n } from './shared/i18n'
createApp(CompanionApp).use(i18n).mount('#app')
