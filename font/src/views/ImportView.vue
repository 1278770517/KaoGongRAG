<script setup lang="ts">
import { computed, ref } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import ResponsePanel from '../components/ResponsePanel.vue'
import { ApiError, canIndex, request, uploadPdf } from '../lib/api'
import type { ImportResult, OcrResult } from '../lib/api'
const props = defineProps<{ origin: string }>()
const emit = defineEmits<{ busy: [value: boolean]; search: [] }>()
const file = ref<File | null>(null)
const endPage = ref(10)
const phase = ref<'idle' | 'uploading' | 'ocr' | 'indexing'>('idle')
const ocr = ref<OcrResult | null>(null)
const indexed = ref<ImportResult | null>(null)
const error = ref('')
const errorBody = ref<unknown>(null)
const dragging = ref(false)
const busy = computed(() => phase.value !== 'idle')
const indexAllowed = computed(() => canIndex(ocr.value) && !busy.value && !['completed', 'running', 'pending'].includes(indexed.value?.status ?? ''))
function choose(chosen?: File) {
  if (busy.value || !chosen) return
  error.value = ''; errorBody.value = null
  if (!chosen.name.toLowerCase().endsWith('.pdf') || chosen.size === 0 || chosen.size > 100 * 1024 * 1024) { file.value = null; ocr.value = null; indexed.value = null; error.value = '请选择非空 PDF 文件，大小不超过 100 MiB。'; return }
  file.value = chosen; ocr.value = null; indexed.value = null
}
function dropped(event: DragEvent) { dragging.value = false; choose(event.dataTransfer?.files[0]) }
function failure(err: unknown) { error.value = err instanceof Error ? err.message : String(err); errorBody.value = err instanceof ApiError ? err.body : null }
async function upload() {
  if (!file.value || busy.value) return
  if (!Number.isInteger(endPage.value) || endPage.value < 1 || endPage.value > 1000) { error.value = '结束页必须为 1—1000 的整数，且不超过 PDF 实际页数。'; return }
  error.value = ''; errorBody.value = null; ocr.value = null; indexed.value = null
  phase.value = 'uploading'; emit('busy', true)
  try { ocr.value = await uploadPdf(props.origin, file.value, endPage.value, () => { phase.value = 'ocr' }) }
  catch (err) { failure(err) }
  finally { phase.value = 'idle'; emit('busy', false) }
}
async function index() {
  if (!indexAllowed.value || !ocr.value) return
  error.value = ''; errorBody.value = null; phase.value = 'indexing'; emit('busy', true)
  try { indexed.value = await request<ImportResult>(props.origin, '/imports/markdown', { path: ocr.value.directory, retry_failed: indexed.value?.status === 'failed' }, 600_000) }
  catch (err) {
    failure(err)
    if (err instanceof ApiError && err.body && typeof err.body === 'object' && 'detail' in err.body) {
      const detail = err.body.detail
      if (detail && typeof detail === 'object' && 'status' in detail && detail.status === 'failed') indexed.value = detail as ImportResult
    }
  } finally { phase.value = 'idle'; emit('busy', false) }
}
</script>
<template>
  <div class="section-intro"><div><span class="eyebrow blue">KNOWLEDGE PIPELINE</span><h1>让文档，成为可检索的知识<span class="blue">。</span></h1><p>从一份 PDF 开始，验证解析、入库与检索的完整链路。</p></div><span class="tag">两阶段导入</span></div>
  <div class="steps"><div :class="{ active: !ocr }"><span>01</span><div><b>上传与解析</b><small>PDF → OCR</small></div></div><i></i><div :class="{ active: ocr && indexed?.status !== 'completed' }"><span>02</span><div><b>确认入库</b><small>分块与索引</small></div></div><i></i><div :class="{ active: indexed?.status === 'completed' }"><span>03</span><div><b>检索验证</b><small>找到关联题目</small></div></div></div>
  <div class="import-layout">
    <section class="panel"><div class="panel-heading"><div class="row"><span class="icon-tile"><AppIcon name="upload" /></span><div><h2>上传 PDF 文档</h2><p>选择需要测试的题目或解析册</p></div></div><span class="subtle">STEP 01</span></div>
      <label class="drop-zone" :class="{ dragging, disabled: busy }" @dragover.prevent="dragging = true" @dragleave.prevent="dragging = false" @drop.prevent="dropped">
        <input type="file" accept=".pdf,application/pdf" :disabled="busy" aria-label="选择 PDF 文件" @change="choose(($event.target as HTMLInputElement).files?.[0])" />
        <span class="upload-art"><AppIcon name="file" :size="34" /></span><strong>{{ file?.name || '点击选择，或将 PDF 拖到这里' }}</strong><span>{{ file ? `${(file.size / 1024 / 1024).toFixed(2)} MiB · 点击更换文件` : '仅支持 PDF · 单个文件最大 100 MiB' }}</span><span class="button secondary small">{{ file ? '更换文件' : '选择本地文件' }}</span>
      </label>
      <div class="page-setting"><label for="end-page">解析结束页 <span class="subtle">从第 1 页开始</span></label><input id="end-page" v-model.number="endPage" type="number" min="1" max="1000" step="1" :disabled="busy" /><p class="help">首次测试建议解析少量页面；结束页不能超过文件实际页数。</p></div>
      <div class="panel-actions"><span class="help">文件只会在点击后上传至当前后端</span><button class="button primary" :disabled="!file || busy" @click="upload"><AppIcon name="upload" :size="17" />{{ phase === 'uploading' ? '正在上传…' : phase === 'ocr' ? 'OCR 解析中…' : '上传并解析' }}</button></div>
    </section>
    <aside class="panel next-panel"><div class="panel-heading"><div class="row"><span class="icon-tile neutral"><AppIcon name="grid" /></span><div><h2>解析结果与入库</h2><p>确认解析完成后，再写入索引</p></div></div></div>
      <div v-if="!ocr" class="empty compact"><span class="empty-symbol"><AppIcon name="file" :size="28" /></span><h3>{{ busy ? '正在处理文档' : '等待第一份文档' }}</h3><p>{{ phase === 'ocr' ? '文件已上传，正在等待 OCR 返回。' : phase === 'uploading' ? '正在传输文件，请保持页面打开。' : '上传完成后，在这里查看解析结果并确认入库。' }}</p><span v-if="busy" class="loading-line"></span></div>
      <div v-else class="result-content"><div class="notice" :class="canIndex(ocr) ? 'success' : 'warning'">{{ canIndex(ocr) ? 'OCR 完整解析成功，可以确认入库' : `OCR 状态：${ocr.manifest.status}，已阻止入库` }}</div><div class="metric-row"><div><strong>{{ ocr.markdown_paths?.length ?? 0 }}</strong><span>成功产物</span></div><div><strong>{{ ocr.manifest.pages?.filter(p => p.status === 'failed').length ?? 0 }}</strong><span>失败页</span></div></div><label class="field-label">解析目录</label><code class="path-box">{{ ocr.directory }}</code><ul v-if="!canIndex(ocr)" class="failed-pages"><li v-for="page in ocr.manifest.pages?.filter(p => p.status === 'failed')" :key="page.page">第 {{ page.page }} 页：{{ page.error }}</li></ul><button class="button primary full" :disabled="!indexAllowed" @click="index">{{ phase === 'indexing' ? '正在分块与建立索引…' : indexed?.status === 'failed' ? '明确重试失败入库' : '确认并开始入库' }}<AppIcon name="arrow" :size="17" /></button><ResponsePanel :value="ocr" title="查看 OCR 响应" /></div>
      <div class="panel-note"><AppIcon name="settings" :size="16" /><span>解析成功不会自动入库。入库完成也不代表题目已审核发布。</span></div>
    </aside>
  </div>
  <div v-if="busy" class="notice" role="status">{{ phase === 'indexing' ? '索引处理中，请保持页面打开；不会自动重复提交。' : 'OCR 可能需要较长时间，当前没有服务端页级实时进度。' }}</div>
  <div v-if="error" class="notice error" role="alert"><strong>请求未完成</strong><p>{{ error }}</p><ResponsePanel :value="errorBody" title="查看错误响应" /></div>
  <section v-if="indexed" class="panel index-result"><div class="row between"><h2>入库结果</h2><span class="tag" :class="indexed.status === 'completed' ? 'success' : 'warning'">{{ indexed.status === 'completed' ? '入库成功' : `状态：${indexed.status}` }}</span></div><p v-if="indexed.status !== 'completed'" class="help">任务尚未成功完成，不会自动轮询或重新提交。{{ indexed.error }}</p><div class="metric-row"><div><strong>{{ indexed.parents ?? '—' }}</strong><span>本批题目</span></div><div><strong>{{ indexed.chunks ?? '—' }}</strong><span>本批分块</span></div><div><strong>{{ indexed.assets ?? '—' }}</strong><span>图片关联</span></div></div><button v-if="indexed.status === 'completed'" class="button secondary" @click="$emit('search')">前往检索验证 →</button><ResponsePanel :value="indexed" /></section>
  <section class="bottom-guide"><span class="icon-tile"><AppIcon name="book" /></span><div><h3>先跑通链路，再打磨业务</h3><p>这里验证已有 API 的真实行为。导入未审核题目后，可在检索测试中启用本地 review 模式。</p></div><span class="tag">测试工作台</span></section>
</template>
