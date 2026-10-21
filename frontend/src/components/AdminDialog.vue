<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, useId, watch } from 'vue'

const props = defineProps<{ open: boolean; title: string; busy?: boolean; wide?: boolean }>()
const emit = defineEmits<{ close: [] }>()
const dialog = ref<HTMLDialogElement | null>(null)
const titleId = useId()
let opener: HTMLElement | null = null
let restorePending = false
function restoreFocus() {
  if (props.busy) {
    restorePending = true
    return
  }
  restorePending = false
  const navigation = document.querySelector<HTMLElement>(
    '.administration-nav [aria-current="page"]',
  )
  const fallback = navigation?.getClientRects().length
    ? navigation
    : document.querySelector<HTMLElement>('.administration-mobile-nav select')
  const target = opener?.isConnected ? opener : fallback
  target?.focus()
}
function containFocus(event: KeyboardEvent) {
  if (event.key !== 'Tab' || !dialog.value) return
  const controls = [
    ...dialog.value.querySelectorAll<HTMLElement>(
      'button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], [tabindex]:not([tabindex="-1"])',
    ),
  ].filter((element) => element.getClientRects().length && !element.closest('[inert]'))
  const index = controls.indexOf(document.activeElement as HTMLElement)
  if (event.shiftKey && index <= 0) {
    event.preventDefault()
    controls.at(-1)?.focus()
  } else if (!event.shiftKey && (index < 0 || index === controls.length - 1)) {
    event.preventDefault()
    controls[0]?.focus()
  }
}
watch(
  () => props.open,
  async (open) => {
    if (open) {
      restorePending = false
      opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
      await nextTick()
      if (!props.open || !dialog.value || dialog.value.open) return
      dialog.value.showModal()
      const target = dialog.value.querySelector<HTMLElement>(
        '[autofocus], input:not([disabled]), select:not([disabled]), textarea',
      )
      ;(target ?? dialog.value.querySelector<HTMLElement>('h2'))?.focus()
    } else {
      dialog.value?.close()
      restoreFocus()
    }
  },
  { immediate: true, flush: 'post' },
)
watch(
  () => props.busy,
  () => {
    if (!props.open && restorePending) restoreFocus()
  },
  { flush: 'post' },
)
onBeforeUnmount(() => {
  dialog.value?.close()
  if (opener?.isConnected) opener.focus()
})
</script>

<template>
  <dialog
    ref="dialog"
    class="admin-dialog"
    :class="{ wide }"
    :aria-labelledby="titleId"
    @cancel.prevent="!busy && emit('close')"
    @keydown="containFocus"
  >
    <template v-if="open">
      <header class="admin-dialog-heading">
        <h2 :id="titleId" tabindex="-1">{{ title }}</h2>
        <button type="button" class="secondary" :disabled="busy" @click="emit('close')">
          Close
        </button>
      </header>
      <div class="admin-dialog-body"><slot /></div>
    </template>
  </dialog>
</template>

<style scoped>
:global(body:has(.admin-dialog[open])) {
  overflow: hidden;
}
.admin-dialog {
  width: min(680px, calc(100% - 32px));
  max-width: none;
  max-height: calc(100dvh - 32px);
  padding: 0;
  border: 1px solid var(--line-strong);
  border-radius: 12px;
  background: var(--surface-dense);
  color: var(--ink);
  box-shadow: 0 24px 64px var(--shadow);
}
.admin-dialog.wide {
  width: min(940px, calc(100% - 32px));
}
.admin-dialog::backdrop {
  background: #030712b3;
}
.admin-dialog-heading {
  position: sticky;
  top: 0;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 20px 24px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-dense);
}
h2 {
  margin: 0;
  font-size: 20px;
  overflow-wrap: anywhere;
}
.admin-dialog-body {
  padding: 24px;
}
.admin-dialog-body :deep(.admin-actions) {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 8px;
  padding-top: 20px;
  border-top: 1px solid var(--line);
}
.admin-dialog-body :deep(.admin-actions .danger-text) {
  margin-right: auto;
}
@media (max-width: 600px) {
  .admin-dialog-heading {
    padding: 16px;
  }
  .admin-dialog-body {
    padding: 16px;
  }
}
</style>
