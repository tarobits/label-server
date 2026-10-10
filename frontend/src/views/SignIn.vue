<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { api, errorMessage } from '../api'
import { auth, type Session } from '../auth'
const registering = ref(false)
const setup = computed(() => auth.session.value?.setup_required)
const form = reactive({ username: '', password: '', registration_code: '', setup_token: '' })
const busy = ref(false),
  error = ref('')
function switchForm() {
  registering.value = !registering.value
  error.value = ''
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
    <form class="panel form-stack auth-card" @submit.prevent="submit">
      <div class="nav-label">LABEL ROOM</div>
      <h1>
        {{ setup ? 'Make yourself at home' : registering ? 'Create your account' : 'Welcome back' }}
      </h1>
      <p class="muted">
        {{
          setup
            ? 'Create the first administrator account to set up your label workspace.'
            : registering
              ? 'Your labels, templates, and print requests in one place.'
              : 'Sign in to your label workspace.'
        }}
      </p>
      <div v-if="error" class="alert danger" role="alert">{{ error }}</div>
      <label v-if="setup"
        >Setup token<input v-model="form.setup_token" autocomplete="off" required />
        <span class="help"
          >Use the token from the server’s startup logs or <code>auth-setup-token</code> in its data
          directory. This verifies that you own the server.</span
        >
      </label>
      <label
        >Username<input
          v-model="form.username"
          autocomplete="username"
          required
          maxlength="64"
          :minlength="setup || registering ? 3 : undefined"
          :pattern="setup || registering ? '[A-Za-z0-9_.-]+' : undefined"
      /></label>
      <p v-if="setup || registering" class="help">
        Use at least 3 letters, numbers, dots, underscores, or hyphens.
      </p>
      <label
        >Password<input
          v-model="form.password"
          type="password"
          :autocomplete="setup || registering ? 'new-password' : 'current-password'"
          :minlength="setup || registering ? 12 : undefined"
          required
      /></label>
      <label v-if="registering"
        >Registration code{{ auth.session.value?.registration_code_required ? '' : ' (optional)'
        }}<input
          v-model="form.registration_code"
          autocomplete="off"
          :required="auth.session.value?.registration_code_required"
        /><span class="help">Ask your administrator for a registration code.</span></label
      >
      <p v-if="registering" class="help">New accounts send labels for approval before printing.</p>
      <button class="primary" :disabled="busy">
        {{
          busy
            ? 'Please wait…'
            : setup
              ? 'Create administrator'
              : registering
                ? 'Create account'
                : 'Sign in'
        }}
      </button>
      <button v-if="!setup" type="button" class="secondary" :disabled="busy" @click="switchForm">
        {{ registering ? 'Back to sign in' : 'Create an account' }}
      </button>
    </form>
  </main>
</template>
<style scoped>
.auth-shell {
  min-height: 100dvh;
  display: grid;
  place-items: center;
  padding: 24px;
}
.auth-card {
  width: min(100%, 480px);
}
h1 {
  font-size: 28px;
}
</style>
