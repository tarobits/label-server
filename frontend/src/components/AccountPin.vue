<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { api, errorMessage } from '../api'
import { confirmAction } from '../confirmation'
import { vValidateForm } from '../formValidation'
import ExpandableContent from './ExpandableContent.vue'

const configured = ref<boolean | null>(null)
const editing = ref(false),
  busy = ref(false),
  error = ref(''),
  success = ref('')
const password = ref(''),
  pin = ref(''),
  confirmation = ref('')
const passwordInput = ref<HTMLInputElement | null>(null)
let disposed = false
function clear() {
  password.value = ''
  pin.value = ''
  confirmation.value = ''
}
onBeforeUnmount(() => {
  disposed = true
  clear()
})
onMounted(async () => {
  try {
    const value = await api<{ configured: boolean }>('/companions/account/pin')
    if (!disposed) configured.value = value.configured
  } catch (issue) {
    if (!disposed) error.value = errorMessage(issue)
  }
})
async function save(remove = false) {
  if (busy.value || !passwordInput.value?.reportValidity()) return
  error.value = ''
  success.value = ''
  if (!remove && pin.value !== confirmation.value) {
    error.value = 'PINs do not match.'
    return
  }
  if (
    remove &&
    !(await confirmAction(
      'Remove your companion PIN and lock your companion sessions?',
      'Remove PIN',
    ))
  )
    return
  busy.value = true
  try {
    const value = await api<{ configured: boolean }>('/companions/account/pin', 'PUT', {
      current_password: password.value,
      pin: remove ? null : pin.value,
    })
    if (disposed) return
    configured.value = value.configured
    editing.value = false
    clear()
    success.value = remove ? 'PIN removed.' : 'PIN saved.'
  } catch (issue) {
    if (!disposed) error.value = errorMessage(issue)
  } finally {
    busy.value = false
  }
}
function toggleEditing() {
  editing.value = !editing.value
  error.value = ''
  success.value = ''
}
</script>

<template>
  <h2>Companion PIN</h2>
  <p v-if="error" class="alert danger" role="alert">{{ error }}</p>
  <p v-if="success" class="alert success" role="status">{{ success }}</p>
  <button
    v-if="configured !== null"
    class="secondary"
    :aria-expanded="editing"
    :disabled="busy"
    @click="toggleEditing"
  >
    {{ editing ? 'Cancel' : configured ? 'Change PIN' : 'Set PIN' }}
  </button>
  <ExpandableContent :open="editing" @closed="clear">
    <form v-validate-form class="form-stack pin-form" @submit.prevent="save()">
      <p class="muted">
        Use this PIN at companions you can access. Changing it locks your companion sessions.
      </p>
      <label
        >Current password<input
          ref="passwordInput"
          v-model="password"
          type="password"
          autocomplete="current-password"
          required
          maxlength="256"
          :disabled="busy"
      /></label>
      <label
        >New PIN<input
          v-model="pin"
          type="password"
          inputmode="numeric"
          pattern="[0-9]{4,12}"
          autocomplete="new-password"
          minlength="4"
          maxlength="12"
          required
          :disabled="busy"
      /></label>
      <label
        >Confirm PIN<input
          v-model="confirmation"
          type="password"
          inputmode="numeric"
          pattern="[0-9]{4,12}"
          autocomplete="new-password"
          minlength="4"
          maxlength="12"
          required
          :disabled="busy"
      /></label>
      <div class="actions">
        <button class="primary" :disabled="busy">Save PIN</button
        ><button
          v-if="configured"
          type="button"
          class="danger"
          :disabled="busy"
          @click="save(true)"
        >
          Remove PIN
        </button>
      </div>
    </form>
  </ExpandableContent>
</template>

<style scoped>
.pin-form {
  max-width: 440px;
  margin-top: 24px;
}
</style>
