<script setup lang="ts">
import { ref, watch } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import QuestionCard from '../components/QuestionCard.vue'
import ResponsePanel from '../components/ResponsePanel.vue'
import { ApiError, request } from '../lib/api'
import type { Question } from '../lib/api'
const props = defineProps<{ origin: string; review: boolean }>()
const emit = defineEmits<{ 'update:review': [value: boolean]; busy: [value: boolean] }>()
const id = ref(''); const question = ref<Question | null>(null); const busy = ref(false)
const error = ref(''); const errorBody = ref<unknown>(null)
watch(() => props.review, () => { question.value = null; error.value = ''; errorBody.value = null })
async function load(value = id.value) {
  if (busy.value) return
  id.value = value; error.value = ''; errorBody.value = null; question.value = null
  if (!value.trim()) { error.value = '请输入完整的 question_id。'; return }
  busy.value = true; emit('busy', true)
  try { question.value = await request<Question>(props.origin, `/questions/${encodeURIComponent(value.trim())}?review=${props.review}`) }
  catch (err) { error.value = err instanceof Error ? err.message : String(err); errorBody.value = err instanceof ApiError ? err.body : null }
  finally { busy.value = false; emit('busy', false) }
}
defineExpose({ load })
</script>
<template>
  <div class="section-intro"><div><span class="eyebrow blue">QUESTION INSPECTOR</span><h1>每一道题，都有据可查<span class="blue">。</span></h1><p>通过题目 ID 读取详情，检查题干、来源和关联图片。</p></div><span class="tag">直接读取 · 不经过检索</span></div>
  <section class="panel search-panel"><form @submit.prevent="load()"><label for="question-id" class="field-label">题目 ID</label><div class="row id-search"><input id="question-id" v-model="id" placeholder="粘贴完整 question_id，或从检索结果打开" :disabled="busy" /><button class="button primary" :disabled="busy || !id.trim()"><AppIcon name="search" :size="17" />{{ busy ? '读取中…' : '读取详情' }}</button></div><label class="checkbox-label detail-review"><input type="checkbox" :checked="review" :disabled="busy" @change="emit('update:review', ($event.target as HTMLInputElement).checked)" />本地 review 模式 <span class="help">需后端启用 LOCAL_REVIEW</span></label></form></section>
  <div v-if="error" class="notice error" role="alert">{{ error }}<ResponsePanel :value="errorBody" title="查看错误响应" /></div>
  <QuestionCard v-if="question" :question="question" :origin="origin" detail />
  <div v-else class="panel empty" :aria-busy="busy"><span class="empty-symbol"><AppIcon name="file" :size="30" /></span><h3>{{ busy ? '正在读取题目' : '查看题目的完整上下文' }}</h3><p>题目 ID 与题号不同，请使用接口返回的 question_id。</p></div>
</template>
