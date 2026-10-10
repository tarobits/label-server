<script setup lang="ts">
import type { PrintAttribution } from '../types'
import { date } from '../workspace'
defineProps<{ attribution?: PrintAttribution | null }>()
</script>

<template>
  <dl class="print-attribution">
    <div>
      <dt>Requested by</dt>
      <dd>
        {{ attribution?.requested_by?.name ?? 'Not recorded'
        }}<span
          v-if="
            attribution?.submitted_by &&
            attribution.submitted_by.id !== attribution.requested_by?.id
          "
        >
          ({{ attribution.submitted_by.name }})</span
        >
      </dd>
      <dd v-if="attribution?.requested_at != null" class="attribution-detail">
        {{ date(attribution.requested_at) }}
      </dd>
    </div>
    <div>
      <dt>Approved by</dt>
      <dd>{{ attribution?.authorization.actor?.name ?? 'Not recorded' }}</dd>
      <dd class="attribution-detail">
        <template v-if="attribution?.authorization.kind === 'direct'">Direct printing</template>
        <template v-else-if="attribution?.authorization.kind === 'approval'"
          >Request approved</template
        >
        <template v-else-if="attribution?.authorization.kind === 'override'"
          >Administrator override</template
        >
        <template v-else>Authorization not recorded</template>
        <span v-if="attribution?.authorization.at != null">
          · {{ date(attribution.authorization.at) }}</span
        >
      </dd>
    </div>
    <div v-if="attribution?.release" class="release-attribution">
      <dt>Released by</dt>
      <dd>{{ attribution.release.actor?.name ?? 'Not recorded' }}</dd>
      <dd class="attribution-detail">Access hold released · {{ date(attribution.release.at) }}</dd>
    </div>
  </dl>
</template>

<style scoped>
.print-attribution {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(160px, 100%), 1fr));
  gap: 12px 24px;
  margin: 0;
  font-size: 13px;
}
.print-attribution > div {
  display: block;
  padding: 0;
  border: 0;
  min-width: 0;
  overflow-wrap: anywhere;
}
dt {
  margin-bottom: 4px;
  color: var(--text-secondary);
  font-size: 12px;
}
dd {
  margin: 0;
  color: var(--ink);
  font-weight: 600;
}
.attribution-detail {
  margin-top: 4px;
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 400;
}
.release-attribution {
  grid-column: 1 / -1;
}
</style>
