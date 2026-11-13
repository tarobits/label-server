<script setup lang="ts">
import { t } from '../shared/i18n'
import { computed, ref, watch } from 'vue'
import { api } from '../shared/api'
import { useAuthStore } from '../auth/auth'
import { useWorkspaceStore } from '../shared/workspace'
import { randomUUID } from '../shared/uuid'
import type { BatchDetail } from '../shared/types'
import AdminDialog from './AdminDialog.vue'
import ExpandableContent from './ExpandableContent.vue'
const props = defineProps<{ batch: BatchDetail }>()
const auth = useAuthStore(),
  w = useWorkspaceStore()
const opened = ref(false),
  selected = ref<string[]>([]),
  mode = ref('paid'),
  cartridge = ref(''),
  includePrinted = ref(false),
  error = ref('')
let requestId = randomUUID()
const eligible = computed(() =>
  props.batch.items.filter(
    (item) =>
      auth.printer(props.batch.printer_id, 'start_any') ||
      (item.attribution?.requested_by?.id === auth.user?.id &&
        auth.printer(props.batch.printer_id, 'start_own')),
  ),
)
const visible = computed(() =>
  eligible.value.filter((item) => includePrinted.value || item.outcome !== 'printed'),
)
const cartridges = computed(() =>
  w.cartridges.filter((item) => !item.archived && auth.cartridge(item.id, 'approve_use')),
)
function open() {
  error.value = ''
  includePrinted.value = false
  selected.value = eligible.value
    .filter((item) => item.outcome !== 'printed')
    .map((item) => item.copy_id)
  mode.value = 'paid'
  cartridge.value = cartridges.value.find((item) => item.id === props.batch.cartridge_id)?.id ?? ''
  opened.value = true
}
watch(
  [selected, mode, cartridge, includePrinted],
  () => {
    requestId = randomUUID()
  },
  { deep: true, flush: 'sync' },
)
watch(includePrinted, (value) => {
  if (!value)
    selected.value = selected.value.filter(
      (id) => props.batch.items.find((item) => item.copy_id === id)?.outcome !== 'printed',
    )
})
async function save() {
  if (w.busy || !selected.value.length) return
  if (
    await w.action(
      () =>
        api(`/batches/${props.batch.id}/retry-offers`, 'POST', {
          request_id: requestId,
          copy_ids: selected.value,
          mode: mode.value,
          cartridge_id: mode.value === 'free' ? cartridge.value : null,
          include_printed: includePrinted.value,
        }),
      mode.value === 'free'
        ? t('uiMessages.freeRetryQueuedPrinterHoldsRemainInPlace')
        : t('uiMessages.retryApprovalSentToTheRequester'),
    )
  )
    opened.value = false
  else error.value = w.actionError
}
</script>
<template>
  <button
    v-if="
      eligible.length &&
      !['printing', 'needs_review'].includes(batch.state) &&
      auth.printer(batch.printer_id, 'view_activity')
    "
    class="secondary"
    @click="open"
  >
    {{ $t('retryControls.retryLabels') }}
  </button>
  <AdminDialog
    :open="opened"
    :title="$t('retryControls.retryLabels')"
    :busy="w.busy"
    @close="opened = false"
  >
    <form class="form-stack" @submit.prevent="save">
      <Transition name="notice"
        ><p v-if="error" role="alert" class="alert danger">{{ error }}</p></Transition
      >
      <label class="checkbox"
        ><input v-model="includePrinted" type="checkbox" />{{
          $t('retryControls.includeConfirmedPrintedCopies')
        }}</label
      >
      <div class="retry-copies">
        <label v-for="item in visible" :key="item.copy_id" class="checkbox">
          <input v-model="selected" type="checkbox" :value="item.copy_id" />
          {{ item.process_name }} ·
          {{ item.attribution?.requested_by?.name ?? $t('uiMessages.unknownRequester') }}
          {{ $t('common.copy') }}
          {{ item.copy_number }}
        </label>
      </div>
      <p v-if="!visible.length" class="muted">{{ $t('retryControls.noUnprintedCopies') }}</p>
      <label
        >{{ $t('common.funding')
        }}<select v-model="mode">
          <option value="paid">{{ $t('retryControls.askRequesterToPay') }}</option>
          <option value="free" :disabled="!cartridges.length">
            {{ $t('retryControls.noAdditionalChargeToRequester') }}
          </option>
        </select></label
      >
      <ExpandableContent :open="mode === 'free'">
        <div class="form-stack">
          <label
            >{{ $t('retryControls.retryCartridge')
            }}<select v-model="cartridge" :required="mode === 'free'">
              <option disabled value="">{{ $t('retryControls.chooseACartridge') }}</option>
              <option v-for="item in cartridges" :key="item.id" :value="item.id">
                {{ item.name }}
              </option>
            </select></label
          >
          <p class="alert warning">
            {{ $t('common.theCartridgeOwnerCoversThisRetrySCostPrevious') }}
          </p>
        </div>
      </ExpandableContent>
      <div class="admin-actions">
        <button :disabled="w.busy || !selected.length || (mode === 'free' && !cartridge)">
          {{
            mode === 'free' ? $t('uiMessages.authorizeFreeRetry') : $t('uiMessages.sendRetryOffer')
          }}
        </button>
      </div>
    </form>
  </AdminDialog>
</template>
<style scoped>
.retry-copies {
  display: grid;
  gap: 12px;
  max-height: 40vh;
  overflow-y: auto;
}
</style>
