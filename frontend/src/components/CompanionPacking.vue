<script setup lang="ts">
import { locale, t } from '../shared/i18n'

import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { api, errorMessage } from '../shared/api'
import type { Batch, BatchDetail } from '../shared/types'
import { useLiveRefresh } from '../shared/live'
import PackingLabels from './PackingLabels.vue'
import MotionSurface from './MotionSurface.vue'

const props = defineProps<{ printerId: string; printerName: string }>()
defineEmits<{ close: [] }>()
const batches = ref<Batch[]>([]),
  batch = ref<BatchDetail | null>(null)
const selected = ref(''),
  page = ref(0),
  total = ref(0),
  error = ref(''),
  loading = ref(true)
const before = ref<number | null>(null)
const pages = computed(() => Math.max(1, Math.ceil(total.value / 20)))
const complete = (item: Batch) => !['printing', 'needs_review'].includes(item.state)
let generation = 0,
  detailGeneration = 0,
  disposed = false
onBeforeUnmount(() => {
  disposed = true
  generation++
  detailGeneration++
})
async function loadBatch() {
  const ticket = ++detailGeneration,
    id = selected.value
  if (!id) {
    batch.value = null
    return
  }
  try {
    const value = await api<BatchDetail>(`/proxy/batches/${encodeURIComponent(id)}`)
    if (disposed || ticket !== detailGeneration) return
    batch.value = value
    error.value = ''
  } catch (issue) {
    if (disposed || ticket !== detailGeneration) return
    batch.value = null
    error.value = errorMessage(issue)
  }
}
async function load() {
  const ticket = ++generation
  try {
    const query = new URLSearchParams({
      printer_id: props.printerId,
      limit: '20',
      offset: String(page.value * 20),
    })
    if (page.value && before.value !== null) query.set('before', String(before.value))
    const result = await api<{ items: Batch[]; total: number; before: number }>(
      `/proxy/batches/page?${query}`,
    )
    if (disposed || ticket !== generation) return
    batches.value = result.items
    total.value = result.total
    before.value = result.before
    error.value = ''
    if (!result.items.some((item) => item.id === selected.value && complete(item))) {
      selected.value = result.items.find(complete)?.id ?? ''
      if (!selected.value) batch.value = null
    } else await loadBatch()
  } catch (issue) {
    if (disposed || ticket !== generation) return
    batches.value = []
    batch.value = null
    detailGeneration++
    error.value = errorMessage(issue)
  } finally {
    if (!disposed && ticket === generation) loading.value = false
  }
}
watch(selected, () => {
  batch.value = null
  void loadBatch()
})
watch(page, () => {
  selected.value = ''
  batches.value = []
  loading.value = true
  void load()
})
useLiveRefresh(load, 10000)
const title = (item: Batch) =>
  `${new Date(item.created_at * 1000).toLocaleString(locale.value)} · ${item.process_names?.join(', ') || t('companionPacking.batch')}`
</script>

<template>
  <section class="station-packing" :aria-label="$t('companionPacking.batchPacking')">
    <div class="row wrap spread">
      <h2 tabindex="-1">{{ $t('companionPacking.packLabels') }} {{ printerName }}</h2>
      <button class="secondary" @click="$emit('close')">
        {{ $t('companionPacking.backToPrinters') }}
      </button>
    </div>
    <p v-if="error" class="alert danger" role="alert">{{ error }}</p>
    <p v-if="loading" class="muted" role="status">{{ $t('companionPacking.loadingBatches') }}</p>
    <div v-if="batches.length || page" class="packing-batches">
      <label
        >{{ $t('companionPacking.batch')
        }}<select v-model="selected">
          <option value="" disabled>{{ $t('companionPacking.chooseACompletedBatch') }}</option>
          <option
            v-for="item in batches"
            :key="item.id"
            :value="item.id"
            :disabled="!complete(item)"
          >
            {{ title(item) }}{{ complete(item) ? '' : ' · Not ready for packing' }}
          </option>
        </select></label
      >
      <nav v-if="pages > 1" class="row" :aria-label="$t('companionPacking.batchPages')">
        <button class="secondary" :disabled="loading || !page" @click="page--">
          {{ $t('common.previous') }}
        </button>
        <span>{{ page + 1 }} / {{ pages }}</span>
        <button class="secondary" :disabled="loading || page + 1 >= pages" @click="page++">
          {{ $t('common.next') }}
        </button>
      </nav>
    </div>
    <p v-if="!loading && !error && !selected" class="empty compact">
      {{ $t('companionPacking.noCompletedBatchesOnThisPage') }}
    </p>
    <MotionSurface :identity="selected">
      <PackingLabels
        v-if="batch && complete(batch)"
        :key="batch.id"
        :batch="batch"
        api-prefix="/proxy"
      />
    </MotionSurface>
  </section>
</template>

<style scoped>
.station-packing {
  display: grid;
  gap: 16px;
}
.station-packing h2 {
  margin: 0;
  overflow-wrap: anywhere;
}
.packing-batches {
  display: flex;
  align-items: end;
  flex-wrap: wrap;
  gap: 16px;
}
.packing-batches label {
  flex: 1 1 320px;
  min-width: 0;
}
.packing-batches select {
  width: 100%;
}
.packing-batches nav {
  flex-wrap: wrap;
}
.station-packing button {
  min-height: 44px;
}
</style>
