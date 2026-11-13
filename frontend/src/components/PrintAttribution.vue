<script setup lang="ts">
import type { PrintAttribution } from '../shared/types'
import { date } from '../shared/workspace'
defineProps<{ attribution?: PrintAttribution | null; queue?: boolean }>()
</script>

<template>
  <dl class="print-attribution">
    <div>
      <dt>
        {{
          queue && attribution?.authorization.kind !== 'approval'
            ? $t('uiMessages.queuedBy')
            : $t('uiMessages.requestedBy')
        }}
      </dt>
      <dd>
        {{ attribution?.requested_by?.name ?? $t('uiMessages.notRecorded')
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
    <div
      v-if="
        !queue ||
        attribution?.authorization.kind === 'approval' ||
        attribution?.authorization.kind === 'override'
      "
    >
      <dt>
        {{
          queue && attribution?.authorization.kind === 'override'
            ? $t('uiMessages.authorizedBy')
            : $t('uiMessages.approvedBy')
        }}
      </dt>
      <dd>{{ attribution?.authorization.actor?.name ?? $t('uiMessages.notRecorded') }}</dd>
      <dd class="attribution-detail">
        <template v-if="attribution?.authorization.kind === 'direct'">{{
          $t('printAttribution.directPrinting')
        }}</template>
        <template v-else-if="attribution?.authorization.kind === 'approval'">{{
          $t('printAttribution.requestApproved')
        }}</template>
        <template v-else-if="attribution?.authorization.kind === 'override'">{{
          $t('printAttribution.administratorOverride')
        }}</template>
        <template v-else>{{ $t('printAttribution.authorizationNotRecorded') }}</template>
        <span v-if="attribution?.authorization.at != null">
          · {{ date(attribution.authorization.at) }}</span
        >
      </dd>
    </div>
    <div
      v-for="change in attribution?.destination_changes ?? []"
      :key="change.id"
      class="release-attribution"
    >
      <dt>{{ $t('printAttribution.printerChangedBy') }}</dt>
      <dd>{{ change.actor.name }} · {{ change.source.name }} → {{ change.target.name }}</dd>
      <dd class="attribution-detail">
        {{ date(change.created_at) }} · {{ change.copy_ids.length }} {{ $t('common.copies2')
        }}<span v-if="change.previous_assignment">
          {{ $t('common.previouslyAssignedTo') }} {{ change.previous_assignment.name }}</span
        >
      </dd>
      <dd v-if="change.reason" class="attribution-detail">{{ change.reason }}</dd>
    </div>
    <div v-if="attribution?.release" class="release-attribution">
      <dt>{{ $t('printAttribution.releasedBy') }}</dt>
      <dd>{{ attribution.release.actor?.name ?? $t('uiMessages.notRecorded') }}</dd>
      <dd class="attribution-detail">
        {{ $t('printAttribution.accessHoldReleased') }} {{ date(attribution.release.at) }}
      </dd>
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
