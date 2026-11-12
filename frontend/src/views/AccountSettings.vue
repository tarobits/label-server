<script setup lang="ts">
import { t } from '../shared/i18n'

import { nextTick, onBeforeUnmount, reactive, ref } from 'vue'
import { api, errorMessage } from '../shared/api'
import { motionPreference } from '../shared/preferences'
import AccountEmail from '../components/AccountEmail.vue'
import AccountPush from '../components/AccountPush.vue'
import AccountSessions from '../components/AccountSessions.vue'
import AccountPicture from '../components/AccountPicture.vue'
import AccountPin from '../components/AccountPin.vue'
import LanguagePicker from '../components/LanguagePicker.vue'
import {
  vValidateForm,
  apiFieldErrors,
  focusFormErrors,
  resetFormValidation,
  type FieldErrors,
} from '../shared/formValidation'

const form = reactive({ current_password: '', new_password: '', confirmation: '' })
const sessionsRevision = ref(0)
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
    success.value = t('common.passwordChangedOtherSessionsSignedOut')
    sessionsRevision.value++
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
    <section class="settings-section" :aria-label="$t('common.profilePicture')">
      <AccountPicture />
    </section>
    <section class="settings-section" aria-labelledby="preferences-heading">
      <h2 id="preferences-heading">{{ $t('accountSettings.preferences') }}</h2>
      <div class="settings-preferences">
        <LanguagePicker account />
        <label
          >{{ $t('accountSettings.reducedMotion') }}
          <select v-model="motionPreference" :aria-label="$t('accountSettings.reducedMotion')">
            <option value="browser">{{ $t('common.browser') }}</option>
            <option value="on">{{ $t('accountSettings.on') }}</option>
            <option value="off">{{ $t('accountSettings.off') }}</option>
          </select>
        </label>
      </div>
    </section>
    <section class="settings-section" :aria-label="$t('accountSettings.emailSettings')">
      <AccountEmail />
    </section>
    <section class="settings-section" :aria-label="$t('common.pushNotifications')">
      <AccountPush />
    </section>
    <section class="settings-section" aria-labelledby="password-heading">
      <h2 id="password-heading">{{ $t('accountSettings.changePassword') }}</h2>
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
          >{{ $t('common.currentPassword')
          }}<input
            v-model="form.current_password"
            name="current_password"
            type="password"
            autocomplete="current-password"
            maxlength="256"
            required
            :disabled="busy"
        /></label>
        <label
          >{{ $t('common.newPassword')
          }}<input
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
          >{{ $t('common.confirmNewPassword')
          }}<input
            v-model="form.confirmation"
            name="confirmation"
            type="password"
            autocomplete="new-password"
            minlength="12"
            maxlength="256"
            required
            :disabled="busy"
        /></label>
        <button class="primary" :disabled="busy" type="submit">
          {{ $t('accountSettings.changePassword') }}
        </button>
      </form>
    </section>
    <section class="settings-section" :aria-label="$t('common.companionPin')">
      <AccountPin />
    </section>
    <section class="settings-section" :aria-label="$t('common.loggedInSessions')">
      <AccountSessions :refresh-key="sessionsRevision" />
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
