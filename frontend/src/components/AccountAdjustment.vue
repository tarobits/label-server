<script setup lang="ts">
import { locale } from '../shared/i18n'

import { computed, nextTick, onUnmounted, reactive, ref, watch } from 'vue'
import AnimatedDetails from './AnimatedDetails.vue'
import { api, errorMessage } from '../shared/api'
import { resetFormValidation, vValidateForm } from '../shared/formValidation'
import { randomUUID } from '../shared/uuid'
import type { UsageAdjustment, UsageUser } from '../shared/types'
import { useAuthStore } from '../auth/auth'
const auth = useAuthStore()

const props = defineProps<{ users: UsageUser[]; userId: string; report?: boolean }>()
const emit = defineEmits<{ saved: []; busy: [value: boolean] }>()
const form = reactive({
  userId: props.report
    ? (auth.user?.id ?? '')
    : !auth.can('usage.edit_accounts') && props.userId === auth.user?.id
      ? ''
      : props.userId,
  recipientId: props.report ? '' : (auth.user?.id ?? ''),
  direction: 'add',
  amount: '',
  currency: 'EUR',
  note: '',
})
const busy = ref(false)
const payers = computed(() =>
  auth.can('usage.edit_accounts')
    ? props.users
    : props.users.filter((user) => user.user_id !== auth.user?.id),
)
const recipients = computed(() =>
  props.report ? props.users.filter((user) => user.user_id !== auth.user?.id) : props.users,
)
watch(busy, (value) => emit('busy', value), { flush: 'sync' })
const formElement = ref<HTMLFormElement | null>(null)
const error = ref('')
const allocationRows = ref<{ cartridge_id: string; cartridge_name: string; owed: string }[]>([])
const allocations = ref<Record<string, string>>({})
const allocating = ref(false)
const allocationReady = ref(false)
const allocationEdited = ref(false)
let allocationGeneration = 0,
  allocationTimer: ReturnType<typeof setTimeout>
watch(
  () => [form.userId, form.recipientId, form.currency, form.amount, form.direction],
  () => {
    const ticket = ++allocationGeneration
    clearTimeout(allocationTimer)
    allocationRows.value = []
    allocations.value = {}
    allocating.value = false
    allocationReady.value = false
    allocationEdited.value = false
    if (props.report) return
    if (
      !form.userId ||
      !form.recipientId ||
      form.userId === form.recipientId ||
      Number(form.amount) <= 0 ||
      !/^[A-Z]{3}$/.test(form.currency)
    )
      return
    allocating.value = true
    allocationTimer = setTimeout(async () => {
      try {
        const result = await api<{
          cartridges: typeof allocationRows.value
          allocations: Record<string, number>
        }>('/accounts/repayments/preview', 'POST', {
          request_id: randomUUID(),
          user_id: form.userId,
          recipient_id: form.recipientId,
          currency: form.currency,
          amount_minor: Math.round(Number(form.amount) * 100) * (form.direction === 'add' ? 1 : -1),
          note: 'Allocation preview',
        })
        if (ticket !== allocationGeneration) return
        allocationRows.value = result.cartridges
        allocations.value = Object.fromEntries(
          result.cartridges.map((row) => [
            row.cartridge_id,
            String(Math.abs(result.allocations[row.cartridge_id] ?? 0) / 1000000),
          ]),
        )
        allocationReady.value = true
      } catch (cause) {
        if (ticket === allocationGeneration) error.value = errorMessage(cause)
      } finally {
        if (ticket === allocationGeneration) allocating.value = false
      }
    }, 200)
  },
)
onUnmounted(() => {
  allocationGeneration++
  clearTimeout(allocationTimer)
})
const saved = ref('')
let signature = '',
  requestId = ''
const canSave = computed(
  () =>
    !!form.userId &&
    !!form.recipientId &&
    form.userId !== form.recipientId &&
    (props.report || allocationReady.value) &&
    Number(form.amount) > 0 &&
    !!form.note.trim(),
)
watch(
  () => props.userId,
  (value) => {
    if (!busy.value && !props.report)
      form.userId = !auth.can('usage.edit_accounts') && value === auth.user?.id ? '' : value
  },
)
watch(form, () => {
  saved.value = ''
  error.value = ''
})

