<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useLiveRefresh } from '../shared/live'
import {
  checkServer,
  checkingServer,
  serverUnavailable,
  serverUnavailableMessage,
} from '../shared/serverConnection'

const dialog = ref<HTMLDialogElement | null>(null)
function retry() {
  void checkServer()
}
useLiveRefresh(checkServer)
onMounted(() => {
  window.addEventListener('online', retry)
  window.addEventListener('offline', retry)
})
onBeforeUnmount(() => {
  window.removeEventListener('online', retry)
  window.removeEventListener('offline', retry)
  dialog.value?.close()
})
watch(
  serverUnavailable,
  async (unavailable) => {
    await nextTick()
    if (unavailable && serverUnavailable.value) {
      if (!dialog.value?.open) dialog.value?.showModal()
    } else if (!serverUnavailable.value) dialog.value?.close()
  },
  { immediate: true },
)
</script>

<template>
  <Teleport to="body">
    <dialog
      ref="dialog"
      class="server-unavailable"
      :aria-label="$t('common.serverUnavailable')"
      aria-describedby="server-unavailable-message"
      @cancel.prevent
    >
      <div class="unavailable-content">
        <p id="server-unavailable-message">{{ serverUnavailableMessage }}</p>
        <button
          type="button"
          class="primary"
          :disabled="checkingServer"
          :aria-busy="checkingServer"
          @click="retry"
        >
          {{ $t('common.retry') }}
        </button>
      </div>
    </dialog>
  </Teleport>
</template>

<style scoped>
.server-unavailable {
  box-sizing: border-box;
  inset: 0;
  width: 100%;
  max-width: none;
  height: 100dvh;
  max-height: none;
  margin: 0;
  padding: 24px;
  border: 0;
  border-radius: 0;
  color: var(--ink);
  background: var(--surface-dense);
}
.server-unavailable[open] {
  display: grid;
  place-items: center;
}
.server-unavailable::backdrop {
  background: var(--surface-dense);
}
.unavailable-content {
  max-width: 28rem;
  text-align: center;
}
p {
  margin: 0 0 24px;
  font-size: 20px;
  font-weight: 600;
  line-height: 1.5;
  text-wrap: balance;
}
</style>
