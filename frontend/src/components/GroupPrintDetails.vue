<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { api, errorMessage } from '../shared/api'
import { date } from '../shared/workspace'
import JobPreview from './JobPreview.vue'

const props = defineProps<{ url: string }>()
interface PrintDetails {
  prints: {
    job_id: string
    batch_id: string | null
    text: string
    url: string
    width_mm: number
    length_mm: number
    copies: number
    outcomes: Record<string, number>
  }[]
  batches: { id: string; created_at: number; can_view: boolean }[]
}
const details = ref<PrintDetails | null>(null)
const loading = ref(false),
  error = ref('')
let generation = 0
async function load() {
  const ticket = ++generation
  details.value = null
  error.value = ''
  loading.value = true
  try {
    const result = await api<PrintDetails>(props.url.replace(/^\/api/, ''))
    if (ticket === generation) details.value = result
  } catch (e) {
    if (ticket === generation) error.value = errorMessage(e)
  } finally {
    if (ticket === generation) loading.value = false
  }
}
watch(() => props.url, load, { immediate: true })
onBeforeUnmount(() => {
  generation++
})
</script>
<template>
  <div class="group-print-details" :aria-busy="loading">
    <Transition name="panel-expand" mode="out-in">
      <p v-if="loading" key="loading" role="status">{{ $t('groupPrintDetails.loadingPrints') }}</p>
      <div v-else-if="error" key="error" class="account-form">
        <p class="alert danger" role="alert">{{ error }}</p>
        <button type="button" class="secondary" @click="load">{{ $t('common.retry') }}</button>
      </div>
      <div v-else-if="details" key="prints">
        <p v-if="!details.prints.length" class="muted">
          {{ $t('groupPrintDetails.noSavedLabelPreviewsAvailable') }}
        </p>
        <article
          v-for="print in details.prints"
          :key="`${print.batch_id}:${print.job_id}`"
          class="funded-print"
        >
          <strong>{{ print.text }}</strong>
          <JobPreview
            :job-id="print.job_id"
            :text="print.text"
            :preview-url="print.url"
            :width-mm="print.width_mm"
            :length-mm="print.length_mm"
          />
          <div class="row wrap">
            <span>{{ $t('app.copyCount', { count: print.copies }) }}</span>
            <span v-for="(count, outcome) in print.outcomes" :key="outcome" class="muted">
              {{ count }} {{ outcome.replaceAll('_', ' ') }}
            </span>
          </div>
          <div v-if="print.batch_id" class="row wrap">
            <span class="muted">{{
              date(details.batches.find((b) => b.id === print.batch_id)!.created_at)
            }}</span>
            <RouterLink
              v-if="details.batches.find((b) => b.id === print.batch_id)?.can_view"
              :to="`/batches/${encodeURIComponent(print.batch_id)}`"
              >{{ $t('common.viewBatch') }}</RouterLink
            >
          </div>
        </article>
      </div>
    </Transition>
  </div>
</template>
<style scoped>
.group-print-details {
  display: grid;
  gap: 20px;
  min-width: 0;
}
.funded-print {
  display: grid;
  gap: 12px;
  min-width: 0;
  overflow-wrap: anywhere;
  padding-block: 16px;
  border-bottom: 1px solid var(--line);
}
.funded-print:last-child {
  border-bottom: 0;
}
</style>
