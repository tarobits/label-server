<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { useAuthStore } from '../auth/auth'
import { accountLanguage, deviceLanguage, t, validPreference } from '../shared/i18n'

const props = defineProps<{ account?: boolean }>()
const auth = props.account ? useAuthStore() : null
const busy = ref(false)
const error = ref('')
let disposed = false
onBeforeUnmount(() => {
  disposed = true
})
async function change(event: Event) {
  const input = event.target as HTMLSelectElement
  const next = validPreference(input.value)
  const previous = props.account ? (accountLanguage.value ?? 'browser') : deviceLanguage.value
  error.value = ''
  if (!props.account) {
    deviceLanguage.value = next
    return
  }
  busy.value = true
  try {
    await auth?.saveLanguage(next)
  } catch {
    if (disposed) return
    input.value = previous
    error.value = t('errors.languageSave')
  } finally {
    if (!disposed) busy.value = false
  }
}
</script>

<template>
  <div class="language-picker">
    <label>
      {{ $t('account.language') }}
      <select
        :value="account ? (accountLanguage ?? 'browser') : deviceLanguage"
        :disabled="busy"
        @change="change"
      >
        <option value="browser">{{ $t('common.browser') }}</option>
        <option value="en" lang="en">English</option>
        <option value="de" lang="de">Deutsch</option>
      </select>
    </label>
    <Transition name="notice"
      ><p v-if="error" class="alert danger" role="alert">{{ error }}</p></Transition
    >
  </div>
</template>

<style scoped>
.language-picker {
  min-width: 0;
}
.language-picker label {
  display: grid;
  gap: 8px;
}
.language-picker select {
  width: 100%;
}
.language-picker .alert {
  margin-top: 12px;
}
</style>
