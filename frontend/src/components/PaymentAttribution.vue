<script setup lang="ts">
import { computed } from 'vue'
import type { Payer } from '../shared/types'
const props = defineProps<{ payers?: Payer[] }>()
const unique = computed(() => [
  ...new Map((props.payers ?? []).map((payer) => [JSON.stringify(payer), payer])).values(),
])
</script>

<template>
  <div v-if="unique.length" class="payment-attribution">
    <small v-for="payer in unique" :key="`${payer.kind}:${payer.id}:${payer.note ?? ''}`">
      {{ $t('paymentAttribution.payer') }} {{ payer.name }} ({{
        payer.kind === 'group' ? 'group account' : 'user'
      }})<span v-if="payer.note"> · {{ payer.note }}</span>
    </small>
  </div>
</template>

<style scoped>
.payment-attribution {
  color: var(--text-secondary);
  overflow-wrap: anywhere;
}
.payment-attribution small {
  display: block;
  margin-top: 4px;
}
</style>
