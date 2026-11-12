<script setup lang="ts">
import SourceLink from '../components/SourceLink.vue'
import { vValidateForm } from '../shared/formValidation'
import { computed, nextTick, reactive, ref } from 'vue'
import { api, errorMessage } from '../shared/api'
import { useAuthStore, type Session } from '../auth/auth'
import BrandLogo from '../components/BrandLogo.vue'
import LanguagePicker from '../components/LanguagePicker.vue'
const auth = useAuthStore()
const registering = ref(false)
const setup = computed(() => auth.session?.setup_required)
const form = reactive({ username: '', password: '', registration_code: '', setup_token: '' })
const busy = ref(false),
  error = ref('')
const usernameInput = ref<HTMLInputElement | null>(null)
async function switchForm() {
  registering.value = !registering.value
  error.value = ''
  await nextTick()
  usernameInput.value?.focus()
}
async function submit() {
  busy.value = true
  error.value = ''
  try {
    const path = setup.value ? 'setup' : registering.value ? 'register' : 'login'
    const body = {
      username: form.username,
      password: form.password,
      ...(setup.value ? { setup_token: form.setup_token } : {}),
      ...(registering.value ? { registration_code: form.registration_code || undefined } : {}),
    }
    auth.accept(await api<Session>(`/auth/${path}`, 'POST', body))
    form.password = ''
    form.setup_token = ''
    form.registration_code = ''
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}
</script>
<template>
  <main class="auth-shell">
    <div class="auth-layout">
      <BrandLogo class="auth-brand" />
      <LanguagePicker />
      <form
        :key="setup ? 'setup' : registering ? 'register' : 'login'"
        v-validate-form
        class="panel form-stack auth-card"
        @submit.prevent="submit"
      >
        <h1>
          {{
            setup
              ? $t('common.createAdministrator')
              : registering
                ? $t('groupAccounts.createAccount')
                : $t('common.signIn')
          }}
        </h1>
        <div v-if="error" class="alert danger" role="alert">{{ error }}</div>
        <label v-if="setup"
          >{{ $t('common.setupToken')
          }}<input v-model="form.setup_token" autocomplete="off" required />
          <span class="help"
            >{{ $t('common.useTheTokenFromTheServerSStartupLogs') }} <code>auth-setup-token</code>
            {{ $t('common.inItsDataDirectory') }}</span
          >
        </label>
        <label
          >{{ setup || registering ? $t('common.username') : $t('common.usernameOrEmail')
          }}<input
            ref="usernameInput"
            v-model="form.username"
            autocomplete="username"
            required
            :maxlength="setup || registering ? 64 : 254"
            autocapitalize="none"
            :spellcheck="false"
            :minlength="setup || registering ? 3 : undefined"
            :pattern="setup || registering ? '[A-Za-z0-9_.-]+' : undefined"
        /></label>
        <p v-if="setup || registering" class="help">
          {{ $t('common.useAtLeast3LettersNumbersDotsUnderscoresOr') }}
        </p>
        <label
          >{{ $t('signIn.password')
          }}<input
            v-model="form.password"
            type="password"
            :autocomplete="setup || registering ? 'new-password' : 'current-password'"
            :minlength="setup || registering ? 12 : undefined"
            required
        /></label>
        <label v-if="registering"
          >{{ $t('signIn.registrationCode')
          }}{{ auth.session?.registration_code_required ? '' : $t('common.optional')
          }}<input
            v-model="form.registration_code"
            autocomplete="off"
            :required="auth.session?.registration_code_required"
          /><span class="help">{{
            $t('signIn.askYourAdministratorForARegistrationCode')
          }}</span></label
        >
        <button class="primary" :disabled="busy">
          {{
            busy
              ? $t('common.pleaseWait')
              : setup
                ? $t('common.createAdministrator')
                : registering
                  ? $t('groupAccounts.createAccount')
                  : $t('common.signIn')
          }}
        </button>
        <button v-if="!setup" type="button" class="secondary" :disabled="busy" @click="switchForm">
          {{ registering ? $t('common.backToSignIn') : $t('administration.createAnAccount') }}
        </button>
        <RouterLink v-if="!setup && !registering" to="/forgot-password">{{
          $t('signIn.forgotPassword')
        }}</RouterLink>
      </form>
      <SourceLink />
    </div>
  </main>
</template>
<style scoped>
.auth-shell {
  min-height: 100dvh;
  display: grid;
  place-items: center;
  padding: 24px;
}
.auth-layout {
  width: min(100%, 440px);
  display: grid;
  gap: 28px;
}
.auth-brand {
  justify-content: center;
  padding: 0;
}
.auth-brand :deep(.brand-icon) {
  width: 48px;
  height: 48px;
  background: var(--accent);
}
.auth-card {
  margin-bottom: 0;
}
.auth-card > button {
  align-self: stretch;
}
h1 {
  font-size: 28px;
}
</style>
