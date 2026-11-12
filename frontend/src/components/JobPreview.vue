<script setup lang="ts">
import { computed, ref } from 'vue'
import { usePreview } from '../shared/previewLoader'
const props = defineProps<{
  jobId: string
  text: string
  widthMm: number
  lengthMm: number
  previewUrl?: string
}>()
const target = ref<HTMLElement | null>(null),
  opened = ref(false),
  dialog = ref<HTMLDialogElement | null>(null)
const source = computed(
  () => props.previewUrl ?? `/api/jobs/${encodeURIComponent(props.jobId)}/preview`,
)
const { image, failed, reload } = usePreview(source, target)
const geometry = computed(() => ({ '--label-ratio': props.lengthMm / props.widthMm }))
function enlarge() {
  opened.value = true
  dialog.value?.showModal()
}
</script>
<template>
  <div ref="target" class="history-label" :style="geometry" :aria-busy="!image && !failed">
    <div v-if="failed" class="help" role="status">
      {{ $t('common.previewUnavailable2') }}
      <button type="button" class="small secondary" @click="reload">
        {{ $t('common.retryPreview') }}
      </button>
    </div>
    <button
      v-else
      type="button"
      class="history-thumbnail"
      :aria-label="`Enlarge label preview: ${text}`"
      :disabled="!image"
      @click="enlarge"
    >
      <img
        v-if="image"
        :src="image"
        :alt="`Label preview: ${text}`"
        loading="lazy"
        decoding="async"
        @error="failed = true"
      />
    </button>
    <small>{{ lengthMm }} × {{ widthMm }} {{ $t('common.mm') }}</small>
  </div>
  <Teleport to="body">
    <dialog
      ref="dialog"
      class="label-preview-dialog"
      :aria-label="$t('common.labelPreview')"
      :style="geometry"
      @close="opened = false"
    >
      <div class="section-heading">
        <h2>{{ $t('common.labelPreview') }}</h2>
        <button type="button" class="secondary" autofocus @click="dialog?.close()">
          {{ $t('common.close') }}
        </button>
      </div>
      <p v-if="failed" class="alert warning">{{ $t('common.savedLabelPreviewIsUnavailable') }}</p>
      <img
        v-else-if="opened && image"
        :src="image"
        :alt="`Enlarged label: ${text}`"
        @error="failed = true"
      />
      <p class="help">{{ lengthMm }} × {{ widthMm }} {{ $t('common.mmSavedPrintPixels') }}</p>
    </dialog>
  </Teleport>
</template>
<style scoped>
.history-label {
  margin-bottom: 8px;
  white-space: normal;
}
.history-thumbnail {
  display: block;
  width: min(280px, calc(120px * var(--label-ratio)));
  max-width: 100%;
  padding: 0;
  border: 0;
  overflow: hidden;
  background: transparent;
  margin-bottom: 6px;
  aspect-ratio: var(--label-ratio);
}
.history-thumbnail:not(:disabled):hover {
  background: transparent;
}
.history-thumbnail img,
.label-preview-dialog img {
  display: block;
  width: 100%;
  height: auto;
  aspect-ratio: var(--label-ratio);
  image-rendering: pixelated;
}
.label-preview-dialog {
  width: min(1000px, calc(100vw - 40px));
  max-height: calc(100vh - 40px);
  padding: 24px;
  border: 1px solid var(--border-strong);
  border-radius: 12px;
  background: var(--surface);
  color: var(--ink);
  box-shadow: 0 24px 80px #0008;
}
.label-preview-dialog::backdrop {
  background: #030712b3;
  backdrop-filter: blur(3px);
}
.label-preview-dialog img {
  width: min(100%, calc(60vh * var(--label-ratio)));
  margin: auto;
}
.label-preview-dialog .help {
  margin-top: 16px;
}
</style>
