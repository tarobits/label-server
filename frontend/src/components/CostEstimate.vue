<script setup lang="ts">
import { computed } from 'vue'
import type { CostEstimate } from '../types'
const props = defineProps<{ estimate?: CostEstimate | null; pending?: boolean }>()
function amount(value: string, currency: string) {
  const format = new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
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
      return 'No price set for this tape.'
    case 'cartridge':
      return 'No matching cartridge registered.'
    default:
      return 'No available print destination.'
  }
})
</script>
<template>
  <Transition name="notice">
    <div v-if="estimate || pending" class="cost-estimate" role="status" aria-label="Estimated cost">
      <span v-if="pending" class="muted">Estimating cost…</span>
      <template v-else-if="prices">
        <span
          >Approx. cost (one batch): <strong>{{ prices }}</strong></span
        >
        <small v-if="estimate?.incomplete">Some matching cartridges have no price.</small>
        <small v-if="estimate?.basis === 'inventory'">Based on registered cartridges.</small>
      </template>
      <span v-else class="muted">Cost unavailable · {{ missing }}</span>
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
