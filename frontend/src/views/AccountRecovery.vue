<script setup lang="ts">
import { t } from '../shared/i18n'

import SourceLink from '../components/SourceLink.vue'
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, ApiError, errorMessage } from '../shared/api'
import { useAuthStore } from '../auth/auth'
import {
  vValidateForm,
  apiFieldErrors,
  focusFormErrors,
  type FieldErrors,
} from '../shared/formValidation'
import BrandLogo from '../components/BrandLogo.vue'
import MotionSurface from '../components/MotionSurface.vue'

const route = useRoute(),
  router = useRouter(),
  auth = useAuthStore()
const mode = computed(() =>
  route.path === '/verify-email' ? 'verify' : route.path === '/reset-password' ? 'reset' : 'forgot',
)
const token = ref(typeof route.query.token === 'string' ? route.query.token : '')
const username = ref(''),
  password = ref(''),
  confirmation = ref('')
const busy = ref(false),
  error = ref(''),
  success = ref('')
const recoveryForm = ref<HTMLFormElement | null>(null)
const fields = ref<FieldErrors>({})
const invalidLink = ref(false)
const title = computed(() =>
  mode.value === 'verify'
    ? t('common.verifyEmail')
    : mode.value === 'reset'
      ? t('common.resetPassword')
      : t('signIn.forgotPassword'),
)
watch(
  () => route.query.token,
  (value) => {
    if (typeof value !== 'string') return
    token.value = value
    error.value = ''
    success.value = ''
    fields.value = {}
    invalidLink.value = false
    // Also handle a new email link opened while this route is already mounted.
    void router.replace({ path: route.path })
  },
  { immediate: true },
)
onBeforeUnmount(() => {
  token.value = ''
  password.value = ''
  confirmation.value = ''
})
async function submit() {
  if (busy.value) return
  error.value = ''
  fields.value = {}
  invalidLink.value = false
  if (mode.value === 'reset' && password.value !== confirmation.value) {
    fields.value = { confirmation: t('common.passwordsDoNotMatch') }
    await nextTick()
    focusFormErrors(recoveryForm.value)
    return
  }
  busy.value = true
  try {
    if (mode.value === 'forgot') {
      const result = await api<{ message: string }>('/auth/password/forgot', 'POST', {
        username: username.value,
      })
      success.value = result.message
    } else if (mode.value === 'verify') {
      await api('/auth/email/verify', 'POST', { token: token.value })
      success.value = t('uiMessages.emailVerified')
      token.value = ''
    } else {
      await api('/auth/password/reset', 'POST', {
        token: token.value,
        new_password: password.value,
      })
      token.value = ''
      password.value = ''
      confirmation.value = ''
      success.value = t('uiMessages.passwordResetSignInWithYourNewPassword')
      await auth.refresh(true)
    }
  } catch (issue) {
    const errors = apiFieldErrors(issue)
    if (
      Object.keys(errors).some((name) =>
        ['username', 'new_password', 'confirmation'].includes(name),
      )
    ) {
      fields.value = errors
      await nextTick()
      focusFormErrors(recoveryForm.value)
    } else error.value = errorMessage(issue)
    invalidLink.value = issue instanceof ApiError && issue.status === 400
  } finally {
    busy.value = false
  }
}
function clearField(event: Event) {
  const name = (event.target as HTMLInputElement).name
  const next = { ...fields.value }
  delete next[name]
  if (name === 'new_password') delete next.confirmation
  fields.value = next
}
</script>

<template>
  <main class="recovery-shell">
    <div class="recovery-layout">
      <BrandLogo class="recovery-brand" />
      <MotionSurface :identity="success ? 'success' : mode" class="panel">
        <form
          ref="recoveryForm"
          v-validate-form="fields"
          class="form-stack"
          :class="{ 'verify-form': mode === 'verify' }"
          @submit.prevent="submit"
          @input="clearField"
        >
          <h1>{{ title }}</h1>
          <p v-if="error" class="alert danger" role="alert">{{ error }}</p>
          <p v-if="success" class="alert success" role="status">{{ success }}</p>
          <template v-if="!success">
            <label v-if="mode === 'forgot'"
              >{{ $t('common.username')
              }}<input
                v-model="username"
                name="username"
                autocomplete="username"
                required
                maxlength="64"
                :disabled="busy"
            /></label>
            <template v-if="mode === 'reset'">
              <label
                >{{ $t('common.newPassword')
                }}<input
                  v-model="password"
                  name="new_password"
                  type="password"
                  autocomplete="new-password"
                  required
                  minlength="12"
                  maxlength="256"
                  :disabled="busy"
              /></label>
              <label
                >{{ $t('common.confirmNewPassword')
                }}<input
                  v-model="confirmation"
                  name="confirmation"
                  type="password"
                  autocomplete="new-password"
                  required
                  minlength="12"
                  maxlength="256"
                  :disabled="busy"
              /></label>
            </template>
            <p v-if="mode !== 'forgot' && !token" class="alert warning">
              {{ $t('common.thisLinkIsMissingItsVerificationTokenOpenThe') }}
            </p>
            <button class="primary" :disabled="busy || (mode !== 'forgot' && !token)">
              {{
                mode === 'forgot'
                  ? $t('uiMessages.sendResetLink')
                  : mode === 'verify'
                    ? $t('common.verifyEmail')
                    : $t('common.resetPassword')
              }}
            </button>
          </template>
          <RouterLink v-if="mode === 'reset' && invalidLink" to="/forgot-password">{{
            $t('accountRecovery.requestANewResetLink')
          }}</RouterLink>
          <RouterLink :to="auth.user ? '/account' : '/'" class="button">{{
            auth.user ? $t('navigation.account') : $t('common.backToSignIn')
          }}</RouterLink>
        </form>
      </MotionSurface>
      <SourceLink />
    </div>
  </main>
</template>

<style scoped>
.recovery-shell {
  min-height: 100dvh;
  display: grid;
  place-items: center;
  padding: 24px;
}
.recovery-layout {
  width: min(100%, 440px);
  display: grid;
  gap: 28px;
}
.recovery-brand {
  justify-content: center;
  padding: 0;
}
.recovery-brand :deep(.brand-icon) {
  width: 48px;
  height: 48px;
  background: var(--accent);
}
.panel {
  margin-bottom: 0;
}
h1 {
  font-size: 28px;
}
.verify-form h1 {
  text-align: center;
}
.verify-form > button {
  align-self: center;
}
</style>
