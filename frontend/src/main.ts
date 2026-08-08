import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import { createPinia } from 'pinia'
import { createApp } from 'vue'

import App from './App.vue'
import router from './router'

const app = createApp(App)

/** 全局错误处理：捕获未处理的组件渲染异常，避免白屏。 */
app.config.errorHandler = (error) => {
  console.error('应用未捕获异常:', error)
}

app.use(createPinia()).use(ElementPlus).use(router).mount('#app')
