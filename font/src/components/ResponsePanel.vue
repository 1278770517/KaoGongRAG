<script setup lang="ts">
defineProps<{ value: unknown; title?: string }>()
</script>
<template><details v-if="value !== null && value !== undefined" class="response-panel"><summary>{{ title ?? '查看原始响应' }} <span>JSON</span></summary><pre>{{ typeof value === 'string' ? value : JSON.stringify(value, null, 2) }}</pre></details></template>
