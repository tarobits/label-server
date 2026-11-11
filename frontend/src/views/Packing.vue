<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, errorMessage } from '../api'
import { useAuthStore } from '../auth'
import type { BatchDetail } from '../types'
import PackingLabels from '../components/PackingLabels.vue'
import { useLiveRefresh } from '../live'
const route = useRoute(),
  auth = useAuthStore()
const batch = ref<BatchDetail | null>(null),
  error = ref('')
let generation = 0
onUnmounted(() => {
  generation++
})
async function load() {
  const ticket = ++generation
  try {
    const value = await api<BatchDetail>(`/batches/${encodeURIComponent(String(route.params.id))}`)
    if (ticket === generation) {
      batch.value = value
      error.value = ''
    }
  } catch (cause) {
    if (ticket === generation) {
      batch.value = null
      error.value = errorMessage(cause)
    }
  }
}
watch(
  () => [route.params.id, JSON.stringify(auth.user)],
  () => {
    generation++
    batch.value = null
    void load()
  },
)
useLiveRefresh(load, 10000)
const complete = computed(
  () => batch.value && !['printing', 'needs_review'].includes(batch.value.state),
)
</script>
<template>
  <div class="section-heading">
    <RouterLink :to="`/batches/${route.params.id}`">Batch details</RouterLink>
  </div>
  <p v-if="error" class="alert danger" role="alert">{{ error }}</p>
  <p v-else-if="batch && !complete" class="alert warning">
    Finish reviewing this batch before packing it.
  </p>
  <PackingLabels v-if="batch && complete" :batch="batch" />
</template>
