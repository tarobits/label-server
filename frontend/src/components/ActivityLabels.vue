<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { useResourceStore } from '../stores/resources'
import { useAuthStore } from '../auth'
import { errorMessage } from '../api'
import type { BatchDetail } from '../types'
import LabelDetails from './LabelDetails.vue'
import QueuePreview from './QueuePreview.vue'
import AnimatedDetails from './AnimatedDetails.vue'
import TapeUsage from './TapeUsage.vue'
import PrintPlanNotice from './PrintPlanNotice.vue'
const props = defineProps<{ batchId: string; state: string }>()
const resources = useResourceStore(),
  auth = useAuthStore()
const detail = ref<BatchDetail | null>(null),
  opened = ref(false),
  loading = ref(false),
  error = ref('')
let stopped = false,
  generation = 0
const labels = computed(() => {
  const grouped = new Map<string, { item: BatchDetail['items'][number]; copies: number }>()
  for (const item of detail.value?.items ?? []) {
    const existing = grouped.get(item.job_id)
    if (existing) existing.copies++
    else grouped.set(item.job_id, { item, copies: 1 })
  }
  return [...grouped.values()]
})
async function load(force = false) {
  const ticket = ++generation,
    actor = auth.user?.id
  loading.value = true
  try {
    const result = await resources.get<BatchDetail>(
      `/batches/${encodeURIComponent(props.batchId)}`,
      { ttl: 5000, force },
    )
    if (!stopped && ticket === generation && auth.user?.id === actor) {
      detail.value = result
      error.value = ''
    }
  } catch (issue) {
    if (!stopped && ticket === generation && auth.user?.id === actor)
      error.value = errorMessage(issue)
  } finally {
    if (ticket === generation) loading.value = false
  }
}
function toggle(open: boolean) {
  opened.value = open
  if (opened.value && !detail.value && !loading.value) void load()
}
watch(
  () => props.state,
  () => {
    if (opened.value) void load(true)
  },
)
onUnmounted(() => {
  stopped = true
  generation++
})
</script>

<template>
  <AnimatedDetails class="activity-labels" @toggle="toggle">
    <template #summary>Details</template>
    <p v-if="error" class="alert warning" role="status">
      {{ error }} <button type="button" class="small secondary" @click="load(true)">Retry</button>
    </p>
    <p v-else-if="loading && !detail" class="help" role="status">Loading labels…</p>
    <template v-if="detail">
      <TapeUsage :plan="detail.print_plan" caption="Saved estimate for this attempt" />
      <PrintPlanNotice :plan="detail.print_plan" />
    </template>
    <section v-for="entry in labels" :key="entry.item.job_id" class="activity-label">
      <strong>{{ entry.item.process_name }}</strong>
      <small>{{ entry.copies }} {{ entry.copies === 1 ? 'copy' : 'copies' }}</small>
      <LabelDetails :label="entry.item" :attribution="entry.item.attribution" />
      <QueuePreview
        :job-id="entry.item.job_id"
        :text="entry.item.process_name"
        :width-mm="entry.item.width_mm"
        :length-mm="entry.item.length_mm"
        :preview-url="`/api/batches/${batchId}/items/${entry.item.copy_id}/preview`"
      />
    </section>
  </AnimatedDetails>
</template>

<style scoped>
.activity-labels {
  margin-top: 12px;
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
.activity-label {
  padding-block: 16px;
  border-bottom: 1px solid var(--line);
}
.activity-label:last-child {
  border-bottom: 0;
}
.activity-label > strong {
  overflow-wrap: anywhere;
}
.activity-label > small {
  display: block;
  margin-top: 4px;
  color: var(--text-secondary);
}
</style>
