<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import AppIcon from './components/AppIcon.vue'
import ResponsePanel from './components/ResponsePanel.vue'
import ImportView from './views/ImportView.vue'
import SearchView from './views/SearchView.vue'
import DetailView from './views/DetailView.vue'
import { ApiError, normalizeOrigin, request } from './lib/api'
type Page = 'import' | 'search' | 'detail'
const page = ref<Page>('import')
const origin = ref('http://127.0.0.1:8000')
try { origin.value = normalizeOrigin(localStorage.getItem('kaogong-api-origin') || origin.value) } catch { /* use local default */ }
const originInput = ref(origin.value)
const settingsOpen = ref(false); const settingsError = ref(''); const busy = ref(false); const review = ref(false)
const health = ref<'unknown' | 'checking' | 'ok' | 'failed'>('unknown')
const healthError = ref(''); const healthBody = ref<unknown>(null)
const detailView = ref<InstanceType<typeof DetailView> | null>(null)
const healthLabel = computed(() => ({ unknown: '尚未检查连接', checking: '正在检查…', ok: '服务连接正常', failed: '服务连接异常' })[health.value])
const nav = [{ id: 'import' as Page, name: 'PDF 导入', icon: 'upload', hint: '01' }, { id: 'search' as Page, name: '检索测试', icon: 'search', hint: '02' }, { id: 'detail' as Page, name: '题目详情', icon: 'file', hint: '03' }]
function applyOrigin() {
  settingsError.value = ''
  try {
    origin.value = normalizeOrigin(originInput.value); originInput.value = origin.value
    try { localStorage.setItem('kaogong-api-origin', origin.value) } catch { /* optional storage */ }
    health.value = 'unknown'; healthError.value = ''; healthBody.value = null; settingsOpen.value = false
  } catch (err) { settingsError.value = err instanceof Error ? err.message : '地址无效' }
}
async function checkHealth() {
  if (busy.value || health.value === 'checking') return
  health.value = 'checking'; healthError.value = ''; healthBody.value = null
  try {
    const data = await request<{ status: string }>(origin.value, '/health', undefined, 12000)
    if (data.status !== 'ok') throw new Error('后端返回了未识别的健康状态')
    health.value = 'ok'; healthBody.value = data
  } catch (err) { health.value = 'failed'; healthError.value = err instanceof Error ? err.message : String(err); healthBody.value = err instanceof ApiError ? err.body : null }
}
async function openQuestion(id: string) { page.value = 'detail'; await nextTick(); detailView.value?.load(id) }
</script>
<template>
  <a href="#main-content" class="skip-link">跳转到主要内容</a>
  <div class="app-shell">
    <aside class="sidebar"><a class="brand" href="#" @click.prevent="!busy && (page = 'import')"><span class="brand-mark"><AppIcon name="book" :size="23" /></span><span>考公<span class="brand-light"> RAG</span><small>KNOWLEDGE LAB</small></span></a>
      <div class="workspace-switch"><span class="workspace-avatar">K</span><div><b>本地测试空间</b><small>开发环境</small></div><span class="workspace-dot"></span></div>
      <span class="nav-label">工作台</span><nav aria-label="主要导航"><button v-for="item in nav" :key="item.id" :class="['nav-item', { selected: page === item.id }]" :aria-current="page === item.id ? 'page' : undefined" :disabled="busy" @click="page = item.id"><AppIcon :name="item.icon" /><span>{{ item.name }}</span><small>{{ item.hint }}</small></button></nav>
      <div class="sidebar-bottom"><div class="sandbox-note"><span class="row"><AppIcon name="code" :size="16" /> 为验证而构建</span><p>上传、入库、检索。<br />让每一步结果都清晰可见。</p><span class="version">PROTOTYPE / V0.1</span></div><button class="sidebar-settings" :disabled="busy || health === 'checking'" @click="settingsOpen = !settingsOpen"><AppIcon name="settings" :size="18" />连接设置<span>↗</span></button></div>
    </aside>
    <div class="main-shell"><header class="topbar"><div class="breadcrumb">测试工作台 <span>/</span><b>{{ nav.find(n => n.id === page)?.name }}</b><span class="environment">LOCAL</span></div><div class="connection-controls"><button class="connection-address" :disabled="busy || health === 'checking'" @click="settingsOpen = !settingsOpen">{{ origin.replace(/^https?:\/\//, '') }}</button><button class="health-button" :class="health" :disabled="busy || health === 'checking'" @click="checkHealth"><i></i>{{ healthLabel }}<AppIcon name="pulse" :size="15" /></button><button class="mobile-settings" aria-label="连接设置" :disabled="busy || health === 'checking'" @click="settingsOpen = !settingsOpen"><AppIcon name="settings" :size="18" /></button></div></header>
      <main id="main-content"><section v-if="settingsOpen" class="panel connection-panel"><form @submit.prevent="applyOrigin"><label for="api-origin" class="field-label">后端地址</label><div class="row id-search"><input id="api-origin" v-model="originInput" type="url" required placeholder="http://127.0.0.1:8000" :disabled="busy" /><button class="button primary" :disabled="busy || health === 'checking'">应用地址</button><button type="button" class="button secondary" @click="settingsOpen = false">关闭</button></div><p class="help">请输入 API origin，不添加 /api。切换地址会清空当前页面结果；仅将地址保存在此浏览器。</p><p v-if="settingsError" class="notice error" role="alert">{{ settingsError }}</p></form></section>
        <div v-if="healthError" class="notice error" role="alert">健康检查失败：{{ healthError }}<ResponsePanel :value="healthBody" /></div>
        <div :key="origin">
          <div v-show="page === 'import'"><ImportView :origin="origin" @busy="busy = $event" @search="page = 'search'" /></div>
          <div v-show="page === 'search'"><SearchView :origin="origin" v-model:review="review" @busy="busy = $event" @open="openQuestion" /></div>
          <div v-show="page === 'detail'"><DetailView ref="detailView" :origin="origin" v-model:review="review" @busy="busy = $event" /></div>
        </div>
        <footer class="page-footer"><span>KAOGONG RAG <i> / </i> 本地接口测试工作台</span><span>Vue 3 · TypeScript · Tailwind CSS</span></footer>
      </main>
    </div>
  </div>
</template>
