<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import { useLiveRefresh } from '../live'
import { useWorkspaceStore, date, metres } from '../workspace'
import Badge from '../components/Badge.vue'
import { useAuthStore } from '../auth'
import PrintAttribution from '../components/PrintAttribution.vue'
import BatchTrigger from '../components/BatchTrigger.vue'
import ActivityLabels from '../components/ActivityLabels.vue'
import ActivityCleanup from '../components/ActivityCleanup.vue'
import HistoryPagination from '../components/HistoryPagination.vue'
import MotionSurface from '../components/MotionSurface.vue'
import { useHistoryPage } from '../history'
import type { Batch } from '../types'
const w = useWorkspaceStore()
const auth = useAuthStore()
const route = useRoute(),
  router = useRouter()
const filterFields = [
  { key: 'printer_id', title: 'Printer', options: 'printers' },
  { key: 'cartridge_id', title: 'Cartridge', options: 'cartridges' },
  { key: 'requester_id', title: 'Requester', options: 'requesters' },
  { key: 'authorizer_id', title: 'Authorizer', options: 'authorizers' },
]
const choices = ref<Record<string, { id: string; name: string }[]>>({})
useLiveRefresh(async () => {
  choices.value = await api('/batches/filters')
}, 10000)
const batches = reactive(
  useHistoryPage<Batch>(
    'batches',
    () => true,
    () =>
      Object.fromEntries(
        filterFields.map((field) => [
          field.key,
          typeof route.query[field.key] === 'string' ? (route.query[field.key] as string) : '',
        ]),
      ),
  ),
)
function setFilter(key: string, event: Event) {
  void router.push({
    query: {
      ...route.query,
      [key]: (event.target as HTMLSelectElement).value || undefined,
      batches_page: undefined,
      batches_before: undefined,
    },
  })
}
const cleanupMessage = ref('')
async function purged(count: number) {
  cleanupMessage.value = `Permanently deleted ${count} duplicate ${count === 1 ? 'attempt' : 'attempts'}.`
  await batches.retry()
}
</script>
<template>
  <section class="panel" aria-labelledby="batch-history-title" :aria-busy="batches.loading">
    <div class="section-heading">
      <h2 id="batch-history-title">Print batches</h2>
      <div class="row wrap">
        <RouterLink to="/printer-changes">Printer changes</RouterLink>
        <span class="muted">{{ batches.total }} attempts</span>
        <ActivityCleanup v-if="auth.user?.is_admin" @purged="purged" />
      </div>
    </div>
    <div class="field-row activity-filters">
      <label v-for="field in filterFields" :key="field.key"
        >{{ field.title
        }}<select :value="route.query[field.key] ?? ''" @change="setFilter(field.key, $event)">
          <option value="">All</option>
          <option
            v-for="option in choices[field.options] ?? []"
            :key="option.id"
            :value="option.id"
          >
            {{ option.name }}
          </option>
        </select></label
      >
    </div>
    <Transition name="notice"
      ><p v-if="cleanupMessage" class="motion-reveal" role="status">
        {{ cleanupMessage }}
      </p></Transition
    >
    <HistoryPagination
      v-bind="batches.pagination"
      label="Print batch pages"
      @change="batches.go($event)"
    />
    <Transition name="notice"
      ><div v-if="batches.error" class="alert danger motion-reveal" role="alert">
        {{ batches.error }}
        <button class="secondary small" :disabled="batches.loading" @click="batches.retry()">
          Retry
        </button>
      </div></Transition
    >
    <Transition name="notice"
      ><p v-if="batches.loading" role="status" class="muted motion-reveal">
        Loading page {{ batches.page }}…
      </p></Transition
    >
    <div v-if="!batches.items.length && !batches.loading && !batches.error" class="empty compact">
      No batches yet.
    </div>
    <MotionSurface
      :identity="String(batches.loadedPage)"
      :order="batches.loadedPage"
      class="history-items"
      :class="{ 'history-loading': batches.loading }"
    >
      <article v-for="batch in batches.items" :key="batch.id" class="activity-batch">
        <div class="list-row">
          <div class="grow">
            <strong
              >{{ batch.process_names?.[0] ?? w.cartridgeName(batch.cartridge_id)
              }}<span v-if="(batch.process_names?.length ?? 0) > 1">
                +{{ batch.process_names!.length - 1 }}</span
              ></strong
            ><small
              >{{ w.cartridgeName(batch.cartridge_id) }} ·
              {{ w.destinationName(batch.printer_id) }} · {{ date(batch.created_at) }} ·
              {{
                batch.consumed_mm === null || batch.consumption_source === 'estimated'
                  ? 'Estimated'
                  : batch.consumption_source === 'reported'
                    ? 'Reported'
                    : batch.consumption_source === 'measured'
                      ? 'Measured'
                      : 'Accounted'
              }}
              {{ metres(batch.consumed_mm ?? batch.estimated_mm) }}</small
            ><small v-if="batch.shortage_warning" class="danger-text"
              >Batch estimate exceeded remaining tape.</small
            >
          </div>
          <Badge :state="batch.state" /><RouterLink :to="`/batches/${batch.id}`">{{
            batch.state === 'needs_review' ? 'Review batch →' : 'Details →'
          }}</RouterLink>
          <RouterLink
            v-if="!['printing', 'needs_review'].includes(batch.state)"
            :to="`/batches/${batch.id}/packing`"
            >Pack labels →</RouterLink
          >
        </div>
        <BatchTrigger :trigger="batch.trigger" />
        <div class="batch-attributions">
          <section
            v-for="(entry, index) in batch.attribution_summary ?? []"
            :key="index"
            class="batch-attribution"
          >
            <p class="attribution-count">
              {{ entry.copies }} {{ entry.copies === 1 ? 'copy' : 'copies' }}
            </p>
            <PrintAttribution :attribution="entry.attribution" queue />
          </section>
        </div>
        <ActivityLabels :batch-id="batch.id" :state="batch.state" />
      </article>
    </MotionSurface>
    <HistoryPagination
      v-if="batches.items.length"
      v-bind="batches.pagination"
      label="Print batch pages, bottom"
      @change="batches.go($event)"
    />
  </section>
</template>

<style scoped>
.history-items {
  transition: opacity var(--motion-state) var(--motion-ease);
}
.history-loading {
  opacity: 0.55;
  pointer-events: none;
}
.activity-batch {
  padding-bottom: 20px;
  border-bottom: 1px solid var(--line);
}
.activity-batch:last-child {
  padding-bottom: 0;
  border-bottom: 0;
}
.activity-batch > .list-row {
  border-bottom: 0;
  padding-bottom: 0;
}
.batch-attributions {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(320px, 100%), 1fr));
  gap: 12px;
}
.batch-attribution {
  background: var(--surface-secondary);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 14px;
}
.attribution-count {
  margin: 0 0 12px;
  font-size: 12px;
  color: var(--text-secondary);
}
.notice-deliveries {
  display: grid;
  gap: 10px;
  margin: 12px 0;
  padding: 0;
  list-style: none;
}
.notice-deliveries li {
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 6px;
}
.notice-deliveries strong {
  min-width: 0;
  overflow-wrap: anywhere;
  font-size: 12px;
}
</style>
