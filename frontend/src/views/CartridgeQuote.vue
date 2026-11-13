<script setup lang="ts">
import { t } from '../shared/i18n'
import { computed, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, errorMessage } from '../shared/api'
import { useAuthStore } from '../auth/auth'
import { useWorkspaceStore } from '../shared/workspace'
import JobPreview from '../components/JobPreview.vue'
import ExpandableContent from '../components/ExpandableContent.vue'
import { vValidateForm } from '../shared/formValidation'

interface Offer {
  id: string
  status: 'pending' | 'accepted' | 'declined'
  unavailable: string | null
  label: { job_id: string; process_name: string; width_mm: number; length_mm: number }
  quote: {
    quote_hash: string
    copies: number
    currency: string
    maximum: string
    amount_micros: number
  } | null
}
const route = useRoute(),
  auth = useAuthStore(),
  w = useWorkspaceStore()
const offer = ref<Offer>(),
  maximum = ref(''),
  error = ref(''),
  loading = ref(false)
let generation = 0
async function load() {
  const ticket = ++generation
  loading.value = true
  error.value = ''
  try {
    const value = await api<Offer>(`/cartridge-quotes/${route.params.id}`)
    if (ticket !== generation) return
    offer.value = value
    maximum.value = value.quote?.maximum ?? ''
  } catch (issue) {
    if (ticket === generation) error.value = errorMessage(issue)
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
const valid = computed(
  () =>
    maximum.value !== '' &&
    Number(maximum.value) >= 0 &&
    Number(maximum.value) <= Number(offer.value?.quote?.maximum),
)
async function act(action: 'accept' | 'decline') {
  if (!offer.value) return
  const quote = offer.value.quote
  if (
    await w.action(
      () =>
        api(
          `/cartridge-quotes/${offer.value!.id}/${action}`,
          'POST',
          action === 'accept'
            ? {
                quote_hash: quote!.quote_hash,
                maximum_price: {
                  currency: quote!.currency,
                  micros: Math.round(Number(maximum.value) * 1000000),
                },
              }
            : {},
        ),
      action === 'accept'
        ? t('uiMessages.priceAcceptedTheOperatorCanNowApproveCartridgeUse')
        : t('uiMessages.priceDeclinedYourLabelsRemainQueued'),
    )
  )
    await load()
}
</script>

<template>
  <section class="panel form-stack">
    <Transition name="notice"
      ><p v-if="error" role="alert" class="alert danger">{{ error }}</p></Transition
    >
    <template v-if="offer">
      <h2>{{ offer.label.process_name }}</h2>
      <JobPreview
        :job-id="offer.label.job_id"
        :text="offer.label.process_name"
        :width-mm="offer.label.width_mm"
        :length-mm="offer.label.length_mm"
      />
      <p v-if="offer.status !== 'pending'" role="status">
        {{
          offer.status === 'accepted'
            ? $t('uiMessages.priceAccepted')
            : $t('uiMessages.priceDeclined')
        }}
      </p>
      <ExpandableContent :open="offer.status === 'pending'">
        <form v-validate-form class="form-stack" @submit.prevent="act('accept')">
          <p v-if="offer.unavailable" class="alert warning" role="status">
            {{ offer.unavailable }}
          </p>
          <template v-if="offer.quote">
            <p>
              {{ offer.quote.copies }} {{ $t('common.remaining') }}
              {{ offer.quote.copies === 1 ? 'copy' : $t('common.copies2') }}
              {{ $t('common.upTo2') }} {{ offer.quote.maximum }}
              {{ offer.quote.currency }}
            </p>
            <p>
              {{ $t('common.thisSetsANewMaximumForTheRemainingCopies') }}
            </p>
            <label
              >{{ $t('cartridgeQuote.maximumTotal') }}{{ offer.quote.currency }})<input
                v-model="maximum"
                type="number"
                min="0"
                :max="offer.quote.maximum"
                step="0.000001"
                required
                :disabled="w.busy || loading"
            /></label>
          </template>
          <div class="row wrap">
            <button class="primary" :disabled="w.busy || loading || !offer.quote || !valid">
              {{ $t('cartridgeQuote.acceptPrice') }}
            </button>
            <button type="button" class="secondary" :disabled="w.busy || loading" @click="load">
              {{ $t('common.refreshQuote') }}
            </button>
            <button
              type="button"
              class="secondary"
              :disabled="w.busy || loading"
              @click="act('decline')"
            >
              {{ $t('common.decline') }}
            </button>
          </div>
        </form>
      </ExpandableContent>
    </template>
    <button v-else-if="error" class="secondary" :disabled="loading" @click="load">
      {{ $t('common.retry') }}
    </button>
  </section>
</template>
