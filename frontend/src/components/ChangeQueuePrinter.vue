<script setup lang="ts">
import { computed, ref } from 'vue'
import { api, errorMessage } from '../shared/api'
import { useAuthStore } from '../auth/auth'
import { useWorkspaceStore } from '../shared/workspace'
import type { Job } from '../shared/types'
import AdminDialog from './AdminDialog.vue'
const props = defineProps<{ jobs: Job[]; copyIds: string[]; loading: boolean }>()
const emit = defineEmits<{ changed: [] }>()
const auth = useAuthStore(),
  w = useWorkspaceStore()
const open = ref(false),
  busy = ref(false),
  error = ref(''),
  printer = ref(''),
  reason = ref('')
const selection = ref<string[]>([]),
  origins = ref<string[]>([])
const targets = computed(() =>
  w.destinations.filter(
    (target) =>
      target.kind === 'printer' &&
      auth.printer(target.id, 'manage_queue') &&
      !props.jobs.some((job) => job.destination_id === target.id),
  ),
)
const allowed = computed(
  () =>
    props.jobs.length > 0 &&
    props.jobs.every((job) => job.can_change_printer) &&
    targets.value.length > 0,
)
function show() {
  selection.value = [...props.copyIds]
  origins.value = [...new Set(props.jobs.map((job) => w.destinationName(job.destination_id)))]
  printer.value = ''
  reason.value = ''
  error.value = ''
  open.value = true
}
async function save() {
  if (busy.value || !printer.value) return
  busy.value = true
  error.value = ''
  try {
    await api('/queue/change-printer', 'POST', {
      copy_ids: selection.value,
      printer_id: printer.value,
      reason: reason.value,
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
  <button class="secondary" :disabled="!allowed || loading || w.busy" @click="show">
    {{ $t('changeQueuePrinter.changePrinter') }}
  </button>
  <AdminDialog
    :open="open"
    :title="$t('changeQueuePrinter.changePrinter')"
    :busy="busy"
    @close="open = false"
  >
    <form v-validate-form class="form-stack" @submit.prevent="save">
      <p>{{ selection.length }} {{ $t('common.queuedCopies2') }} {{ origins.join(', ') }}</p>
      <label
        >{{ $t('changeQueuePrinter.replacementPrinter') }}
        <select v-model="printer" required :disabled="busy">
          <option disabled value="">{{ $t('changeQueuePrinter.chooseAPrinter') }}</option>
          <option v-for="target in targets" :key="target.id" :value="target.id">
            {{ target.name }}
          </option>
        </select>
      </label>
      <label
        >{{ $t('changeQueuePrinter.reasonOptional')
        }}<textarea v-model="reason" maxlength="1000" rows="2" :disabled="busy" />
      </label>
      <p class="help">
        {{ $t('changeQueuePrinter.queuedCopiesMayPrintAutomaticallyOnTheReplacementPrinter') }}
      </p>
      <Transition name="notice"
        ><p v-if="error" class="alert danger motion-reveal" role="alert">{{ error }}</p></Transition
      >
      <div class="admin-actions">
        <button type="button" class="secondary" :disabled="busy" @click="open = false">
          {{ $t('common.cancel') }}
        </button>
        <button type="submit" class="primary" :disabled="busy || !printer">
          {{ busy ? $t('uiMessages.changing') : $t('changeQueuePrinter.changePrinter') }}
        </button>
      </div>
    </form>
  </AdminDialog>
</template>
