<script setup lang="ts">
import type { PrintPlan } from '../types'
withDefaults(defineProps<{ plan?: PrintPlan | null; caption?: string }>(), {
  caption: 'Estimated tape use',
})
</script>

<template>
  <section class="tape-usage" aria-label="Tape usage">
    <template v-if="plan?.breakdown">
      <p class="help">{{ caption }} · {{ plan.estimated_mm.toFixed(2) }} mm total</p>
      <dl aria-label="Tape usage breakdown">
        <div>
          <dt>Design</dt>
          <dd>{{ plan.breakdown.design_mm.toFixed(2) }} mm</dd>
        </div>
        <div>
          <dt>Feed</dt>
          <dd>{{ plan.breakdown.feed_mm.toFixed(2) }} mm</dd>
        </div>
        <div>
          <dt>Leader</dt>
          <dd>{{ plan.breakdown.leader_mm.toFixed(2) }} mm</dd>
        </div>
        <div>
          <dt>Unused</dt>
          <dd>{{ plan.breakdown.unused_mm.toFixed(2) }} mm</dd>
        </div>
      </dl>
    </template>
    <p v-else class="help">Tape breakdown not recorded.</p>
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
