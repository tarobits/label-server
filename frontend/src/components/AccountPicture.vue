<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { api, errorMessage } from '../api'
import { useAuthStore } from '../auth'
import UserAvatar from './UserAvatar.vue'
const auth = useAuthStore()
const version = ref<string | null>(null),
  busy = ref(true),
  error = ref(''),
  success = ref('')
let disposed = false
onBeforeUnmount(() => {
  disposed = true
})
onMounted(async () => {
  try {
    const result = await api<{ avatar_version: string | null }>('/auth/avatar/info')
    if (!disposed) version.value = result.avatar_version
  } catch (issue) {
    if (!disposed) error.value = errorMessage(issue)
  } finally {
    busy.value = false
  }
})
async function upload(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || busy.value) return
  error.value = ''
  success.value = ''
  if (file.size > 5_000_000) {
    error.value = 'Profile pictures are limited to 5 MB'
    return
  }
  busy.value = true
  try {
    const result = await api<{ avatar_version: string }>('/auth/avatar', 'PUT', file)
    if (!disposed) {
      version.value = result.avatar_version
      success.value = 'Profile picture saved.'
    }
  } catch (issue) {
    if (!disposed) error.value = errorMessage(issue)
  } finally {
    busy.value = false
  }
}
async function remove() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  success.value = ''
  try {
    await api('/auth/avatar', 'DELETE')
    if (!disposed) {
      version.value = null
      success.value = 'Profile picture removed.'
    }
  } catch (issue) {
    if (!disposed) error.value = errorMessage(issue)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="form-stack">
    <h2>Profile picture</h2>
    <UserAvatar
      :username="auth.user?.username ?? ''"
      :src="version ? `/api/auth/avatar?v=${version}` : null"
    />
    <label
      >Choose image<input
        type="file"
        accept="image/png,image/jpeg,image/webp"
        :disabled="busy"
        @change="upload"
    /></label>
    <p class="help">Visible to people using companions you can access.</p>
    <Transition name="notice"
      ><p v-if="error" class="alert danger" role="alert">{{ error }}</p></Transition
    >
    <Transition name="notice"
      ><p v-if="success" class="alert success" role="status">{{ success }}</p></Transition
    >
    <Transition name="notice"
      ><button
        v-if="version"
        type="button"
        class="secondary motion-reveal"
        :disabled="busy"
        @click="remove"
      >
        Remove picture
      </button></Transition
    >
  </div>
</template>
