<script setup lang="ts">
import { computed } from 'vue'
export interface StationDashboard {
  held: boolean
  cartridge_check_pending: boolean
  queued_labels: number
  shared_queued_labels: number
  printed_last_24h: number
  cartridge: {
    name: string
    remaining_mm: number
    nominal_length_mm: number
    uncertain: boolean
    profile_name: string | null
    width_mm: number | null
    foreground: string | null
    background: string | null
  } | null
  active_batch: BatchSummary | null
  last_batch: BatchSummary | null
}
interface BatchSummary {
  state: string
  total_labels: number
  confirmed_labels: number
  finished_at: number | null
}
const props = defineProps<{ details: StationDashboard; stale: boolean; printing: boolean }>()
const stock = computed(() => props.details.cartridge)
const metres = (mm: number) => `${(Math.max(0, mm) / 1000).toFixed(2)} m`
const lastResult = computed(() => {
  const batch = props.details.last_batch
  if (!batch) return ''
  return batch.state === 'printed'
    ? `${batch.confirmed_labels} labels completed`
    : `${batch.confirmed_labels} of ${batch.total_labels} labels confirmed`
})
</script>

<template>
  <div class="printer-telemetry">
    <dl class="printer-counts">
      <div>
        <dt>Queued labels</dt>
        <dd>
          {{ details.queued_labels
          }}<span v-if="details.shared_queued_labels" class="shared-queue">
            + {{ details.shared_queued_labels }} shared</span
          >
        </dd>
      </div>
      <div>
        <dt>Printed · last 24h</dt>
        <dd>{{ details.printed_last_24h }}</dd>
      </div>
    </dl>
    <div class="printer-stock">
      <template v-if="stock">
        <div class="stock-heading">
          <span
            class="stock-swatch"
            :style="{ background: stock.background ?? '#fff', color: stock.foreground ?? '#000' }"
            aria-hidden="true"
            >Aa</span
          >
          <div>
            <strong>{{ stock.name }}</strong
            ><small>{{ stock.profile_name }}</small>
          </div>
        </div>
        <div class="stock-amount">
          <span>{{ stock.uncertain ? 'Estimate needs review' : 'Estimated remaining' }}</span
          ><strong>{{ metres(stock.remaining_mm) }}</strong>
        </div>
        <meter
          v-if="stock.nominal_length_mm > 0 && !stock.uncertain"
          class="stock-meter"
          aria-label="Estimated cartridge remaining"
          min="0"
          :max="stock.nominal_length_mm"
          :low="stock.nominal_length_mm * 0.15"
          :optimum="stock.nominal_length_mm"
          :value="Math.max(0, Math.min(stock.nominal_length_mm, stock.remaining_mm))"
          :aria-valuetext="`${metres(stock.remaining_mm)} of ${metres(stock.nominal_length_mm)}`"
        />
      </template>
      <p v-else class="muted stock-empty">No cartridge installed</p>
    </div>
    <div v-if="details.active_batch" class="batch-strip" :class="{ active: printing }">
      <strong>{{ printing ? 'Active batch' : 'Awaiting batch result' }}</strong>
      <span>{{ details.active_batch.total_labels }} labels</span>
    </div>
    <p v-else-if="details.last_batch" class="last-batch">
      <span>Last batch</span><strong>{{ lastResult }}</strong
      ><time
        v-if="details.last_batch.finished_at"
        :datetime="new Date(details.last_batch.finished_at * 1000).toISOString()"
        >{{
          new Date(details.last_batch.finished_at * 1000).toLocaleTimeString([], {
            hour: '2-digit',
            minute: '2-digit',
          })
        }}</time
      >
    </p>
    <p v-if="stale" class="stale-data">Last known server data</p>
  </div>
</template>

<style scoped>
.printer-telemetry {
  display: grid;
  gap: 12px;
}
.printer-counts {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin: 0;
}
.printer-counts dt {
  font-size: 0.875rem;
  color: var(--muted);
  margin-bottom: 4px;
}
.printer-counts > div {
  display: block;
  padding: 0;
  border: 0;
}
.printer-counts dd {
  margin: 0;
  font-size: 1.5rem;
  line-height: 1.2;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
}
.shared-queue {
  display: inline-block;
  font-size: 0.875rem;
  font-weight: 400;
  color: var(--muted);
}
.printer-stock {
  border-top: 1px solid var(--line);
  padding-top: 12px;
}
.stock-heading {
  display: flex;
  align-items: center;
  gap: 12px;
}
.stock-heading > div {
  min-width: 0;
}
.stock-heading strong,
.stock-heading small {
  display: block;
  overflow-wrap: anywhere;
}
.stock-heading small {
  color: var(--muted);
  margin-top: 2px;
  font-size: 0.875rem;
}
.stock-swatch {
  display: grid;
  place-items: center;
  flex: 0 0 36px;
  height: 30px;
  border: 1px solid var(--line);
  border-radius: 4px;
  font-weight: 700;
}
.stock-amount {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 8px;
  margin-top: 8px;
  font-size: 0.875rem;
  color: var(--muted);
}
.stock-amount strong {
  color: var(--ink);
  font-variant-numeric: tabular-nums;
}
.stock-meter {
  display: block;
  width: 100%;
  height: 12px;
  margin-top: 6px;
}
.stock-meter::-webkit-meter-bar {
  background: var(--surface-deepest);
  border: none;
}
.stock-meter::-webkit-meter-optimum-value {
  background: var(--success);
}
.stock-meter::-webkit-meter-suboptimum-value {
  background: #f59e0b;
}
.stock-meter::-moz-meter-bar {
  background: var(--success);
}
.stock-empty {
  margin: 0;
}
.batch-strip {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 12px;
  border-radius: 8px;
  background: var(--surface-secondary);
  font-size: 0.875rem;
}
.batch-strip.active {
  background: var(--accent-fill);
  color: var(--accent-hover);
}
.last-batch {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 8px;
  margin: 0;
  color: var(--muted);
  font-size: 0.875rem;
}
.last-batch strong {
  color: var(--ink);
  font-weight: 500;
}
.last-batch time {
  margin-inline-start: auto;
}
.stale-data {
  margin: 0;
  color: #fbbf24;
  font-size: 0.875rem;
}
</style>
