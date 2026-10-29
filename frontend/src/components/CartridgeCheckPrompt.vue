<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '../auth'
import { installCartridge } from '../cartridges'
import { confirmation } from '../confirmation'
import { useWorkspaceStore } from '../workspace'

const w = useWorkspaceStore()
const auth = useAuthStore()
const route = useRoute()
const shown = reactive(new Set<string>())
const pending = computed(() =>
  w.printerStatuses.find(
    (status) =>
      status.cartridge_check_pending &&
      status.cartridge_check_ready &&
      status.connected &&
      status.cartridge_check_key &&
      status.active_cartridge_id &&
      !status.printing &&
      !status.needs_review.length &&
      auth.atLeast(status.printer_id, 'full') &&
      !shown.has(
        `${status.printer_id}:${status.active_cartridge_id}:${status.cartridge_check_key}`,
      ),
  ),
)
watch(
  () => [pending.value, w.busy, confirmation.value, route.path] as const,
  async ([status, busy, dialog]) => {
    if (!status?.active_cartridge_id || busy || dialog || route.path.startsWith('/batches/')) return
    shown.add(`${status.printer_id}:${status.active_cartridge_id}:${status.cartridge_check_key}`)
    await w.action(
      () => installCartridge(status.printer_id, status.active_cartridge_id),
      'Cartridge confirmed. Eligible queued labels may now print.',
    )
  },
  { immediate: true },
)
</script>

<template></template>
