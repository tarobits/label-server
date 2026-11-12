<script setup lang="ts">
import { computed, ref } from 'vue'
import type { BatchDetail } from '../shared/types'
import JobPreview from './JobPreview.vue'
import { freezeLeavingItem } from '../shared/collectionMotion'
const props = withDefaults(defineProps<{ batch: BatchDetail; apiPrefix?: string }>(), {
  apiPrefix: '',
})
const order = ref('print')
const complete = computed(() => !['printing', 'needs_review'].includes(props.batch.state))
const groups = computed(() => {
  const result: {
    item: BatchDetail['items'][number]
    copies: number
    name: string
    last: number
  }[] = []
  if (!complete.value) return result
  for (const item of props.batch?.items ?? []) {
    if (item.outcome !== 'printed') continue
    const previous = result.at(-1),
      name = item.attribution?.requested_by?.name ?? 'Unknown requester'
    if (
      previous &&
      previous.item.job_id === item.job_id &&
      previous.last + 1 === item.position &&
      JSON.stringify(previous.item.attribution) === JSON.stringify(item.attribution)
    ) {
      previous.copies++
      previous.last = item.position
    } else result.push({ item, copies: 1, name, last: item.position })
  }
  return order.value === 'requester'
    ? result.sort((a, b) => a.name.localeCompare(b.name) || a.item.position - b.item.position)
    : result
})
</script>
<template>
  <label class="packing-sort"
    >{{ $t('common.sortBy')
    }}<select v-model="order">
      <option value="print">{{ $t('common.printOrder') }}</option>
      <option value="requester">{{ $t('common.requester') }}</option>
    </select></label
  >
  <p v-if="complete && !groups.length" class="empty">
    {{ $t('packingLabels.noConfirmedPrintedLabels') }}
  </p>
  <TransitionGroup
    name="collection"
    tag="div"
    class="packing-grid"
    @before-leave="freezeLeavingItem"
  >
    <article v-for="group in groups" :key="group.item.copy_id" class="panel packing-label">
      <div class="section-heading">
        <h2>{{ group.name }}</h2>
        <strong>{{ group.copies }} {{ group.copies === 1 ? 'copy' : $t('common.copies2') }}</strong>
      </div>
      <JobPreview
        :job-id="group.item.job_id"
        :text="group.item.process_name"
        :width-mm="group.item.width_mm"
        :length-mm="group.item.length_mm"
        :preview-url="`/api${apiPrefix}/batches/${batch.id}/items/${group.item.copy_id}/preview`"
      />
      <small
        >{{ $t('packingLabels.printPosition') }} {{ group.item.position + 1
        }}{{ group.copies > 1 ? `–${group.last + 1}` : '' }}</small
      >
    </article>
  </TransitionGroup>
</template>
<style scoped>
.packing-sort {
  max-width: 240px;
}
.packing-grid {
  position: relative;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 340px), 1fr));
  gap: 20px;
  margin-top: 20px;
}
.packing-label {
  display: grid;
  gap: 16px;
  align-content: start;
}
.packing-label h2 {
  overflow-wrap: anywhere;
}
.packing-label small {
  color: var(--text-secondary);
}
</style>
