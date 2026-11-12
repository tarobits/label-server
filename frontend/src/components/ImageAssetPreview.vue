<script setup lang="ts">
import { computed, ref } from 'vue'
import { usePreview } from '../previewLoader'

const props = defineProps<{ asset: { id: string; name: string }; large?: boolean }>()
const emit = defineEmits<{ enlarge: [] }>()
const target = ref<HTMLElement | null>(null)
const source = computed(
  () =>
    `/api/image-assets/${encodeURIComponent(props.asset.id)}/preview${props.large ? '?size=large' : ''}`,
)
const { image, failed, reload } = usePreview(source, target)
</script>

<template>
  <div ref="target" class="asset-preview" :class="{ large }" :aria-busy="!image && !failed">
    <div v-if="failed" class="preview-error" role="status">
      <span class="help">Preview unavailable</span>
      <button type="button" class="small secondary" @click="reload">Retry preview</button>
    </div>
    <img
      v-else-if="large && image"
      class="image-enlarged-preview"
      :src="image"
      :alt="asset.name"
      @error="failed = true"
    />
    <button
      v-else-if="!large"
      type="button"
      class="image-thumbnail"
      :aria-label="`Preview ${asset.name}`"
      :disabled="!image"
      @click="emit('enlarge')"
    >
      <img v-if="image" :src="image" alt="" width="120" height="80" @error="failed = true" />
    </button>
  </div>
</template>

<style scoped>
.asset-preview {
  min-width: 120px;
  min-height: 80px;
}
.asset-preview.large {
  min-height: min(60vh, 600px);
}
.image-thumbnail,
.image-enlarged-preview {
  background-color: #fff;
  background-image: conic-gradient(#e5e7eb 25%, #fff 0 50%, #e5e7eb 0 75%, #fff 0);
  background-size: 16px 16px;
}
.image-thumbnail {
  display: block;
  width: 120px;
  height: 80px;
  padding: 0;
  overflow: hidden;
}
.image-thumbnail img {
  display: block;
  object-fit: contain;
}
.image-enlarged-preview {
  display: block;
  width: 100%;
  height: min(60vh, 600px);
  object-fit: contain;
  border-radius: 6px;
}
.preview-error {
  display: grid;
  justify-items: center;
  gap: 8px;
}
</style>
