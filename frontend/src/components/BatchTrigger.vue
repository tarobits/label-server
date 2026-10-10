<script setup lang="ts">
import type { BatchTrigger } from '../types'
import { date } from '../workspace'
defineProps<{ trigger?: BatchTrigger | null }>()
</script>

<template>
  <p class="batch-trigger">
    <template v-if="trigger?.kind === 'manual'">
      <span>Manually started by </span><strong>{{ trigger.actor?.name ?? 'Not recorded' }}</strong>
      <span v-if="trigger.at != null"> · {{ date(trigger.at) }}</span>
    </template>
    <template v-else-if="trigger?.kind === 'automatic'"
      >Started automatically by the queue</template
    >
    <template v-else>Batch starter not recorded</template>
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
