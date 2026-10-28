<script setup lang="ts">
import { ref } from 'vue'
import type { Cartridge } from '../types'
import { api } from '../api'
import { useWorkspaceStore } from '../workspace'
import { vValidateForm } from '../formValidation'
import AnimatedDetails from './AnimatedDetails.vue'
const props = defineProps<{ cartridge: Cartridge }>()
const w = useWorkspaceStore()
const price = ref('')
const currency = ref('EUR')
function opened(open: boolean) {
  if (!open) return
  price.value =
    props.cartridge.price_minor === null ? '' : (props.cartridge.price_minor / 100).toFixed(2)
  currency.value = props.cartridge.currency
}
async function save() {
  await w.action(
    () =>
      api(`/cartridges/${props.cartridge.id}/price`, 'PUT', {
        price_minor: price.value === '' ? null : Math.round(Number(price.value) * 100),
        currency: currency.value,
      }),
    'Cartridge price updated.',
  )
}
</script>
<template>
  <AnimatedDetails class="cartridge-price" @toggle="opened">
    <template #summary
      >Price:
      {{
        cartridge.price_minor === null
          ? 'Not set'
          : `${(cartridge.price_minor / 100).toFixed(2)} ${cartridge.currency}`
      }}</template
    >
    <form v-validate-form class="form-stack inset" @submit.prevent="save">
      <div class="field-row">
        <label
          >Cartridge price<input v-model="price" type="number" min="0" max="10000000" step="0.01"
        /></label>
        <label
          >Currency<input v-model="currency" required pattern="[A-Z]{3}" maxlength="3"
        /></label>
      </div>
      <p class="help">Applies to future print attempts.</p>
      <button class="secondary" :disabled="w.busy || cartridge.estimate_locked">Save price</button>
    </form>
  </AnimatedDetails>
</template>
