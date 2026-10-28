<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { api, errorMessage } from '../api'
import { resetFormValidation, vValidateForm } from '../formValidation'
import { randomUUID } from '../uuid'
import type { UsageAdjustment, UsageUser } from '../types'

const props = defineProps<{ users: UsageUser[]; userId: string }>()
const emit = defineEmits<{ saved: [] }>()
const form = reactive({
  userId: props.userId,
  direction: 'add',
  amount: '',
  currency: 'EUR',
  note: '',
})
const busy = ref(false)
const formElement = ref<HTMLFormElement | null>(null)
const error = ref('')
const saved = ref('')
let signature = '',
  requestId = ''
const canSave = computed(() => !!form.userId && Number(form.amount) > 0 && !!form.note.trim())
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
  if (busy.value || !canSave.value) return
  busy.value = true
  error.value = ''
  saved.value = ''
  const body = {
    user_id: form.userId,
    amount_minor: Math.round(Number(form.amount) * 100) * (form.direction === 'add' ? 1 : -1),
    currency: form.currency,
    note: form.note.trim(),
  }
  if (signature !== JSON.stringify(body)) {
    signature = JSON.stringify(body)
    requestId = randomUUID()
  }
  try {
    const result = await api<UsageAdjustment>('/usage/adjustments', 'POST', {
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
      <div class="row">
        <button class="primary" :disabled="!canSave">
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
