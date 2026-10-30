<script setup lang="ts">
import { onUnmounted, ref, watch } from 'vue'
import { api, errorMessage } from '../api'
import { useAuthStore } from '../auth'
import { date, useWorkspaceStore } from '../workspace'

interface PurgePreview {
  confirmation: string
  batches: number
  notifications: number
  deliveries: number
  groups: {
    retained_batch_id: string
    process_names: string[]
    printer_id: string
    copies: number
    duplicates: number
    first_at: number
    last_at: number
    error: string
  }[]
}
const emit = defineEmits<{ purged: [count: number] }>()
const auth = useAuthStore(),
  w = useWorkspaceStore()
const dialog = ref<HTMLDialogElement | null>(null),
  preview = ref<PurgePreview | null>(null),
  error = ref(''),
  loading = ref(false),
  purging = ref(false)
let sequence = 0

async function scan() {
  const ticket = ++sequence
  preview.value = null
  error.value = ''
  loading.value = true
  try {
    const result = await api<PurgePreview>('/admin/history/duplicates')
    if (ticket === sequence) preview.value = result
  } catch (cause) {
    if (ticket === sequence) error.value = errorMessage(cause)
  } finally {
    if (ticket === sequence) loading.value = false
  }
}
function open() {
  dialog.value?.showModal()
  void scan()
}
function close() {
  if (purging.value) return
  sequence++
  loading.value = false
  dialog.value?.close()
}
async function purge() {
  if (!preview.value?.batches || purging.value) return
  const ticket = ++sequence
  purging.value = true
  error.value = ''
  try {
    const result = await api<{ batches: number }>('/admin/history/duplicates/purge', 'POST', {
      confirmation: preview.value.confirmation,
    })
    if (ticket !== sequence) return
    emit('purged', result.batches)
    dialog.value?.close()
  } catch (cause) {
    if (ticket === sequence) {
      preview.value = null
      error.value = errorMessage(cause)
    }
  } finally {
    if (ticket === sequence) purging.value = false
  }
}
watch([() => auth.user?.id, () => auth.user?.is_admin], () => {
  sequence++
  purging.value = false
  close()
})
onUnmounted(() => sequence++)
</script>

<template>
  <button class="secondary small" @click="open">Purge duplicates…</button>
  <Teleport to="body">
    <dialog
      ref="dialog"
      class="cleanup-dialog"
      aria-labelledby="cleanup-title"
      :aria-busy="loading || purging"
      @cancel.prevent="close"
    >
      <h2 id="cleanup-title">Purge duplicate failures</h2>
      <div class="cleanup-body">
        <Transition name="notice">
          <p v-if="loading" class="muted motion-reveal" role="status">Scanning history…</p>
        </Transition>
        <Transition name="notice">
          <div v-if="error" class="alert danger motion-reveal" role="alert">{{ error }}</div>
        </Transition>
        <Transition name="notice">
          <div v-if="preview" class="motion-reveal">
            <template v-if="preview.batches">
              <p>
                Permanently delete {{ preview.batches }} duplicate
                {{ preview.batches === 1 ? 'attempt' : 'attempts' }} and their label-history and
                zero-usage records<span v-if="preview.notifications"
                  >, plus {{ preview.notifications }} linked
                  {{ preview.notifications === 1 ? 'notification' : 'notifications' }} and
                  {{ preview.deliveries }} delivery
                  {{ preview.deliveries === 1 ? 'record' : 'records' }}</span
                >.
              </p>
              <p>
                Keeps the oldest failure in each group below. Only matching attempts where printing
                never started are included. This cannot be undone.
              </p>
              <ul class="cleanup-groups" aria-label="Duplicate groups">
                <li v-for="group in preview.groups" :key="group.retained_batch_id">
                  <div class="row spread wrap">
                    <strong>{{ group.process_names.join(' · ') }}</strong>
                    <span>{{ group.duplicates }} to delete</span>
                  </div>
                  <small class="muted">
                    {{ w.destinationName(group.printer_id) }} · {{ group.copies }}
                    {{ group.copies === 1 ? 'copy' : 'copies' }} · {{ date(group.first_at) }} –
                    {{ date(group.last_at) }}
                  </small>
                  <p>{{ group.error }}</p>
                  <RouterLink :to="`/batches/${group.retained_batch_id}`" @click="close">
                    Original to keep →
                  </RouterLink>
                </li>
              </ul>
            </template>
            <p v-else role="status">No duplicate failures eligible for removal.</p>
          </div>
        </Transition>
      </div>
      <div class="cleanup-actions row wrap">
        <button class="secondary" autofocus :disabled="purging" @click="close">
          {{ preview?.batches || loading || error ? 'Cancel' : 'Close' }}
        </button>
        <button v-if="error" class="secondary" :disabled="loading" @click="scan">
          Refresh preview
        </button>
        <button
          v-if="preview?.batches"
          class="primary"
          :disabled="purging || loading"
          @click="purge"
        >
          {{ purging ? 'Purging…' : `Permanently delete ${preview.batches}` }}
        </button>
      </div>
    </dialog>
  </Teleport>
</template>

<style scoped>
.cleanup-dialog {
  width: min(720px, calc(100% - 32px));
  max-height: calc(100dvh - 32px);
  box-sizing: border-box;
  padding: 24px;
  background: var(--surface-dense);
  color: var(--ink);
  border: 1px solid var(--line-strong);
  border-radius: 12px;
  box-shadow: 0 24px 64px var(--shadow);
}
.cleanup-dialog[open] {
  display: flex;
  flex-direction: column;
}
.cleanup-dialog::backdrop {
  background: #030712b3;
}
.cleanup-body {
  overflow: auto;
  min-height: 0;
  margin-top: 16px;
  overflow-wrap: anywhere;
}
.cleanup-body p {
  margin: 0 0 16px;
}
.cleanup-groups {
  list-style: none;
  padding: 0;
  margin: 24px 0 0;
}
.cleanup-groups li {
  padding: 16px 0;
  border-top: 1px solid var(--line);
}
.cleanup-groups p {
  margin: 8px 0;
}
.cleanup-actions {
  justify-content: flex-end;
  margin-top: 24px;
  flex-shrink: 0;
}
</style>
