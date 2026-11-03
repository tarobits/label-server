<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, ApiError, errorMessage } from '../api'
import { useAuthStore } from '../auth'
import { vValidateForm, apiFieldErrors, focusFormErrors, type FieldErrors } from '../formValidation'
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
    ? 'Verify email'
    : mode.value === 'reset'
      ? 'Reset password'
      : 'Forgot password?',
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
    fields.value = { confirmation: 'Passwords do not match.' }
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
      success.value = 'Email verified.'
      token.value = ''
    } else {
      await api('/auth/password/reset', 'POST', {
        token: token.value,
        new_password: password.value,
      })
      token.value = ''
      password.value = ''
      confirmation.value = ''
      success.value = 'Password reset. Sign in with your new password.'
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
              >Username<input
                v-model="username"
                name="username"
                autocomplete="username"
                required
                maxlength="64"
                :disabled="busy"
            /></label>
            <template v-if="mode === 'reset'">
              <label
                >New password<input
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
                >Confirm new password<input
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
              This link is missing its verification token. Open the link from your email again.
            </p>
            <button class="primary" :disabled="busy || (mode !== 'forgot' && !token)">
              {{
                mode === 'forgot'
                  ? 'Send reset link'
                  : mode === 'verify'
                    ? 'Verify email'
                    : 'Reset password'
              }}
            </button>
          </template>
          <RouterLink v-if="mode === 'reset' && invalidLink" to="/forgot-password"
            >Request a new reset link</RouterLink
          >
          <RouterLink :to="auth.user ? '/account' : '/'" class="button">{{
            auth.user ? 'Account settings' : 'Back to sign in'
          }}</RouterLink>
        </form>
      </MotionSurface>
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
