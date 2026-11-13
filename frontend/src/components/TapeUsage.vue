<script setup lang="ts">
import { t } from '../shared/i18n'
import type { PrintPlan } from '../shared/types'
withDefaults(defineProps<{ plan?: PrintPlan | null; caption?: string }>(), {
  caption: t('uiMessages.estimatedTapeUse'),
})
</script>

<template>
  <section class="tape-usage" :aria-label="$t('common.tapeUsage')">
    <template v-if="plan?.breakdown">
      <p class="help">
        {{ caption }} · {{ plan.estimated_mm.toFixed(2) }} {{ $t('common.mmTotal') }}
      </p>
      <dl :aria-label="$t('common.tapeUsageBreakdown')">
        <div>
          <dt>{{ $t('tapeUsage.design') }}</dt>
          <dd>{{ plan.breakdown.design_mm.toFixed(2) }} {{ $t('common.mm') }}</dd>
        </div>
        <div>
          <dt>{{ $t('tapeUsage.feed') }}</dt>
          <dd>{{ plan.breakdown.feed_mm.toFixed(2) }} {{ $t('common.mm') }}</dd>
        </div>
        <div>
          <dt>{{ $t('tapeUsage.leader') }}</dt>
          <dd>{{ plan.breakdown.leader_mm.toFixed(2) }} {{ $t('common.mm') }}</dd>
        </div>
        <div>
          <dt>{{ $t('common.unused') }}</dt>
          <dd>{{ plan.breakdown.unused_mm.toFixed(2) }} {{ $t('common.mm') }}</dd>
        </div>
      </dl>
    </template>
    <p v-else class="help">{{ $t('common.tapeBreakdownNotRecorded') }}</p>
  </section>
</template>

<style scoped>
.tape-usage {
  margin-block: 12px;
  white-space: normal;
}
p {
  margin: 0 0 12px;
}
dl {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(120px, 100%), 1fr));
  gap: 12px;
  margin: 0;
  font-size: 13px;
}
dl > div {
  display: block;
  min-width: 0;
  padding: 0;
  border: 0;
}
dt {
  color: var(--text-secondary);
  margin-bottom: 4px;
}
dd {
  margin: 0;
  font-variant-numeric: tabular-nums;
}
</style>
