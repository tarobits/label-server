<script setup lang="ts">
import type { BatchTrigger } from '../shared/types'
import { date } from '../shared/workspace'
defineProps<{ trigger?: BatchTrigger | null }>()
</script>

<template>
  <p class="batch-trigger">
    <template v-if="trigger?.kind === 'manual'">
      <span>{{ $t('batchTrigger.manuallyStartedBy') + ' ' }}</span
      ><strong>{{ trigger.actor?.name ?? 'Not recorded' }}</strong>
      <span v-if="trigger.at != null"> · {{ date(trigger.at) }}</span>
    </template>
    <template v-else-if="trigger?.kind === 'automatic'">{{
      $t('common.startedAutomaticallyByTheQueue')
    }}</template>
    <template v-else>{{ $t('batchTrigger.batchStarterNotRecorded') }}</template>
  </p>
  <p v-if="trigger?.stop_request" class="batch-trigger">
    {{
      trigger.stop_request.mode === 'emergency'
        ? $t('common.emergencyStop')
        : $t('common.stopAfterCurrentLabel')
    }}
    {{ $t('common.requestedBy') }}
    <strong>{{ trigger.stop_request.actor?.name ?? 'Not recorded' }}</strong> ·
    {{ date(trigger.stop_request.at) }}
  </p>
</template>

<style scoped>
.batch-trigger {
  color: var(--text-secondary);
  font-size: 12px;
  overflow-wrap: anywhere;
}
strong {
  color: var(--ink);
}
</style>
