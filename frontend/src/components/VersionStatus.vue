<script setup lang="ts">
import { computed, ref } from 'vue'
import { useLiveRefresh } from '../live'

type VersionInfo = {
  current_version: string
  latest_version: string | null
  update_available: boolean
  release_url: string | null
}
const version = ref<VersionInfo>()
const dismissed = ref('')
try {
  dismissed.value = sessionStorage.getItem('dismissed-release') || ''
} catch {
  /* Storage may be disabled. */
}
useLiveRefresh(async () => {
  const response = await fetch('/api/version', { credentials: 'same-origin' })
  if (response.ok) version.value = await response.json()
}, 5000)
const showUpdate = computed(
  () => version.value?.update_available && version.value.latest_version !== dismissed.value,
)
function dismiss() {
  dismissed.value = version.value?.latest_version || ''
  try {
    sessionStorage.setItem('dismissed-release', dismissed.value)
  } catch {
    /* Dismissing still works without storage. */
  }
}
</script>

<template>
  <span v-if="version" class="version-number">v{{ version.current_version }}</span>
  <aside v-if="showUpdate" class="update-notice" role="status" aria-label="Software update">
    <div>
      <strong>Update available</strong>
      <p>Version {{ version?.latest_version }} is ready.</p>
      <a :href="version?.release_url || undefined" target="_blank" rel="noopener noreferrer"
        >View release</a
      >
    </div>
    <button type="button" aria-label="Dismiss update notification" @click="dismiss">×</button>
  </aside>
</template>

<style scoped>
.version-number {
  white-space: nowrap;
}
.update-notice {
  position: fixed;
  right: 20px;
  bottom: 20px;
  z-index: 50;
  display: flex;
  align-items: flex-start;
  gap: 24px;
  max-width: calc(100vw - 40px);
  padding: 16px 18px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
  color: var(--ink);
  box-shadow: 0 4px 20px var(--shadow);
  font-size: 13px;
}
.update-notice p {
  margin: 6px 0;
}
.update-notice button {
  padding: 0 4px;
  border: 0;
  background: transparent;
  font-size: 22px;
  line-height: 1;
}
</style>
