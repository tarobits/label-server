<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import ChangelogDialog from './ChangelogDialog.vue'
import { api } from '../api'
import { useAuthStore } from '../auth'
import { unseenReleases, type ReleaseNotes } from '../changelog'
import { useLiveRefresh } from '../live'

const auth = useAuthStore()
const actor = auth.user?.id
const releases = ref<ReleaseNotes[]>([])
const open = ref(false)
let checked = false
let pending = false
let stopped = false

function show() {
  if (stopped || !pending || document.hidden || document.querySelector('dialog[open]')) return
  pending = false
  open.value = true
}
useLiveRefresh(async () => {
  if (!checked) {
    if (document.querySelector('dialog[open]')) return
    const visit = await api<{ previous_version: string | null; current_version: string }>(
      '/auth/changelog',
      'POST',
    )
    if (stopped || actor !== auth.user?.id) return
    checked = true
    releases.value = unseenReleases(visit.previous_version, visit.current_version)
    pending = releases.value.length > 0
  }
  show()
})
onMounted(() => document.addEventListener('close', show, true))
onBeforeUnmount(() => {
  stopped = true
  document.removeEventListener('close', show, true)
})
</script>

<template>
  <ChangelogDialog :open="open" title="What’s new" :releases="releases" @close="open = false" />
</template>
