<script setup lang="ts">
import { ref } from 'vue'
import JobPreview from './JobPreview.vue'
defineProps<{
  jobId: string
  text: string
  widthMm: number
  lengthMm: number
  previewUrl?: string
}>()
const requested = ref(false)
function toggle(event: Event) {
  if ((event.currentTarget as HTMLDetailsElement).open) requested.value = true
}
</script>

<template>
  <details class="queue-preview" @toggle="toggle">
    <summary>Preview</summary>
    <JobPreview
      v-if="requested"
      :job-id="jobId"
      :text="text"
      :width-mm="widthMm"
      :length-mm="lengthMm"
      :preview-url="previewUrl"
    />
  </details>
</template>

<style scoped>
.queue-preview {
  margin-top: 8px;
  white-space: normal;
}
summary {
  width: fit-content;
  padding-block: 6px;
  color: var(--text-secondary);
  cursor: pointer;
}
summary:hover,
details[open] > summary {
  color: var(--ink);
}
</style>
