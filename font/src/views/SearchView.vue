<script setup lang="ts">
import { ref, watch } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import QuestionCard from '../components/QuestionCard.vue'
import ResponsePanel from '../components/ResponsePanel.vue'
import { ApiError, request } from '../lib/api'
import type { SearchResult } from '../lib/api'
const props = defineProps<{ origin: string; review: boolean }>()
const emit = defineEmits<{ 'update:review': [value: boolean]; busy: [value: boolean]; open: [id: string] }>()
const query = ref(''); const limit = ref(5); const busy = ref(false)
const result = ref<SearchResult | null>(null); const error = ref(''); const errorBody = ref<unknown>(null)
const elapsed = ref(0)
watch(() => props.review, () => { result.value = null; error.value = ''; errorBody.value = null })
async function search() {
  if (busy.value) return
  error.value = ''; errorBody.value = null
  if (!query.value.trim() || query.value.length > 2000 || !Number.isInteger(limit.value) || limit.value < 1 || limit.value > 50) { error.value = '请输入 1—2000 字的检索内容，返回数量为 1—50 的整数。'; return }
  result.value = null; busy.value = true; emit('busy', true); const start = performance.now()
  try { result.value = await request<SearchResult>(props.origin, '/search', { query: query.value.trim(), limit: limit.value, review: props.review }) }
  catch (err) { error.value = err instanceof Error ? err.message : String(err); errorBody.value = err instanceof ApiError ? err.body : null }
  finally { elapsed.value = Math.round(performance.now() - start); busy.value = false; emit('busy', false) }
}
</script>
<template>
  <div class="section-intro"><div><span class="eyebrow blue">RETRIEVAL PLAYGROUND</span><h1>从问题出发，找到关联知识<span class="blue">。</span></h1><p>测试向量与关键词混合召回，查看真实题目和来源。</p></div><span class="tag">Dense + BM25</span></div>
  <section class="panel search-panel"><form @submit.prevent="search"><label for="search-query" class="field-label">你想检索什么？</label><textarea id="search-query" v-model="query" placeholder="例如：官渡之战的背景与历史意义" maxlength="2000" rows="3" :disabled="busy"></textarea><div class="search-controls"><div class="row"><label for="search-limit">返回数量</label><input id="search-limit" v-model.number="limit" class="short-input" type="number" min="1" max="50" :disabled="busy" /></div><label class="checkbox-label"><input type="checkbox" :checked="review" :disabled="busy" @change="emit('update:review', ($event.target as HTMLInputElement).checked)" />本地 review 模式</label><button class="button primary" :disabled="busy || !query.trim()"><AppIcon name="search" :size="18" />{{ busy ? '正在检索…' : '开始检索' }}</button></div></form><p class="help">review 可读取未审核题目，需要后端启用 LOCAL_REVIEW；普通模式仅返回已发布数据。</p></section>
  <div v-if="error" class="notice error" role="alert">{{ error }}<ResponsePanel :value="errorBody" title="查看错误响应" /></div>
  <div v-if="result?.degraded.length" class="notice warning" role="status">检索已降级：{{ result.degraded.join('、') }} 路不可用，当前结果来自其余召回路径。</div>
  <div class="results-heading row between"><h2>检索结果 <span class="count">{{ result?.results.length ?? '—' }}</span></h2><span class="subtle">{{ result ? `${elapsed} ms · 按融合排名排序` : '等待检索请求' }}</span></div>
  <div v-if="busy" class="panel empty" role="status"><span class="loading-line"></span><h3>正在寻找关联题目</h3><p>等待后端召回与排序…</p></div>
  <div v-else-if="!result || !result.results.length" class="panel empty"><span class="empty-symbol"><AppIcon name="search" :size="30" /></span><h3>{{ result ? '没有找到可见题目' : '你的下一次发现，从这里开始' }}</h3><p>{{ result ? '尝试其他关键词，或检查数据是否入库、发布及 review 权限。' : '输入一个关键词或问题，验证知识库的检索效果。' }}</p></div>
  <div v-else class="question-list"><QuestionCard v-for="question in result.results" :key="question.question_id" :question="question" :origin="origin" @open="emit('open', $event)" /></div>
  <p v-if="result?.results.length" class="help">融合分用于结果排序，不是相似度概率；返回非空不代表存在确切答案。</p><ResponsePanel :value="result" title="查看完整检索响应" />
</template>
