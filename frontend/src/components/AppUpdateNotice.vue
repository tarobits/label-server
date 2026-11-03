<script setup lang="ts">
import { useLiveRefresh } from '../live'
import {
  applyingAppUpdate,
  appUpdateError,
  checkForAppUpdate,
  dismissAppUpdate,
  reloadForAppUpdate,
  showAppUpdate,
} from '../pwa'

useLiveRefresh(async () => checkForAppUpdate(), 60000)
</script>

<template>
  <Transition name="notice">
    <aside
      v-if="showAppUpdate"
      class="app-update-notice motion-reveal"
      role="status"
      aria-label="App update"
    >
      <strong>App update ready</strong>
      <p>Reloading discards unsaved changes.</p>
      <p v-if="appUpdateError" class="danger-text" role="alert">{{ appUpdateError }}</p>
      <div class="update-actions">
        <button type="button" :disabled="applyingAppUpdate" @click="dismissAppUpdate">Later</button>
        <button
          type="button"
          class="primary"
          :disabled="applyingAppUpdate"
          :aria-busy="applyingAppUpdate"
          @click="reloadForAppUpdate"
        >
          Reload
        </button>
      </div>
    </aside>
  </Transition>
</template>

<style scoped>
.app-update-notice {
  position: fixed;
  right: 20px;
  bottom: max(20px, env(safe-area-inset-bottom));
  z-index: 50;
  box-sizing: border-box;
  max-width: calc(100vw - 40px);
  padding: 16px 18px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
  color: var(--ink);
  font-size: 13px;
}
p {
  margin: 6px 0 16px;
  color: var(--text-secondary);
}
.update-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
</style>
