<script setup lang="ts">
import { nextTick, onUnmounted, ref, watch } from 'vue'
import { confirmation, resolveConfirmation } from '../confirmation'
const dialog = ref<HTMLDialogElement | null>(null)
watch(confirmation, async (pending) => {
  await nextTick()
  if (pending) {
    if (!dialog.value?.open) dialog.value?.showModal()
  } else dialog.value?.close()
})
onUnmounted(() => resolveConfirmation(false))
</script>
<template>
  <Teleport to="body">
    <dialog
      ref="dialog"
      class="confirm-dialog"
      aria-labelledby="confirmation-title"
      aria-describedby="confirmation-message"
      @cancel.prevent="resolveConfirmation(false)"
    >
      <h2 id="confirmation-title">Confirm action</h2>
      <p id="confirmation-message">{{ confirmation?.message }}</p>
      <div class="dialog-actions">
        <button class="secondary" autofocus @click="resolveConfirmation(false)">Cancel</button>
        <button class="primary" @click="resolveConfirmation(true)">
          {{ confirmation?.confirmLabel }}
        </button>
      </div>
    </dialog>
  </Teleport>
</template>
<style scoped>
.confirm-dialog {
  width: min(440px, calc(100vw - 40px));
  box-sizing: border-box;
  padding: 28px;
  border: 1px solid var(--border-strong);
  border-radius: 12px;
  background: var(--surface);
  color: var(--ink);
  box-shadow: 0 24px 80px #0008;
}
.confirm-dialog::backdrop {
  background: #030712b3;
  backdrop-filter: blur(3px);
}
.confirm-dialog p {
  margin: 16px 0 24px;
  color: var(--text-secondary);
  overflow-wrap: anywhere;
  white-space: pre-line;
}
.dialog-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 10px;
}
</style>
