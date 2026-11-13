<script setup lang="ts">
import { t } from '../shared/i18n'
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { api, errorMessage } from '../shared/api'
import { useAuthStore } from '../auth/auth'
import { useAvatarStore } from '../auth/avatar'
import UserAvatar from './UserAvatar.vue'
const auth = useAuthStore()
const avatar = useAvatarStore()
const { version } = storeToRefs(avatar)
const busy = ref(true),
  error = ref(''),
  success = ref('')
let disposed = false
onBeforeUnmount(() => {
  disposed = true
})
onMounted(async () => {
  try {
    await avatar.refresh()
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
    error.value = t('uiMessages.profilePicturesAreLimitedTo5MB')
    return
  }
  busy.value = true
  const owner = auth.user?.id
  try {
    const result = await api<{ avatar_version: string }>('/auth/avatar', 'PUT', file)
    avatar.setVersion(result.avatar_version, owner)
    if (!disposed) {
      success.value = t('uiMessages.profilePictureSaved')
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
  const owner = auth.user?.id
  try {
    await api('/auth/avatar', 'DELETE')
    avatar.setVersion(null, owner)
    if (!disposed) {
      success.value = t('uiMessages.profilePictureRemoved')
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
    <h2>{{ $t('common.profilePicture') }}</h2>
    <UserAvatar :username="auth.user?.username ?? ''" :src="avatar.src" />
    <label
      >{{ $t('accountPicture.chooseImage')
      }}<input
        type="file"
        accept="image/png,image/jpeg,image/webp"
        :disabled="busy"
        @change="upload"
    /></label>
    <p class="help">{{ $t('common.visibleToPeopleUsingCompanionsYouCanAccess') }}</p>
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
        {{ $t('accountPicture.removePicture') }}
      </button></Transition
    >
  </div>
</template>
