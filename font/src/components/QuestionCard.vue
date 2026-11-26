<script setup lang="ts">
import { ref } from 'vue'
import type { Question } from '../lib/api'
import { assetUrl, missingOptions } from '../lib/api'
import ResponsePanel from './ResponsePanel.vue'
defineProps<{ question: Question; origin: string; detail?: boolean }>()
defineEmits<{ open: [id: string] }>()
const failedImages = ref<string[]>([])
function safeImage(path: string, origin: string) { try { return assetUrl(path, origin) } catch { return '' } }
</script>
<template>
  <article class="question-card">
    <div class="row between"><span class="eyebrow">{{ question.number ? `题目 ${question.number}` : '题目' }}</span><span v-if="question.score !== undefined" class="score">融合分 {{ question.score }}</span></div>
    <p class="question-text">{{ question.question_text || '未提供题干' }}</p>
    <div v-if="missingOptions(question).length" class="options"><p v-for="[key, value] in missingOptions(question)" :key="key"><b>{{ key }}</b>{{ value }}</p></div>
    <template v-for="(path, index) in question.image_urls ?? []" :key="path">
      <p v-if="!safeImage(path, origin) || failedImages.includes(path)" class="notice warning">图片 {{ index + 1 }} 无法加载，请检查图片权限与后端服务。</p>
      <img v-else class="question-image" :src="safeImage(path, origin)" :alt="`题目配图 ${index + 1}`" loading="lazy" @error="failedImages.push(path)" />
    </template>
    <div v-if="detail && question.answer != null" class="notice">参考答案：{{ question.answer }}</div>
    <details v-if="detail && question.raw_text" class="raw-text"><summary>来源原文 / 解析</summary><p class="question-text">{{ question.raw_text }}</p></details>
    <div class="row between question-footer"><span>来源页 {{ question.source_pages?.join('、') || '未提供' }}</span><button v-if="!detail" class="text-button" @click="$emit('open', question.question_id)">查看详情 →</button></div>
    <code class="question-id">{{ question.question_id }}</code>
    <ResponsePanel v-if="detail" :value="question" />
  </article>
</template>
