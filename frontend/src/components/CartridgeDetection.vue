<script setup lang="ts">
import { computed } from 'vue'
import { useAuthStore } from '../auth'
import { installCartridge } from '../cartridges'
import { useWorkspaceStore } from '../workspace'
import type { Status } from '../types'

const props = defineProps<{ status?: Status }>()
const w = useWorkspaceStore()
const auth = useAuthStore()
const visible = computed(
  () =>
    props.status &&
    (props.status.media_warning || props.status.cartridge_check_pending) &&
    auth.atLeast(props.status.printer_id, 'full'),
)
const locked = computed(
  () => w.busy || !!props.status?.printing || !!props.status?.needs_review.length,
)
async function confirm() {
  const status = props.status
  if (!status?.active_cartridge_id) return
  await w.action(
    () => installCartridge(status.printer_id, status.active_cartridge_id),
    'Cartridge confirmed. Eligible queued labels may now print.',
  )
}
</script>

<template>
  <Transition name="notice">
    <div v-if="visible" class="alert warning cartridge-detection">
      <p>
        {{
          status?.cartridge_check_pending
            ? 'Printer opened or tape changed. Confirm the installed cartridge.'
            : status?.media_confirmed
              ? 'Using confirmed cartridge.'
              : status?.media_warning
        }}
      </p>
      <p v-if="status?.detected_media" class="help">Detected: {{ status.detected_media }}</p>
      <button
        v-if="!status?.media_confirmed || status?.cartridge_check_pending"
        class="secondary"
        :disabled="
          locked ||
          !status?.connected ||
          (status?.cartridge_check_pending && !status.cartridge_check_ready)
        "
        @click="confirm"
      >
        Confirm cartridge
      </button>
    </div>
  </Transition>
</template>

<style scoped>
.cartridge-detection p {
  margin: 0;
  white-space: pre-line;
  overflow-wrap: anywhere;
}
.cartridge-detection {
  display: grid;
  gap: 12px;
  justify-items: start;
}
</style>
