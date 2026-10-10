<script setup lang="ts">
import { workspace as w, date, metres } from '../workspace'
import Badge from '../components/Badge.vue'
import { auth } from '../auth'
import PrintAttribution from '../components/PrintAttribution.vue'
import BatchTrigger from '../components/BatchTrigger.vue'
const { batches, notices, overview } = w
function noticeState(notice: (typeof notices.value)[number]) {
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
  <section class="panel">
    <div class="section-heading">
      <h2>Print batches</h2>
      <span class="muted">Latest 100 attempts</span>
    </div>
    <div v-if="!batches.length" class="empty compact">No batches yet.</div>
    <article v-for="batch in batches" :key="batch.id" class="activity-batch">
      <div class="list-row">
        <div class="grow">
          <strong>{{ w.cartridgeName(batch.cartridge_id) }}</strong
          ><small
            >{{ w.destinationName(batch.printer_id) }} · {{ date(batch.created_at) }} ·
            {{ batch.consumed_mm === null ? 'Estimated' : 'Consumed' }}
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
          <PrintAttribution :attribution="entry.attribution" />
        </section>
      </div>
    </article>
  </section>
  <section v-if="auth.user.value?.is_admin" class="panel">
    <div class="section-heading">
      <h2>Notifications</h2>
      <span class="badge" :class="overview.notifications_enabled ? 'printed' : 'queued'">{{
        overview.notifications_enabled ? 'ntfy enabled' : 'ntfy not configured'
      }}</span>
    </div>
    <p v-if="!overview.notifications_enabled" class="help">
      Alerts are saved here. Configure ntfy to deliver them to your devices.
    </p>
    <div v-if="!notices.length" class="empty compact">
      All quiet. Alerts and tape reminders will appear here.
    </div>
    <article v-for="notice in notices" :key="notice.id" class="notification">
      <div class="row spread">
        <strong>{{ notice.title }}</strong
        ><Badge :state="noticeState(notice)" />
      </div>
      <p>{{ notice.message }}</p>
      <small
        >{{ date(notice.created_at) }} · {{ notice.attempts }} delivery attempts<span
          v-if="notice.last_error"
        >
          · {{ notice.last_error }}</span
        ></small
      ><a v-if="notice.path.startsWith('/#/')" :href="notice.path">Open details →</a>
    </article>
  </section>
</template>

<style scoped>
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
</style>
