<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Template } from '../types'

const props = defineProps<{ template: Template }>()
const failed = ref('')
const attempt = ref(0)
const source = computed(() => {
  const missing = (props.template.asset_notices ?? [])
    .map((notice) => `${notice.kind}:${notice.id}`)
    .sort()
    .join(',')
  return `/api/templates/${encodeURIComponent(props.template.id)}/preview.webp?revision=${props.template.revision}&missing=${encodeURIComponent(missing)}${attempt.value ? `&retry=${attempt.value}` : ''}`
})
</script>

<template>
  <div class="template-preview">
    <img
      v-if="failed !== source"
      :key="source"
      :src="source"
      :alt="`Preview of ${template.name}`"
      loading="lazy"
      decoding="async"
      @error="failed = source"
    />
    <div v-else class="preview-error" role="status">
      <span class="help">Preview unavailable</span>
      <button type="button" class="small secondary" @click="attempt++">Retry preview</button>
    </div>
  </div>
</template>

<style scoped>
.template-preview {
  height: 150px;
  padding: 12px;
  margin-bottom: 20px;
  border-radius: 6px;
  background: var(--surface-dense);
  display: flex;
  align-items: center;
  justify-content: center;
}
.template-preview img {
  display: block;
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
}
.preview-error {
  display: grid;
  justify-items: center;
  gap: 8px;
}
</style>
