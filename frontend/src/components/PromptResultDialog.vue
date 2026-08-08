<template>
  <el-dialog
    :model-value="modelValue"
    title="反推提示词结果"
    width="min(1000px, 94vw)"
    destroy-on-close
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div
      v-loading="loading"
      class="result-dialog"
    >
      <div
        v-if="!loading && !latest"
        class="empty-result"
      >
        暂无反推结果，请先运行任务。
      </div>
      <template v-if="latest">
        <div class="result-head">
          <strong>版本 {{ latest.version }}</strong>
          <span>{{ latest.review_status === 'PASSED' ? '已完成' : '待审核' }}</span>
          <small v-if="latest.created_at">{{ latest.created_at }}</small>
        </div>
        <section>
          <div class="section-title">
            <h3>即梦完整提示词</h3>
            <div class="section-actions">
              <el-button
                size="small"
                @click="copy(latest.positive_prompt)"
              >
                复制正向提示词
              </el-button>
              <el-button
                v-if="results.length > 1"
                size="small"
                type="danger"
                plain
                :loading="deleting"
                @click="removeResult(latest)"
              >
                删除此版本
              </el-button>
            </div>
          </div>
          <textarea
            readonly
            :value="latest.positive_prompt"
            aria-label="即梦完整提示词"
          />
        </section>
        <section>
          <div class="section-title">
            <h3>反向提示词</h3>
            <el-button
              size="small"
              @click="copy(latest.negative_prompt)"
            >
              复制反向提示词
            </el-button>
          </div>
          <textarea
            class="negative"
            readonly
            :value="latest.negative_prompt"
            aria-label="反向提示词"
          />
        </section>
        <details v-if="results.length > 1">
          <summary>历史版本（{{ results.length }}）</summary>
          <div
            v-for="result in results"
            :key="result.id"
            class="history-row"
          >
            <button
              type="button"
              class="history-item"
              :class="{ active: result.id === selectedId }"
              @click="selectedId = result.id"
            >
              版本 {{ result.version }} · {{ result.review_status }}
            </button>
            <el-button
              v-if="result.id !== selectedId || results.length > 1"
              size="small"
              type="danger"
              text
              @click="removeResult(result)"
            >
              删除
            </el-button>
          </div>
        </details>
      </template>
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '@/services/api'
import type { PromptResultItem } from '@/stores/rows'

const props = defineProps<{
  modelValue: boolean
  results: PromptResultItem[]
  loading: boolean
  rowId: string | null
}>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  deleted: []
}>()
const selectedId = ref<string | null>(null)
const deleting = ref(false)
const latest = computed(() => props.results.find(item => item.id === selectedId.value) ?? props.results[0])
watch(() => props.results, results => { selectedId.value = results[0]?.id ?? null }, { immediate: true })

async function copy(text: string) {
  await globalThis.navigator.clipboard.writeText(text)
  ElMessage.success('已复制')
}

async function removeResult(result: PromptResultItem) {
  try {
    await ElMessageBox.confirm(`确定删除版本 ${result.version} 的反推结果吗？`, '删除版本', { type: 'warning' })
  } catch { return }
  deleting.value = true
  try {
    await api.delete(`/api/v1/rows/${props.rowId}/results/${result.id}`)
    ElMessage.success('已删除')
    emit('deleted')
  } catch (err: unknown) {
    const msg = (err as { response?: { data?: { error?: { message?: string } } } })?.response?.data?.error?.message
    ElMessage.error(msg ?? '删除失败')
  } finally {
    deleting.value = false
  }
}
</script>

<style scoped>
.result-dialog { min-height: 180px; }
.empty-result { padding: 48px; text-align: center; color: #94a3b8; }
.result-head { display: flex; align-items: center; gap: 12px; margin-bottom: 18px; color: #475569; }
.result-head strong { color: #0f172a; font-size: 16px; }
.result-head small { margin-left: auto; color: #94a3b8; }
section { margin: 18px 0; }
.section-title { display: flex; align-items: center; justify-content: space-between; }
.section-actions { display: flex; gap: 8px; }
h3 { margin: 0 0 10px; color: #1e293b; font-size: 14px; }
textarea { width: 100%; min-height: 280px; box-sizing: border-box; resize: vertical; border: 1px solid #dbe2ea; border-radius: 8px; padding: 14px; background: #f8fafc; color: #334155; font: 13px/1.75 system-ui, sans-serif; }
textarea.negative { min-height: 150px; }
details { margin-top: 20px; color: #475569; }
.history-row { display: flex; align-items: center; gap: 8px; margin-top: 6px; }
.history-item { flex: 1; padding: 8px 10px; border: 1px solid #e2e8f0; border-radius: 5px; background: #fff; text-align: left; cursor: pointer; }
.history-item.active { border-color: #409eff; background: #ecf5ff; }
</style>
