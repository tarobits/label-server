<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errorMessage } from '../shared/api'
import ExpandableContent from './ExpandableContent.vue'

export interface BillingSelection {
  account_id: string
  mode: 'wait' | 'risk' | 'direct'
  note?: string
}
const model = defineModel<BillingSelection | null>({ default: null })
const accounts = ref<{ id: string; name: string; archived: boolean; permissions: string[] }[]>([])
const error = ref('')
const selected = computed(() => accounts.value.find((a) => a.id === model.value?.account_id))
onMounted(async () => {
  try {
    const result = await api<{ accounts: typeof accounts.value }>('/accounts/groups')
    accounts.value = result.accounts.filter(
      (a) => !a.archived && a.permissions.some((p) => ['request', 'direct'].includes(p)),
    )
  } catch (e) {
    error.value = errorMessage(e)
  }
})
function select(event: Event) {
  const id = (event.target as HTMLSelectElement).value
  const account = accounts.value.find((a) => a.id === id)
  model.value = account
    ? { account_id: id, mode: account.permissions.includes('request') ? 'wait' : 'direct' }
    : null
}
</script>
<template>
  <ExpandableContent :open="!!accounts.length || !!error">
    <div class="billing-fields">
      <p v-if="error" class="alert danger" role="alert">{{ error }}</p>
      <label
        >{{ $t('billingPicker.payingAccount') }}
        <select :value="model?.account_id ?? ''" @change="select">
          <option value="">{{ $t('billingPicker.myPersonalAccount') }}</option>
          <option v-for="account in accounts" :key="account.id" :value="account.id">
            {{ account.name }}
          </option>
        </select>
      </label>
      <ExpandableContent :open="!!model">
        <div v-if="model" class="billing-fields">
          <label
            >{{ $t('common.funding') }}
            <select v-model="model.mode">
              <option v-if="selected?.permissions.includes('request')" value="wait">
                {{ $t('common.waitForApproval') }}
              </option>
              <option v-if="selected?.permissions.includes('request')" value="risk">
                {{ $t('billingPicker.printAtMyExpensePendingApproval') }}
              </option>
              <option v-if="selected?.permissions.includes('direct')" value="direct">
                {{ $t('billingPicker.chargeTheGroupDirectly') }}
              </option>
            </select>
          </label>
          <label
            >{{ $t('billingPicker.purposeOptional') }}<input v-model="model.note" maxlength="500"
          /></label>
          <p v-if="model.mode === 'risk'" class="muted">
            {{ $t('common.youRemainResponsibleForPaymentUnlessTheGroupApproves') }}
          </p>
        </div>
      </ExpandableContent>
    </div>
  </ExpandableContent>
</template>
<style scoped>
.billing-fields {
  display: grid;
  gap: 16px;
}
.billing-fields p {
  margin: 0;
}
</style>
