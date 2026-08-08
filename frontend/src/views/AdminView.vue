<template>
  <section class="admin-view">
    <div class="admin-heading">
      <div>
        <h1>系统管理</h1>
        <p>管理生成模板、模型连接与操作审计</p>
      </div>
      <el-button
        :icon="Refresh"
        :loading="activeLoading"
        @click="refreshActiveTab"
      >
        刷新
      </el-button>
    </div>

    <el-tabs
      v-model="activeTab"
      class="admin-tabs"
      @tab-change="handleTabChange"
    >
      <el-tab-pane
        label="提示词模板"
        name="templates"
      >
        <div class="toolbar">
          <div class="toolbar-summary">
            共 {{ templates.length }} 个版本
          </div>
          <el-button
            type="primary"
            :icon="Plus"
            @click="templateFormVisible = !templateFormVisible"
          >
            创建版本
          </el-button>
        </div>

        <el-form
          v-if="templateFormVisible"
          class="edit-panel"
          label-position="top"
          @submit.prevent="createTemplate"
        >
          <div class="form-grid">
            <el-form-item
              label="模板名称"
              required
            >
              <el-input
                v-model="templateForm.name"
                placeholder="例如：沙发场景生成"
              />
            </el-form-item>
            <el-form-item
              label="输出 Schema"
              required
            >
              <el-input
                v-model="templateForm.outputSchema"
                placeholder="例如：{&quot;type&quot;:&quot;object&quot;}"
              />
            </el-form-item>
          </div>
          <el-form-item
            label="System Prompt"
            required
          >
            <el-input
              v-model="templateForm.systemPrompt"
              type="textarea"
              :rows="3"
            />
          </el-form-item>
          <el-form-item
            label="User Prompt"
            required
          >
            <el-input
              v-model="templateForm.userPrompt"
              type="textarea"
              :rows="3"
            />
          </el-form-item>
          <div class="panel-actions">
            <el-button @click="templateFormVisible = false">
              取消
            </el-button>
            <el-button
              type="primary"
              native-type="submit"
              :loading="creatingTemplate"
            >
              保存新版本
            </el-button>
          </div>
        </el-form>

        <el-table
          v-loading="templateLoading"
          :data="templates"
          stripe
          height="100%"
          empty-text="暂无提示词模板"
        >
          <el-table-column
            prop="name"
            label="名称"
            min-width="220"
            show-overflow-tooltip
          />
          <el-table-column
            prop="version"
            label="版本"
            width="90"
          >
            <template #default="scope">
              v{{ scope.row.version }}
            </template>
          </el-table-column>
          <el-table-column
            label="状态"
            width="100"
          >
            <template #default="scope">
              <el-tag
                :type="scope.row.is_active ? 'success' : 'info'"
                size="small"
              >
                {{ scope.row.is_active ? '已激活' : '未激活' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column
            label="创建时间"
            min-width="180"
          >
            <template #default="scope">
              {{ formatDate(scope.row.created_at) }}
            </template>
          </el-table-column>
          <el-table-column
            label="操作"
            width="110"
            fixed="right"
          >
            <template #default="scope">
              <el-button
                link
                type="primary"
                :disabled="scope.row.is_active"
                :loading="activatingTemplateId === scope.row.id"
                @click="activateTemplate(scope.row)"
              >
                激活
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane
        label="AI 能力"
        name="capability"
      >
        <div
          v-loading="capabilityLoading"
          class="capability-pane"
        >
          <el-descriptions
            :column="3"
            border
            size="small"
          >
            <el-descriptions-item label="Provider">
              {{ capability.provider || '未配置' }}
            </el-descriptions-item>
            <el-descriptions-item label="Base URL">
              {{ capability.base_url || '未配置' }}
            </el-descriptions-item>
            <el-descriptions-item label="模型">
              {{ capability.model || '未配置' }}
            </el-descriptions-item>
            <el-descriptions-item label="配置状态">
              <el-tag
                :type="capability.configured ? 'success' : 'warning'"
                size="small"
              >
                {{ capability.configured ? '已配置' : '未配置' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="能力状态">
              <el-tag
                :type="capabilityStatusType"
                size="small"
              >
                {{ capability.status || '未知' }}
              </el-tag>
            </el-descriptions-item>
          </el-descriptions>

          <el-form
            class="edit-panel capability-form"
            label-position="top"
            @submit.prevent="saveCapability"
          >
            <div class="form-grid capability-grid">
              <el-form-item label="Provider">
                <el-select v-model="capabilityForm.provider">
                  <el-option
                    label="OpenAI Compatible"
                    value="openai-compatible"
                  />
                </el-select>
              </el-form-item>
              <el-form-item
                label="Base URL"
                required
              >
                <el-input
                  v-model="capabilityForm.baseUrl"
                  placeholder="https://api.example.com/v1"
                />
              </el-form-item>
              <el-form-item
                label="模型"
                required
              >
                <el-input
                  v-model="capabilityForm.model"
                  placeholder="例如：gpt-4.1-mini"
                />
              </el-form-item>
              <el-form-item label="API Key">
                <el-input
                  v-model="capabilityForm.apiKey"
                  type="password"
                  show-password
                  autocomplete="new-password"
                  :placeholder="capability.api_key_configured ? '留空以保留当前密钥' : '请输入 API Key'"
                />
              </el-form-item>
              <el-form-item
                label="Chat Completions 路径"
                required
              >
                <el-input
                  v-model="capabilityForm.chatPath"
                  placeholder="/chat/completions"
                />
              </el-form-item>
              <el-form-item
                label="请求超时（秒）"
                required
              >
                <el-input-number
                  v-model="capabilityForm.timeoutSeconds"
                  :min="10"
                  :max="600"
                  :step="10"
                  controls-position="right"
                />
              </el-form-item>
            </div>
            <p class="config-note">
              配置将加密保存，API Key 不会回显。保存后对新运行的任务立即生效，无需重启服务。
            </p>
            <div class="panel-actions">
              <el-button
                :icon="Connection"
                :loading="testingCapability"
                @click="testCapability"
              >
                测试连接
              </el-button>
              <el-button
                type="primary"
                native-type="submit"
                :loading="savingCapability"
              >
                保存配置
              </el-button>
            </div>
          </el-form>
        </div>
      </el-tab-pane>

      <el-tab-pane
        label="审计日志"
        name="audit"
      >
        <el-table
          v-loading="auditLoading"
          :data="auditEvents"
          stripe
          height="100%"
          empty-text="暂无审计记录"
        >
          <el-table-column
            label="时间"
            min-width="180"
          >
            <template #default="scope">
              {{ formatDate(scope.row.created_at || scope.row.timestamp) }}
            </template>
          </el-table-column>
          <el-table-column
            prop="event_type"
            label="事件类型"
            min-width="160"
            show-overflow-tooltip
          />
          <el-table-column
            prop="row_id"
            label="行 ID"
            min-width="120"
            show-overflow-tooltip
          >
            <template #default="scope">
              {{ shortId(scope.row.row_id) }}
            </template>
          </el-table-column>
          <el-table-column
            prop="job_id"
            label="任务 ID"
            min-width="120"
            show-overflow-tooltip
          >
            <template #default="scope">
              {{ shortId(scope.row.job_id) }}
            </template>
          </el-table-column>
          <el-table-column
            label="详情"
            min-width="300"
            show-overflow-tooltip
          >
            <template #default="scope">
              {{ formatDetails(scope.row.details) }}
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Connection, Plus, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import type { TabsPaneContext } from 'element-plus'
import { api, extractApiError } from '@/services/api'

/** 提示词模板接口数据。 */
interface PromptTemplate {
  /** 模板唯一标识。 */
  id: string
  /** 模板名称。 */
  name: string
  /** 模板版本号。 */
  version: number
  /** 是否为当前激活版本。 */
  is_active: boolean
  /** 创建时间。 */
  created_at: string | null
}

/** AI 能力接口数据。 */
interface AICapability {
  /** 脱敏后的供应商标识。 */
  provider: string
  /** 脱敏后的服务地址。 */
  base_url: string
  /** 脱敏后的模型名称。 */
  model: string
  /** Chat Completions 请求路径。 */
  chat_path: string
  /** 请求超时秒数。 */
  timeout_seconds: number
  /** API Key 是否已配置。 */
  api_key_configured: boolean
  /** 是否已经完成配置。 */
  configured: boolean
  /** 配置来源。 */
  source: string
  /** 当前能力检测状态。 */
  status: string
}

/** 审计事件接口数据。 */
interface AuditEvent {
  /** 事件创建时间。 */
  created_at?: string | null
  /** 兼容接口返回的事件时间字段。 */
  timestamp?: string | null
  /** 事件类型。 */
  event_type: string
  /** 关联行标识。 */
  row_id?: string | null
  /** 关联任务标识。 */
  job_id?: string | null
  /** 事件详情。 */
  details?: unknown
}

/** 当前激活页签。 */
const activeTab = ref('templates')
/** 提示词模板列表。 */
const templates = ref<PromptTemplate[]>([])
/** 审计事件列表。 */
const auditEvents = ref<AuditEvent[]>([])
/** AI 能力信息。 */
const capability = reactive<AICapability>({
  provider: '',
  base_url: '',
  model: '',
  chat_path: '/chat/completions',
  timeout_seconds: 240,
  api_key_configured: false,
  configured: false,
  source: '',
  status: '',
})
/** AI 能力编辑表单。 */
const capabilityForm = reactive({
  provider: 'openai-compatible',
  baseUrl: '',
  apiKey: '',
  model: '',
  chatPath: '/chat/completions',
  timeoutSeconds: 240,
})
/** 模板列表加载状态。 */
const templateLoading = ref(false)
/** AI 能力加载状态。 */
const capabilityLoading = ref(false)
/** 审计列表加载状态。 */
const auditLoading = ref(false)
/** 创建模板状态。 */
const creatingTemplate = ref(false)
/** 正在激活的模板标识。 */
const activatingTemplateId = ref('')
/** 测试 AI 能力状态。 */
const testingCapability = ref(false)
/** 保存 AI 能力状态。 */
const savingCapability = ref(false)
/** 模板创建区域是否显示。 */
const templateFormVisible = ref(false)
/** 模板创建表单。 */
const templateForm = reactive({ name: '', systemPrompt: '', userPrompt: '', outputSchema: '' })
/** 当前页签对应的加载状态。 */
const activeLoading = computed(() => activeTab.value === 'templates' ? templateLoading.value : activeTab.value === 'capability' ? capabilityLoading.value : auditLoading.value)
/** AI 能力状态对应的标签类型。 */
const capabilityStatusType = computed<'success' | 'warning' | 'danger' | 'info'>(() => {
  const status = capability.status.toUpperCase()
  if (['READY', 'AVAILABLE', 'PASS', 'PASSED', 'ACTIVE'].includes(status)) return 'success'
  if (['FAILED', 'ERROR', 'UNAVAILABLE'].includes(status)) return 'danger'
  if (['STALE', 'PENDING', 'TESTING'].includes(status)) return 'warning'
  return 'info'
})

/**
 * 提取统一响应中的业务数据。
 * @param responseData Axios 返回的响应体。
 * @returns 解包后的业务数据。
 */
function unwrapData<T>(responseData: unknown): T {
  const body = responseData as { data?: T }
  return (body?.data ?? responseData) as T
}

/**
 * 提取列表响应，兼容 data 数组和 data.items 结构。
 * @param responseData Axios 返回的响应体。
 * @returns 业务列表。
 */
function unwrapList<T>(responseData: unknown): T[] {
  const data = unwrapData<T[] | { items?: T[] }>(responseData)
  return Array.isArray(data) ? data : (data?.items ?? [])
}

/**
 * 从请求异常中提取可展示消息。
 * @param reason 捕获的未知异常。
 * @param fallback 无后端消息时使用的文案。
 * @returns 最终错误提示。
 */
function errorMessage(reason: unknown, fallback: string): string {
  return extractApiError(reason, fallback)
}

/**
 * 格式化接口时间。
 * @param value ISO 时间字符串。
 * @returns 本地时间文本。
 */
function formatDate(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

/**
 * 缩短 UUID 显示，避免列被超长 ID 撑满。
 * @param value 原始 ID。
 * @returns 前 8 位 + 省略号，或 —。
 */
function shortId(value?: string | null): string {
  if (!value) return '—'
  return value.length > 12 ? `${value.slice(0, 8)}…` : value
}

/**
 * 格式化审计详情。
 * @param details 任意详情数据。
 * @returns 可读详情文本。
 */
function formatDetails(details: unknown): string {
  if (details === null || details === undefined || details === '') return '—'
  if (typeof details === 'string') return details
  /** 对象类型做格式化 JSON 输出，键值对更可读。 */
  return JSON.stringify(details, null, 2)
}

/** 加载提示词模板列表。 */
async function fetchTemplates(): Promise<void> {
  templateLoading.value = true
  try {
    const response = await api.get('/api/v1/admin/prompt-templates')
    templates.value = unwrapList<PromptTemplate>(response.data)
  } catch (reason: unknown) {
    ElMessage.error(errorMessage(reason, '提示词模板加载失败'))
  } finally {
    templateLoading.value = false
  }
}

/** 创建新的提示词模板版本。 */
async function createTemplate(): Promise<void> {
  if (!templateForm.name.trim() || !templateForm.systemPrompt.trim() || !templateForm.userPrompt.trim() || !templateForm.outputSchema.trim()) {
    ElMessage.warning('请完整填写模板名称、提示词和输出 Schema')
    return
  }
  let outputSchema: unknown
  try {
    outputSchema = JSON.parse(templateForm.outputSchema)
  } catch {
    ElMessage.warning('输出 Schema 必须是有效的 JSON')
    return
  }
  creatingTemplate.value = true
  try {
    await api.post('/api/v1/admin/prompt-templates', {
      name: templateForm.name.trim(),
      system_prompt: templateForm.systemPrompt,
      user_prompt_template: templateForm.userPrompt,
      output_schema_json: JSON.stringify(outputSchema),
    })
    Object.assign(templateForm, { name: '', systemPrompt: '', userPrompt: '', outputSchema: '' })
    templateFormVisible.value = false
    ElMessage.success('提示词模板版本已创建')
    await fetchTemplates()
  } catch (reason: unknown) {
    ElMessage.error(errorMessage(reason, '提示词模板创建失败'))
  } finally {
    creatingTemplate.value = false
  }
}

/**
 * 激活指定模板版本。
 * @param template 待激活的模板。
 */
async function activateTemplate(template: PromptTemplate): Promise<void> {
  activatingTemplateId.value = template.id
  try {
    await api.post(`/api/v1/admin/prompt-templates/${template.id}/activate`)
    ElMessage.success(`已激活 ${template.name} v${template.version}`)
    await fetchTemplates()
  } catch (reason: unknown) {
    ElMessage.error(errorMessage(reason, '模板激活失败'))
  } finally {
    activatingTemplateId.value = ''
  }
}

/** 加载 AI 能力配置。 */
async function fetchCapability(): Promise<void> {
  capabilityLoading.value = true
  try {
    const response = await api.get('/api/v1/admin/ai-capability')
    const data = unwrapData<Partial<AICapability>>(response.data) || {}
    Object.assign(capability, {
      provider: '',
      base_url: '',
      model: '',
      chat_path: '/chat/completions',
      timeout_seconds: 240,
      api_key_configured: false,
      configured: false,
      source: '',
      status: '',
      ...data,
    })
    Object.assign(capabilityForm, {
      provider: capability.provider || 'openai-compatible',
      baseUrl: capability.base_url || '',
      apiKey: '',
      model: capability.model || '',
      chatPath: capability.chat_path || '/chat/completions',
      timeoutSeconds: capability.timeout_seconds || 240,
    })
  } catch (reason: unknown) {
    ElMessage.error(errorMessage(reason, 'AI 能力加载失败'))
  } finally {
    capabilityLoading.value = false
  }
}

/** 保存 AI 能力配置。 */
async function saveCapability(): Promise<void> {
  if (!capabilityForm.baseUrl.trim() || !capabilityForm.model.trim() || !capabilityForm.chatPath.trim()) {
    ElMessage.warning('请完整填写 Base URL、模型和请求路径')
    return
  }
  if (!capability.api_key_configured && !capabilityForm.apiKey.trim()) {
    ElMessage.warning('首次配置时必须填写 API Key')
    return
  }
  savingCapability.value = true
  try {
    await api.put('/api/v1/admin/ai-capability', {
      provider: capabilityForm.provider,
      base_url: capabilityForm.baseUrl.trim(),
      api_key: capabilityForm.apiKey.trim() || null,
      model: capabilityForm.model.trim(),
      chat_path: capabilityForm.chatPath.trim(),
      timeout_seconds: capabilityForm.timeoutSeconds,
    })
    capabilityForm.apiKey = ''
    ElMessage.success('AI 配置已保存并立即生效')
    await fetchCapability()
  } catch (reason: unknown) {
    ElMessage.error(errorMessage(reason, 'AI 配置保存失败'))
  } finally {
    savingCapability.value = false
  }
}

/** 执行 AI 能力连接测试。 */
async function testCapability(): Promise<void> {
  testingCapability.value = true
  try {
    await api.post('/api/v1/admin/ai-capability/test')
    ElMessage.success('AI 能力测试已完成')
    await fetchCapability()
  } catch (reason: unknown) {
    ElMessage.error(errorMessage(reason, 'AI 能力测试失败'))
  } finally {
    testingCapability.value = false
  }
}

/** 加载审计事件列表。 */
async function fetchAuditEvents(): Promise<void> {
  auditLoading.value = true
  try {
    const response = await api.get('/api/v1/admin/audit-events')
    auditEvents.value = unwrapList<AuditEvent>(response.data)
  } catch (reason: unknown) {
    ElMessage.error(errorMessage(reason, '审计日志加载失败'))
  } finally {
    auditLoading.value = false
  }
}

/** 刷新当前激活页签。 */
async function refreshActiveTab(): Promise<void> {
  if (activeTab.value === 'templates') await fetchTemplates()
  else if (activeTab.value === 'capability') await fetchCapability()
  else await fetchAuditEvents()
}

/**
 * 页签切换时按需加载数据。
 * @param name 切换后的页签名称。
 * @param context Element Plus 页签上下文。
 */
function handleTabChange(name: string | number, context: TabsPaneContext): void {
  void context
  activeTab.value = String(name)
  void refreshActiveTab()
}

onMounted(fetchTemplates)
</script>

<style scoped>
.admin-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 18px 20px 20px;
  overflow: hidden;
  background: #f3f5f7;
}

.admin-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.admin-heading h1 {
  margin: 0;
  font-size: 20px;
  line-height: 28px;
}

.admin-heading p {
  margin: 2px 0 0;
  color: #6b7280;
  font-size: 13px;
}

.admin-tabs {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
  padding: 0 16px 16px;
  border: 1px solid #dfe3e8;
  border-radius: 6px;
  background: #fff;
}

.admin-tabs :deep(.el-tabs__content),
.admin-tabs :deep(.el-tab-pane) {
  flex: 1;
  min-height: 0;
}

.admin-tabs :deep(.el-tabs__content) {
  overflow: hidden;
}

.admin-tabs :deep(.el-tab-pane) {
  display: flex;
  flex-direction: column;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 44px;
  padding-bottom: 10px;
}

.toolbar-summary {
  color: #6b7280;
  font-size: 13px;
}

.edit-panel {
  flex: none;
  margin-bottom: 12px;
  padding: 14px;
  border: 1px solid #dfe3e8;
  border-left: 3px solid #2f7e5a;
  background: #f8faf9;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 16px;
}

.panel-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.capability-pane {
  min-height: 160px;
}

.capability-form {
  margin-top: 16px;
  margin-bottom: 0;
}

.config-note {
  margin: 0 0 12px;
  color: #6b7280;
  font-size: 13px;
  line-height: 1.6;
}

.admin-view :deep(.el-form-item) {
  margin-bottom: 12px;
}

.admin-view :deep(.el-form-item__label) {
  padding-bottom: 5px;
  font-size: 13px;
}

@media (max-width: 600px) {
  .admin-view {
    padding: 12px;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
