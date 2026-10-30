<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { reactive, ref } from 'vue'
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
import type { Batch, Notice } from '../types'
const w = useWorkspaceStore()
const auth = useAuthStore()
const { overview } = storeToRefs(w)
const batches = reactive(useHistoryPage<Batch>('batches'))
const notices = reactive(useHistoryPage<Notice>('notifications', () => !!auth.user?.is_admin))
const cleanupMessage = ref('')
async function purged(count: number) {
  cleanupMessage.value = `Permanently deleted ${count} duplicate ${count === 1 ? 'attempt' : 'attempts'}.`
  await Promise.all([batches.retry(), notices.retry()])
}
function deliveryState(delivery: NonNullable<Notice['deliveries']>[number]) {
  return delivery.cancelled
    ? 'cancelled'
    : delivery.delivered_at
      ? 'delivered'
      : delivery.last_error
        ? 'retrying'
        : 'pending'
}
function noticeState(notice: Notice) {
  return notice.cancelled
    ? 'cancelled'
    : notice.delivered_at
      ? 'delivered'
      : notice.last_error
        ? 'retrying'
        : 'pending'
}
</script>
<template>
  <section class="panel" aria-labelledby="batch-history-title" :aria-busy="batches.loading">
    <div class="section-heading">
      <h2 id="batch-history-title">Print batches</h2>
      <div class="row wrap">
        <span class="muted">{{ batches.total }} attempts</span>
        <ActivityCleanup v-if="auth.user?.is_admin" @purged="purged" />
      </div>
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
  <section
    v-if="auth.user?.is_admin"
    class="panel"
    aria-labelledby="notification-history-title"
    :aria-busy="notices.loading"
  >
    <div class="section-heading">
      <h2 id="notification-history-title">Notifications</h2>
      <span class="badge" :class="overview.notifications_enabled ? 'printed' : 'queued'">{{
        overview.notifications_enabled ? 'ntfy enabled' : 'ntfy not configured'
      }}</span>
    </div>
    <p v-if="!overview.notifications_enabled" class="help">
      Alerts are saved here. Configure ntfy to deliver them to your devices.
    </p>
    <HistoryPagination
      v-bind="notices.pagination"
      label="Notification pages"
      @change="notices.go($event)"
    />
    <Transition name="notice"
      ><div v-if="notices.error" class="alert danger motion-reveal" role="alert">
        {{ notices.error }}
        <button class="secondary small" :disabled="notices.loading" @click="notices.retry()">
          Retry
        </button>
      </div></Transition
    >
    <Transition name="notice"
      ><p v-if="notices.loading" role="status" class="muted motion-reveal">
        Loading page {{ notices.page }}…
      </p></Transition
    >
    <div v-if="!notices.items.length && !notices.loading && !notices.error" class="empty compact">
      All quiet.
    </div>
    <MotionSurface
      :identity="String(notices.loadedPage)"
      :order="notices.loadedPage"
      class="history-items"
      :class="{ 'history-loading': notices.loading }"
    >
      <article v-for="notice in notices.items" :key="notice.id" class="notification">
        <div class="row spread">
          <strong>{{ notice.title }}</strong
          ><Badge :state="noticeState(notice)" />
        </div>
        <p>{{ notice.message }}</p>
        <ul
          v-if="notice.deliveries?.length"
          class="notice-deliveries"
          aria-label="Endpoint deliveries"
        >
          <li v-for="(delivery, index) in notice.deliveries" :key="index">
            <div class="row spread">
              <strong>{{ delivery.endpoint_name }}</strong>
              <Badge :state="deliveryState(delivery)" />
            </div>
            <small
              >{{ delivery.attempts }} delivery attempts<span v-if="delivery.delivered_at">
                · {{ date(delivery.delivered_at) }}</span
              ><span v-if="delivery.last_error"> · {{ delivery.last_error }}</span></small
            >
          </li>
        </ul>
        <small
          >{{ date(notice.created_at) }} · {{ notice.attempts }} delivery attempts<span
            v-if="notice.last_error"
          >
            · {{ notice.last_error }}</span
          ></small
        ><a v-if="notice.path.startsWith('/#/')" :href="notice.path">Open details →</a>
      </article>
    </MotionSurface>
    <HistoryPagination
      v-if="notices.items.length"
      v-bind="notices.pagination"
      label="Notification pages, bottom"
      @change="notices.go($event)"
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
