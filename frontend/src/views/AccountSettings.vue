<script setup lang="ts">
import { nextTick, onBeforeUnmount, reactive, ref } from 'vue'
import { api, errorMessage } from '../api'
import { motionPreference } from '../preferences'
import {
  vValidateForm,
  apiFieldErrors,
  focusFormErrors,
  resetFormValidation,
  type FieldErrors,
} from '../formValidation'

const form = reactive({ current_password: '', new_password: '', confirmation: '' })
const passwordForm = ref<HTMLFormElement | null>(null)
const errors = ref<FieldErrors>({})
const busy = ref(false),
  error = ref(''),
  success = ref('')
let disposed = false
onBeforeUnmount(() => {
  disposed = true
  Object.assign(form, { current_password: '', new_password: '', confirmation: '' })
})
function clearField(event: Event) {
  const field = (event.target as HTMLInputElement).name
  const next = { ...errors.value }
  delete next[field]
  if (field === 'new_password') delete next.confirmation
  errors.value = next
  success.value = ''
}
async function savePassword() {
  if (busy.value) return
  errors.value = {}
  error.value = ''
  success.value = ''
  if (form.new_password !== form.confirmation) {
    errors.value = { confirmation: 'Passwords do not match.' }
    await nextTick()
    focusFormErrors(passwordForm.value)
    return
  }
  busy.value = true
  try {
    await api('/auth/password', 'POST', {
      current_password: form.current_password,
      new_password: form.new_password,
    })
    if (disposed) return
    Object.assign(form, { current_password: '', new_password: '', confirmation: '' })
    resetFormValidation(passwordForm.value)
    success.value = 'Password changed. Other sessions signed out.'
  } catch (issue) {
    if (disposed) return
    const fields = apiFieldErrors(issue)
    if (Object.keys(fields).length) {
      errors.value = fields
      await nextTick()
      focusFormErrors(passwordForm.value)
    } else error.value = errorMessage(issue)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="account-settings panel">
    <section class="settings-section" aria-labelledby="preferences-heading">
      <h2 id="preferences-heading">Preferences</h2>
      <div class="settings-preferences">
        <label>
          <span class="language-label">Language <small>Coming soon</small></span>
          <select aria-label="Language" disabled>
            <option value="browser">Browser</option>
          </select>
        </label>
        <label
          >Reduced motion
          <select v-model="motionPreference" aria-label="Reduced motion">
            <option value="browser">Browser</option>
            <option value="on">On</option>
            <option value="off">Off</option>
          </select>
        </label>
      </div>
    </section>
    <section class="settings-section" aria-labelledby="password-heading">
      <h2 id="password-heading">Change password</h2>
      <form
        ref="passwordForm"
        v-validate-form="errors"
        class="form-stack password-form"
        @submit.prevent="savePassword"
        @input="clearField"
      >
        <p v-if="error" class="alert danger" role="alert">{{ error }}</p>
        <p v-if="success" class="alert success" role="status">{{ success }}</p>
        <label
          >Current password<input
            v-model="form.current_password"
            name="current_password"
            type="password"
            autocomplete="current-password"
            maxlength="256"
            required
            :disabled="busy"
        /></label>
        <label
          >New password<input
            v-model="form.new_password"
            name="new_password"
            type="password"
            autocomplete="new-password"
            minlength="12"
            maxlength="256"
            required
            :disabled="busy"
        /></label>
        <label
          >Confirm new password<input
            v-model="form.confirmation"
            name="confirmation"
            type="password"
            autocomplete="new-password"
            minlength="12"
            maxlength="256"
            required
            :disabled="busy"
        /></label>
        <button class="primary" :disabled="busy" type="submit">Change password</button>
      </form>
    </section>
  </div>
</template>

<style scoped>
.account-settings {
  max-width: 850px;
}
.settings-section + .settings-section {
  border-top: 1px solid var(--line);
  margin-top: 32px;
  padding-top: 32px;
}
.settings-section h2 {
  margin-bottom: 24px;
}
.settings-preferences {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 24px;
}
.language-label {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 10px;
}
.language-label small {
  font-weight: 400;
}
.password-form {
  max-width: 440px;
}
.password-form button {
  justify-self: start;
}
@media (max-width: 600px) {
  .settings-preferences {
    grid-template-columns: 1fr;
  }
}
</style>