async function save() {
  if (busy.value || allocating.value || !canSave.value) return
  busy.value = true
  error.value = ''
  saved.value = ''
  const body = {
    user_id: form.userId,
    recipient_id: form.recipientId,
    amount_minor:
      Math.round(Number(form.amount) * 100) *
      (auth.can('usage.edit_accounts') && !props.report && form.direction === 'subtract' ? -1 : 1),
    currency: form.currency,
    note: form.note.trim(),
    cartridge_allocations: allocationEdited.value
      ? Object.fromEntries(
          Object.entries(allocations.value)
            .filter(([, value]) => Number(value) > 0)
            .map(([key, value]) => [
              key,
              Math.round(Number(value) * 1000000) * (form.direction === 'add' ? 1 : -1),
            ]),
        )
      : null,
  }
  if (signature !== JSON.stringify(body)) {
    signature = JSON.stringify(body)
    requestId = randomUUID()
  }
  try {
    const payload = props.report
      ? {
          recipient_id: body.recipient_id,
          amount_minor: body.amount_minor,
          currency: body.currency,
          note: body.note,
        }
      : body
    const result = await api<UsageAdjustment>(
      props.report ? '/accounts/payment-reports' : '/accounts/repayments',
      'POST',
      {
        ...payload,
        request_id: requestId,
      },
    )
    resetFormValidation(formElement.value)
    form.amount = ''
    form.note = ''
    signature = ''
    // Flush form watchers before showing the saved receipt.
    await nextTick()
    saved.value = props.report
      ? 'Payment reported. Awaiting confirmation; your balance has not changed.'
      : `${new Intl.NumberFormat(locale.value, { style: 'currency', currency: result.currency, signDisplay: 'always' }).format(result.amount_minor / 100)} recorded for ${result.username}.`
    emit('saved')
  } catch (cause) {
    error.value = errorMessage(cause)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <form ref="formElement" v-validate-form class="form-stack inset" @submit.prevent="save">
    <fieldset :disabled="busy" class="adjustment-fields form-stack">
      <div class="field-row">
        <label v-if="!report"
          >{{ $t('common.user')
          }}<select v-model="form.userId" required>
            <option disabled value="">{{ $t('common.selectAUser') }}</option>
            <option v-for="user in payers" :key="user.user_id" :value="user.user_id">
              {{ user.username }}
            </option>
          </select></label
        >
        <label v-if="report || auth.can('usage.edit_accounts')"
          >{{ $t('common.recipient')
          }}<select v-model="form.recipientId" required>
            <option disabled value="">{{ $t('common.chooseARecipient') }}</option>
            <option v-for="user in recipients" :key="user.user_id" :value="user.user_id">
              {{ user.username }}
            </option>
          </select></label
        >
        <label v-else
          >{{ $t('common.recipient') }}<input :value="auth.user?.username" readonly
        /></label>
        <label v-if="!report && auth.can('usage.edit_accounts')"
          >{{ $t('accountAdjustment.adjustment')
          }}<select v-model="form.direction">
            <option value="add">{{ $t('accountAdjustment.addCreditPayment') }}</option>
            <option value="subtract">{{ $t('common.subtractFromBalance') }}</option>
          </select></label
        >
      </div>
      <div class="field-row">
        <label
          >{{ $t('common.amount')
          }}<input
            v-model="form.amount"
            type="number"
            min="0.01"
            max="10000000"
            step="0.01"
            required
        /></label>
        <label
          >{{ $t('common.currency')
          }}<input v-model="form.currency" required pattern="[A-Z]{3}" maxlength="3"
        /></label>
      </div>
      <label>{{ $t('common.reason') }}<input v-model="form.note" required maxlength="500" /></label>
      <AnimatedDetails v-if="allocationRows.length">
        <template #summary>{{ $t('accountAdjustment.cartridgeAllocations') }}</template>
        <label v-for="row in allocationRows" :key="row.cartridge_id"
          >{{ row.cartridge_name }} · {{ row.owed }} {{ form.currency }} {{ $t('common.owed2')
          }}<input
            v-model="allocations[row.cartridge_id]"
            @input="allocationEdited = true"
            type="number"
            min="0"
            step="0.000001"
            :aria-label="`Payment toward ${row.cartridge_name}`"
        /></label>
      </AnimatedDetails>
      <div class="row">
        <button class="primary" :disabled="!canSave || allocating">
          {{
            busy
              ? 'Recording…'
              : report
                ? 'Report payment'
                : auth.can('usage.edit_accounts')
                  ? 'Record adjustment'
                  : 'Confirm received payment'
          }}
        </button>
      </div>
    </fieldset>
    <Transition name="notice"
      ><p v-if="error" class="alert danger" role="alert">{{ error }}</p></Transition
    >
    <Transition name="notice"
      ><p v-if="saved" class="alert success" role="status">{{ saved }}</p></Transition
    >
  </form>
</template>

<style scoped>
.adjustment-fields {
  border: 0;
  padding: 0;
  margin: 0;
  min-width: 0;
}
</style>
