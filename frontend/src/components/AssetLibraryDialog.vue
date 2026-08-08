<template>
  <div
    v-if="visible"
    class="asset-library-overlay"
    role="dialog"
    aria-modal="true"
    :aria-label="`${kindLabel}图片库`"
    @click.self="close"
    @keydown.esc="close"
  >
    <div class="asset-library-dialog">
      <div class="dialog-header">
        <span class="dialog-title">{{ kindLabel }}图片库</span>
        <button
          class="close-btn"
          aria-label="关闭"
          @click="close"
        >
          &times;
        </button>
      </div>
      <div class="search-bar">
        <input
          v-model="searchText"
          class="search-input"
          placeholder="搜索文件名..."
          aria-label="搜索图片"
        >
        <span class="asset-count">{{ filtered.length }} 张图片</span>
      </div>
      <div class="asset-grid-scroll">
        <div
          v-if="loading"
          class="loading-hint"
        >
          加载中...
        </div>
        <div
          v-else-if="filtered.length === 0"
          class="empty-hint"
        >
          暂无{{ kindLabel }}图片，请先上传
        </div>
        <div
          v-else
          class="asset-grid"
        >
          <div
            v-for="asset in filtered"
            :key="asset.id"
            class="asset-card"
            :class="{ selected: selectedId === asset.id }"
            tabindex="0"
            role="button"
            :aria-label="`选择图片 ${asset.original_filename}`"
            draggable="true"
            @click="select(asset)"
            @keydown.enter="select(asset)"
            @dragstart="onDragStart($event, asset)"
          >
            <img
              :src="asset.thumbnail_url"
              :alt="asset.original_filename"
              class="asset-thumb"
              loading="lazy"
            >
            <div
              class="asset-name"
              :title="asset.original_filename"
            >
              {{ asset.original_filename }}
            </div>
          </div>
        </div>
      </div>
      <div class="dialog-footer">
        <button
          class="btn-cancel"
          @click="close"
        >
          取消
        </button>
        <button
          class="btn-confirm"
          :disabled="!selectedId"
          @click="confirm"
        >
          确认选择
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { useRowsStore, type AssetItem } from '@/stores/rows'

const props = defineProps<{
  visible: boolean
  kind: 'scene_reference' | 'sofa_product'
}>()

const emit = defineEmits<{
  close: []
  select: [assetId: string]
}>()

const store = useRowsStore()
const assets = ref<AssetItem[]>([])
const loading = ref(false)
const searchText = ref('')
const selectedId = ref<string | null>(null)

const kindLabel = computed(() =>
  props.kind === 'scene_reference' ? '场景参考' : '沙发产品',
)

const filtered = computed(() => {
  if (!searchText.value) return assets.value
  const q = searchText.value.toLowerCase()
  return assets.value.filter(a =>
    a.original_filename?.toLowerCase().includes(q),
  )
})

watch(() => props.visible, async (v) => {
  if (v) {
    selectedId.value = null
    searchText.value = ''
    loading.value = true
    try {
      assets.value = await store.fetchAssets(props.kind)
    } finally {
      loading.value = false
    }
    /** 打开后自动聚焦搜索框，便于键盘操作。 */
    await nextTick()
    document.querySelector<HTMLInputElement>('.search-input')?.focus()
  }
})

function select(asset: AssetItem) {
  selectedId.value = asset.id
}

function confirm() {
  if (selectedId.value) {
    emit('select', selectedId.value)
    emit('close')
  }
}

function close() {
  emit('close')
}

function onDragStart(event: globalThis.DragEvent, asset: AssetItem) {
  event.dataTransfer?.setData('application/x-asset-id', asset.id)
  event.dataTransfer?.setData('application/x-asset-kind', props.kind)
}
</script>

<style scoped>
.asset-library-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  z-index: 2000;
  display: flex;
  align-items: center;
  justify-content: center;
}

.asset-library-dialog {
  background: #fff;
  border-radius: 12px;
  width: 760px;
  max-width: 90vw;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.18);
}

.dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid #eee;
}

.dialog-title {
  font-size: 16px;
  font-weight: 600;
}

.close-btn {
  border: none;
  background: none;
  font-size: 22px;
  cursor: pointer;
  color: #999;
  line-height: 1;
}

.close-btn:hover { color: #333; }

.search-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 20px;
  border-bottom: 1px solid #f0f0f0;
}

.search-input {
  flex: 1;
  padding: 6px 12px;
  border: 1px solid #ddd;
  border-radius: 6px;
  font-size: 13px;
  outline: none;
}

.search-input:focus { border-color: #409eff; }

.asset-count {
  color: #999;
  font-size: 12px;
  white-space: nowrap;
}

.asset-grid-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
}

.loading-hint, .empty-hint {
  text-align: center;
  color: #999;
  padding: 48px 0;
  font-size: 14px;
}

.asset-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 12px;
}

.asset-card {
  border: 2px solid #eee;
  border-radius: 8px;
  overflow: hidden;
  cursor: pointer;
  transition: border-color 0.15s, transform 0.1s;
  background: #fafafa;
}

.asset-card:hover,
.asset-card:focus-visible {
  border-color: #c0d8f0;
  outline: none;
}

.asset-card.selected {
  border-color: #409eff;
  box-shadow: 0 0 0 2px rgba(64, 158, 255, 0.2);
}

.asset-thumb {
  width: 100%;
  height: 100px;
  object-fit: cover;
  display: block;
}

.asset-name {
  padding: 6px 8px;
  font-size: 11px;
  color: #666;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 14px 20px;
  border-top: 1px solid #eee;
}

.btn-cancel, .btn-confirm {
  padding: 7px 20px;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
  border: 1px solid #ddd;
}

.btn-cancel {
  background: #fff;
  color: #666;
}

.btn-cancel:hover { background: #f5f5f5; }

.btn-confirm {
  background: #409eff;
  color: #fff;
  border-color: #409eff;
}

.btn-confirm:hover:not(:disabled) { background: #66b1ff; }

.btn-confirm:disabled {
  background: #a0cfff;
  border-color: #a0cfff;
  cursor: not-allowed;
}
</style>
