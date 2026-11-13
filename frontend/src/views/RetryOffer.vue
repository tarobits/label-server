<script setup lang="ts">
import { t } from '../shared/i18n'
import { computed, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, errorMessage } from '../shared/api'
import { useAuthStore } from '../auth/auth'
import { useWorkspaceStore } from '../shared/workspace'
import CostEstimate from '../components/CostEstimate.vue'
import JobPreview from '../components/JobPreview.vue'
import ExpandableContent from '../components/ExpandableContent.vue'
import type { CostEstimate as Estimate } from '../shared/types'
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
      action === 'accept'
        ? t('uiMessages.retryQueuedPrinterHoldsRemainInPlace')
        : t('uiMessages.retryDeclined'),
    )
  )
    await load()
}
</script>
<template>
  <section class="panel form-stack">
    <h2>{{ $t('retryOffer.retryApproval') }}</h2>
    <Transition name="notice"
      ><p v-if="error" role="alert" class="alert danger">{{ error }}</p></Transition
    >
    <template v-if="offer">
      <strong
        >{{ offer.label.process_name }} · {{ offer.label.copies }}
        {{ offer.label.copies === 1 ? 'copy' : $t('common.copies2') }}</strong
      >
      <JobPreview
        :job-id="offer.label.job_id"
        :text="offer.label.process_name"
        :width-mm="offer.label.width_mm"
        :length-mm="offer.label.length_mm"
      />
      <p v-if="offer.status !== 'pending'" role="status">
        {{
          offer.status === 'queued' ? $t('uiMessages.retryQueued') : $t('uiMessages.retryDeclined')
        }}
      </p>
      <ExpandableContent :open="offer.status === 'pending'">
        <div class="form-stack">
          <CostEstimate v-if="estimate" :estimate="estimate" />
          <p>
            {{ $t('common.yourPreviousChargesRemainUnchangedAcceptingAddsANew') }}
          </p>
          <div v-if="estimate?.quotes.length" class="field-row">
            <label
              >{{ $t('common.currency')
              }}<select v-model="currency">
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
              >{{ $t('retryOffer.maximumTotal')
              }}<input v-model="maximum" type="number" min="0" step="0.000001"
            /></label>
          </div>
          <div class="row wrap">
            <button :disabled="loading || w.busy || !canAccept" @click="act('accept')">
              {{ $t('retryOffer.acceptPaidRetry') }}
            </button>
            <button class="secondary" :disabled="loading || w.busy" @click="load">
              {{ $t('common.refreshQuote') }}
            </button>
            <button class="secondary" :disabled="w.busy" @click="act('decline')">
              {{ $t('common.decline') }}
            </button>
          </div>
        </div>
      </ExpandableContent>
    </template>
  </section>
</template>
