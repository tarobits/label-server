<script setup lang="ts">
import { computed, nextTick, onUnmounted, reactive, ref, watch } from 'vue'
import AnimatedDetails from './AnimatedDetails.vue'
import { api, errorMessage } from '../api'
import { resetFormValidation, vValidateForm } from '../formValidation'
import { randomUUID } from '../uuid'
import type { UsageAdjustment, UsageUser } from '../types'
import { useAuthStore } from '../auth'
const auth = useAuthStore()

const props = defineProps<{ users: UsageUser[]; userId: string }>()
const emit = defineEmits<{ saved: [] }>()
const form = reactive({
  userId: props.userId,
  recipientId: auth.user?.id ?? '',
  direction: 'add',
  amount: '',
  currency: 'EUR',
  note: '',
})
const busy = ref(false)
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
    allocationReady.value &&
    Number(form.amount) > 0 &&
    !!form.note.trim(),
)
watch(
  () => props.userId,
  (value) => {
    if (!busy.value) form.userId = value
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
    amount_minor: Math.round(Number(form.amount) * 100) * (form.direction === 'add' ? 1 : -1),
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
    const result = await api<UsageAdjustment>('/accounts/repayments', 'POST', {
      ...body,
      request_id: requestId,
    })
    resetFormValidation(formElement.value)
    form.amount = ''
    form.note = ''
    signature = ''
    // Flush form watchers before showing the saved receipt.
    await nextTick()
    saved.value = `${new Intl.NumberFormat(undefined, { style: 'currency', currency: result.currency, signDisplay: 'always' }).format(result.amount_minor / 100)} recorded for ${result.username}.`
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
        <label
          >User<select v-model="form.userId" required>
            <option disabled value="">Select a user</option>
            <option v-for="user in users" :key="user.user_id" :value="user.user_id">
              {{ user.username }}
            </option>
          </select></label
        >
        <label v-if="auth.can('usage.edit_accounts')"
          >Recipient<select v-model="form.recipientId" required>
            <option disabled value="">Choose a recipient</option>
            <option v-for="user in users" :key="user.user_id" :value="user.user_id">
              {{ user.username }}
            </option>
          </select></label
        >
        <label
          >Adjustment<select v-model="form.direction">
            <option value="add">Add credit / payment</option>
            <option value="subtract">Subtract from balance</option>
          </select></label
        >
      </div>
      <div class="field-row">
        <label
          >Amount<input
            v-model="form.amount"
            type="number"
            min="0.01"
            max="10000000"
            step="0.01"
            required
        /></label>
        <label
          >Currency<input v-model="form.currency" required pattern="[A-Z]{3}" maxlength="3"
        /></label>
      </div>
      <label>Reason<input v-model="form.note" required maxlength="500" /></label>
      <AnimatedDetails v-if="allocationRows.length">
        <template #summary>Cartridge allocations</template>
        <label v-for="row in allocationRows" :key="row.cartridge_id"
          >{{ row.cartridge_name }} · {{ row.owed }} {{ form.currency }} owed<input
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
          {{ busy ? 'Recording…' : 'Record adjustment' }}
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
