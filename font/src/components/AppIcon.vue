<script setup lang="ts">
defineProps<{ name: string; size?: number }>()
const paths: Record<string, string> = {
  grid: 'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
  upload: 'M12 16V3m-5 5 5-5 5 5M4 15v5a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-5',
  search: 'M21 21l-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0',
  file: 'M14 2H5v20h14V7z M14 2v6h5 M8 13h8 M8 17h6',
  arrow: 'M5 12h14m-5-5 5 5-5 5',
  check: 'm5 12 4 4L19 6',
  pulse: 'M2 12h5l3-8 4 16 3-8h5',
  settings: 'M12 8v8m-4-4h8 M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0',
  code: 'm8 7-5 5 5 5m8-10 5 5-5 5m-3-14-2 18',
  book: 'M12 5v16M3 3c4-1 7 0 9 2 2-2 5-3 9-2v16c-4-1-7 0-9 2-2-2-5-3-9-2z',
}
</script>
<template><svg :width="size ?? 20" :height="size ?? 20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path :d="paths[name] ?? paths.file" /></svg></template>
