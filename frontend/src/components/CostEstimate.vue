<script setup lang="ts">
import { t, locale } from '../shared/i18n'

import { computed } from 'vue'
import type { CostEstimate } from '../shared/types'
const props = defineProps<{ estimate?: CostEstimate | null; pending?: boolean }>()
function amount(value: string, currency: string) {
  const format = new Intl.NumberFormat(locale.value, {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 6,
  })
  const number = Number(value)
  return number > 0 && number < 0.01 ? `< ${format.format(0.01)}` : format.format(number)
}
const prices = computed(() =>
  (props.estimate?.quotes ?? [])
    .map((quote) => {
      const low = amount(quote.minimum, quote.currency),
        high = amount(quote.maximum, quote.currency)
      return low === high ? low : `${low}–${high}`
    })
    .join(' / '),
)
const missing = computed(() => {
  switch (props.estimate?.reason) {
    case 'price':
      return t('uiMessages.noPriceSetForThisTape')
    case 'cartridge':
      return t('uiMessages.noMatchingCartridgeRegistered')
    default:
      return t('uiMessages.noAvailablePrintDestination')
  }
})
</script>
<template>
  <Transition name="notice">
    <div
      v-if="estimate || pending"
      class="cost-estimate"
      role="status"
      :aria-label="$t('costEstimate.estimatedCost')"
    >
      <span v-if="pending" class="muted">{{ $t('costEstimate.estimatingCost') }}</span>
      <template v-else-if="prices">
        <span
          >{{ $t('costEstimate.approxCostOneBatch') }} <strong>{{ prices }}</strong></span
        >
        <small v-if="estimate?.incomplete">{{
          $t('common.someMatchingCartridgesHaveNoPrice')
        }}</small>
        <small v-if="estimate?.basis === 'inventory'">{{
          $t('costEstimate.basedOnRegisteredCartridges')
        }}</small>
      </template>
      <span v-else class="muted">{{ $t('costEstimate.costUnavailable') }} {{ missing }}</span>
    </div>
  </Transition>
</template>
<style scoped>
.cost-estimate {
  margin-block: 8px;
  font-size: 13px;
  white-space: normal;
  font-variant-numeric: tabular-nums;
}
small {
  display: block;
  color: var(--text-secondary);
}
</style>
