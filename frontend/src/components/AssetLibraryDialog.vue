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
/** 最近一次资产列表请求的递增序号。 */
let assetsRequestId = 0

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
    const requestId = ++assetsRequestId
    selectedId.value = null
    searchText.value = ''
    assets.value = []
    loading.value = true
    try {
      const latestAssets = await store.fetchAssets(props.kind)
      if (requestId === assetsRequestId && props.visible) assets.value = latestAssets
    } finally {
      if (requestId === assetsRequestId) loading.value = false
    }
    /** 打开后自动聚焦搜索框，便于键盘操作。 */
    await nextTick()
    document.querySelector<HTMLInputElement>('.search-input')?.focus()
  } else {
    assetsRequestId++
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
  padding: 20px;
  background: rgb(28 43 36 / 58%);
  backdrop-filter: blur(4px);
  z-index: 2000;
  display: flex;
  align-items: center;
  justify-content: center;
}

.asset-library-dialog {
  overflow: hidden;
  border: 1px solid rgb(255 255 255 / 42%);
  background: #fffdf8;
  border-radius: 20px;
  width: 760px;
  max-width: 90vw;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 30px 80px rgb(20 32 27 / 30%);
}

.dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 24px 16px;
  border-bottom: 1px solid #e3ddd2;
}

.dialog-title {
  color: #26352f;
  font-family: "Noto Serif SC", "Songti SC", serif;
  font-size: 18px;
  font-weight: 700;
}

.close-btn {
  border: none;
  background: none;
  font-size: 22px;
  cursor: pointer;
  color: #879089;
  line-height: 1;
}

.close-btn:hover { color: #315f4c; }

.search-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 24px;
  border-bottom: 1px solid #eee8dd;
  background: #f8f5ee;
}

.search-input {
  flex: 1;
  min-height: 40px;
  padding: 8px 12px;
  border: 1px solid #d8d0c3;
  border-radius: 9px;
  font-size: 13px;
  outline: none;
}

.search-input:focus { border-color: #527764; box-shadow: 0 0 0 3px rgb(49 95 76 / 9%); }

.asset-count {
  color: #879089;
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
  border: 2px solid #e5dfd4;
  border-radius: 11px;
  overflow: hidden;
  cursor: pointer;
  transition: border-color .2s, transform .2s, box-shadow .2s;
  background: #f8f5ee;
}

.asset-card:hover,
.asset-card:focus-visible {
  border-color: #9caf9f;
  transform: translateY(-2px);
  box-shadow: 0 9px 20px rgb(62 50 38 / 10%);
  outline: none;
}

.asset-card.selected {
  border-color: #315f4c;
  box-shadow: 0 0 0 3px rgb(49 95 76 / 14%);
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
  color: #59665f;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 15px 24px;
  border-top: 1px solid #e3ddd2;
}

.btn-cancel, .btn-confirm {
  padding: 7px 20px;
  min-height: 38px;
  border-radius: 9px;
  font-size: 13px;
  cursor: pointer;
  border: 1px solid #d8d0c3;
}

.btn-cancel {
  background: #fff;
  color: #59665f;
}

.btn-cancel:hover { background: #f3eee4; }

.btn-confirm {
  background: #315f4c;
  color: #fff;
  border-color: #315f4c;
}

.btn-confirm:hover:not(:disabled) { background: #24483a; }

.btn-confirm:disabled {
  background: #9eb1a7;
  border-color: #9eb1a7;
  cursor: not-allowed;
}
</style>
