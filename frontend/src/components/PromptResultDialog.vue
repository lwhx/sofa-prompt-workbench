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
          <el-tag
            v-if="latest.id === selectedResultId"
            type="success"
          >
            正式版本
          </el-tag>
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
                :disabled="latest.is_stale || latest.id === selectedResultId"
                :loading="selecting"
                size="small"
                type="primary"
                @click="selectResult(latest)"
              >
                {{ latest.id === selectedResultId ? '已选为正式版' : '选为正式版' }}
              </el-button>
              <el-button
                v-if="latest.review_status === 'NEEDS_REVIEW'"
                size="small"
                type="warning"
                @click="openReview(latest)"
              >
                确认人工方向
              </el-button>
              <el-button
                v-if="results.length > 1 && latest.id !== selectedResultId"
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
              v-if="result.id !== selectedResultId"
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
    <el-dialog
      v-model="reviewOpen"
      title="人工方向审核确认"
      width="min(560px, 90vw)"
      append-to-body
    >
      <el-form label-width="88px">
        <el-form-item label="视角方向">
          <el-input v-model="reviewForm.view_type" />
        </el-form-item>
        <el-form-item label="近端">
          <el-input v-model="reviewForm.near_end" />
        </el-form-item>
        <el-form-item label="远端">
          <el-input v-model="reviewForm.far_end" />
        </el-form-item>
        <el-form-item label="审核备注">
          <el-input
            v-model="reviewForm.note"
            type="textarea"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="reviewOpen = false">
          取消
        </el-button>
        <el-button
          type="primary"
          :loading="confirming"
          @click="confirmReview"
        >
          确认方向并重新生成
        </el-button>
      </template>
    </el-dialog>
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
  rowRevision: number
  selectedResultId: string | null
}>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  changed: []
}>()
const selectedId = ref<string | null>(null)
const deleting = ref(false)
const selecting = ref(false)
const confirming = ref(false)
const reviewOpen = ref(false)
const reviewResultId = ref<string | null>(null)
const reviewForm = ref({ view_type: '', near_end: '', far_end: '', note: '' })
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
    emit('changed')
  } catch (err: unknown) {
    const msg = (err as { response?: { data?: { error?: { message?: string } } } })?.response?.data?.error?.message
    ElMessage.error(msg ?? '删除失败')
  } finally {
    deleting.value = false
  }
}

async function selectResult(result: PromptResultItem) {
  if (!props.rowId || result.id === props.selectedResultId) return
  selecting.value = true
  try {
    await api.post(`/api/v1/rows/${props.rowId}/results/${result.id}/select`, {
      expected_revision: props.rowRevision,
    })
    ElMessage.success('已设为正式版本')
    emit('changed')
  } catch (err: unknown) {
    const msg = (err as { response?: { data?: { error?: { message?: string } } } })?.response?.data?.error?.message
    ElMessage.error(msg ?? '正式选版失败')
  } finally {
    selecting.value = false
  }
}

function openReview(result: PromptResultItem) {
  reviewResultId.value = result.id
  reviewForm.value = {
    view_type: result.sofa_view?.view_type ?? '',
    near_end: result.sofa_view?.near_end ?? '',
    far_end: result.sofa_view?.far_end ?? '',
    note: '',
  }
  reviewOpen.value = true
}

async function confirmReview() {
  if (!props.rowId || !reviewResultId.value) return
  confirming.value = true
  try {
    await api.post(`/api/v1/rows/${props.rowId}/review/confirm`, {
      expected_revision: props.rowRevision,
      result_id: reviewResultId.value,
      view_override: {
        view_type: reviewForm.value.view_type,
        near_end: reviewForm.value.near_end,
        far_end: reviewForm.value.far_end,
      },
      note: reviewForm.value.note || null,
    })
    reviewOpen.value = false
    ElMessage.success('人工方向已确认，任务将按确认方向重新生成')
    emit('changed')
  } catch (err: unknown) {
    const msg = (err as { response?: { data?: { error?: { message?: string } } } })?.response?.data?.error?.message
    ElMessage.error(msg ?? '人工方向确认失败')
  } finally {
    confirming.value = false
  }
}
</script>

<style scoped>
.result-dialog { min-height: 180px; }
.empty-result { padding: 64px 48px; border: 1px dashed #d8d0c3; border-radius: 14px; background: #f8f5ee; text-align: center; color: #879089; }
.result-head { display: flex; align-items: center; gap: 12px; margin-bottom: 20px; padding: 12px 15px; border: 1px solid #e3ddd2; border-radius: 11px; color: #68756e; background: #f8f5ee; }
.result-head strong { color: var(--sofa-green); font-family: "Noto Serif SC", "Songti SC", serif; font-size: 17px; }
.result-head small { margin-left: auto; color: #929a95; }
section { margin: 20px 0; }
.section-title { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.section-actions { display: flex; gap: 8px; }
h3 { margin: 0 0 11px; color: #33473e; font-family: "Noto Serif SC", "Songti SC", serif; font-size: 15px; }
textarea { width: 100%; min-height: 280px; box-sizing: border-box; resize: vertical; border: 1px solid #ddd6ca; border-radius: 12px; padding: 16px; outline: none; background: #fbf9f4; color: #3f4d46; font: 13px/1.8 "Noto Sans SC", sans-serif; transition: border-color .2s ease; }
textarea:focus { border-color: #81988c; }
textarea.negative { min-height: 150px; }
details { margin-top: 20px; color: #475569; }
.history-row { display: flex; align-items: center; gap: 8px; margin-top: 6px; }
.history-item { flex: 1; padding: 9px 11px; border: 1px solid #e2dcd0; border-radius: 8px; background: #fffdfa; color: #59665f; text-align: left; cursor: pointer; }
.history-item.active { border-color: #769180; background: #e8f0eb; color: #315f4c; }

@media (max-width: 700px) {
  .section-title { align-items: flex-start; flex-direction: column; }
  .section-actions { flex-wrap: wrap; }
  .result-head { align-items: flex-start; flex-wrap: wrap; }
  .result-head small { width: 100%; margin-left: 0; }
}
</style>
