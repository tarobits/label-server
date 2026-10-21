<script setup lang="ts">
import { ref } from 'vue'
import JobPreview from './JobPreview.vue'
import AnimatedDetails from './AnimatedDetails.vue'
defineProps<{
  jobId: string
  text: string
  widthMm: number
  lengthMm: number
  previewUrl?: string
}>()
const requested = ref(false)
function toggle(open: boolean) {
  if (open) requested.value = true
}
</script>

<template>
  <AnimatedDetails class="queue-preview" @toggle="toggle">
    <template #summary>Preview</template>
    <JobPreview
      v-if="requested"
      :job-id="jobId"
      :text="text"
      :width-mm="widthMm"
      :length-mm="lengthMm"
      :preview-url="previewUrl"
    />
  </AnimatedDetails>
</template>

<style scoped>
.queue-preview {
  margin-top: 8px;
  white-space: normal;
}
:deep(summary) {
  width: fit-content;
  padding-block: 6px;
  color: var(--text-secondary);
  cursor: pointer;
}
:deep(summary:hover),
details[data-expanded='true'] :deep(summary) {
  color: var(--ink);
}
</style>
