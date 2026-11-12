<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { api, errorMessage } from '../shared/api'
import { confirmAction } from '../shared/confirmation'
import { resetFormValidation, vValidateForm } from '../shared/formValidation'
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
const pinForm = ref<HTMLFormElement | null>(null)
let disposed = false
function clear() {
  password.value = ''
  pin.value = ''
  confirmation.value = ''
  resetFormValidation(pinForm.value)
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
  if (!editing.value) resetFormValidation(pinForm.value)
  editing.value = !editing.value
  error.value = ''
  success.value = ''
}
</script>

<template>
  <h2>{{ $t('common.companionPin') }}</h2>
  <p v-if="error" class="alert danger" role="alert">{{ error }}</p>
  <p v-if="success" class="alert success" role="status">{{ success }}</p>
  <button
    v-if="configured !== null"
    type="button"
    class="secondary"
    :aria-expanded="editing"
    :disabled="busy"
    @click="toggleEditing"
  >
    {{ editing ? $t('common.cancel') : configured ? 'Change PIN' : 'Set PIN' }}
  </button>
  <ExpandableContent :open="editing" @closed="clear">
    <form ref="pinForm" v-validate-form class="form-stack pin-form" @submit.prevent="save()">
      <p class="muted">
        {{ $t('common.useThisPinAtCompanionsYouCanAccessChanging') }}
      </p>
      <label
        >{{ $t('common.currentPassword')
        }}<input
          ref="passwordInput"
          v-model="password"
          type="password"
          autocomplete="current-password"
          required
          maxlength="256"
          :disabled="busy"
      /></label>
      <label
        >{{ $t('accountPin.newPin')
        }}<input
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
        >{{ $t('accountPin.confirmPin')
        }}<input
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
      <div class="row wrap">
        <button type="submit" class="primary" :disabled="busy">
          {{ $t('accountPin.savePin') }}</button
        ><button
          v-if="configured"
          type="button"
          class="danger"
          :disabled="busy"
          @click="save(true)"
        >
          {{ $t('accountPin.removePin') }}
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
