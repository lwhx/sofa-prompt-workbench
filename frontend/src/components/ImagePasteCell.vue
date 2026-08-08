<template>
  <div
    class="image-cell"
    :class="{ 'has-asset': !!asset, 'drag-over': isDragOver }"
    tabindex="0"
    :aria-label="`${label}，可拖拽、粘贴或点击上传`"
    draggable="true"
    @dragstart="onDragStart"
    @dragover.prevent="onDragOver"
    @dragleave.prevent="isDragOver = false"
    @drop.prevent="onDrop"
    @click="onCellClick"
    @keydown.enter.prevent="onCellClick"
  >
    <input
      ref="fileInput"
      type="file"
      accept="image/jpeg,image/png,image/webp"
      @click.stop
      @change="onFileChange"
    >
    <template v-if="loading">
      <div class="cell-loading">
        <span class="loading-spinner" />
        <small>处理中…</small>
      </div>
    </template>
    <template v-else-if="asset">
      <img
        :src="asset.thumbnail_url"
        :alt="asset.filename"
      >
      <div class="asset-overlay">
        <button
          type="button"
          class="overlay-btn"
          title="查看大图"
          @click.stop="emit('preview', asset.public_url)"
        >
          查看
        </button>
        <button
          type="button"
          class="overlay-btn"
          title="替换图片"
          @click.stop="openPicker"
        >
          替换
        </button>
        <button
          type="button"
          class="overlay-btn"
          title="从图片库选择已有图片"
          @click.stop="emit('pickFromLibrary')"
        >
          图库
        </button>
        <button
          type="button"
          class="overlay-btn danger"
          title="移除图片（不删除原图库）"
          @click.stop="emit('remove')"
        >
          移除
        </button>
      </div>
      <div
        class="asset-caption"
        :title="asset.filename"
      >
        <span>{{ asset.filename }}</span>
        <small v-if="asset.width && asset.height">{{ asset.width }}×{{ asset.height }}</small>
      </div>
    </template>
    <template v-else>
      <div class="empty-icon">
        ＋
      </div>
      <strong>粘贴 / 拖入图片</strong>
      <button
        type="button"
        class="library-link"
        @click.stop="emit('pickFromLibrary')"
      >
        从图片库选择
      </button>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { AssetSummary } from '@/stores/rows'

const props = defineProps<{
  asset?: AssetSummary | null
  label: string
  /** 传递资产 kind 用于拖拽时校验类型 */
  assetKind?: 'scene_reference' | 'sofa_product'
  /** 是否正在执行上传或绑定操作 */
  loading?: boolean
}>()
const emit = defineEmits<{
  upload: [file: globalThis.File]
  preview: [url: string]
  remove: []
  pickFromLibrary: []
  /** 从其他行拖入已有资产 */
  dropAsset: [assetId: string, kind: string]
}>()

const fileInput = ref<HTMLInputElement>()
const isDragOver = ref(false)

/** 打开系统文件选择对话框 */
function openPicker() { fileInput.value?.click() }

/**
 * 单元格点击处理。
 * 仅在无图片（空状态）时打开文件选择框。
 */
function onCellClick() {
  if (!props.asset) openPicker()
}

/** 校验文件类型并触发上传事件 */
function accept(file?: globalThis.File) {
  if (file?.type.startsWith('image/')) emit('upload', file)
}

/** 文件选择回调 */
function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  accept(input.files?.[0])
  input.value = ''
}

/** 拖出：当前单元格有图时，设置拖拽数据 */
function onDragStart(event: globalThis.DragEvent) {
  if (props.asset && props.assetKind) {
    event.dataTransfer?.setData('application/x-asset-id', props.asset.id)
    event.dataTransfer?.setData('application/x-asset-kind', props.assetKind)
  }
}

/** 拖入悬停 */
function onDragOver(event: globalThis.DragEvent) {
  const types = event.dataTransfer?.types
  if (!types) return
  const hasAssetData = Array.from(types).includes('application/x-asset-id')
  const hasFile = Array.from(types).includes('Files')
  if (hasAssetData || hasFile) {
    isDragOver.value = true
  }
}

/**
 * 拖拽放置回调。
 * 支持两种放入方式：
 * 1. 从其他行拖入已有资产（application/x-asset-id）
 * 2. 从系统拖入文件（Files）
 */
function onDrop(event: globalThis.DragEvent) {
  isDragOver.value = false
  const dt = event.dataTransfer
  // 兼容 jsdom：getData 可能不存在
  const getData = (key: string): string => {
    try { return dt?.getData?.(key) ?? '' } catch { return '' }
  }
  const assetId = getData('application/x-asset-id')
  const assetKind = getData('application/x-asset-kind')
  if (assetId) {
    emit('dropAsset', assetId, assetKind || '')
    return
  }
  accept(Array.from(dt?.files ?? []).find(file => file.type.startsWith('image/')))
}
</script>

<style scoped>
.image-cell {
  position: relative; width: 120px; height: 82px; overflow: hidden; cursor: pointer;
  border: 1px dashed #c8d0da; border-radius: 5px; background: #f7f9fb;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  color: #697587; transition: .15s ease;
}
.image-cell:hover, .image-cell:focus-visible { border-color: #2878c7; box-shadow: 0 0 0 2px #2878c71a; outline: none; }
.image-cell.drag-over { border-color: #2878c7; border-style: solid; background: #e8f2fe; }
.image-cell.has-asset { cursor: default; }
.image-cell input { display: none; }
.image-cell img { width: 100%; height: 58px; object-fit: cover; align-self: flex-start; }
.empty-icon { font-size: 20px; line-height: 1; color: #2878c7; }
.image-cell strong { margin-top: 4px; color: #344154; font-size: 12px; }
.image-cell > span { margin-top: 2px; font-size: 10px; }
.library-link {
  margin-top: 4px; border: none; background: none; color: #2878c7;
  font-size: 11px; cursor: pointer; text-decoration: underline; padding: 0;
}
.library-link:hover { color: #1a5fa8; }
.asset-caption { width: 100%; height: 24px; padding: 2px 5px; box-sizing: border-box; display: flex; align-items: center; justify-content: space-between; gap: 4px; background: #fff; }
.asset-caption span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 10px; color: #334155; }
.asset-caption small { display: none; }
.asset-overlay { position: absolute; inset: 0 0 24px; display: flex; align-items: center; justify-content: center; gap: 3px; background: #0f172a99; opacity: 0; transition: .15s; flex-wrap: wrap; padding: 4px; }
.image-cell:hover .asset-overlay, .image-cell:focus-within .asset-overlay { opacity: 1; }
.overlay-btn { border: 0; border-radius: 4px; padding: 3px 6px; color: #fff; background: #ffffff2e; cursor: pointer; font-size: 10px; }
.overlay-btn:hover { background: #ffffff48; }
.overlay-btn.danger { color: #fecaca; }
/* 操作中加载态 */
.cell-loading { display: flex; flex-direction: column; align-items: center; gap: 6px; color: #2878c7; }
.cell-loading small { font-size: 11px; }
.loading-spinner { width: 20px; height: 20px; border: 2px solid #c8d8f0; border-top-color: #2878c7; border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
