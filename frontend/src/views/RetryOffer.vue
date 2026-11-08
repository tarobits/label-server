<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, errorMessage } from '../api'
import { useAuthStore } from '../auth'
import { useWorkspaceStore } from '../workspace'
import CostEstimate from '../components/CostEstimate.vue'
import JobPreview from '../components/JobPreview.vue'
import ExpandableContent from '../components/ExpandableContent.vue'
import type { CostEstimate as Estimate } from '../types'
interface Offer {
  id: string
  status: string
  mode: string
  actor_name: string
  label: {
    job_id: string
    process_name: string
    width_mm: number
    length_mm: number
    copies: number
  }
}
const route = useRoute(),
  auth = useAuthStore(),
  w = useWorkspaceStore()
const offer = ref<Offer>(),
  estimate = ref<Estimate>(),
  error = ref(''),
  currency = ref(''),
  maximum = ref(''),
  loading = ref(false)
let generation = 0
async function load() {
  const ticket = ++generation
  loading.value = true
  error.value = ''
  estimate.value = undefined
  try {
    const value = await api<Offer>(`/retries/${route.params.id}`)
    if (ticket !== generation) return
    offer.value = value
    if (value.status === 'pending') {
      const quote = await api<Estimate>(`/retries/${value.id}/quote`, 'POST', {})
      if (ticket !== generation) return
      estimate.value = quote
      currency.value = quote.quotes[0]?.currency ?? ''
      maximum.value = quote.quotes[0]?.maximum ?? ''
    }
  } catch (cause) {
    if (ticket === generation) error.value = errorMessage(cause)
  } finally {
    if (ticket === generation) loading.value = false
  }
}
watch(
  () => [route.params.id, auth.user?.id],
  () => {
    offer.value = undefined
    void load()
  },
  { immediate: true },
)
onUnmounted(() => {
  generation++
})
watch(currency, (value) => {
  maximum.value = estimate.value?.quotes.find((quote) => quote.currency === value)?.maximum ?? ''
})
const canAccept = computed(
  () =>
    estimate.value?.quote_id &&
    currency.value &&
    maximum.value !== '' &&
    Number(maximum.value) >= 0,
)
async function act(action: 'accept' | 'decline') {
  if (!offer.value) return
  if (
    await w.action(
      () =>
        api(
          `/retries/${offer.value!.id}/${action}`,
          'POST',
          action === 'accept'
            ? {
                quote_id: estimate.value!.quote_id,
                maximum_price: {
                  currency: currency.value,
                  micros: Math.round(Number(maximum.value) * 1000000),
                },
              }
            : {},
        ),
      action === 'accept' ? 'Retry queued. Printer holds remain in place.' : 'Retry declined.',
    )
  )
    await load()
}
</script>
<template>
  <section class="panel form-stack">
    <h2>Retry approval</h2>
    <Transition name="notice"
      ><p v-if="error" role="alert" class="alert danger">{{ error }}</p></Transition
    >
    <template v-if="offer">
      <strong
        >{{ offer.label.process_name }} · {{ offer.label.copies }}
        {{ offer.label.copies === 1 ? 'copy' : 'copies' }}</strong
      >
      <JobPreview
        :job-id="offer.label.job_id"
        :text="offer.label.process_name"
        :width-mm="offer.label.width_mm"
        :length-mm="offer.label.length_mm"
      />
      <p v-if="offer.status !== 'pending'" role="status">
        {{ offer.status === 'queued' ? 'Retry queued.' : 'Retry declined.' }}
      </p>
      <ExpandableContent :open="offer.status === 'pending'">
        <div class="form-stack">
          <CostEstimate v-if="estimate" :estimate="estimate" />
          <p>
            Your previous charges remain unchanged. Accepting adds a new paid attempt. Your maximum
            includes all copies and overhead; unexpected excess is covered by the cartridge owner.
          </p>
          <div v-if="estimate?.quotes.length" class="field-row">
            <label
              >Currency<select v-model="currency">
                <option
                  v-for="quote in estimate.quotes"
                  :key="quote.currency"
                  :value="quote.currency"
                >
                  {{ quote.currency }}
                </option>
              </select></label
            >
            <label
              >Maximum total<input v-model="maximum" type="number" min="0" step="0.000001"
            /></label>
          </div>
          <div class="row wrap">
            <button :disabled="loading || w.busy || !canAccept" @click="act('accept')">
              Accept paid retry
            </button>
            <button class="secondary" :disabled="loading || w.busy" @click="load">
              Refresh quote
            </button>
            <button class="secondary" :disabled="w.busy" @click="act('decline')">Decline</button>
          </div>
        </div>
      </ExpandableContent>
    </template>
  </section>
</template>
