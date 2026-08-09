import {
  ElButton,
  ElDescriptions,
  ElDescriptionsItem,
  ElDialog,
  ElForm,
  ElFormItem,
  ElInput,
  ElInputNumber,
  ElLoading,
  ElOption,
  ElSelect,
  ElTable,
  ElTableColumn,
  ElTabPane,
  ElTabs,
  ElTag,
  ElTooltip,
} from 'element-plus'
import 'element-plus/dist/index.css'
import { createPinia } from 'pinia'
import { createApp } from 'vue'

import App from './App.vue'
import router from './router'

/** Vue 应用实例。 */
const app = createApp(App)

/** 全局错误处理：捕获未处理的组件渲染异常，避免白屏。 */
app.config.errorHandler = (error) => {
  console.error('应用未捕获异常:', error)
}

app
  .use(createPinia())
  .use(ElButton)
  .use(ElDescriptions)
  .use(ElDescriptionsItem)
  .use(ElDialog)
  .use(ElForm)
  .use(ElFormItem)
  .use(ElInput)
  .use(ElInputNumber)
  .use(ElLoading)
  .use(ElOption)
  .use(ElSelect)
  .use(ElTable)
  .use(ElTableColumn)
  .use(ElTabPane)
  .use(ElTabs)
  .use(ElTag)
  .use(ElTooltip)
  .use(router)
  .mount('#app')
