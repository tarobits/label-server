<script setup lang="ts">
import { computed, ref } from 'vue'
const props = defineProps<{
  jobId: string
  text: string
  widthMm: number
  lengthMm: number
  previewUrl?: string
}>()
const failed = ref(false),
  opened = ref(false),
  retry = ref(0),
  dialog = ref<HTMLDialogElement | null>(null)
const source = computed(
  () =>
    `${props.previewUrl ?? `/api/jobs/${encodeURIComponent(props.jobId)}/preview`}${retry.value ? `?retry=${retry.value}` : ''}`,
)
const geometry = computed(() => ({ '--label-ratio': props.lengthMm / props.widthMm }))
function reload() {
  failed.value = false
  retry.value++
}
function enlarge() {
  opened.value = true
  dialog.value?.showModal()
}
</script>
<template>
  <div class="history-label" :style="geometry">
    <div v-if="failed" class="help" role="status">
      Preview unavailable.
      <button type="button" class="small secondary" @click="reload">Retry preview</button>
    </div>
    <button
      v-else
      type="button"
      class="history-thumbnail"
      :aria-label="`Enlarge label preview: ${text}`"
      @click="enlarge"
    >
      <img
        :src="source"
        :alt="`Label preview: ${text}`"
        loading="lazy"
        decoding="async"
        @error="failed = true"
      />
    </button>
    <small>{{ lengthMm }} × {{ widthMm }} mm</small>
  </div>
  <Teleport to="body">
    <dialog
      ref="dialog"
      class="label-preview-dialog"
      aria-label="Label preview"
      :style="geometry"
      @close="opened = false"
    >
      <div class="section-heading">
        <h2>Label preview</h2>
        <button type="button" class="secondary" autofocus @click="dialog?.close()">Close</button>
      </div>
      <p v-if="failed" class="alert warning">Saved label preview is unavailable.</p>
      <img
        v-else-if="opened"
        :src="source"
        :alt="`Enlarged label: ${text}`"
        @error="failed = true"
      />
      <p class="help">{{ lengthMm }} × {{ widthMm }} mm · Saved print pixels</p>
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
