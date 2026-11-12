<script setup lang="ts">
import { ref } from 'vue'
import { api, errorMessage } from '../shared/api'
import { useWorkspaceStore } from '../shared/workspace'
import AdminDialog from './AdminDialog.vue'

const props = defineProps<{ url: string; copies: number; revision?: number; disabled?: boolean }>()
const emit = defineEmits<{ changed: [] }>()
const w = useWorkspaceStore()
const open = ref(false),
  busy = ref(false),
  count = ref(1),
  error = ref('')
let target = '',
  original = 1,
  revision: number | undefined
function show() {
  target = props.url
  original = props.copies
  revision = props.revision
  count.value = original
  error.value = ''
  open.value = true
}
async function save() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await api(target, 'PUT', {
      copies: count.value,
      ...(revision === undefined ? { expected_copies: original } : { expected_revision: revision }),
    })
    open.value = false
    emit('changed')
    await w.refresh()
  } catch (cause) {
    error.value = errorMessage(cause)
  } finally {
    busy.value = false
  }
}
</script>
<template>
  <button class="text-button" :disabled="disabled || w.busy" @click="show">
    {{ $t('changeCopies.changeCopies') }}
  </button>
  <AdminDialog
    :open="open"
    :title="$t('changeCopies.changeCopies')"
    :busy="busy"
    @close="open = false"
  >
    <form v-validate-form class="form-stack" @submit.prevent="save">
      <label
        >{{ $t('common.copies')
        }}<input
          v-model.number="count"
          type="number"
          min="1"
          max="1000"
          step="1"
          required
          :disabled="busy"
      /></label>
      <Transition name="notice"
        ><p v-if="error" class="alert danger motion-reveal" role="alert">{{ error }}</p></Transition
      >
      <div class="admin-actions">
        <button type="button" class="secondary" :disabled="busy" @click="open = false">
          {{ $t('common.cancel') }}
        </button>
        <button type="submit" class="primary" :disabled="busy || count === original">
          {{ busy ? 'Saving…' : 'Save' }}
        </button>
      </div>
    </form>
  </AdminDialog>
</template>
